"""/api/playlist gives every entry a "vkey": the site plus the video id.

The page skips a link whose URL is already in the list. The same video can come
back under another URL (a Short as /shorts/ID in a channel list and as
watch?v=ID when pasted, music.youtube.com against www.youtube.com), so the page
also skips an entry whose vkey is already there (jsdom test add_while_running).
The key is empty when the site or the id is unknown, and for the Generic
extractor, whose ids are not stable: those fall back to the URL check alone."""
import json
import re
import types

from conftest import PLATFORM_APP_FILES, read_source


def _playlist(app_module, monkeypatch, *entries):
    out = "\n".join(json.dumps(e) for e in entries)
    fake = types.SimpleNamespace(returncode=0, stdout=out, stderr="")
    monkeypatch.setattr(app_module, "_ytdlp", lambda *a, **k: fake)
    with app_module.app.test_client() as client:
        r = client.post("/api/playlist", json={"url": "https://example.com/list"},
                        headers={"X-EGM-Token": app_module._API_TOKEN})
    assert r.status_code == 200
    return r.get_json()["entries"]


def test_a_playlist_entry_carries_site_and_id(app_module, monkeypatch):
    e = _playlist(app_module, monkeypatch,
                  {"id": "AbC123", "ie_key": "Youtube", "url": "https://www.youtube.com/shorts/AbC123", "title": "s"})
    assert e[0]["vkey"] == "youtube:AbC123"
    assert e[0]["url"] == "https://www.youtube.com/shorts/AbC123", "the url is untouched"


def test_a_single_video_dump_uses_extractor_key(app_module, monkeypatch):
    e = _playlist(app_module, monkeypatch,
                  {"id": "AbC123", "extractor_key": "Youtube", "webpage_url": "https://music.youtube.com/watch?v=AbC123"})
    assert e[0]["vkey"] == "youtube:AbC123"


def test_two_link_forms_of_one_video_get_the_same_key(app_module, monkeypatch):
    e = _playlist(app_module, monkeypatch,
                  {"id": "AbC123", "ie_key": "Youtube", "url": "https://www.youtube.com/shorts/AbC123"},
                  {"id": "AbC123", "extractor_key": "Youtube", "webpage_url": "https://www.youtube.com/watch?v=AbC123"},
                  {"id": "Other99", "ie_key": "Youtube", "url": "https://www.youtube.com/watch?v=Other99"})
    assert e[0]["vkey"] == e[1]["vkey"] != e[2]["vkey"]


def test_the_same_id_on_another_site_is_a_different_video(app_module, monkeypatch):
    e = _playlist(app_module, monkeypatch,
                  {"id": "1234", "ie_key": "Vimeo", "url": "https://vimeo.com/1234"},
                  {"id": "1234", "ie_key": "Dailymotion", "url": "https://www.dailymotion.com/video/1234"})
    assert e[0]["vkey"] != e[1]["vkey"]


def test_unknown_site_missing_id_or_generic_gives_no_key(app_module, monkeypatch):
    e = _playlist(app_module, monkeypatch,
                  {"id": "x", "url": "https://e.com/a"},
                  {"ie_key": "Youtube", "url": "https://e.com/b"},
                  {"id": "clip", "ie_key": "Generic", "url": "https://e.com/c.mp4"},
                  {"id": "", "ie_key": "Youtube", "url": "https://e.com/d"})
    assert [x["vkey"] for x in e] == ["", "", "", ""]


def _func_source(rel):
    m = re.search(r"^def _video_key\(.*?(?=^\S)", read_source(rel), re.S | re.M)
    assert m, f"{rel} has no _video_key"
    return m.group(0)


def test_all_three_backends_carry_the_same_function_and_use_it():
    assert len({_func_source(rel) for rel in PLATFORM_APP_FILES}) == 1, "the three backends must stay identical"
    for rel in PLATFORM_APP_FILES:
        assert '"vkey": _video_key(e)' in read_source(rel), rel
