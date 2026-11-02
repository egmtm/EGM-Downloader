"""Unusual input to the local API gets a clean 4xx, and nothing invalid is stored.

Found by sending every route wrong types, empty, very long and control-character values, path
values and parallel calls (all three backends, through the test client with the network, child
processes and background work stubbed). Before the fixes:
  * a JSON body that is a list, a number or a string answered 500 on about twenty routes;
  * a number, list, object or null where a route expects text answered 500 on about fifteen
    (url, id, name, folder, job_id, content, format_id, audio_quality, quality ...);
  * a 1 MB folder name or a null character in a rename answered 500;
  * two settings resets at once answered 500 (one temporary file for both);
  * /api/settings/save stored any type for most keys, and /api/history/import stored any entry
    that had an "id" (markup in the format or thumbnail, a number as the thumbnail name, which
    then made deleting that entry answer 500).
Every data file of the app is moved into tmp_path here; nothing is fetched or started.
"""
import importlib.util
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")
NON_TEXT = [123, 1.5, True, [], ["x"], {"a": 1}]


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
            "egm_unusual_input_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def api(backend, tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    for name in ("SETTINGS_FILE", "HISTORY_FILE", "SUBS_FILE", "COOKIES_FILE"):
        monkeypatch.setattr(backend, name, data / Path(getattr(backend, name)).name)
    monkeypatch.setattr(backend, "THUMBNAILS_DIR", data / "thumbnails")
    monkeypatch.setattr(backend, "_settings_cache", {})
    monkeypatch.setattr(backend, "_subs_cache", None)

    def offline(*a, **k):
        raise backend.urllib.error.URLError("offline")
    monkeypatch.setattr(backend, "_safe_urlopen", offline)
    for name in ("_run_download_slot", "_run_update", "_run_deno_install", "_run_subfetch"):
        if hasattr(backend, name):
            monkeypatch.setattr(backend, name, lambda *a, **k: None)
    monkeypatch.setattr(backend, "_ytdlp", lambda *a, **k: subprocess.CompletedProcess([], 1, "", "offline"))
    for name in ("_popen", "_popen_yt"):
        monkeypatch.setattr(backend, name, lambda *a, **k: None)
    client = backend.app.test_client()
    headers = {"X-EGM-Token": backend._API_TOKEN}

    class Api:
        mod = backend
        dl = tmp_path / "downloads"

        def post(self, path, body=None, raw=None):
            if raw is not None:
                return client.post(path, data=raw, content_type="application/json", headers=headers)
            return client.post(path, json=body, headers=headers)

        def get(self, path):
            return client.get(path, headers=headers)

        def delete(self, path):
            return client.delete(path, headers=headers)
    Api.dl.mkdir()
    return Api()


def _post_routes(mod):
    return sorted(r.rule for r in mod.app.url_map.iter_rules()
                  if "POST" in r.methods and r.rule != "/api/shutdown" and "<" not in r.rule)


@pytest.mark.parametrize("raw", ["[1, 2]", "5", '"text"', "true"])
def test_a_json_body_that_is_not_an_object_is_a_bad_request_on_every_route(api, raw):
    answers = {path: api.post(path, raw=raw).status_code for path in _post_routes(api.mod)}
    assert len(answers) > 20
    assert {p: c for p, c in answers.items() if c != 400} == {}


def test_without_the_token_the_answer_is_still_forbidden(api):
    r = api.mod.app.test_client().post("/api/settings/save", data="[1]", content_type="application/json")
    assert r.status_code == 403


def _fixtures(api):
    done = api.dl / "clip.mp4"
    done.write_bytes(b"x")
    api.mod.jobs["jdone"] = {"status": "done", "file": str(done), "filename": done.name}
    sid = api.post("/api/subscriptions/add", {"url": "https://example.invalid/c", "name": "n"}).get_json()
    sid = (sid.get("subscription") or sid).get("id")
    assert sid

    def add_video(subs):
        for s in subs:
            if s["id"] == sid:
                s["videos"] = [{"video_id": "vid00000001", "title": "t", "downloaded": False}]
        return True
    api.mod._mutate_subscriptions(add_video)
    return sid


