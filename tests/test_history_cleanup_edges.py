"""Edges of "what the user clears, or what history drops, is not kept elsewhere on disk".

test_history_leaves_nothing_behind.py covers the main paths. Three edges were not covered:

* the name rule for unlinking a dropped entry's thumbnail must hold for the whole name. A name that only
  starts like one the app writes ("<id>.jpg/../../cookies.txt") reaches outside thumbnails/ wherever
  the path is resolved through it (on Windows ".." is resolved by name, so no folder is even needed);
* Clear History removes the log by name, so the log must rotate to exactly the name it removes: a
  rotation renamed elsewhere would keep every past line;
* more than one entry can fall off at once (a history file longer than the cap, for instance one that
  was imported): each takes its thumbnail with it.

All three backends are driven through the real functions with every path in a temporary folder.
"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "mac/app.py", "linux/app.py")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_history_edges_" + path.split("/")[0], ROOT / path)
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


@pytest.fixture
def backend(backend_module, tmp_path, monkeypatch):
    mod = backend_module
    data = tmp_path / "data"
    thumbs = data / "thumbnails"
    thumbs.mkdir(parents=True)
    monkeypatch.setattr(mod, "THUMBNAILS_DIR", thumbs)
    monkeypatch.setattr(mod, "HISTORY_FILE", data / "egm_history.json")
    if hasattr(mod, "DATA_DIR"):
        monkeypatch.setattr(mod, "DATA_DIR", data)
    else:
        monkeypatch.setattr(mod, "get_data_dir", lambda: data)
    mod.data_for_test = data
    return mod


def _fake_thumbnails(mod, monkeypatch):
    def fake(url, entry_id):
        name = f"{entry_id}.jpg"
        (mod.THUMBNAILS_DIR / name).write_bytes(b"\xff\xd8\xff")
        return name
    monkeypatch.setattr(mod, "_download_thumbnail", fake)


def _add(mod, tmp_path, n):
    f = tmp_path / f"v{n}.mp4"
    f.write_bytes(b"x")
    mod._append_history({"url": f"https://example.com/{n}", "title": f"t{n}", "thumbnail": "https://cdn.example/x.jpg"}, f)


def _entry(i, thumbnail):
    return {"id": f"e{i}", "url": "u", "title": "t", "thumbnail": thumbnail, "completed_at": "2026-01-01T00:00:00Z"}


# A name that starts like one the app writes. The folder makes it resolve on Linux and macOS as it would
# on Windows without one.
PREFIXED = "0a.jpg/../../cookies.txt"


def _prefixed_setup(backend):
    (backend.THUMBNAILS_DIR / "0a.jpg").mkdir()
    outside = backend.data_for_test / "cookies.txt"
    outside.write_text("keep", encoding="utf-8")
    assert (backend.THUMBNAILS_DIR / PREFIXED).resolve() == outside.resolve()   # the test reaches outside, or it checks nothing
    backend.HISTORY_FILE.write_text(json.dumps([_entry(0, PREFIXED)]), encoding="utf-8")
    return outside


def test_a_dropped_entry_whose_name_only_starts_like_a_thumbnail_removes_nothing_outside(backend, tmp_path, monkeypatch):
    outside = _prefixed_setup(backend)
    monkeypatch.setattr(backend, "_HISTORY_MAX", 1)
    _fake_thumbnails(backend, monkeypatch)
    _add(backend, tmp_path, 1)
    assert len(backend._load_history()) == 1
    assert outside.read_text(encoding="utf-8") == "keep"


def test_an_import_never_removes_a_file_outside_through_a_name_that_only_starts_like_a_thumbnail(backend):
    outside = _prefixed_setup(backend)
    r = backend.app.test_client().post("/api/history/import", json={"items": []},
                                       headers={"X-EGM-Token": backend._API_TOKEN})
    assert r.status_code == 200
    assert outside.read_text(encoding="utf-8") == "keep"


def test_every_entry_that_falls_off_at_once_takes_its_thumbnail(backend, tmp_path, monkeypatch):
    names = [f"{i:02x}.jpg" for i in range(4)]
    for n in names:
        (backend.THUMBNAILS_DIR / n).write_bytes(b"\xff\xd8\xff")
    backend.HISTORY_FILE.write_text(json.dumps([_entry(i, n) for i, n in enumerate(names)]), encoding="utf-8")
    monkeypatch.setattr(backend, "_HISTORY_MAX", 2)
    _fake_thumbnails(backend, monkeypatch)
    _add(backend, tmp_path, 9)
    kept = backend._load_history()
    assert len(kept) == 2
    left = sorted(p.name for p in backend.THUMBNAILS_DIR.iterdir())
    assert left == sorted(e["thumbnail"] for e in kept), "a picture of an entry no longer listed was left behind"


def test_clear_history_removes_the_log_after_it_has_rotated(backend, monkeypatch):
    """Rotate for real (through _egm_log), then clear: no copy of the log may be left."""
    monkeypatch.setattr(backend, "_DEBUG_LOG_MAX", 200)
    for i in range(20):
        backend._egm_log(f"download started (video): example.com line {i}")
    data = backend.data_for_test
    logs = sorted(p.name for p in data.iterdir() if p.name.startswith("egm_debug"))
    assert len(logs) >= 2, f"the log did not rotate, so this checks nothing: {logs}"
    r = backend.app.test_client().post("/api/history/clear", headers={"X-EGM-Token": backend._API_TOKEN})
    assert r.get_json() == {"ok": True}
    left = sorted(p.name for p in data.iterdir() if p.name.startswith("egm_debug"))
    assert left == [], f"Clear History left {left}"
