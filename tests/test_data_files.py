"""The app's own data files: wrong content is survived, and nothing in them is lost silently.

* A history file holding valid JSON that is not a list ({} or null) made /api/history answer
  500, and new entries were dropped without a word; a subscriptions file whose "subscriptions"
  is not a list of objects made every subscriptions route answer 500.
* A file that could not be parsed was treated as empty and replaced by the next save, so a hand
  edit with one stray character lost the whole history. A copy is now kept as <name>.unreadable.
* A settings save made before the file had been read wrote only the new keys and dropped the rest.
"""
import importlib.util
import json
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
            "egm_data_files_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture
def files(backend, tmp_path, monkeypatch):
    for name in ("SETTINGS_FILE", "HISTORY_FILE", "SUBS_FILE"):
        monkeypatch.setattr(backend, name, tmp_path / Path(getattr(backend, name)).name)
    monkeypatch.setattr(backend, "THUMBNAILS_DIR", tmp_path / "thumbnails")
    monkeypatch.setattr(backend, "_settings_cache", {})
    monkeypatch.setattr(backend, "_subs_cache", None)
    monkeypatch.setattr(backend, "_download_thumbnail", lambda *a: "")
    client = backend.app.test_client()
    headers = {"X-EGM-Token": backend._API_TOKEN}
    return backend, client, headers


@pytest.mark.parametrize("content", ["{}", "null", '"text"', "5"])
def test_a_history_file_that_is_not_a_list_reads_as_empty(files, content):
    backend, client, headers = files
    backend.HISTORY_FILE.write_text(content)
    r = client.get("/api/history", headers=headers)
    assert r.status_code == 200 and r.get_json()["items"] == []
    backend._append_history({"url": "https://example.invalid/v", "title": "t"}, backend.HISTORY_FILE.parent / "x.mp4")
    assert len(client.get("/api/history", headers=headers).get_json()["items"]) == 1


def test_a_damaged_history_file_is_kept_before_it_is_replaced(files):
    backend, client, headers = files
    damaged = '[{"id": "a", "title": "old 1"}, {"id": "b", "title": "old 2"}] x'
    backend.HISTORY_FILE.write_text(damaged)
    backend._append_history({"url": "https://example.invalid/v", "title": "new"}, backend.HISTORY_FILE.parent / "x.mp4")
    backup = backend.HISTORY_FILE.with_name(backend.HISTORY_FILE.name + ".unreadable")
    assert backup.read_text() == damaged
    assert [i["title"] for i in json.loads(backend.HISTORY_FILE.read_text())] == ["new"]


def test_clear_history_also_removes_the_kept_copy_of_a_damaged_history_file(files):
    backend, client, headers = files
    backend.HISTORY_FILE.write_text('[{"id": "a", "title": "old"}] x')
    backend._append_history({"url": "https://example.invalid/v", "title": "new"}, backend.HISTORY_FILE.parent / "x.mp4")
    backup = backend.HISTORY_FILE.with_name(backend.HISTORY_FILE.name + ".unreadable")
    other = backend.SUBS_FILE.with_name(backend.SUBS_FILE.name + ".unreadable")
    other.write_text("{x")                                      # the subscriptions copy is not history
    assert backup.exists()
    assert client.post("/api/history/clear", headers=headers).get_json() == {"ok": True}
    assert not backup.exists(), "the damaged file's copy survived Clear history"
    assert other.exists()
    assert client.get("/api/history", headers=headers).get_json()["items"] == []


def test_reset_settings_also_removes_the_kept_copy_of_a_damaged_settings_file(files):
    backend, client, headers = files
    backend.SETTINGS_FILE.write_text("[1, 2]")
    client.post("/api/settings/save", json={"quit_on_done": True}, headers=headers)
    backup = backend.SETTINGS_FILE.with_name(backend.SETTINGS_FILE.name + ".unreadable")
    history_copy = backend.HISTORY_FILE.with_name(backend.HISTORY_FILE.name + ".unreadable")
    history_copy.write_text("[x")                               # the history copy is not settings
    assert backup.exists()
    assert client.post("/api/settings/reset", headers=headers).get_json() == {"ok": True}
    assert not backup.exists(), "the damaged file's copy survived Reset settings"
    assert history_copy.exists()
    assert json.loads(backend.SETTINGS_FILE.read_text()) == {}


def test_reset_settings_without_a_kept_copy_still_works(files):
    backend, client, headers = files
    client.post("/api/settings/save", json={"quit_on_done": True}, headers=headers)
    assert client.post("/api/settings/reset", headers=headers).get_json() == {"ok": True}
    assert json.loads(backend.SETTINGS_FILE.read_text()) == {}


def test_clear_history_without_a_kept_copy_still_works(files):
    backend, client, headers = files
    backend._append_history({"url": "https://example.invalid/v", "title": "t"}, backend.HISTORY_FILE.parent / "x.mp4")
    assert client.post("/api/history/clear", headers=headers).get_json() == {"ok": True}
    assert client.get("/api/history", headers=headers).get_json()["items"] == []


@pytest.mark.parametrize("content", ['{"subscriptions": {"a": 1}}', '{"subscriptions": [1, "x"]}', "[]", "{x"])
def test_a_subscriptions_file_with_the_wrong_shape_reads_as_empty_and_is_kept(files, content):
    backend, client, headers = files
    backend.SUBS_FILE.write_text(content)
    r = client.get("/api/subscriptions", headers=headers)
    assert r.status_code == 200, r.status_code
    assert backend.SUBS_FILE.with_name(backend.SUBS_FILE.name + ".unreadable").read_text() == content


def test_a_settings_save_before_any_read_keeps_the_other_settings(files):
    backend, client, headers = files
    backend.SETTINGS_FILE.write_text(json.dumps({"theme": "aurora-deep", "concurrency": 4, "language": "de"}))
    assert client.post("/api/settings/save", json={"quit_on_done": True}, headers=headers).status_code == 200
    stored = json.loads(backend.SETTINGS_FILE.read_text())
    assert stored == {"theme": "aurora-deep", "concurrency": 4, "language": "de", "quit_on_done": True}


def test_a_settings_file_that_is_not_an_object_does_not_stop_saving(files):
    backend, client, headers = files
    backend.SETTINGS_FILE.write_text("[1, 2]")
    client.post("/api/settings/save", json={"quit_on_done": True}, headers=headers)
    assert json.loads(backend.SETTINGS_FILE.read_text()) == {"quit_on_done": True}
    assert backend.SETTINGS_FILE.with_name(backend.SETTINGS_FILE.name + ".unreadable").read_text() == "[1, 2]"