def test_a_non_text_value_where_text_is_expected_is_a_bad_request(api):
    sid = _fixtures(api)
    cases = [
        ("/api/info", {"url": "https://example.invalid/v"}, "url"),
        ("/api/playlist", {"url": "https://example.invalid/p"}, "url"),
        ("/api/download", {"url": "https://example.invalid/v", "download_dir": str(api.dl)}, "url"),
        ("/api/download", {"url": "https://example.invalid/v", "download_dir": str(api.dl)}, "format_id"),
        ("/api/download", {"url": "https://example.invalid/v", "download_dir": str(api.dl)}, "audio_quality"),
        ("/api/rename", {"job_id": "jdone", "name": "n"}, "job_id"),
        ("/api/rename", {"job_id": "jdone", "name": "n"}, "name"),
        ("/api/open-folder", {"folder": str(api.dl)}, "folder"),
        ("/api/cookies/save", {"content": "# Netscape HTTP Cookie File\n"}, "content"),
        ("/api/subscriptions/add", {"url": "https://example.invalid/c2", "name": "n"}, "url"),
        ("/api/subscriptions/add", {"url": "https://example.invalid/c3", "name": "n"}, "name"),
        ("/api/subscriptions/update", {"id": sid, "name": "n"}, "id"),
        ("/api/subscriptions/update", {"id": sid, "quality": "best"}, "quality"),
        ("/api/subscriptions/fetch", {"id": sid}, "id"),
        ("/api/subscriptions/fetch-status", {"fetch_id": "f"}, "fetch_id"),
        ("/api/subscriptions/mark-downloaded", {"sub_id": sid, "video_id": "vid00000001"}, "sub_id"),
        ("/api/subscriptions/mark-downloaded", {"sub_id": sid, "video_id": "vid00000001"}, "video_id"),
        ("/api/subscriptions/mark-all-seen", {"id": sid}, "id"),
        ("/api/subscriptions/reorder", {"id": sid, "direction": "up"}, "id"),
        ("/api/subscriptions/reorder", {"id": sid, "direction": "up"}, "direction"),
        ("/api/subscriptions/remove", {"id": sid}, "id"),
    ]
    if hasattr(api.mod, "UPDATE_TMP_DIR"):
        cases += [("/api/download-update", {"zip_url": "https://egerena.com/a.zip", "expected_checksum": "ab" * 32}, k)
                  for k in ("zip_url", "expected_checksum")]
    errors = {}
    for path, base, key in cases:
        for value in NON_TEXT + [None]:
            r = api.post(path, dict(base, **{key: value}))
            if r.status_code >= 500:
                errors.setdefault(f"{path} {key}", []).append(repr(value))
    assert errors == {}


def test_a_folder_name_too_long_for_the_system_is_not_found_not_an_error(api):
    r = api.post("/api/open-folder", {"folder": "A" * (1024 * 1024)})
    assert r.status_code == 400


def test_a_null_character_in_a_new_name_is_refused_and_the_file_stays(api):
    _fixtures(api)
    r = api.post("/api/rename", {"job_id": "jdone", "name": "a\x00b"})
    assert r.status_code == 400
    assert (api.dl / "clip.mp4").exists()


