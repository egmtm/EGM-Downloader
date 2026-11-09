"""Behaviour tests for the guard helpers, on every backend.

Each test here fails when one small deliberate change is made to one helper in one copy
(app.py, linux/app.py or mac/app.py) and passes on the real code. Before these tests, about
ninety such changes passed the whole suite: most guards were checked only for their name or a
line of text, or only in the Windows copy. Nothing here is fetched: name lookups and HTTP calls
are stubbed, and the only addresses used are IP literals.
"""
import base64
import copy
import importlib.util
import io
import json
import os
import socket
import threading
import time
import zipfile
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
            "egm_strength_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(autouse=True)
def _data_files_in_tmp(backend, tmp_path_factory, monkeypatch):
    """The Windows copy keeps its data next to app.py (the repository root in a checkout): keep
    every data file of every copy in a temporary folder, so no test here writes the developer's
    own. (Not tmp_path: the atomic write test checks what that folder holds.)"""
    data = tmp_path_factory.mktemp("egm_data")
    for name in ("SETTINGS_FILE", "HISTORY_FILE", "SUBS_FILE", "COOKIES_FILE"):
        monkeypatch.setattr(backend, name, data / Path(getattr(backend, name)).name)
    monkeypatch.setattr(backend, "THUMBNAILS_DIR", data / "thumbnails")
    monkeypatch.setattr(backend, "_settings_cache", {})
    monkeypatch.setattr(backend, "_subs_cache", None)


def _client(backend):
    return backend.app.test_client()


# ── _validate_download_dir ──────────────────────────────────────────────────────────────────

def test_a_folder_that_is_not_writable_is_refused(backend, tmp_path, monkeypatch):
    target = tmp_path / "videos"
    target.mkdir()
    ok, _, _ = backend._validate_download_dir(str(target))
    assert ok
    monkeypatch.setattr(backend.os, "access", lambda p, mode: False)
    ok, _, err = backend._validate_download_dir(str(target))
    assert not ok and "not writable" in err


# ── _safe_extract ───────────────────────────────────────────────────────────────────────────

def _zip(tmp_path, members):
    p = tmp_path / "a.zip"
    with zipfile.ZipFile(p, "w") as z:
        for name in members:
            z.writestr(name, "x")
    return zipfile.ZipFile(p)


@pytest.mark.parametrize("name", ["../evil.exe", "/abs.exe", "\\win.exe", "a/../../b.exe"])
def test_safe_extract_refuses_a_member_path_that_climbs_or_is_absolute(backend, tmp_path, name):
    out = tmp_path / "out"
    out.mkdir()
    with _zip(tmp_path, [name]) as z, pytest.raises(RuntimeError):
        backend._safe_extract(z, name, out)
    assert list(out.rglob("*")) == []


def test_safe_extract_refuses_a_member_that_is_not_there(backend, tmp_path):
    with _zip(tmp_path, ["deno.exe"]) as z, pytest.raises(RuntimeError):
        backend._safe_extract(z, "ffmpeg.exe", tmp_path)


# ── _safe_urlopen / _is_allowed_host ────────────────────────────────────────────────────────

class _Resp(io.BytesIO):
    def __init__(self, url):
        super().__init__(b"x")
        self.url = url
        self.closed_by_caller = False

    def close(self):
        self.closed_by_caller = True
        super().close()


def test_safe_urlopen_refuses_a_host_off_the_list_before_any_request(backend, monkeypatch):
    calls = []
    monkeypatch.setattr(backend.urllib.request, "urlopen", lambda *a, **k: calls.append(a) or _Resp(a[0]))
    for url in ("https://example.invalid/x", "https://evil-github.com/x", "https://github.com.example.invalid/x",
                "https://notgithub.com/x"):
        with pytest.raises(RuntimeError):
            backend._safe_urlopen(url, 5)
    assert calls == []


def test_safe_urlopen_refuses_a_redirect_that_ends_off_the_list(backend, monkeypatch):
    resp = _Resp("https://example.invalid/landed")
    monkeypatch.setattr(backend.urllib.request, "urlopen", lambda *a, **k: resp)
    with pytest.raises(RuntimeError):
        backend._safe_urlopen("https://github.com/x", 5)
    assert resp.closed_by_caller


def test_safe_urlopen_lets_an_allowed_host_through(backend, monkeypatch):
    monkeypatch.setattr(backend.urllib.request, "urlopen", lambda *a, **k: _Resp("https://github.com/x"))
    assert backend._safe_urlopen("https://github.com/x", 5).url == "https://github.com/x"


# ── _is_internal_host and the thumbnail download ────────────────────────────────────────────

@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "192.168.1.10", "172.16.0.5", "169.254.169.254", "::1", "0.0.0.0"])
def test_internal_addresses_are_internal(backend, host):
    assert backend._is_internal_host(host) is True


def test_a_public_address_is_not_internal(backend):
    assert backend._is_internal_host("8.8.8.8") is False


def test_an_empty_or_unresolvable_host_counts_as_internal(backend, monkeypatch):
    assert backend._is_internal_host("") is True

    def no_lookup(*a, **k):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", no_lookup)
    assert backend._is_internal_host("unresolvable.invalid") is True


def test_a_thumbnail_on_an_internal_address_is_never_fetched(backend, monkeypatch):
    monkeypatch.setattr(backend.urllib.request, "urlopen", lambda *a, **k: pytest.fail("fetched an internal address"))
    monkeypatch.setattr(backend.urllib.request.OpenerDirector, "open", lambda *a, **k: pytest.fail("fetched an internal address"))
    monkeypatch.setattr(backend, "_sec_event", lambda *a: None)
    for url in ("https://127.0.0.1/x.jpg", "https://10.0.0.1/x.jpg", "https://[::1]/x.jpg"):
        assert backend._fetch_thumbnail(url, "Mozilla/5.0") == b""


