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
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


class _Done:
    def __init__(self, rc=0):
        self.returncode, self.stdout, self.stderr = rc, "", ""


def _write_install(root: Path, version: str, with_exe=True, marker="old"):
    mod = root / "node_modules" / "electron"
    (mod / "dist").mkdir(parents=True, exist_ok=True)
    (mod / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    (mod / "marker.txt").write_text(marker, encoding="utf-8")
    if with_exe:
        (mod / "dist" / "electron.exe").write_text("exe", encoding="utf-8")


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
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_find_npm", lambda node_exe: ["npm"])
    monkeypatch.setattr(mod, "_clean_electron_locales", lambda: None)

    class Env:
        pass

    e = Env()
    e.mod, e.dir, e.calls = mod, edir, []
    e.npm_ok = True          # False: npm exits 1 (offline)
    e.make_exe = True        # False: npm works but the Electron binary never arrives
    e.seen_live = []         # content of the LIVE install at the moment npm runs

    def fake_run(cmd, *a, **k):
        cwd = Path(k.get("cwd", "."))
        e.calls.append((list(map(str, cmd)), cwd))
        if cmd[:2] == ["npm", "ci"] or cmd[:2] == ["npm", "install"]:
            live = edir / "node_modules" / "electron" / "marker.txt"
            e.seen_live.append(live.read_text(encoding="utf-8") if live.exists() else None)
            if not e.npm_ok:
                return _Done(1)
            ver = json.loads((cwd / "package-lock.json").read_text(encoding="utf-8"))[
                "packages"]["node_modules/electron"]["version"]
            _write_install(cwd, ver, with_exe=e.make_exe, marker="new")
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


# ── the launcher flow ─────────────────────────────────────────────────────────

def test_the_reinstall_marker_no_longer_deletes_node_modules_first():
    src = LAUNCH.read_text(encoding="utf-8")
    assert 'shutil.rmtree(ELECTRON_DIR / "node_modules"' not in src
    assert "ensure_npm(node_exe, force=_reinstalling_electron)" in src
    assert "def _electron_needs_reinstall" not in src
