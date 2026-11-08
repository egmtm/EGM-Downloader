"""What the user clears, or what history drops, is not kept elsewhere on disk.

An independent privacy review found two places where something outlived the history:

* egm_debug.log lines like "download started (...): youtube.com" carry a time and the site, and
  Clear History used to leave the log (and egm_debug.log.old, where it rotates to) in place, so a
  person with access to the PC could still read which sites were used and when.
* Past the 500 entry cap _append_history dropped the oldest entries but not their thumbnail files,
  so thumbnails/ kept pictures of downloads that were no longer listed.
* The Console window's four rings (memory only, 1000 lines each) hold what past downloads did: the
  yt-dlp output has their URLs, the Flask output their requests, the diagnostics ring the same lines
  as egm_debug.log (a download starting, with the site and the time) and the ffmpeg ring the paths of
  converted files. Clear History left all four until the app was closed.

All three backends are driven through the real route and the real function, with every path
pointed at a temporary folder (nothing of the developer's own data is touched).
"""
import importlib.util
import json
import re
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
        spec = importlib.util.spec_from_file_location("egm_history_left_" + path.split("/")[0], ROOT / path)
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
    """The backend with its data folder, history file and thumbnails folder in tmp_path."""
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


# ── Clear History ─────────────────────────────────────────────────────────────────────────────

def _clear(mod):
    return mod.app.test_client().post("/api/history/clear", headers={"X-EGM-Token": mod._API_TOKEN})


def test_clear_history_also_removes_the_debug_log_and_its_rotated_copy(backend):
    data = backend.data_for_test
    line = "2026-11-08 10:00:00 [EGM] download started (video): youtube.com\n"
    (data / "egm_debug.log").write_text(line, encoding="utf-8")
    (data / "egm_debug.log.old").write_text(line * 3, encoding="utf-8")
    assert _clear(backend).get_json() == {"ok": True}
    assert not (data / "egm_debug.log").exists(), "the log still lists the sites of past downloads"
    assert not (data / "egm_debug.log.old").exists(), "the rotated log still lists them"


def test_clear_history_leaves_the_users_other_files_alone(backend):
    data = backend.data_for_test
    for name in ("egm_settings.json", "cookies.txt", "egm_subscriptions.json"):
        (data / name).write_text("keep", encoding="utf-8")
    (data / "egm_debug.log").write_text("x", encoding="utf-8")
    _clear(backend)
    assert [p.read_text(encoding="utf-8") for p in (data / "egm_settings.json", data / "cookies.txt",
                                                    data / "egm_subscriptions.json")] == ["keep"] * 3


def test_clear_history_works_when_there_is_no_log(backend):
    assert _clear(backend).get_json() == {"ok": True}


def test_the_log_starts_again_after_a_clear(backend):
    """Clearing is not a switch: later lines are written to a new file, as before."""
    data = backend.data_for_test
    (data / "egm_debug.log").write_text("old\n", encoding="utf-8")
    _clear(backend)
    backend._egm_log("after the clear")
    text = (data / "egm_debug.log").read_text(encoding="utf-8")
    assert "after the clear" in text and "old" not in text


# ── The Console's output rings ───────────────────────────────────────────────────────────────

def _logs(mod, **query):
    return mod.app.test_client().get("/api/logs", query_string=query, headers={"X-EGM-Token": mod._API_TOKEN}).get_json()


def _all_ring_lines(mod, **query):
    """Every line the Console would show, across the four rings."""
    got = _logs(mod, yt=1, flask=1, ffmpeg=1, **query)
    return got, [e["m"] for key in ("lines", "yt_lines", "flask_lines", "ffmpeg_lines") for e in got[key]]


def _fill_rings(mod, marker):
    mod._yt_log(f"[generic] Extracting URL: https://example.com/watch?v={marker}")
    mod._flask_raw_log(f'127.0.0.1 - - "POST /api/download HTTP/1.1" 200 - {marker}')
    mod._egm_log(f"download started (video): example.com {marker}")
    mod._ffmpeg_log(f"Input #0, mov, from 'C:\\Users\\someone\\Videos\\{marker}.mp4':")


