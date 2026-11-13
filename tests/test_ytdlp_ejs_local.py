"""yt-dlp's YouTube solver script ships with the app and is updated together with yt-dlp.

Every yt-dlp call passes --remote-components ejs:github, and yt-dlp-ejs was not installed, so yt-dlp
downloaded its challenge solver script from GitHub at run time (an independent privacy review listed
it as code fetched at run time). yt-dlp looks for the script in this order (read from yt-dlp
2026.10.26, extractor/youtube/jsc/_builtin/ejs.py): the installed yt-dlp-ejs package, its own cache,
a vendored copy, and only last the GitHub release assets, and only because of that flag. The package
is accepted only when its major.minor version equals the one yt-dlp pins and its script hashes match
what yt-dlp lists (checked by hand for 0.8.0 against yt-dlp 2026.10.26: both hashes equal).

So:
* requirements.txt (both) and the launcher's two pip lists install yt-dlp-ejs, so a fresh install has it;
* Update Plugins installs, after every successful yt-dlp update, the yt-dlp-ejs version that yt-dlp
  names (it pins it with ==), so the pair never drifts. A failure there is reported, not hidden;
* the flag stays on every yt-dlp call as the fallback.

Nothing here installs or downloads anything: pip and the metadata read are replaced by fakes.
"""
import importlib.util
import re
import types
from pathlib import Path

import pytest

from conftest import ROOT, read_source

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
FLOOR = "yt-dlp-ejs>=0.8.0"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_ejs_" + path.split("/")[0], Path(ROOT) / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend_module(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


# ── What is installed ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", ("requirements.txt", "linux/requirements.txt"))
def test_both_requirements_files_install_the_solver_package(rel):
    lines = [l.strip() for l in read_source(rel).splitlines()]
    assert FLOOR in lines, f"{rel} does not install yt-dlp-ejs"


def test_both_launcher_pip_lists_install_it_too():
    src = read_source("windows/launch.py")
    assert len(re.findall(r'"yt-dlp-ejs>=0\.8\.0"', src)) == 2


def test_the_remote_flag_stays_on_every_yt_dlp_call_as_the_fallback():
    for rel in APP_FILES:
        assert read_source(rel).count('"--remote-components", "ejs:github"') == 3, rel


# ── Reading the pin ───────────────────────────────────────────────────────────────────────────

def _fake_yt(stdout="", raises=None):
    def run_yt(*cmd, **kw):
        if raises:
            raise raises
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
    return run_yt


REQUIRES = ("certifi>=2026.10.19; extra == 'default'\n"
            "yt-dlp-ejs==0.8.0; extra == \"default\"\n"
            "yt-dlp-ejs==0.8.0; extra == \"pin\"\n")


def test_the_pin_is_read_from_the_requirement_yt_dlp_names_for_its_default_extra(backend_module, monkeypatch):
    monkeypatch.setattr(backend_module, "_run_yt", _fake_yt(REQUIRES))
    assert backend_module._ytdlp_ejs_pin() == "0.8.0"


@pytest.mark.parametrize("stdout", [
    "", "certifi>=1\n", "yt-dlp-ejs>=0.8.0; extra == 'default'\n", "yt-dlp-ejs; extra == 'default'\n",
    "yt-dlp-ejs==0.8.0; extra == 'pin'\n", "yt-dlp-ejs==0.8.0 && echo x; extra == 'default'\n",
    "yt-dlp-ejs==../x; extra == 'default'\n",
])
def test_no_pin_when_yt_dlp_names_none_or_the_line_is_not_a_plain_version(backend_module, monkeypatch, stdout):
    monkeypatch.setattr(backend_module, "_run_yt", _fake_yt(stdout))
    assert backend_module._ytdlp_ejs_pin() is None


# ── Update Plugins ────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def updater(backend_module, tmp_path, monkeypatch):
    """The real _run_update with pip replaced by a recorder."""
    m = backend_module
    calls = []
    state = {"fail": set(), "pin": "0.8.0"}

    def fake_run(*cmd, **kw):
        calls.append(list(cmd))
        spec = next((c for c in cmd if str(c).startswith(("yt-dlp==", "yt-dlp-ejs=="))), None)
        name = "ejs" if spec and str(spec).startswith("yt-dlp-ejs") else "ytdlp"
        rc = 1 if name in state["fail"] else 0
        return types.SimpleNamespace(returncode=rc, stdout="", stderr="ERROR: boom" if rc else "")

    monkeypatch.setattr(m, "_run", fake_run)
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_get_latest_ytdlp_version", lambda *a, **k: "2026.10.26")
    monkeypatch.setattr(m, "_get_ytdlp_version", lambda *a, **k: "2026.10.26")
    monkeypatch.setattr(m, "_load_settings", lambda *a, **k: {"yt_dlp_channel": "stable"})
    monkeypatch.setattr(m, "_ytdlp_ejs_pin", lambda: state["pin"])
    if hasattr(m, "PACKAGES_DIR"):
        pk = tmp_path / "packages"
        pk.mkdir()
        monkeypatch.setattr(m, "PACKAGES_DIR", pk)
        state["packages"] = pk

    def go():
        m._run_update(True, False)
        return m.update_status
    return types.SimpleNamespace(calls=calls, state=state, go=go, mod=m)