def test_settings_keep_the_type_the_page_writes(api):
    good = {"concurrency": 6, "fragments": 4, "theme": "aurora-deep", "quit_on_done": True,
            "output_format": "mkv", "default_audio_format": "opus_192", "yt_dlp_channel": "nightly",
            "ffmpeg_channel": "stable", "window_bounds": {"x": 10, "y": 20, "width": 900, "height": 700},
            "last_seen_version": "1.5.2.1", "random_theme_scope": "all"}
    assert api.post("/api/settings/save", good).status_code == 200
    bad = {"concurrency": "abc", "fragments": [4], "theme": "bad theme<b>", "quit_on_done": "",
           "output_format": ["mkv"], "default_audio_format": "x" * 1000, "yt_dlp_channel": "beta",
           "ffmpeg_channel": None, "window_bounds": "big", "last_seen_version": "<i>",
           "random_theme_scope": None, "subtitles": {"a": 1}}
    assert api.post("/api/settings/save", bad).status_code == 200
    stored = json.loads(api.mod.SETTINGS_FILE.read_text(encoding="utf-8"))
    expect = dict(good, quit_on_done=False, subtitles=True)
    assert {k: stored.get(k) for k in expect} == expect
    assert api.post("/api/settings/save", {"concurrency": 999, "fragments": "8"}).status_code == 200
    stored = json.loads(api.mod.SETTINGS_FILE.read_text(encoding="utf-8"))
    assert (stored["concurrency"], stored["fragments"]) == (20, 8)


def test_settings_resets_and_saves_at_the_same_time_all_succeed_and_leave_valid_json(api):
    codes = []

    def reset():
        codes.append(api.post("/api/settings/reset", {}).status_code)

    def save(i):
        codes.append(api.post("/api/settings/save", {"concurrency": 2 + (i % 5) * 2}).status_code)
    threads = [threading.Thread(target=reset) for _ in range(8)] + \
              [threading.Thread(target=save, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert codes.count(200) == 16, codes
    json.loads(api.mod.SETTINGS_FILE.read_text(encoding="utf-8"))
    assert not list(api.mod.SETTINGS_FILE.parent.glob("*.tmp"))


def test_imported_history_keeps_only_well_formed_fields(api):
    items = [
        {"id": "a1", "title": "fine", "url": "https://example.invalid/v", "format": "mp4", "size_bytes": 10,
         "thumbnail": "0123abcd-ef.jpg", "completed_at": "2026-01-01T00:00:00Z", "extra": "x"},
        {"id": "a2", "title": "t", "format": '<img src=x onerror=alert(1)>', "size_bytes": "<b>1</b>",
         "thumbnail": 'x"><img src=y>'},
        {"id": "a3", "thumbnail": 123, "format": 5},
        {"id": 7, "title": "number id"},
        {"id": "../../x", "title": "path id"},
        "not an entry",
    ]
    r = api.post("/api/history/import", {"items": items})
    assert r.status_code == 200 and r.get_json()["count"] == 3
    stored = {e["id"]: e for e in api.get("/api/history?per_page=50").get_json()["items"]}
    assert set(stored) == {"a1", "a2", "a3"}
    assert stored["a1"] == {k: v for k, v in items[0].items() if k != "extra"}
    assert "format" not in stored["a2"] and "size_bytes" not in stored["a2"] and stored["a2"]["thumbnail"] == ""
    assert stored["a3"]["thumbnail"] == "" and "format" not in stored["a3"]
    for eid in ("a1", "a2", "a3"):
        assert api.delete(f"/api/history/{eid}").status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("shell", ["windows", "mac", "linux"])
def test_the_shell_writes_settings_through_its_own_temporary_file(shell, tmp_path):
    """The backend replaces egm_settings.json through egm_settings.json.tmp. The shell writes the
    same file; with the same temporary name the two could rename each other's half written copy."""
    src = (ROOT / shell / "electron" / "main.js").read_text(encoding="utf-8")
    start = src.index("function atomicWriteJson(")
    body = src[start: src.index("\n}\n", start) + 3]
    target = tmp_path / "egm_settings.json"
    script = (f"const fs = require('fs'); const used = [];\n"
              f"const real = fs.writeFileSync; fs.writeFileSync = (p, ...a) => {{ used.push(p); return real(p, ...a); }};\n"
              f"{body}\natomicWriteJson({json.dumps(str(target))}, {{a: 1}});\n"
              f"process.stdout.write(JSON.stringify(used));")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    used = json.loads(out.stdout)
    assert used and all(p != str(target) + ".tmp" for p in used), used
    assert json.loads(target.read_text()) == {"a": 1}
