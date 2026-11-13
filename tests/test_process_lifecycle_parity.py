"""Process lifecycle on Mac and Linux: cancel, stop and quit must end the whole process tree,
and nothing else.

On Mac and Linux, _kill_proc ends a tracked process with os.killpg on its process group. That is
only safe, and only complete, when every process it can be called on was started in its own
session (start_new_session=True):
  * without its own session the process shares the app's group, so Cancel would end Flask (and
    Electron above it) along with the download;
  * with a single PID kill instead of the group kill, ffmpeg children started by yt-dlp would be
    left running after Cancel or quit.

test_process_group_scoping.py guards one function by name. These tests cover the whole class:
every process start in mac/app.py and linux/app.py, the real kill on a real process group, and
the quit path (/api/shutdown) that Electron calls on every platform.

The Electron side: every ipcMain handler in each shell must check the sender before it does
anything. test_parity.py counts the checks; the per handler test here also catches a handler that
lost its check while another one gained a second, and a check that moved below the work.
"""
import ast
import importlib.util
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
POSIX_APPS = ("mac/app.py", "linux/app.py")
SPAWNERS = {"_popen", "_popen_yt"}

# Process starts that are never tracked and never killed: they only hand a path to the desktop
# (Finder or the file manager) and return at once. Keyed by the function that holds them.
FIRE_AND_FORGET = {"open_folder"}


