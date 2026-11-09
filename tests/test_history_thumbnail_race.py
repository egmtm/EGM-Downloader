"""A download that finishes while Clear History runs never leaves a history entry whose picture is gone.

_append_history used to fetch and write the thumbnail outside _history_lock and only then add the
entry, and Clear History swept the thumbnails folder after releasing the lock. So a download could add
its entry (naming a picture it had just written) between the clear's emptying of the list and its
sweep: the sweep removed the picture and the entry showed a broken image.

Now the entry is written first, the picture is fetched with no lock held (no network I/O under the
history lock), and the picture is stored, and named in the entry, under the lock and only if the entry
is still there. Clear History sweeps the folder under the same lock. Whatever order the two run in,
every picture an entry names exists and no picture is left without its entry.

The interleavings are forced with events, on all three backends, through the real route and the
real _append_history; only the network (urllib's opener) and the DNS check are stand ins.
"""
import importlib.util
import os
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_thumb_race_" + path.split("/")[0], ROOT / path)
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


class _Gate(type(Path())):
    """The thumbnails folder, whose listing (Clear History's sweep) can be held at a gate."""
    gate = None

    def iterdir(self):
        g = _Gate.gate
        if g is not None:
            _Gate.gate = None
            g["reached"].set()
            assert g["release"].wait(10), "the test never released the sweep"
        return super().iterdir()


@pytest.fixture
def backend(backend_module, tmp_path, monkeypatch):
    mod = backend_module
    data = tmp_path / "data"
    thumbs = _Gate(data / "thumbnails")
    thumbs.mkdir(parents=True)
    monkeypatch.setattr(mod, "THUMBNAILS_DIR", thumbs)
    monkeypatch.setattr(mod, "HISTORY_FILE", data / "egm_history.json")
    if hasattr(mod, "DATA_DIR"):
        monkeypatch.setattr(mod, "DATA_DIR", data)
    else:
        monkeypatch.setattr(mod, "get_data_dir", lambda: data)
    monkeypatch.setattr(mod, "_sec_event", lambda *a: None)
    monkeypatch.setattr(mod, "_is_internal_host", lambda host: False)
    _Gate.gate = None
    yield mod
    _Gate.gate = None


class _Reply:
    """What urllib's opener returns: a JPEG from a public image server."""
    url = "https://cdn.example/x.jpg"
    headers = {"Content-Type": "image/jpeg", "Content-Length": str(len(JPEG))}

    def read(self, n=-1):
        return JPEG

    def close(self):
        pass


def _network(monkeypatch, on_fetch=None):
    """Every urllib request (urlopen and build_opener().open both go through OpenerDirector.open)
    answers the JPEG, after on_fetch() returns."""
    def fake_open(self, fullurl, data=None, timeout=None):
        if on_fetch:
            on_fetch()
        return _Reply()
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)


