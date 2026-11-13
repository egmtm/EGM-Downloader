"""In the shell, the picture of a finished download is fetched by Chromium in the main process, not by Python.

The backend's side, on all three backends (with EGM_ELECTRON, so _SHELL_FETCHES_THUMBNAILS, set):

* when a download finishes, its history entry is written at once without a picture, and the backend
  waits for the shell: the page's /api/status answer names the entry in X-EGM-Thumbnail (the shell's
  main process reads it; tests/frontend/thumbnail_fetch.test.mjs runs that side);
* GET /api/history/<id>/thumbnail gives the shell the URL, only while it is waited for;
* POST /api/history/<id>/thumbnail takes the bytes. Token protected like the other routes; the name
  must be an entry id the backend waits for (no file is ever written under another name); the body
  is checked again whatever the shell says (at most 500 KB, a JPEG, PNG or WebP by its first bytes)
  and stored under the name rule; only an HTTPS URL with no breakout characters is ever waited for;
* when the shell cannot fetch it (an empty body), sends something that is not a usable picture, or
  has not answered after _THUMB_WAIT seconds, the backend fetches it itself, with yt-dlp's agent;
* Clear History stops the wait: nothing is fetched afterwards for what it cleared.

The last test compares the shell's address check with the backend's: the shell refuses at least
every address the backend refuses.
"""
import importlib.util
import io
import ipaddress
import json
import re
import subprocess
import time
import urllib.parse
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
JOB = "5eedf00d01"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_shell_thumb_" + path.split("/")[0], ROOT / path)
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
    """In the shell: the backend waits for the shell's picture (a long wait, unless a test shortens it).
    Its own fetch is a stand in that records what it was asked and answers a JPEG."""
    mod = backend_module
    data = tmp_path / "data"
    (data / "thumbnails").mkdir(parents=True)
    monkeypatch.setattr(mod, "THUMBNAILS_DIR", data / "thumbnails")
    monkeypatch.setattr(mod, "HISTORY_FILE", data / "egm_history.json")
    if hasattr(mod, "DATA_DIR"):
        monkeypatch.setattr(mod, "DATA_DIR", data)
    else:
        monkeypatch.setattr(mod, "get_data_dir", lambda: data)
    monkeypatch.setattr(mod, "_sec_event", lambda *a: None)
    monkeypatch.setattr(mod, "_SHELL_FETCHES_THUMBNAILS", True)
    monkeypatch.setattr(mod, "_THUMB_WAIT", 3600)
    mod.backend_fetches = []

    def own_fetch(url, user_agent):
        mod.backend_fetches.append((url, user_agent))
        return JPEG
    monkeypatch.setattr(mod, "_fetch_thumbnail", own_fetch)
    mod._thumb_pending.clear()
    yield mod
    mod._thumb_pending.clear()
    mod.jobs.pop(JOB, None)


def _token(mod):
    return {"X-EGM-Token": mod._API_TOKEN}


def _finish(mod, tmp_path, thumbnail="https://cdn.example/vi/x/hq.jpg"):
    """A download finishes: the job as run_download leaves it, and its history entry."""
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    job = {"status": "converting", "url": "https://video.example/v", "title": "t", "thumbnail": thumbnail, "user_agent": UA}
    mod.jobs[JOB] = job
    mod._append_history(job, f)
    job["status"] = "done"
    return mod._load_history()[0]["id"]        # newest first


def _url(entry):
    return f"/api/history/{entry}/thumbnail"


def _wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


# ── the shell is told, and given the URL ──────────────────────────────────────────────────────

