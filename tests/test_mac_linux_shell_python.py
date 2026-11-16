"""The macOS and Linux shells start the bundled Python the way the Windows packaged build does.

* With the bundled Python (resources/python/bin/python3, or python/bin/python3 beside the shell), the
  probe and the backend run without any PYTHON variable of the user's environment, with
  PYTHONNOUSERSITE=1 (for the Pythons app.py starts), and app.py runs with -E -s.
* The system Python, the fallback, runs as before: the user's environment and no flag.
* Linux: yt-dlp's PYTHONPATH is the packages folder alone, not the user's value appended, and the
  yt-dlp child gets no -E or -I (it needs that PYTHONPATH). macOS has no packages folder.

findPython and startFlask are cut out of each main.js and run in Node against stand ins for Electron
and child_process, so what runs is the shipped text.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
SHELLS = ("mac/electron/main.js", "linux/electron/main.js")
RES = "/Applications/EGM Downloader.app/Contents/Resources"
BUNDLED = RES + "/python/bin/python3"
USER_ENV = {"PATH": "/usr/bin", "HOME": "/home/u", "PYTHONHOME": "/opt/py", "PYTHONPATH": "/home/u/mine",
            "PYTHONSTARTUP": "/home/u/start.py", "PYTHONNOUSERSITE": "0", "PYTHONUSERBASE": "/home/u/base",
            "PYTHONWARNINGS": "error", "PYTHONSAFEPATH": "0", "pythonpath": "/lower", "EGM_DEV_MODE": "0"}


def _code(rel):
    src = read_source(rel)
    python = src[src.index("// ── Find Python"):src.index("// ── Start Flask")]
    start = src.index("async function startFlask() {")
    return python + "let flaskProc = null;\n" + src[start:src.index("\n}\n", start) + 3]


RUNNER = r"""
const vm = require('vm');
const scenario = JSON.parse(process.argv[2]);
const probes = [], spawned = [], boxes = [];
const ctx = {
  path: require('path').posix,
  __dirname: scenario.resourcesPath + '/app.asar/electron',
  process: { resourcesPath: scenario.resourcesPath, env: scenario.env },
  app: { quit() {}, isQuitting: false },
  execFileSync: (cmd, args, opts) => {
    probes.push({ cmd, args, env: opts && opts.env ? opts.env : null });
    if (!scenario.working.includes(cmd)) throw new Error('not found');
  },
  spawn: (cmd, args, opts) => { spawned.push({ cmd, args, env: opts.env }); return { on() {} }; },
  dialog: { showErrorBox: (t) => boxes.push(t) },
  dropSplash() {}, splashProgress() {},
  PORT: 8899, HOST: '127.0.0.1', EGM_TOKEN: 'token',
  JSON, Object, String, console,
};
vm.runInNewContext(%s + "\nstartFlask();", ctx);
process.on('exit', () => console.log(JSON.stringify({ probes, spawned, boxes })));
"""


def _run(tmp_path, rel, working):
    if NODE is None:
        pytest.skip("node is not installed")
    runner = tmp_path / "runner.js"
    runner.write_text(RUNNER % json.dumps(_code(rel)), encoding="utf-8")
    scenario = {"resourcesPath": RES, "env": USER_ENV, "working": working}
    r = subprocess.run([NODE, str(runner), json.dumps(scenario)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("rel", SHELLS)
def test_the_bundled_python_runs_with_e_and_s_and_without_the_users_python_variables(tmp_path, rel):
    out = _run(tmp_path, rel, [BUNDLED, "python3"])
    (probe,) = out["probes"]
    assert probe["cmd"] == BUNDLED and probe["env"] is not None
    (proc,) = out["spawned"]
    assert proc["cmd"] == BUNDLED
    assert proc["args"] == ["-E", "-s", RES + "/app.asar/app/app.py"]
    for env in (probe["env"], proc["env"]):
        assert [k for k in env if k.startswith("PYTHON")] == ["PYTHONNOUSERSITE"], env
        assert env["PYTHONNOUSERSITE"] == "1" and env["PATH"] == "/usr/bin" and env["HOME"] == "/home/u"
    assert proc["env"]["EGM_ELECTRON"] == "1" and proc["env"]["EGM_DEV_MODE"] == "0"
    assert proc["env"]["pythonpath"] == "/lower", "only the names Python reads are dropped"


@pytest.mark.parametrize("rel", SHELLS)
def test_the_second_bundled_place_counts_as_bundled_too(tmp_path, rel):
    beside = RES + "/app.asar/python/bin/python3"
    out = _run(tmp_path, rel, [beside])
    (proc,) = out["spawned"]
    assert proc["cmd"] == beside and proc["args"][:2] == ["-E", "-s"]
    assert out["probes"][-1]["env"]["PYTHONNOUSERSITE"] == "1"


@pytest.mark.parametrize("rel", SHELLS)
def test_the_system_python_fallback_runs_as_before(tmp_path, rel):
    out = _run(tmp_path, rel, ["python3"])
    assert [p["cmd"] for p in out["probes"]][-1] == "python3"
    assert out["probes"][-1]["env"] is None, "the system Python's probe keeps the user's environment"
    (proc,) = out["spawned"]
    assert proc["cmd"] == "python3" and proc["args"] == [RES + "/app.asar/app/app.py"]
    for k, v in USER_ENV.items():
        assert proc["env"][k] == v, k


def test_the_two_shells_start_python_with_the_same_code():
    def part(rel):
        src = read_source(rel)
        spawn = src[src.index("  const bundled = "):src.index("    cwd: ", src.index("  const bundled = "))]
        return src[src.index("// ── Find Python"):src.index("// ── Start Flask")] + spawn
    assert part(SHELLS[0]) == part(SHELLS[1])


# ── the backends ──────────────────────────────────────────────────────────────

def _load_linux(tmp_path, monkeypatch):
    import importlib.util
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(tmp_path))
    spec = importlib.util.spec_from_file_location("egm_linux_python_env", ROOT / "linux" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_linux_yt_dlp_gets_the_packages_folder_alone_on_its_pythonpath(tmp_path, monkeypatch):
    mod = _load_linux(tmp_path, monkeypatch)
    packages = tmp_path / "packages"
    packages.mkdir()
    monkeypatch.setattr(mod, "PACKAGES_DIR", packages)
    monkeypatch.setenv("PYTHONPATH", "/home/u/mine")
    assert mod._yt_env()["PYTHONPATH"] == str(packages)
    monkeypatch.setattr(mod, "PACKAGES_DIR", tmp_path / "none")
    assert mod._yt_env()["PYTHONPATH"] == "/home/u/mine", "without a packages folder the variable is left alone"


def test_linux_yt_dlp_is_started_without_e_or_i(tmp_path, monkeypatch):
    mod = _load_linux(tmp_path, monkeypatch)
    seen = []

    def run(cmd, *a, **k):
        seen.append(list(cmd))

        class R:
            returncode, stdout, stderr = 0, "2026.01.01\n", ""
        return R()
    monkeypatch.setattr(mod.subprocess, "run", run)
    for name in ("_ffmpeg_args", "_deno_args", "_cookies_args", "_bgutil_args"):
        monkeypatch.setattr(mod, name, lambda: [])
    mod._ytdlp("--version", timeout=5)
    mod._get_ytdlp_version()
    assert len(seen) == 2
    for cmd in seen:
        assert cmd[0] == sys.executable and cmd[1:3] == ["-m", "yt_dlp"], cmd
        assert not {"-E", "-I", "-s"} & set(cmd), cmd


def test_the_macos_backend_has_no_packages_folder_and_sets_no_pythonpath():
    src = read_source("mac/app.py")
    assert "PYTHONPATH" not in src and "PACKAGES_DIR" not in src


@pytest.mark.parametrize("rel", ("mac/app.py", "linux/app.py"))
def test_no_backend_reads_a_python_variable(rel):
    """The backend runs with -E, so a PYTHON variable it read would be the user's or nothing."""
    import re
    src = read_source(rel)
    reads = re.findall(r"""environ(?:\.get)?[\[(]\s*["'](PYTHON\w*)""", src) + re.findall(r"""getenv\(\s*["'](PYTHON\w*)""", src)
    assert reads == [], reads