def _job(tmp_path, n=0):
    f = tmp_path / f"v{n}.mp4"
    f.write_bytes(b"x")
    return {"url": f"https://video.example/{n}", "title": f"t{n}", "thumbnail": "https://cdn.example/x.jpg",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0 Safari/537.36"}, f


def _clear(mod):
    r = mod.app.test_client().post("/api/history/clear", headers={"X-EGM-Token": mod._API_TOKEN})
    assert r.status_code == 200


def _consistent(mod):
    """Every picture an entry names exists, and every picture in the folder belongs to an entry."""
    items = mod._load_history()
    named = {e["thumbnail"] for e in items if e.get("thumbnail")}
    files = set(os.listdir(mod.THUMBNAILS_DIR))
    assert named <= files, f"an entry names a picture that is gone: {sorted(named - files)}"
    assert files <= named, f"a picture is left without its entry: {sorted(files - named)}"
    return items


def test_a_download_finishing_between_the_clear_and_its_sweep_keeps_its_picture(backend, tmp_path, monkeypatch):
    """The reported race: Clear History has emptied the list when a download adds its entry and picture."""
    _network(monkeypatch)
    gate = {"reached": threading.Event(), "release": threading.Event()}
    _Gate.gate = gate
    clear = threading.Thread(target=_clear, args=(backend,))
    clear.start()
    assert gate["reached"].wait(10), "Clear History never reached its sweep"
    job, f = _job(tmp_path)
    done = threading.Event()
    adder = threading.Thread(target=lambda: (backend._append_history(job, f), done.set()))
    adder.start()
    done.wait(1.0)             # the old code finished here; the new one waits for the clear's lock
    gate["release"].set()
    clear.join(10)
    adder.join(10)
    assert not clear.is_alive() and not adder.is_alive()
    items = _consistent(backend)
    assert len(items) == 1 and items[0]["thumbnail"], "the download that came after the clear lost its entry or picture"


def test_a_picture_that_arrives_after_the_clear_is_not_written(backend, tmp_path, monkeypatch):
    """The other order: the picture is still being fetched when Clear History runs. No lock is held
    while it is fetched (no network I/O under the history lock)."""
    in_fetch, release, seen = threading.Event(), threading.Event(), {}

    def on_fetch():
        seen["lock_held"] = backend._history_lock.locked()
        in_fetch.set()
        assert release.wait(10)
    _network(monkeypatch, on_fetch)
    job, f = _job(tmp_path)
    adder = threading.Thread(target=backend._append_history, args=(job, f))
    adder.start()
    assert in_fetch.wait(10), "the picture was never fetched"
    assert seen["lock_held"] is False, "the picture is fetched while the history lock is held"
    _clear(backend)
    release.set()
    adder.join(10)
    _consistent(backend)


def test_a_picture_is_stored_only_for_an_entry_that_is_still_there(backend, tmp_path, monkeypatch):
    """Deleted, dropped by the cap or replaced by an import while its picture was on the way."""
    _network(monkeypatch)
    for gone in ("delete", "import", "cap"):
        in_fetch, release = threading.Event(), threading.Event()
        _network(monkeypatch, lambda: (in_fetch.set(), release.wait(10)))
        job, f = _job(tmp_path, gone)
        adder = threading.Thread(target=backend._append_history, args=(job, f))
        adder.start()
        assert in_fetch.wait(10)
        c = backend.app.test_client()
        h = {"X-EGM-Token": backend._API_TOKEN}
        if gone == "delete":
            (entry,) = [e for e in backend._load_history() if e["title"] == f"t{gone}"]
            assert c.delete(f"/api/history/{entry['id']}", headers=h).status_code == 200
        elif gone == "import":
            assert c.post("/api/history/import", json={"items": []}, headers=h).status_code == 200
        else:
            monkeypatch.setattr(backend, "_HISTORY_MAX", 1)
            _network(monkeypatch)
            backend._append_history(*_job(tmp_path, "newer"))
        release.set()
        adder.join(10)
        items = _consistent(backend)
        assert all(e["title"] != f"t{gone}" for e in items)


def test_a_download_with_no_race_still_gets_its_picture(backend, tmp_path, monkeypatch):
    _network(monkeypatch)
    backend._append_history(*_job(tmp_path))
    (entry,) = _consistent(backend)
    assert entry["thumbnail"] == entry["id"] + ".jpg"
    assert (Path(backend.THUMBNAILS_DIR) / entry["thumbnail"]).read_bytes() == JPEG


def test_the_store_itself_checks_the_picture_and_the_name(backend, tmp_path, monkeypatch):
    """_attach_thumbnail checks again whatever its caller did: at most the cap, a JPEG, PNG or WebP by
    its first bytes, and a stored name of the one shape the serve and delete routes accept. An imported
    entry id can be [A-Za-z0-9_-]; such an id gets no picture file."""
    _network(monkeypatch)
    backend._append_history(*_job(tmp_path))
    c = backend.app.test_client()
    h = {"X-EGM-Token": backend._API_TOKEN}
    items = [{"id": "e1", "title": "plain"}, {"id": "ABC_def", "title": "imported"}]
    assert c.post("/api/history/import", json={"items": items}, headers=h).status_code == 200
    big = JPEG + b"\x00" * (backend._THUMB_CAP + 1 - len(JPEG))
    assert backend._attach_thumbnail("e1", big) is False, "over the cap"
    assert backend._attach_thumbnail("e1", b"<html></html>") is False, "not a picture"
    assert backend._attach_thumbnail("ABC_def", JPEG) is False, "a name the serve route would refuse"
    assert backend._attach_thumbnail("e1", big[:backend._THUMB_CAP]) is True
    assert os.listdir(backend.THUMBNAILS_DIR) == ["e1.jpg"]
    assert [e.get("thumbnail") for e in backend._load_history()] == ["e1.jpg", ""]