def test_the_status_answer_names_the_entry_and_the_backend_fetches_nothing_itself(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    r = backend.app.test_client().get(f"/api/status/{JOB}", headers=_token(backend))
    assert r.get_json()["status"] == "done"
    assert r.headers.get("X-EGM-Thumbnail") == entry
    assert backend.backend_fetches == [], "the backend fetched the picture although the shell will"
    assert backend._load_history()[0]["thumbnail"] == "", "the entry is there at once, its picture comes later"


def test_the_shell_is_given_the_url_only_while_it_is_waited_for(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    c = backend.app.test_client()
    assert c.get(_url(entry), headers=_token(backend)).get_json() == {"url": "https://cdn.example/vi/x/hq.jpg"}
    assert c.get(_url(entry)).status_code == 403, "without the per run token"
    assert c.get(_url("0" * 36), headers=_token(backend)).status_code == 404, "an entry nobody waits for"
    assert c.post(_url(entry), data=JPEG, headers=_token(backend)).status_code == 200
    assert c.get(_url(entry), headers=_token(backend)).status_code == 404, "still given after it was delivered"
    assert entry not in backend._thumb_pending, "still waited for: the backend would fetch it again when the wait ends"
    assert "X-EGM-Thumbnail" not in c.get(f"/api/status/{JOB}", headers=_token(backend)).headers


# ── the receiving endpoint ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body, ext", [(JPEG, ".jpg"), (PNG, ".png"), (WEBP, ".webp")])
def test_a_good_picture_is_stored_under_the_name_rule(backend, tmp_path, body, ext):
    entry = _finish(backend, tmp_path)
    r = backend.app.test_client().post(_url(entry), data=body, headers=_token(backend))
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    (stored,) = backend._load_history()
    assert stored["thumbnail"] == entry + ext
    assert (backend.THUMBNAILS_DIR / stored["thumbnail"]).read_bytes() == body
    assert backend.backend_fetches == []
    served = backend.app.test_client().get(f"/api/thumbnail/{stored['thumbnail']}")
    assert served.status_code == 200 and served.data == body


def test_a_picture_without_the_token_is_refused(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    for headers in ({}, {"X-EGM-Token": "not-this-run"}):
        assert backend.app.test_client().post(_url(entry), data=JPEG, headers=headers).status_code == 403
    assert backend._load_history()[0]["thumbnail"] == "" and list(backend.THUMBNAILS_DIR.iterdir()) == []
    assert entry in backend._thumb_pending, "a refused caller must not end the wait"


@pytest.mark.parametrize("body", [b"<html>not an image</html>", b"GIF89a" + b"\x00" * 32, b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                                  b"\x00\xd8\xff" + JPEG, b"RIFF\x00\x00\x00\x00WAVE"])
def test_a_body_that_is_not_a_picture_is_refused_and_the_backend_fetches_it_itself(backend, tmp_path, body):
    entry = _finish(backend, tmp_path)
    r = backend.app.test_client().post(_url(entry), data=body, headers=_token(backend))
    assert r.status_code == 400
    assert _wait_for(lambda: backend._load_history()[0]["thumbnail"]), "the backend did not fetch it itself"
    assert backend.backend_fetches == [("https://cdn.example/vi/x/hq.jpg", UA)]
    assert (backend.THUMBNAILS_DIR / (entry + ".jpg")).read_bytes() == JPEG, "the refused body was stored"


def test_a_body_over_the_cap_is_refused_without_being_read_into_a_file(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    c = backend.app.test_client()
    big = JPEG + b"\x00" * (backend._THUMB_CAP + 1 - len(JPEG))
    r = c.post(_url(entry), data=big, headers=_token(backend))
    assert r.status_code == 413
    assert _wait_for(lambda: backend._load_history()[0]["thumbnail"]), "the backend did not fetch it itself"
    assert backend.backend_fetches == [("https://cdn.example/vi/x/hq.jpg", UA)]
    assert (backend.THUMBNAILS_DIR / (entry + ".jpg")).read_bytes() == JPEG, "the oversized body was stored"
    exact = _finish(backend, tmp_path)
    assert c.post(_url(exact), data=big[:backend._THUMB_CAP], headers=_token(backend)).status_code == 200, "exactly the cap is fine"


@pytest.mark.parametrize("name", ["ABCDEF", "..", "x.jpg", "3f2c1a9e%2F..%2Fcookies", "a" * 65, "%2e%2e", "-" * 70])
def test_a_bad_name_writes_nothing_anywhere(backend, tmp_path, name):
    """A name that is not an entry id is refused by the route's own rule, whatever the wait list holds:
    the name is planted there (the shape a lookup of the raw and the decoded path would find), so a
    route that only looked the name up would answer the GET with 200 and fail here. The GET comes
    first: a POST that reached the lookup would take the planted name out of the list (the store
    refuses it again by the name rule), and a GET after it could not tell."""
    _finish(backend, tmp_path)
    planted = {name, urllib.parse.unquote(name)}
    for key in planted:
        backend._thumb_pending[key] = ("https://cdn.example/vi/x/hq.jpg", UA)
    c = backend.app.test_client()
    assert c.get(f"/api/history/{name}/thumbnail", headers=_token(backend)).status_code == 404
    assert c.post(f"/api/history/{name}/thumbnail", data=JPEG, headers=_token(backend)).status_code == 404
    assert planted <= set(backend._thumb_pending), "the route touched the wait list before the name rule"
    assert list(backend.THUMBNAILS_DIR.iterdir()) == []
    assert sorted(p.name for p in backend.THUMBNAILS_DIR.parent.iterdir()) == ["egm_history.json", "thumbnails"]


def test_an_entry_id_nobody_waits_for_cannot_be_given_a_picture(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    c = backend.app.test_client()
    for other in ("0" * 36, entry[:-1] + ("0" if entry[-1] != "0" else "1")):
        assert c.post(_url(other), data=JPEG, headers=_token(backend)).status_code == 404
    assert list(backend.THUMBNAILS_DIR.iterdir()) == []


@pytest.mark.parametrize("thumbnail", ["http://cdn.example/x.jpg", "ftp://cdn.example/x.jpg", "file:///etc/passwd",
                                       "https://cdn.example/x.jpg') ; background:url(x", "https://cdn.example/a b.jpg", ""])
def test_a_url_that_is_not_plain_https_is_never_waited_for_nor_fetched(backend, tmp_path, thumbnail):
    entry = _finish(backend, tmp_path, thumbnail=thumbnail)
    c = backend.app.test_client()
    assert "X-EGM-Thumbnail" not in c.get(f"/api/status/{JOB}", headers=_token(backend)).headers
    assert c.get(_url(entry), headers=_token(backend)).status_code == 404
    assert c.post(_url(entry), data=JPEG, headers=_token(backend)).status_code == 404
    assert backend.backend_fetches == [] and list(backend.THUMBNAILS_DIR.iterdir()) == []


# ── the fallback ──────────────────────────────────────────────────────────────────────────────

def test_when_the_shell_could_not_fetch_it_the_backend_does_with_yt_dlps_agent(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    r = backend.app.test_client().post(_url(entry), data=b"", headers=_token(backend))
    assert r.status_code == 202
    assert _wait_for(lambda: backend._load_history()[0]["thumbnail"] == entry + ".jpg")
    assert backend.backend_fetches == [("https://cdn.example/vi/x/hq.jpg", UA)]


def test_when_the_shell_does_not_answer_the_backend_fetches_it_after_the_wait(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_THUMB_WAIT", 0.05)
    entry = _finish(backend, tmp_path)
    assert _wait_for(lambda: backend._load_history()[0]["thumbnail"] == entry + ".jpg")
    assert backend.backend_fetches == [("https://cdn.example/vi/x/hq.jpg", UA)]
    assert backend.app.test_client().post(_url(entry), data=PNG, headers=_token(backend)).status_code == 404, \
        "a late picture from the shell replaced the one already stored"


def test_without_the_shell_the_backend_fetches_it_at_once(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_SHELL_FETCHES_THUMBNAILS", False)
    entry = _finish(backend, tmp_path)
    assert backend._load_history()[0]["thumbnail"] == entry + ".jpg"
    assert "X-EGM-Thumbnail" not in backend.app.test_client().get(f"/api/status/{JOB}", headers=_token(backend)).headers


def test_clear_history_ends_the_wait_and_nothing_is_fetched_afterwards(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "_THUMB_WAIT", 0.05)
    entry = _finish(backend, tmp_path)
    c = backend.app.test_client()
    assert c.post("/api/history/clear", headers=_token(backend)).status_code == 200
    time.sleep(0.3)
    assert backend.backend_fetches == [], "a picture was fetched for a download Clear History removed"
    assert c.get(_url(entry), headers=_token(backend)).status_code == 404
    assert c.post(_url(entry), data=JPEG, headers=_token(backend)).status_code == 404
    assert backend._load_history() == [] and list(backend.THUMBNAILS_DIR.iterdir()) == []


def test_the_shell_and_the_wait_never_both_store_a_picture(backend, tmp_path, monkeypatch):
    """The wait ends while the shell's picture arrives: one of them stores it, the other finds it taken."""
    monkeypatch.setattr(backend, "_THUMB_WAIT", 0)
    for _ in range(20):
        backend._thumb_pending.clear()
        entry = _finish(backend, tmp_path)
        backend.app.test_client().post(_url(entry), data=PNG, headers=_token(backend))
        _wait_for(lambda: backend._load_history()[0]["thumbnail"])
        time.sleep(0.02)
        names = [p.name for p in backend.THUMBNAILS_DIR.iterdir() if p.name.startswith(entry)]
        assert len(names) == 1 and backend._load_history()[0]["thumbnail"] == names[0]
        for p in backend.THUMBNAILS_DIR.iterdir():
            p.unlink()
        backend.HISTORY_FILE.unlink()


# ── the shell's address check covers the backend's ────────────────────────────────────────────

def _py_internal(ip):
    a = ipaddress.ip_address(ip)
    return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified


ADDRESSES = ["0.0.0.0", "0.1.2.3", "10.0.0.1", "10.255.255.255", "100.64.0.1", "100.127.255.254", "127.0.0.1", "127.8.9.10",
             "169.254.169.254", "172.16.0.1", "172.31.255.255", "192.0.0.1", "192.0.2.10", "192.168.1.1", "198.18.0.1",
             "198.19.255.1", "198.51.100.7", "203.0.113.9", "224.0.0.1", "239.255.255.250", "240.0.0.1", "255.255.255.255",
             "8.8.8.8", "1.1.1.1", "93.184.216.34", "151.101.1.1", "100.63.255.255", "100.128.0.1", "172.15.255.255",
             "172.32.0.1", "192.167.1.1", "192.169.1.1", "11.0.0.1", "223.255.255.254", "198.17.255.255", "198.20.0.1",
             "::", "::1", "::ffff:127.0.0.1", "::ffff:8.8.8.8", "::ffff:7f00:1", "fe80::1", "fe80::1%eth0", "fc00::1",
             "fd12:3456::1", "ff02::1", "fec0::1", "64:ff9b::808:808", "100::1", "2001:db8::1", "2001::1", "2001:1ff::1",
             "2002:c0a8:101::1", "2606:4700::6810:84e5", "2a00:1450:4001:82a::200e", "2001:4860:4860::8888", "3fff::1",
             "2001:200::1", "1:2:3:4:5:6:7:8"]


@pytest.mark.parametrize("rel", ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js"))
def test_the_shell_refuses_every_address_the_backend_refuses(rel):
    src = read_source(rel)
    fn = re.search(r"\nfunction isInternalAddress\(ip\) \{.*?\n\}\n", src, re.S).group(0)
    script = f"{fn}\nconsole.log(JSON.stringify({json.dumps(ADDRESSES)}.map(isInternalAddress)));"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-1500:]
    shell = dict(zip(ADDRESSES, json.loads(r.stdout)))
    missed = [a for a in ADDRESSES if _py_internal(a.split("%")[0]) and not shell[a]]
    assert not missed, f"{rel} lets through addresses the backend refuses: {missed}"
    public = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "151.101.1.1", "11.0.0.1", "2606:4700::6810:84e5",
              "2a00:1450:4001:82a::200e", "2001:4860:4860::8888", "2001:200::1"]
    assert [a for a in public if shell[a]] == [], "a public address is refused"


# ── gaps found by mutation (session 4's thumbnail code) ────────────────────────────────────────

def test_the_picture_is_stored_only_under_the_history_lock(backend, tmp_path):
    """_attach_thumbnail checks the entry and writes the file and the entry under _history_lock: a
    finishing download that wrote the history file from an earlier read would lose an entry."""
    import threading
    entry = _finish(backend, tmp_path)
    done = threading.Event()
    with backend._history_lock:
        t = threading.Thread(target=lambda: (backend._attach_thumbnail(entry, JPEG), done.set()), daemon=True)
        t.start()
        time.sleep(0.3)
        assert not done.is_set(), "the picture was stored while another thread held the history lock"
        assert list(backend.THUMBNAILS_DIR.iterdir()) == []
    assert done.wait(5), "it never finished once the lock was free"
    assert backend._load_history()[0]["thumbnail"] == f"{entry}.jpg"
    assert (backend.THUMBNAILS_DIR / f"{entry}.jpg").read_bytes() == JPEG


class _Counting(io.BytesIO):
    """A request body without a length header (the server says the stream ends by itself, as with a
    chunked upload), counting what the route reads."""
    taken = 0

    def read(self, n=-1):
        data = super().read(n)
        _Counting.taken += len(data)
        return data

    def readinto(self, buf):            # the app's request size limit wraps the stream and reads this way
        n = super().readinto(buf)
        _Counting.taken += n
        return n


def test_the_upload_reads_at_most_one_byte_past_the_cap(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    body = JPEG + b"\x00" * (backend._THUMB_CAP * 3)
    _Counting.taken = 0
    r = backend.app.test_client().post(_url(entry), headers=_token(backend), environ_overrides={
        "wsgi.input": _Counting(body), "wsgi.input_terminated": True, "CONTENT_LENGTH": ""})
    assert r.status_code == 413
    assert _Counting.taken == backend._THUMB_CAP + 1, f"read {_Counting.taken} bytes of a {len(body)} byte body"
    # the refused upload hands the picture to the backend's own fetch, in a thread: let it end while the
    # data folder is still the test's
    assert _wait_for(lambda: backend._load_history()[0]["thumbnail"])


@pytest.mark.parametrize("data, ext", [
    (PNG, ".png"), (b"\x89PNG\r\n\x1a\x00" + b"\x00" * 64, ""), (b"\x89PNG" + b"\x00" * 64, ""),
    (WEBP, ".webp"), (b"RIFF\x00\x00\x00\x00WEBX" + b"\x00" * 64, ""), (b"RIFFWEBP" + b"\x00" * 64, ""),
    (b"RIFF\x00\x00\x00\x00\x00WEBP" + b"\x00" * 64, ""),
    (JPEG, ".jpg"), (b"\xff\xd8\x00" + b"\x00" * 64, ""), (b"\xff\x00\xff" + b"\x00" * 64, ""), (b"\x00\xd8\xff", ""),
])
def test_the_picture_is_told_by_its_whole_signature(backend_module, data, ext):
    assert backend_module._thumb_image_ext(data) == ext


@pytest.mark.parametrize("rel", APP_FILES)
@pytest.mark.parametrize("electron, expected", [("1", True), ("0", False), (None, False)])
def test_the_shell_fetches_the_pictures_only_when_started_by_the_shell(rel, electron, expected, tmp_path_factory, monkeypatch):
    if electron is None:
        monkeypatch.delenv("EGM_ELECTRON", raising=False)
    else:
        monkeypatch.setenv("EGM_ELECTRON", electron)
    assert _load(rel, tmp_path_factory)._SHELL_FETCHES_THUMBNAILS is expected


def test_the_backend_waits_30_seconds_for_the_shell(backend_module):
    assert backend_module._THUMB_WAIT == 30


# ── a delete or an import ends the wait ───────────────────────────────────────────────────────

def _gone_from_the_wait(backend, entry):
    """The shell is told no more (404) and nothing fetches it: neither the shell nor the backend's timer."""
    assert backend.app.test_client().get(_url(entry), headers=_token(backend)).status_code == 404
    assert entry not in backend._thumb_pending
    backend._thumbnail_by_backend(entry)          # what the 30 second timer runs
    assert backend.backend_fetches == []


def test_deleting_the_entry_ends_the_wait_for_its_picture(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    assert backend.app.test_client().get(_url(entry), headers=_token(backend)).status_code == 200
    r = backend.app.test_client().delete(f"/api/history/{entry}", headers=_token(backend))
    assert r.status_code == 200
    _gone_from_the_wait(backend, entry)
    # and a picture the shell delivers for it afterwards is not written anywhere
    assert backend.app.test_client().post(_url(entry), data=JPEG, headers=_token(backend)).status_code == 404
    assert list(backend.THUMBNAILS_DIR.iterdir()) == []


def test_an_import_without_the_entry_ends_the_wait_and_one_with_it_keeps_it(backend, tmp_path):
    entry = _finish(backend, tmp_path)
    kept = backend._load_history()
    c = backend.app.test_client()
    assert c.post("/api/history/import", json={"items": kept}, headers=_token(backend)).status_code == 200
    assert c.get(_url(entry), headers=_token(backend)).status_code == 200, "an import that still has the entry keeps it waiting"
    other = [{"id": "0" * 36, "url": "https://video.example/o", "title": "o", "completed_at": "2026-01-01T00:00:00Z"}]
    assert c.post("/api/history/import", json={"items": other}, headers=_token(backend)).status_code == 200
    _gone_from_the_wait(backend, entry)
