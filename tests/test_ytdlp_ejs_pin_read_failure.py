"""A failed read of the solver pin is a failure, not "this yt-dlp names no solver package".

_ytdlp_ejs_pin (three backends, and windows/launch.py) asks a child Python which yt-dlp-ejs version the
installed yt-dlp names. A timeout, an exception or a child that exits non zero used to give None, the
same answer as a yt-dlp that names none: Update Plugins then logged "this yt-dlp names no solver
package" and ended "done", and the pair stayed broken without a word.

Now a failed read has its own outcome ("could not read"): Update Plugins counts yt-dlp-ejs as failed
(the run ends with an error that names it), and the launcher logs it and starts as before (the step
stays non fatal). A yt-dlp that really names none keeps its old outcome. No pip and no network here."""
import importlib.util
import subprocess
import sys
import types
from pathlib import Path

import pytest

from conftest import ROOT

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
NAMED = "yt-dlp-ejs==0.8.0; extra == \"default\"\n"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_pinfail_" + path.split("/")[0], Path(ROOT) / path)
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


def _child(stdout="", rc=0, raises=None):
    def run(*cmd, **kw):
        if raises:
            raise raises
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr="Traceback ..." if rc else "")
    return run


FAILED_READS = [dict(raises=subprocess.TimeoutExpired("python", 30)), dict(raises=OSError("no python")),
                dict(rc=1), dict(rc=1, stdout="half a line")]


# ── the backends ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("child", FAILED_READS)
def test_a_failed_read_has_its_own_outcome(backend_module, monkeypatch, child):
    monkeypatch.setattr(backend_module, "_run_yt", _child(**child))
    assert backend_module._ytdlp_ejs_pin() == backend_module.EJS_PIN_UNREADABLE == "could not read"


def test_a_yt_dlp_that_names_none_still_gives_none(backend_module, monkeypatch):
    monkeypatch.setattr(backend_module, "_run_yt", _child("certifi>=1\n"))
    assert backend_module._ytdlp_ejs_pin() is None
    monkeypatch.setattr(backend_module, "_run_yt", _child(NAMED))
    assert backend_module._ytdlp_ejs_pin() == "0.8.0"


@pytest.fixture
def update(backend_module, tmp_path, monkeypatch):
    m = backend_module
    pips = []
    monkeypatch.setattr(m, "_run", lambda *cmd, **kw: (pips.append(cmd), types.SimpleNamespace(returncode=0, stdout="", stderr=""))[1])
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_get_latest_ytdlp_version", lambda *a, **k: "2026.10.26")
    monkeypatch.setattr(m, "_get_ytdlp_version", lambda *a, **k: "2026.10.26")
    monkeypatch.setattr(m, "_load_settings", lambda *a, **k: {"yt_dlp_channel": "stable"})
    if hasattr(m, "PACKAGES_DIR"):
        (tmp_path / "packages").mkdir()
        monkeypatch.setattr(m, "PACKAGES_DIR", tmp_path / "packages")

    def go(pin):
        monkeypatch.setattr(m, "_ytdlp_ejs_pin", lambda: pin)
        pips.clear()
        m._run_update(True, False)
        return m.update_status, [c for c in pips if any(str(a).startswith("yt-dlp-ejs==") for a in c)]
    return types.SimpleNamespace(go=go, mod=m)


def test_update_plugins_reports_a_failed_read_as_a_failure(update):
    st, ejs = update.go(update.mod.EJS_PIN_UNREADABLE)
    assert st["done"] is False and st["error"] and "yt-dlp-ejs" in st["error"], st
    assert any("could not read" in line for line in st["log"]), st["log"]
    assert not any("names no solver package" in line for line in st["log"]), "a failed read is not 'names none'"
    assert ejs == [], "nothing is installed when the version is unknown"


def test_update_plugins_still_ends_done_when_yt_dlp_names_none(update):
    st, ejs = update.go(None)
    assert st["done"] is True and st["error"] is None, st
    assert any("names no solver package" in line for line in st["log"])


# ── the launcher ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_pinfail", f"{ROOT}/windows/launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls, mod.logged, mod.read = [], [], {}

    def fake_run(cmd, **kw):
        cmd = list(cmd)
        mod.calls.append(cmd)
        if "-c" in cmd:
            if "raises" in mod.read:
                raise mod.read["raises"]
            return types.SimpleNamespace(returncode=mod.read.get("rc", 0), stdout=mod.read.get("stdout", ""), stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_py_log", lambda m: mod.logged.append(m))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(mod, "_meta_version", lambda n: None)
    monkeypatch.setitem(sys.modules, "brotli", None)             # an import fails: a real install
    return mod


@pytest.mark.parametrize("child", FAILED_READS)
def test_the_launcher_logs_a_failed_read_as_a_failure_and_starts(launcher, child):
    launcher.read = child
    assert launcher._ytdlp_ejs_pin(sys.executable) == launcher._EJS_PIN_UNREADABLE == "could not read"
    launcher.calls.clear()
    launcher.ensure_python_deps()                                # must not raise
    assert not any(any(str(a).startswith("yt-dlp-ejs==") for a in c) for c in launcher.calls), "nothing paired"
    assert any("yt-dlp-ejs" in m and "could not read" in m for m in launcher.logged), launcher.logged


def test_the_launcher_says_nothing_when_yt_dlp_names_none(launcher):
    launcher.read = {"stdout": "certifi>=1\n"}
    launcher.ensure_python_deps()
    assert launcher._ytdlp_ejs_pin(sys.executable) is None
    assert not any("could not read" in m for m in launcher.logged)