# ── _verify_manifest ────────────────────────────────────────────────────────────────────────

def test_verify_manifest_accepts_only_a_signature_by_the_trusted_key(backend, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key, other = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    monkeypatch.setattr(backend, "_MANIFEST_PUBLIC_KEY_PEM",
                        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    feed = {"version": "1.0.0.1", "build": 5, "downloadUrl": "https://egerena.com/a.zip", "_checksums": {"sha256": "ab" * 32}}

    def signed(by, data=feed):
        payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        return dict(data, signature=base64.b64encode(by.sign(payload)).decode())
    good = signed(key)
    assert backend._verify_manifest(good) is True
    assert backend._verify_manifest(dict(good, build=6)) is False
    assert backend._verify_manifest(signed(other)) is False
    assert backend._verify_manifest({k: v for k, v in good.items() if k != "signature"}) is False


# ── _safe_thumb_url and _safe_video_id ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["https://a.invalid/x(1).jpg", "https://a.invalid/x).jpg", "javascript:alert(1)",
                                 "data:image/png;base64,AA", "https://a.invalid/x'.jpg", "https://a.invalid/x y.jpg"])
def test_thumbnail_urls_that_could_break_out_of_a_style_are_dropped(backend, url):
    assert backend._safe_thumb_url(url) == ""


def test_a_plain_thumbnail_url_is_kept(backend):
    assert backend._safe_thumb_url(" https://a.invalid/x.jpg ") == "https://a.invalid/x.jpg"


@pytest.mark.parametrize("vid", ["abc def", "abc<script>", 'abc"x', "a" * 129, ""])
def test_video_ids_outside_the_allowlist_are_dropped(backend, vid):
    assert backend._safe_video_id(vid) == ""


# ── _atomic_write_text ──────────────────────────────────────────────────────────────────────

def test_atomic_write_replaces_in_one_step_and_keeps_the_old_file_on_failure(backend, tmp_path, monkeypatch):
    target = tmp_path / "egm_settings.json"
    target.write_text('{"old": true}', encoding="utf-8")
    synced = []
    real_fsync = os.fsync
    monkeypatch.setattr(backend.os, "fsync", lambda fd: synced.append(fd) or real_fsync(fd))
    backend._atomic_write_text(target, '{"new": true}', owner_only=True)
    assert target.read_text(encoding="utf-8") == '{"new": true}' and synced
    if os.name != "nt":
        assert (target.stat().st_mode & 0o777) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["egm_settings.json"]
    with pytest.raises(Exception):
        backend._atomic_write_text(target, "half \udcff written", owner_only=True)   # cannot be encoded
    assert target.read_text(encoding="utf-8") == '{"new": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["egm_settings.json"], "the temporary file was left"


# ── _mutate_subscriptions ───────────────────────────────────────────────────────────────────

@pytest.fixture
def subs_file(backend, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "SUBS_FILE", tmp_path / "egm_subscriptions.json")
    monkeypatch.setattr(backend, "_subs_cache", None)
    backend._save_subscriptions([{"id": "a", "name": "first"}])
    return backend.SUBS_FILE


def test_an_aborted_change_leaves_the_file_and_the_cache_untouched(backend, subs_file):
    before = subs_file.read_text(encoding="utf-8")
    cached = copy.deepcopy(backend._load_subscriptions())

    def change_then_abort(subs):
        subs[0]["name"] = "changed"
        subs.append({"id": "b"})
        raise backend._AbortMutation("stop")
    assert backend._mutate_subscriptions(change_then_abort) == "stop"
    assert subs_file.read_text(encoding="utf-8") == before
    assert backend._load_subscriptions() == cached


def test_parallel_changes_are_all_kept(backend, subs_file):
    def add(i):
        def fn(subs):
            time.sleep(0.01)              # widen the window between reading and saving
            subs.append({"id": f"n{i}"})
            return True
        backend._mutate_subscriptions(fn)
    threads = [threading.Thread(target=add, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    ids = {s["id"] for s in json.loads(subs_file.read_text(encoding="utf-8"))["subscriptions"]}
    assert ids == {"a"} | {f"n{i}" for i in range(8)}


# ── the per-run token and the Host header ───────────────────────────────────────────────────

def test_api_routes_need_the_exact_token(backend):
    c = _client(backend)
    assert c.get("/api/settings").status_code == 403
    assert c.get("/api/settings", headers={"X-EGM-Token": ""}).status_code == 403
    assert c.get("/api/settings", headers={"X-EGM-Token": backend._API_TOKEN[:-1]}).status_code == 403
    assert c.get("/api/settings", headers={"X-EGM-Token": backend._API_TOKEN + "x"}).status_code == 403
    assert c.post("/api/settings/save", json={}).status_code == 403
    assert c.get("/api/settings", headers={"X-EGM-Token": backend._API_TOKEN}).status_code == 200


def test_only_the_thumbnail_route_is_exempt_from_the_token(backend):
    c = _client(backend)
    assert c.get("/api/thumbnail/0123abcd.jpg").status_code == 404     # exempt: answered, not forbidden
    for path in ("/api/history", "/api/subscriptions", "/api/logs", "/api/thumbnailx"):
        assert c.get(path).status_code == 403, path


def test_a_foreign_host_header_is_refused_even_with_the_token(backend):
    c = _client(backend)
    r = c.get("/api/settings", headers={"X-EGM-Token": backend._API_TOKEN, "Host": "evil.example"})
    assert r.status_code == 403
    r = c.get("/api/settings", headers={"X-EGM-Token": backend._API_TOKEN, "Host": "127.0.0.1:8899"})
    assert r.status_code == 200