def _pips(calls):
    return [c for c in calls if "pip" in c]


def test_yt_dlp_and_its_solver_package_are_updated_together(updater):
    st = updater.go()
    pips = _pips(updater.calls)
    assert any("yt-dlp==2026.10.26" in c for c in pips)
    ejs = [c for c in pips if "yt-dlp-ejs==0.8.0" in c]
    assert len(ejs) == 1
    assert pips.index(ejs[0]) > max(i for i, c in enumerate(pips) if "yt-dlp==2026.10.26" in c), "ejs goes second"
    assert st["error"] is None and st["done"] is True
    assert any("yt-dlp-ejs -> 0.8.0" in l for l in st["log"]), st["log"]


def _linux_only(updater):
    """Skips on the Windows and macOS backends (they install into the bundled Python itself). Decided by
    the backend's file, not by an attribute: on the Linux backend the overlay folder must exist."""
    if Path(updater.mod.__file__).resolve() != Path(ROOT, "linux", "app.py").resolve():
        pytest.skip("Linux only: the other backends install into the bundled Python itself")
    assert hasattr(updater.mod, "PACKAGES_DIR"), "linux/app.py has no PACKAGES_DIR: the overlay is gone or renamed"


def test_linux_puts_the_solver_package_in_the_same_overlay_as_yt_dlp(updater):
    _linux_only(updater)
    updater.go()
    ejs = next(c for c in _pips(updater.calls) if "yt-dlp-ejs==0.8.0" in c)
    assert "--target" in ejs and str(updater.state["packages"]) in ejs
    assert "--upgrade" in ejs and "--force-reinstall" in ejs, "with --target pip would call it already satisfied"


def test_linux_removes_the_superseded_solver_dist_info(updater):
    _linux_only(updater)
    pk = updater.state["packages"]
    for v in ("0.7.0", "0.8.0"):
        (pk / f"yt_dlp_ejs-{v}.dist-info").mkdir()
    updater.go()
    assert sorted(p.name for p in pk.glob("yt_dlp_ejs-*.dist-info")) == ["yt_dlp_ejs-0.8.0.dist-info"]


def test_a_failed_yt_dlp_update_does_not_install_the_solver(updater):
    updater.state["fail"] = {"ytdlp"}
    st = updater.go()
    assert not [c for c in _pips(updater.calls) if "yt-dlp-ejs==0.8.0" in c]
    assert st["error"] == "Update failed: yt-dlp"


def test_a_failed_solver_install_is_reported(updater):
    updater.state["fail"] = {"ejs"}
    st = updater.go()
    assert st["error"] == "Update failed: yt-dlp-ejs" and not st["done"]
    assert any("yt-dlp-ejs update failed" in l for l in st["log"])


def test_a_yt_dlp_that_names_no_solver_package_is_left_to_the_fallback(updater):
    updater.state["pin"] = None
    st = updater.go()
    assert not [c for c in _pips(updater.calls) if any(str(a).startswith("yt-dlp-ejs") for a in c)]
    assert st["error"] is None and st["done"] is True
    assert any("yt-dlp-ejs" in l for l in st["log"]), "say why nothing was installed"


def test_the_solver_package_is_not_touched_when_yt_dlp_is_not_updated(updater):
    updater.mod._run_update(False, False)
    assert not _pips(updater.calls)


def test_linux_reads_the_pin_from_the_yt_dlp_it_just_installed(updater):
    """pip --target leaves the old yt_dlp dist-info beside the new one; importlib.metadata reads whichever
    the folder lists first, so the pin could come from the old yt-dlp (each stable names another ejs)."""
    _linux_only(updater)
    import os
    pk = updater.state["packages"]
    old, new = pk / "yt_dlp-2026.2.21.dist-info", pk / "yt_dlp-2026.10.26.dist-info"
    old.mkdir()
    new.mkdir()
    os.utime(old, (1_700_000_000, 1_700_000_000))
    seen = []
    updater.mod._ytdlp_ejs_pin = lambda: (seen.append(sorted(p.name for p in pk.glob("yt_dlp-*.dist-info"))), "0.8.0")[1]
    updater.go()
    assert seen == [["yt_dlp-2026.10.26.dist-info"]], "the pin must be read with only the new dist-info left"


def test_linux_keeps_the_yt_dlp_dist_info_when_the_install_failed(updater):
    _linux_only(updater)
    import os
    pk = updater.state["packages"]
    for name, t in (("yt_dlp-2026.2.21.dist-info", 1_700_000_000), ("yt_dlp-2026.10.26.dist-info", 1_800_000_000)):
        (pk / name).mkdir()
        os.utime(pk / name, (t, t))
    updater.state["fail"] = {"ytdlp"}
    updater.go()
    assert len(list(pk.glob("yt_dlp-*.dist-info"))) == 2, "nothing is removed after a failed install"
