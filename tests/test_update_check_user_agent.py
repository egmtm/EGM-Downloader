"""The app's own requests say who is asking in one way only: the plain name EGM-Downloader.

The Linux update check used to send "EGMDownloader/<app version>", so egerena.com was told the exact
build each Linux user runs, while Windows and Mac sent the plain name. All three now send the same,
with no version and no ID. (Requests made by other programs the app starts, such as pip, npm or
yt-dlp, send their own agent strings.)
Nothing here touches the network: the request is captured before it would be sent.
"""
import importlib.util
import types
from pathlib import Path

import pytest

from conftest import ROOT

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_ua_" + path.split("/")[0], Path(ROOT) / path)
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


def test_the_update_check_sends_the_plain_name(backend_module, monkeypatch):
    seen = []

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    def fake_urlopen(req, timeout):
        seen.append(req)
        return Reply()

    monkeypatch.setattr(backend_module, "_safe_urlopen", fake_urlopen)
    if hasattr(backend_module, "PORTABLE_MODE"):
        monkeypatch.setattr(backend_module, "PORTABLE_MODE", False)   # the portable build answers without a request
    backend_module.app.test_client().get("/api/check-app-update", headers={"X-EGM-Token": backend_module._API_TOKEN})
    assert len(seen) == 1, "the update check made no request (or more than one)"
    assert seen[0].get_header("User-agent") == "EGM-Downloader"

