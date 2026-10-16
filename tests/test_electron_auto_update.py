"""
Windows: Electron updates itself after an app update, and a failed or offline
download never leaves the app without Electron.

Before: only a new MAJOR was reinstalled (and node_modules was deleted first), so
point releases never reached existing installs and a failed major download left
nothing behind. Now an install that is older than the version the shipped
package-lock.json pins (same major) is rebuilt next to the live one and swapped in
only when it works. windows/launch.py is import safe, so these tests drive the real
functions with a fake npm in a temp folder. Nothing is downloaded or run.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


class _Done:
    def __init__(self, rc=0, err=b""):
        self.returncode, self.stdout, self.stderr = rc, b"", err   # bytes, like the real captured output


def _write_install(root: Path, version: str, with_exe=True, marker="old"):
    mod = root / "node_modules" / "electron"
    (mod / "dist").mkdir(parents=True, exist_ok=True)
    (mod / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (mod / "marker.txt").write_text(marker, encoding="utf-8")
    if with_exe:
        (mod / "dist" / "electron.exe").write_text("exe", encoding="utf-8")
        (mod / "path.txt").write_text("electron.exe", encoding="utf-8")   # Electron's installer writes it last


def _write_pins(root: Path, spec: str, locked: str):
    (root / "package.json").write_text(
        json.dumps({"dependencies": {"electron": spec}}), encoding="utf-8")
    (root / "package-lock.json").write_text(
        json.dumps({"packages": {"node_modules/electron": {"version": locked}}}), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_electron_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    edir = tmp_path / "electron"
    edir.mkdir()
    monkeypatch.setattr(mod, "ELECTRON_DIR", edir)
    msgs = []
    monkeypatch.setattr(mod, "_gui_msg", lambda m="", *a, **k: msgs.append(m))
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_find_npm", lambda node_exe: ["npm"])
    monkeypatch.setattr(mod, "_clean_electron_locales", lambda: None)

    class Env:
        pass

    e = Env()
    e.mod, e.dir, e.calls = mod, edir, []
    for name in ("HTTPS_PROXY", "https_proxy", "npm_config_proxy", "npm_config_https_proxy"):
        monkeypatch.delenv(name, raising=False)        # the machine running the tests may have a proxy
    e.reachable, e.probes = True, []   # the host check never touches the real network
    monkeypatch.setattr(mod, "_update_hosts_reachable",
                        lambda *a, **k: (e.probes.append(1), e.reachable)[1])
    e.npm_ok = True          # False: npm exits 1 (offline)
    e.make_exe = True        # False: npm works but the Electron binary never arrives
    e.make_path = True       # False: the binary is there but the unpack never finished (no path.txt)
    e.npm_error = b"npm error code ECONNREFUSED\nnpm error network request failed"   # what a failing npm prints
    e.ci_error = None        # bytes: only `npm ci` fails with this (npm install still works)
    e.msgs = msgs            # every message the launcher shows
    e.seen_live = []         # content of the LIVE install at the moment npm runs

    def fake_run(cmd, *a, **k):
        cwd = Path(k.get("cwd", "."))
        e.calls.append((list(map(str, cmd)), cwd))
        if cmd[:2] == ["npm", "ci"] or cmd[:2] == ["npm", "install"]:
            live = edir / "node_modules" / "electron" / "marker.txt"
            e.seen_live.append(live.read_text(encoding="utf-8") if live.exists() else None)
            if cmd[1] == "ci" and e.ci_error is not None:
                return _Done(1, e.ci_error)
            if not e.npm_ok:
                return _Done(1, e.npm_error)
            ver = json.loads((cwd / "package-lock.json").read_text(encoding="utf-8"))[
                "packages"]["node_modules/electron"]["version"]
            _write_install(cwd, ver, with_exe=e.make_exe, marker="new")
            if not e.make_path:
                (cwd / "node_modules" / "electron" / "path.txt").unlink(missing_ok=True)
        return _Done(0)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    return e


# ── what needs updating ───────────────────────────────────────────────────────

@pytest.mark.parametrize("installed, locked, expected", [
    ("44.7.2", "44.7.2", None),                 # same: nothing to do
    ("44.7.1", "44.7.2", "update"),             # point release behind
    ("44.6.0", "44.7.0", "update"),             # minor behind
    ("44.7.3", "44.7.2", None),                 # newer is never touched (no loop)
    ("45.0.0-beta.2", "45.0.0-beta.3", "update"),
    ("45.0.0-beta.3", "45.0.0-beta.3", None),
    ("45.0.0-beta.3", "45.0.0", "update"),      # beta behind the stable release
    ("45.0.0", "45.0.0-beta.3", None),
])
def test_update_kind_by_version(env, installed, locked, expected):
    major = locked.split(".")[0]
    _write_pins(env.dir, f"^{major}.0.0", locked)
    _write_install(env.dir, installed)
    assert env.mod._electron_update_kind() == expected


def test_update_kind_major_and_missing(env):
    _write_pins(env.dir, "^45.0.0", "45.0.0")
    assert env.mod._electron_update_kind() == "missing"
    _write_install(env.dir, "44.7.2")
    assert env.mod._electron_update_kind() == "major"


@pytest.mark.parametrize("break_what", ["lockfile gone", "lockfile garbage", "no electron entry", "odd version"])
def test_update_kind_never_forces_a_reinstall_on_unreadable_data(env, break_what):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    lock = env.dir / "package-lock.json"
    if break_what == "lockfile gone":
        lock.unlink()
    elif break_what == "lockfile garbage":
        lock.write_text("{not json", encoding="utf-8")
    elif break_what == "no electron entry":
        lock.write_text(json.dumps({"packages": {}}), encoding="utf-8")
    else:
        lock.write_text(json.dumps({"packages": {"node_modules/electron": {"version": "latest"}}}), encoding="utf-8")
    assert env.mod._electron_update_kind() is None


def test_version_key_orders_prereleases(env):
    k = env.mod._ver_key
    assert k("45.0.0-alpha.9") < k("45.0.0-beta.1") < k("45.0.0-beta.3") < k("45.0.0-rc.1") < k("45.0.0")
    assert k("44.7.2") < k("44.10.0") < k("45.0.0-alpha.1")
    assert k("latest") is None and k("44.7") is None


# ── ensure_npm: nothing to do, success, failure ───────────────────────────────

def test_up_to_date_does_nothing(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.2")
    env.mod.ensure_npm("node.exe")
    assert env.calls == []


def test_update_builds_beside_the_live_copy_then_swaps(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    env.mod.ensure_npm("node.exe")
    # npm ran in the staging folder, never in the live one, and the live copy was still intact then
    assert env.calls and all(cwd == env.dir / ".electron-stage" for _, cwd in env.calls[:1])
    assert env.seen_live == ["old"]
    live = env.dir / "node_modules" / "electron"
    assert json.loads((live / "package.json").read_text())["version"] == "44.7.2"
    assert (live / "marker.txt").read_text() == "new"
    assert not (env.dir / "node_modules.old").exists()
    assert not (env.dir / ".electron-stage").exists()


@pytest.mark.parametrize("failure", ["offline", "no binary"])
def test_failed_update_keeps_the_current_electron(env, failure):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    if failure == "offline":
        env.npm_ok = False
    else:
        env.make_exe = False
    env.mod.ensure_npm("node.exe")           # must return, not exit
    live = env.dir / "node_modules" / "electron"
    assert json.loads((live / "package.json").read_text())["version"] == "44.7.1"
    assert (live / "marker.txt").read_text() == "old" and (live / "dist" / "electron.exe").exists()
    assert not (env.dir / ".electron-stage").exists() and not (env.dir / "node_modules.old").exists()


def test_failed_major_update_exits_but_keeps_the_old_install_for_the_retry(env):
    _write_pins(env.dir, "^45.0.0", "45.0.0")
    _write_install(env.dir, "44.7.2")
    env.npm_ok = False
    with pytest.raises(SystemExit):
        env.mod.ensure_npm("node.exe")
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "old"
    assert env.mod._electron_update_kind() == "major"      # the next launch tries again


def test_swap_failure_puts_the_old_electron_back(env, monkeypatch):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    real = env.mod.os.replace
    state = {"n": 0}

    def flaky(src, dst):
        state["n"] += 1
        if state["n"] == 2:                  # the second step: new into place
            raise PermissionError("locked")
        return real(src, dst)

    monkeypatch.setattr(env.mod.os, "replace", flaky)
    env.mod.ensure_npm("node.exe")
    live = env.dir / "node_modules" / "electron"
    assert (live / "marker.txt").read_text() == "old"
    assert not (env.dir / "node_modules.old").exists()


def test_swap_blocked_at_the_first_step_changes_nothing(env, monkeypatch):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    monkeypatch.setattr(env.mod.os, "replace", lambda s, d: (_ for _ in ()).throw(PermissionError("locked")))
    env.mod.ensure_npm("node.exe")
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "old"


def test_force_reinstalls_the_same_version_safely(env):
    """Advanced > Reinstall Electron goes through the same swap."""
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.2")
    env.mod.ensure_npm("node.exe", force=True)
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "new"
    env.npm_ok = False
    env.mod.ensure_npm("node.exe", force=True)           # offline: keeps what is there
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "new"


def test_first_install_goes_straight_in_and_a_failure_exits(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    env.mod.ensure_npm("node.exe")
    assert env.calls[0][1] == env.dir and env.seen_live == [None]
    assert (env.dir / "node_modules" / "electron" / "dist" / "electron.exe").exists()
    # a damaged node_modules (no electron inside) is rebuilt in place too
    import shutil
    shutil.rmtree(env.dir / "node_modules" / "electron")
    (env.dir / "node_modules" / "junk.txt").write_text("x")
    env.npm_ok = False
    with pytest.raises(SystemExit):
        env.mod.ensure_npm("node.exe")


# ── offline: no npm at all, so no minutes long stall ──────────────────────────
# With no connection npm can look stuck for minutes (name lookups), then falls back
# to a second try. An optional point update therefore checks the hosts it needs first.

def test_offline_point_update_keeps_the_current_electron_without_starting_npm(env, monkeypatch):
    msgs = []
    monkeypatch.setattr(env.mod, "_gui_msg", lambda m, *a, **k: msgs.append(m))
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    env.reachable = False
    env.mod.ensure_npm("node.exe")
    assert env.calls == [] and msgs == []                  # npm never started, nothing shown
    live = env.dir / "node_modules" / "electron"
    assert json.loads((live / "package.json").read_text())["version"] == "44.7.1"
    assert (live / "marker.txt").read_text() == "old"
    assert not (env.dir / ".electron-stage").exists() and not (env.dir / "node_modules.old").exists()
    assert env.mod._electron_update_kind() == "update"      # the next online launch tries again
    env.reachable = True
    env.mod.ensure_npm("node.exe")
    assert json.loads((live / "package.json").read_text())["version"] == "44.7.2"


@pytest.mark.parametrize("case", ["force", "major"])
def test_the_registry_check_only_guards_the_optional_point_update(env, case):
    """Explicit reinstall and a needed major keep their own handling."""
    env.reachable = False
    if case == "force":
        _write_pins(env.dir, "^44.7.0", "44.7.2")
        _write_install(env.dir, "44.7.2")
        env.mod.ensure_npm("node.exe", force=True)
    elif case == "major":
        _write_pins(env.dir, "^45.0.0", "45.0.0")
        _write_install(env.dir, "44.7.2")
        env.mod.ensure_npm("node.exe")
    assert env.probes == [] and env.calls                  # the check was not consulted; npm ran
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "new"


def _load_launch(monkeypatch=None):
    spec = importlib.util.spec_from_file_location("egm_launch_registry_check_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if monkeypatch is not None:   # the machine running the tests may have a proxy: these hosts are the direct ones
        for name in (*mod._PROXY_VARS, "ELECTRON_GET_USE_PROXY"):
            monkeypatch.delenv(name, raising=False)
    return mod


def test_host_check_connects_to_the_registry_and_to_github_and_closes(monkeypatch):
    mod, seen = _load_launch(monkeypatch), []

    class Sock:
        def close(self):
            seen.append("closed")

    monkeypatch.setattr(mod.socket, "create_connection",
                        lambda addr, timeout=None: (seen.append((addr, timeout)), Sock())[1])
    assert mod._update_hosts_reachable(timeout=2) is True
    assert sorted(x for x in seen if x != "closed") == [(("github.com", 443), 2), (("registry.npmjs.org", 443), 2)]
    assert seen.count("closed") == 2


@pytest.mark.parametrize("blocked", ["registry.npmjs.org", "github.com", "both"])
def test_host_check_is_false_when_any_needed_host_does_not_answer(monkeypatch, blocked):
    """The package comes from the registry and the Electron binary from GitHub: both
    must answer, or the update would start and then fail halfway."""
    mod = _load_launch(monkeypatch)

    class Sock:
        def close(self):
            pass

    def connect(addr, timeout=None):
        if blocked == "both" or addr[0] == blocked:
            raise OSError("blocked")
        return Sock()

    monkeypatch.setattr(mod.socket, "create_connection", connect)
    assert mod._update_hosts_reachable(timeout=1) is False


def test_host_check_is_false_when_the_connection_fails(monkeypatch):
    mod = _load_launch(monkeypatch)

    def offline(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(mod.socket, "create_connection", offline)
    assert mod._update_hosts_reachable(timeout=1) is False


def test_host_check_returns_in_time_when_the_name_lookup_hangs(monkeypatch):
    import threading
    import time
    mod, release = _load_launch(monkeypatch), threading.Event()
    monkeypatch.setattr(mod.socket, "create_connection", lambda *a, **k: release.wait(10))
    t0 = time.monotonic()
    result = mod._update_hosts_reachable(timeout=0.3)
    elapsed = time.monotonic() - t0
    release.set()
    assert result is False and elapsed < 2          # both hosts hang: one shared wait (about 1.3 s), not two


@pytest.mark.parametrize("var", ["HTTPS_PROXY", "https_proxy", "npm_config_proxy", "npm_config_https_proxy"])
def test_behind_a_proxy_the_proxy_and_github_are_checked(monkeypatch, var):
    """npm goes through the proxy, so the proxy is what must answer (a dead one stalled every
    start); Electron's binary download goes to GitHub directly unless ELECTRON_GET_USE_PROXY is set."""
    mod = _load_launch(monkeypatch)
    monkeypatch.setenv(var, "http://proxy.example:8080")
    assert mod._update_targets() == [("proxy.example", 8080), ("github.com", 443)]
    monkeypatch.setenv("ELECTRON_GET_USE_PROXY", "1")
    assert mod._update_targets() == [("proxy.example", 8080)]


