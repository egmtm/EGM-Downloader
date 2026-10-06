"""The info route returns a short list of thumbnail candidates.

Some live streams point at a thumbnail that does not exist yet, which left a
broken image on the card. /api/info now returns "thumbnails": the one yt-dlp
chose first, then its other entries best first, https only, with the same
breakout checks as _safe_thumb_url. The page tries them in order (jsdom test
card_layout_thumb)."""
import json
import re
import types

import pytest

from conftest import PLATFORM_APP_FILES, read_source


def _info(**kw):
    base = {"title": "T", "thumbnail": "https://cdn.example/best.jpg", "formats": [], "is_live": True}
    base.update(kw)
    return base


def _post_info(app_module, monkeypatch, info):
    fake = types.SimpleNamespace(returncode=0, stdout=json.dumps(info), stderr="")
    monkeypatch.setattr(app_module, "_ytdlp", lambda *a, **k: fake)
    with app_module.app.test_client() as client:
        r = client.post("/api/info", json={"url": "https://example.com/live"},
                        headers={"X-EGM-Token": app_module._API_TOKEN})
    assert r.status_code == 200
    return r.get_json()


def test_the_chosen_thumbnail_comes_first_then_the_others_best_first(app_module, monkeypatch):
    info = _info(thumbnails=[{"url": "https://cdn.example/low.jpg"}, {"url": "https://cdn.example/mid.jpg"},
                             {"url": "https://cdn.example/best.jpg"}])
    d = _post_info(app_module, monkeypatch, info)
    assert d["thumbnails"] == ["https://cdn.example/best.jpg", "https://cdn.example/mid.jpg", "https://cdn.example/low.jpg"]
    assert d["thumbnail"] == "https://cdn.example/best.jpg", "the old field stays"


def test_only_safe_https_urls_are_offered_without_duplicates_and_capped(app_module, monkeypatch):
    bad = ["http://cdn.example/plain.jpg", "javascript:alert(1)", 'https://cdn.example/a"b.jpg',
           "https://cdn.example/a b.jpg", "https://cdn.example/a(1).jpg", "", None, 5]
    many = [{"url": f"https://cdn.example/{i}.jpg"} for i in range(20)]
    info = _info(thumbnails=[{"url": u} for u in bad] + [{"url": "https://cdn.example/best.jpg"}] + many + ["not a dict"])
    out = _post_info(app_module, monkeypatch, info)["thumbnails"]
    assert out[0] == "https://cdn.example/best.jpg"
    assert len(out) == 8 and len(set(out)) == 8
    assert all(u.startswith("https://") and not any(c in u for c in "\"'<> ()") for u in out)


def test_a_video_without_any_thumbnail_returns_an_empty_list(app_module, monkeypatch):
    d = _post_info(app_module, monkeypatch, _info(thumbnail=None))
    assert d["thumbnails"] == []


def _func_source(rel):
    src = read_source(rel)
    m = re.search(r"^def _thumb_candidates\(.*?(?=^\S)", src, re.S | re.M)
    assert m, f"{rel} has no _thumb_candidates"
    return m.group(0)


def test_all_three_backends_carry_the_same_function_and_use_it():
    sources = {rel: _func_source(rel) for rel in PLATFORM_APP_FILES}
    assert len(set(sources.values())) == 1, "the three backends must stay identical"
    for rel in PLATFORM_APP_FILES:
        assert '"thumbnails": _thumb_candidates(info)' in read_source(rel), rel