def _load_mac(tmp_path, monkeypatch):
    import importlib.util
    monkeypatch.setenv("HOME", str(tmp_path))
    spec = importlib.util.spec_from_file_location("egm_mac_python_env", ROOT / "mac" / "app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mac_yt_dlp_and_its_ffmpeg_get_certifis_list(tmp_path, monkeypatch):
    # ffmpeg 9 checks certificates by default and the Mac build has no list of its own: a live
    # recording failed with "certificate verify failed" (EGM, Nov 16). Its OpenSSL reads SSL_CERT_FILE.
    import types
    mod = _load_mac(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "certifi", types.SimpleNamespace(where=lambda: "/bundled/certifi/cacert.pem"))
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert mod._yt_env()["SSL_CERT_FILE"] == "/bundled/certifi/cacert.pem"
    monkeypatch.setenv("SSL_CERT_FILE", "/home/u/corp.pem")
    assert mod._yt_env()["SSL_CERT_FILE"] == "/home/u/corp.pem", "a value the user set is kept"
    monkeypatch.delenv("SSL_CERT_FILE")
    monkeypatch.setitem(sys.modules, "certifi", None)   # import fails
    assert "SSL_CERT_FILE" not in mod._yt_env(), "without certifi the environment is left as it was"


def test_mac_every_yt_dlp_child_is_started_with_that_environment(tmp_path, monkeypatch):
    # The list only helps if the children get it: the download and the live runs start through _popen_yt,
    # the info and playlist calls through _run_yt.
    import types
    mod = _load_mac(tmp_path, monkeypatch)
    monkeypatch.setitem(sys.modules, "certifi", types.SimpleNamespace(where=lambda: "/bundled/certifi/cacert.pem"))
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    seen = {}
    monkeypatch.setattr(mod.subprocess, "Popen", lambda cmd, **kw: seen.setdefault("popen", kw.get("env")))
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, **kw: seen.setdefault("run", kw.get("env")))
    mod._popen_yt("yt-dlp", "a link")
    mod._run_yt("yt-dlp", "a link", timeout=5)
    for how in ("popen", "run"):
        assert seen[how] is not None, f"{how}: the child inherits the app's environment, without the list"
        assert seen[how]["SSL_CERT_FILE"] == "/bundled/certifi/cacert.pem", how
