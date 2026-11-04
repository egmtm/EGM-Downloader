"""A plugins update that did not install something must say so.

/api/update-status drives the page: "done" shows "Update complete" and folds the log away, "error"
shows the error. A failed pip run (offline, a package index error) used to be written to the log
only, and the run still ended "done", so the page reported success. On Mac and Linux a nightly
yt-dlp download that failed ended the run with neither, so the page showed nothing at all.
pip and the network are stubbed; nothing is installed or fetched.
"""
import importlib.util
import subprocess
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_plugin_update_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def stubbed(backend, monkeypatch, tmp_path):
    calls = []
    result = {"rc": 0}

    def fake_run(*cmd, timeout=None, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(list(cmd), result["rc"], stdout="",
                                           stderr="" if result["rc"] == 0 else "ERROR: no connection")
    monkeypatch.setattr(backend, "_run", fake_run)
    monkeypatch.setattr(backend, "_get_latest_ytdlp_version", lambda *a, **k: "2099.1.1")
    monkeypatch.setattr(backend, "_get_ytdlp_version", lambda: "2026.1.1")
    monkeypatch.setattr(backend, "_get_optlibs_versions", lambda: {})
    if hasattr(backend, "PACKAGES_DIR"):
        monkeypatch.setattr(backend, "PACKAGES_DIR", tmp_path / "packages")
    settings = {"yt_dlp_channel": "stable"}
    monkeypatch.setattr(backend, "_load_settings", lambda: dict(settings))
    return result, settings, calls


def _run(backend, ytdlp=False, optlibs=False):
    if Path(backend.__file__).resolve() == ROOT / "app.py":
        backend._run_update(ytdlp, False, False, optlibs)
    else:
        backend._run_update(ytdlp, False, optlibs)
    return backend.update_status


def test_a_successful_update_is_done_without_an_error(backend, stubbed):
    st = _run(backend, ytdlp=True, optlibs=True)
    assert st["done"] and not st["error"] and not st["running"], st


@pytest.mark.parametrize("what", ["ytdlp", "optlibs"])
def test_a_failed_pip_run_is_reported_as_an_error_not_as_done(backend, stubbed, what):
    result, _, calls = stubbed
    result["rc"] = 1
    st = _run(backend, **{what: True})
    assert calls, "pip was not run"
    assert st["error"] and not st["done"], st


def test_a_failed_nightly_download_is_reported(backend, stubbed, monkeypatch):
    _, settings, _ = stubbed
    settings["yt_dlp_channel"] = "nightly"

    def offline(*a, **k):
        raise urllib.error.URLError("offline")
    monkeypatch.setattr(backend, "_safe_urlopen", offline)
    if Path(backend.__file__).resolve() == ROOT / "app.py":
        # Windows hands the nightly address to pip, which does the download.
        stubbed[0]["rc"] = 1
    st = _run(backend, ytdlp=True)
    assert st["error"] and not st["done"] and not st["running"], st