@pytest.mark.parametrize("value, want", [
    ("proxy.example:3128", [("proxy.example", 3128), ("github.com", 443)]),            # no scheme
    ("http://user:pw@proxy.example", [("proxy.example", 80), ("github.com", 443)]),     # default ports
    ("https://proxy.example", [("proxy.example", 443), ("github.com", 443)]),
    ("http://proxy.example:99999", [("github.com", 443)]),                              # unreadable: npm decides
])
def test_the_proxy_address_is_read_like_npm_reads_it(monkeypatch, value, want):
    mod = _load_launch(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", value)
    assert mod._update_targets() == want


def test_a_dead_proxy_skips_the_optional_update_instead_of_stalling(env, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    env.reachable = False                                   # the proxy does not answer
    env.mod.ensure_npm("node.exe")
    assert env.probes == [1] and env.calls == []            # checked, npm never started


def test_an_offline_first_install_says_so_at_once_and_keeps_what_is_there(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    mod = env.dir / "node_modules" / "electron"
    (mod / "dist").mkdir(parents=True)
    (mod / "package.json").write_text(json.dumps({"version": "44.7.2"}), encoding="utf-8")
    (mod / "dist" / "partial.bin").write_text("x", encoding="utf-8")
    env.reachable = False
    with pytest.raises(SystemExit):
        env.mod.ensure_npm("node.exe")
    assert env.calls == [] and env.probes == [1]            # no npm wait
    assert "cannot be reached" in env.msgs[-1]
    assert (mod / "dist" / "partial.bin").exists()          # nothing deleted on the way out


# ── one launcher at a time ────────────────────────────────────────────────────
def test_a_second_launcher_does_not_get_the_setup_lock(env):
    """_signal_running_instance() only sees a running app. A second launcher started while the
    first one installs or updates Electron would delete what the first one is building."""
    assert env.mod._take_launcher_lock() is True
    first = env.mod._LAUNCH_LOCK
    assert env.mod._take_launcher_lock() is False           # a second start while the first holds it
    first.close()                                           # the first launcher exits
    assert env.mod._take_launcher_lock() is True
    env.mod._LAUNCH_LOCK.close()


def test_the_uninstaller_removes_the_launcher_lock_file():
    """The lock file lives in the electron folder and stays after the launcher exits: left behind, it would
    stop the uninstaller's last RMDir of that folder and of the install folder."""
    src = LAUNCH.read_text(encoding="utf-8")
    name = re.search(r'ELECTRON_DIR / "(\.launcher\.lock)"', src).group(1)
    nsi = (LAUNCH.parent / "setup.nsi").read_text(encoding="utf-8")
    delete = 'Delete "$INSTDIR\\electron\\' + name + '"'
    assert delete in nsi
    assert nsi.index(delete) < nsi.index('RMDir "$INSTDIR\\electron"\n')


def test_the_launcher_takes_the_lock_before_any_setup_and_after_the_running_app_check():
    src = LAUNCH.read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    assert main.index("_signal_running_instance()") < main.index("_take_launcher_lock()") < main.index("ensure_python()")


def test_without_a_proxy_the_check_still_guards_the_point_update(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    env.reachable = False
    env.mod.ensure_npm("node.exe")
    assert env.probes == [1] and env.calls == []


# ── a run that died in the middle of a swap ───────────────────────────────────

def test_leftover_old_copy_is_restored_when_the_live_one_is_gone(env):
    _write_pins(env.dir, "^44.7.0", "44.7.1")
    _write_install(env.dir, "44.7.1", marker="previous")
    (env.dir / "node_modules").rename(env.dir / "node_modules.old")
    env.mod.ensure_npm("node.exe")
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "previous"
    assert not (env.dir / "node_modules.old").exists()


def test_leftover_old_copy_is_dropped_when_the_live_one_is_fine(env):
    _write_pins(env.dir, "^44.7.0", "44.7.1")
    _write_install(env.dir, "44.7.1", marker="live")
    (env.dir / "node_modules.old" / "electron").mkdir(parents=True)
    env.mod.ensure_npm("node.exe")
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "live"
    assert not (env.dir / "node_modules.old").exists()


# ── a stage left behind by a killed update ────────────────────────────────────
# A launcher killed (or a PC shut down) while npm fills .electron-stage leaves up to
# ~250 MB there. Only the next ONLINE update used to clear it; ensure_npm now clears
# it at the top, before any early return.

@pytest.mark.parametrize("state", ["up to date", "offline with an update pending"])
def test_a_leftover_stage_is_removed_at_startup_even_when_nothing_else_runs(env, state):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    if state == "up to date":
        _write_install(env.dir, "44.7.2")
    else:
        _write_install(env.dir, "44.7.1")
        env.reachable = False
    stage = env.dir / ".electron-stage"
    (stage / "node_modules" / "electron").mkdir(parents=True)
    (stage / "node_modules" / "electron" / "big.bin").write_text("x", encoding="utf-8")
    env.mod.ensure_npm("node.exe")
    assert not stage.exists()
    assert env.calls == []                                   # npm never started
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "old"


# ── an install that never finished ────────────────────────────────────────────
# A first install killed (or cut off by the 300 s limit on a slow link) after npm ci
# and before the binary arrived left a package.json and no binary. The launcher
# counted that as installed and ended every launch on "electron.exe not found".
# Electron's own installer writes path.txt LAST, after unpacking the zip, so a
# binary plus path.txt is a complete install (the renamed binary counts too).

@pytest.mark.parametrize("state", ["no binary", "binary but unpack not finished", "path.txt but no binary"])
def test_an_install_that_never_finished_is_missing_and_gets_repaired(env, state):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    mod = env.dir / "node_modules" / "electron"
    (mod / "dist").mkdir(parents=True)
    (mod / "package.json").write_text(json.dumps({"version": "44.7.2"}), encoding="utf-8")
    if state == "binary but unpack not finished":
        (mod / "dist" / "electron.exe").write_text("half", encoding="utf-8")
    elif state == "path.txt but no binary":
        (mod / "path.txt").write_text("electron.exe", encoding="utf-8")
    assert env.mod._electron_update_kind() == "missing"
    env.mod.ensure_npm("node.exe")                          # offline would exit; npm works here
    assert env.calls and env.calls[0][1] == env.dir          # rebuilt in place, as any first install
    assert (mod / "marker.txt").read_text() == "new"
    assert env.mod._electron_update_kind() is None           # and it is complete now


def test_the_renamed_binary_with_path_txt_is_a_complete_install(env):
    """Every healthy install looks like this after its first launch."""
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.2")
    (env.dir / "node_modules" / "electron" / "dist" / "electron.exe").rename(
        env.dir / "node_modules" / "electron" / "dist" / "EGM Downloader.exe")
    assert env.mod._electron_update_kind() is None
    env.mod.ensure_npm("node.exe")
    assert env.calls == []


def test_an_update_whose_unpack_did_not_finish_is_not_swapped_in(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    _write_install(env.dir, "44.7.1")
    env.make_path = False
    env.mod.ensure_npm("node.exe")                           # must return, not exit
    live = env.dir / "node_modules" / "electron"
    assert json.loads((live / "package.json").read_text())["version"] == "44.7.1"
    assert (live / "marker.txt").read_text() == "old" and (live / "path.txt").exists()
    assert not (env.dir / ".electron-stage").exists() and not (env.dir / "node_modules.old").exists()


# ── npm ci failed: when is npm install a sensible second try? ─────────────────
# Only when the lockfile does not match package.json (npm reports EUSAGE). Offline,
# or on any other failure, the second try fails the same way after the same wait and
# the message "Lockfile out of sync" is simply wrong.

_EUSAGE = (b"npm error code EUSAGE\nnpm error `npm ci` can only install packages when your "
           b"package.json and package-lock.json are in sync.")


def _npm_commands(env):
    return [c[1] for c, _ in env.calls if c[0] == "npm" and c[1] in ("ci", "install")]


def test_a_lockfile_out_of_sync_falls_back_to_npm_install_and_says_so(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    env.ci_error = _EUSAGE
    env.mod.ensure_npm("node.exe")
    assert _npm_commands(env) == ["ci", "install"]
    assert sum("Lockfile out of sync" in m for m in env.msgs) == 1
    assert (env.dir / "node_modules" / "electron" / "marker.txt").read_text() == "new"


@pytest.mark.parametrize("what", ["first install", "update"])
def test_any_other_npm_ci_failure_does_not_start_a_second_try(env, what):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    if what == "update":
        _write_install(env.dir, "44.7.1")
    env.npm_ok = False                                         # offline: ECONNREFUSED text
    if what == "first install":
        with pytest.raises(SystemExit):
            env.mod.ensure_npm("node.exe")
    else:
        env.mod.ensure_npm("node.exe")                         # keeps the current Electron
    assert _npm_commands(env) == ["ci"]
    assert not any("Lockfile" in m for m in env.msgs)


def test_the_fallback_reads_text_output_too(env):
    _write_pins(env.dir, "^44.7.0", "44.7.2")
    env.ci_error = _EUSAGE.decode("utf-8")                     # a str, not bytes
    env.mod.ensure_npm("node.exe")
    assert _npm_commands(env) == ["ci", "install"]


# ── the launcher flow ─────────────────────────────────────────────────────────

def test_the_reinstall_marker_no_longer_deletes_node_modules_first():
    src = LAUNCH.read_text(encoding="utf-8")
    assert 'shutil.rmtree(ELECTRON_DIR / "node_modules"' not in src
    assert "ensure_npm(node_exe, force=_reinstalling_electron)" in src
    assert "def _electron_needs_reinstall" not in src