def _spawn_calls(path):
    """[(function name, line, call node)] for every process start in a backend file."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name in SPAWNERS:
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            is_spawn = (isinstance(f, ast.Name) and f.id in SPAWNERS) or (
                isinstance(f, ast.Attribute) and f.attr == "Popen"
                and isinstance(f.value, ast.Name) and f.value.id == "subprocess")
            if is_spawn:
                out.append((fn.name, node.lineno, node))
    return out


def _new_session(call):
    return any(k.arg == "start_new_session" and isinstance(k.value, ast.Constant)
               and k.value.value is True for k in call.keywords)


@pytest.mark.parametrize("path", POSIX_APPS)
def test_every_process_start_that_can_be_killed_has_its_own_session(path):
    calls = _spawn_calls(path)
    tracked = [(name, line) for name, line, call in calls if name not in FIRE_AND_FORGET]
    # Downloads, live attempts, the live check and conversions: at least these four starts.
    assert len(tracked) >= 4, f"{path}: only {tracked} found; the scan no longer sees the starts"
    missing = [(name, line) for name, line, call in calls
               if name not in FIRE_AND_FORGET and not _new_session(call)]
    assert not missing, (
        f"{path}: these process starts lack start_new_session=True: {missing}. _kill_proc ends "
        "the process group, so without its own session Cancel would also end the app.")


def _load_backend(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_lifecycle_" + path.split("/")[0], ROOT / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=POSIX_APPS)
def posix_backend(request, tmp_path_factory):
    return _load_backend(request.param, tmp_path_factory)


def _alive(pid):
    """True while pid is a running (not zombie) process."""
    r = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = r.stdout.strip()
    return bool(state) and not state.startswith("Z")


def _wait_gone(pid, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _start_tree():
    """A shell in its own session with one child, the shape of yt-dlp with ffmpeg below it."""
    proc = subprocess.Popen(["sh", "-c", "sleep 300 & echo $!; wait"], stdout=subprocess.PIPE,
                            text=True, start_new_session=True)
    child = int(proc.stdout.readline())
    return proc, child


def _end_tree(proc, child):
    for pid in (child, proc.pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    proc.wait(timeout=5)


skip_on_windows = pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")


@skip_on_windows
def test_kill_proc_ends_the_child_processes_too(posix_backend):
    proc, child = _start_tree()
    try:
        posix_backend._kill_proc(proc)
        assert _wait_gone(proc.pid), "the tracked process survived _kill_proc"
        assert _wait_gone(child), "the tracked process's child survived _kill_proc (single PID kill?)"
    finally:
        _end_tree(proc, child)


@skip_on_windows
def test_quit_ends_every_tracked_process_tree_before_the_backend_exits(posix_backend, monkeypatch):
    proc, child = _start_tree()
    exited = threading.Event()
    seen_alive_at_exit = []

    def fake_exit(code):
        seen_alive_at_exit.extend(p for p in (proc.pid, child) if not _wait_gone(p, 2.0))
        exited.set()

    monkeypatch.setattr(posix_backend.os, "_exit", fake_exit)
    with posix_backend._active_procs_lock:
        posix_backend._active_procs["t_quit"] = proc
    try:
        with posix_backend.app.test_client() as client:
            r = client.post("/api/shutdown", headers={"X-EGM-Token": posix_backend._API_TOKEN})
        assert r.status_code == 200
        assert exited.wait(10), "/api/shutdown never reached its exit"
        assert not seen_alive_at_exit, f"still running when the backend exits: {seen_alive_at_exit}"
    finally:
        with posix_backend._active_procs_lock:
            posix_backend._active_procs.pop("t_quit", None)
        _end_tree(proc, child)


# ── Electron: each IPC handler checks the sender first ─────────────────────────────────────────

SHELLS = ("windows", "mac", "linux")
_HANDLER_RE = re.compile(r"ipcMain\.(handle|on)\(\s*'([\w-]+)'\s*,\s*(?:async\s*)?\(([^)]*)\)\s*=>\s*\{")


def _handler_bodies(src):
    """{name: body text} for every ipcMain handler, the body cut at its matching brace."""
    out = {}
    for m in _HANDLER_RE.finditer(src):
        depth, i = 1, m.end()
        while depth and i < len(src):
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        out[m.group(2)] = (m.group(3).split(",")[0].strip(), src[m.end():i - 1])
    return out


def _first_statement(body):
    body = re.sub(r"//[^\n]*", "", body).strip()
    if body.startswith("try {"):
        body = body[len("try {"):].strip()
    return body


@pytest.mark.parametrize("shell", SHELLS)
def test_every_ipc_handler_checks_the_sender_before_anything_else(shell):
    src = (ROOT / shell / "electron" / "main.js").read_text(encoding="utf-8")
    bodies = _handler_bodies(src)
    registrations = len(re.findall(r"ipcMain\.(?:handle|on)\b", src))
    assert len(bodies) == registrations >= 15, (
        f"{shell}: parsed {len(bodies)} handlers of {registrations} registrations")
    late = [name for name, (arg, body) in bodies.items()
            if not _first_statement(body).startswith(f"if (!isTrustedSender({arg})")]
    assert not late, f"{shell}/electron/main.js: these handlers do not check the sender first: {late}"


# ── Electron killed (crash, force quit): the backend must not run on alone ─────────────────────

def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _data_dir(path, home):
    return (Path(home) / "Library" / "Application Support" / "EGM Downloader" if path.startswith("mac")
            else Path(home) / ".local" / "share" / "egm-downloader")


@skip_on_windows
@pytest.mark.parametrize("path", POSIX_APPS)
def test_the_backend_ends_when_electron_is_killed(path, tmp_path):
    import socket
    home = tmp_path / "home"
    ffmpeg_dir = _data_dir(path, home) / "ffmpeg_bin"
    ffmpeg_dir.mkdir(parents=True)
    for name in ("ffmpeg", "ffprobe"):   # present, so start-up downloads nothing
        (ffmpeg_dir / name).write_text("")
    port = _free_port()
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(home), "XDG_CONFIG_HOME": str(home),
           "TMP": str(tmp_path), "TEMP": str(tmp_path), "PORT": str(port), "EGM_ELECTRON": "1",
           "EGM_API_TOKEN": "ci-test-token-not-secret"}
    env.pop("EGM_DEV_MODE", None)
    # A stand-in for Electron: a shell that starts the backend as its child and waits.
    parent = subprocess.Popen(["sh", "-c", '"$0" "$1" >/dev/null 2>&1 & echo $!; wait',
                               sys.executable, str(ROOT / path)],
                              stdout=subprocess.PIPE, text=True, env=env, start_new_session=True)
    backend = int(parent.stdout.readline())
    try:
        end = time.time() + 30
        while time.time() < end:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail(f"{path}: the backend never listened on {port}")
        time.sleep(3)
        assert _alive(backend), f"{path}: the backend ended while Electron was still running"
        os.kill(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)
        assert _wait_gone(backend, 10), (
            f"{path}: the backend kept running after Electron was killed; it would keep the port "
            "and its downloads, and serve the next launch")
    finally:
        for pid in (backend, parent.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
