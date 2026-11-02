"""Force refresh on a subscription starts the list from scratch, but keeps what was downloaded.

Every video found again is New, as before. A video that was marked downloaded stays marked (and
keeps its saved path); it used to come back as not downloaded, so the files already on disk were
offered for download again. The subscription's own settings (folder, format, quality, name, auto
fetch) are not part of the list and are left exactly as they were.
"""
import importlib.util
import json
import types
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
            "egm_force_refresh_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


SETTINGS = {"folder": "/data/x", "format": "mp3", "quality": "720", "auto_fetch": True, "name": "Mine"}


def _video(vid, **kw):
    v = {"video_id": vid, "title": "t " + vid, "duration": 5, "upload_date": "20260101",
         "thumbnail_url": "", "availability": "public", "is_new": False, "formats": [],
         "downloaded": False, "download_path": None}
    v.update(kw)
    return v


@pytest.fixture
def subscription(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "SUBS_FILE", tmp_path / "egm_subscriptions.json")
    monkeypatch.setattr(backend, "_subs_cache", None)
    sub = {"id": "s1", "url": "https://example.invalid/c", "thumbnail_url": "", **SETTINGS,
           "videos": [_video("aaaaaaaaaaa", downloaded=True, download_path="/data/x/a.mp3"),
                      _video("bbbbbbbbbbb"),
                      _video("ccccccccccc", downloaded=True, download_path="/data/x/c.mp3")]}
    backend.SUBS_FILE.write_text(json.dumps({"subscriptions": [sub]}))

    def listing(ids):
        out = "\n".join(json.dumps({"id": i, "title": "now " + i}) for i in ids)
        monkeypatch.setattr(backend, "_run_yt", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=out, stderr=""))
    return backend, listing


def _run(backend, force):
    backend._subfetch_jobs["f1"] = {"status": "pending"}
    backend._run_subfetch("f1", "s1", "https://example.invalid/c", force, False)
    assert backend._subfetch_jobs["f1"]["status"] == "done", backend._subfetch_jobs["f1"]
    return {v["video_id"]: v for v in backend._subfetch_jobs["f1"]["subscription"]["videos"]}, backend._subfetch_jobs["f1"]


def test_force_refresh_keeps_the_downloaded_marks_and_paths(subscription):
    backend, listing = subscription
    listing(["aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"])          # c is gone, d is new
    videos, job = _run(backend, True)
    assert set(videos) == {"aaaaaaaaaaa", "bbbbbbbbbbb", "ddddddddddd"}
    assert videos["aaaaaaaaaaa"]["downloaded"] is True and videos["aaaaaaaaaaa"]["download_path"] == "/data/x/a.mp3"
    assert videos["bbbbbbbbbbb"]["downloaded"] is False and videos["bbbbbbbbbbb"]["download_path"] is None
    assert videos["ddddddddddd"]["downloaded"] is False
    assert all(v["is_new"] is True for v in videos.values()), "every video found again stays New"
    assert job["new_count"] == 3 and job["total"] == 3


def test_force_refresh_does_not_touch_the_subscriptions_own_settings(subscription):
    backend, listing = subscription
    listing(["aaaaaaaaaaa"])
    _run(backend, True)
    saved = json.loads(backend.SUBS_FILE.read_text())["subscriptions"][0]
    for k, v in SETTINGS.items():
        assert saved[k] == v, k


def test_a_normal_fetch_is_unchanged(subscription):
    backend, listing = subscription
    listing(["aaaaaaaaaaa", "ddddddddddd"])
    videos, job = _run(backend, False)
    assert set(videos) == {"aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"}
    assert videos["aaaaaaaaaaa"]["downloaded"] is True and videos["ccccccccccc"]["downloaded"] is True
    assert [k for k, v in videos.items() if v["is_new"]] == ["ddddddddddd"]
    assert job["new_count"] == 1