@pytest.mark.parametrize("ring", ["yt_lines", "flask_lines", "lines", "ffmpeg_lines"])
def test_clear_history_empties_each_of_the_four_console_rings(backend, ring):
    _fill_rings(backend, "ring-marker")
    before, _ = _all_ring_lines(backend)
    assert any("ring-marker" in e["m"] for e in before[ring]), "the test did not fill " + ring
    _clear(backend)
    after, _ = _all_ring_lines(backend)
    assert not any("ring-marker" in e["m"] for e in after[ring]), f"{ring} still lists a cleared download"


def test_an_open_console_goes_on_after_the_rings_are_emptied(backend):
    """The line counters keep counting: a Console already open asks for lines newer than the last one
    it saw, so a counter that went back to 0 would hide everything until it passed that number."""
    _fill_rings(backend, "before")
    seen, _ = _all_ring_lines(backend)
    _clear(backend)
    _fill_rings(backend, "after-the-clear")
    later, _ = _all_ring_lines(backend, since=seen["next"], yts=seen["yt_next"], fs=seen["flask_next"],
                               fm=seen["ffmpeg_next"])
    for key in ("lines", "yt_lines", "flask_lines", "ffmpeg_lines"):
        assert any("after-the-clear" in e["m"] for e in later[key]), f"{key} stopped delivering after the clear"


# ── Trimmed history ───────────────────────────────────────────────────────────────────────────

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


def test_the_thumbnail_of_an_entry_that_falls_off_the_end_of_history_is_removed(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_HISTORY_MAX", 3)
    _fake_thumbnails(backend, monkeypatch)
    for n in range(3):
        _add(backend, tmp_path, n)
    before = backend._load_history()
    assert len(before) == 3
    oldest, others = before[-1], before[:-1]
    assert (backend.THUMBNAILS_DIR / oldest["thumbnail"]).exists()

    _add(backend, tmp_path, 3)

    after = backend._load_history()
    assert len(after) == 3 and oldest["id"] not in [e["id"] for e in after]
    assert not (backend.THUMBNAILS_DIR / oldest["thumbnail"]).exists(), "the dropped entry's picture was left behind"
    for e in after:
        assert (backend.THUMBNAILS_DIR / e["thumbnail"]).exists(), "a kept entry lost its picture"
    assert {e["id"] for e in others} <= {e["id"] for e in after}


def test_below_the_cap_nothing_is_removed(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_HISTORY_MAX", 5)
    _fake_thumbnails(backend, monkeypatch)
    for n in range(5):
        _add(backend, tmp_path, n)
    assert len(list(backend.THUMBNAILS_DIR.iterdir())) == 5


def test_a_dropped_entry_with_a_hostile_thumbnail_name_cannot_remove_a_file_elsewhere(backend, tmp_path, monkeypatch):
    """An imported history file can set `thumbnail` to a path. Only a name of the shape the app writes
    is ever unlinked (the same rule the delete route and the serve route use)."""
    outside = backend.THUMBNAILS_DIR.parent / "cookies.txt"
    outside.write_text("keep", encoding="utf-8")
    absolute = tmp_path / "abs.jpg"
    absolute.write_text("keep", encoding="utf-8")
    evil = [{"id": f"e{i}", "url": "u", "title": "t", "thumbnail": t, "completed_at": "2026-01-01T00:00:00Z"}
            for i, t in enumerate(["../cookies.txt", str(absolute), "..\\cookies.txt", "a/b.jpg"])]
    backend.HISTORY_FILE.write_text(json.dumps(evil), encoding="utf-8")
    monkeypatch.setattr(backend, "_HISTORY_MAX", 1)
    _fake_thumbnails(backend, monkeypatch)
    _add(backend, tmp_path, 1)
    assert len(backend._load_history()) == 1
    assert outside.read_text(encoding="utf-8") == "keep"
    assert absolute.read_text(encoding="utf-8") == "keep"


def test_a_dropped_entry_without_a_thumbnail_is_fine(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_HISTORY_MAX", 1)
    old = [{"id": "e0", "url": "u", "title": "t", "thumbnail": "", "completed_at": "2026-01-01T00:00:00Z"},
           {"id": "e1", "url": "u", "title": "t", "completed_at": "2026-01-01T00:00:00Z"}]
    backend.HISTORY_FILE.write_text(json.dumps(old), encoding="utf-8")
    _fake_thumbnails(backend, monkeypatch)
    _add(backend, tmp_path, 9)
    assert len(backend._load_history()) == 1
