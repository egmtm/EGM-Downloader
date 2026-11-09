"""The Windows app update (app.py): nothing is downloaded before the user asks for it, and the
download is bounded by the size the signed feed gives.

* /api/check-app-update passes the feed's size_bytes on to the page, only when the signed feed holds
  a positive whole number, so the update dialog can show it before Update Now.
* /api/download-update needs that size from the page (sent with the address and the checksum,
  under the same per run token) and refuses without it; it refuses before reading anything when the
  server announces more, and stops as soon as the bytes read pass it, removing the partial file.
* The downloaded file is hashed in blocks, never read whole into memory.

The feed is signed with a throwaway key made here, whose public half replaces the app's key, so the
real signature check runs. Nothing here contacts any outside server.
"""
import base64
import hashlib
import io
import json
import pathlib
import zipfile

import pytest


class _Resp(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.url = "https://egerena.com/apps/x"
        self.headers = headers if headers is not None else {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _get(mod, path):
    return mod.app.test_client().get(path, headers={"X-EGM-Token": mod._API_TOKEN})


@pytest.fixture
def feed_of(app_module, monkeypatch):
    """Serves a feed signed with a throwaway key the backend trusts for one test."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = Ed25519PrivateKey.generate()
    monkeypatch.setattr(app_module, "_MANIFEST_PUBLIC_KEY_PEM",
                        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    monkeypatch.setattr(app_module, "PORTABLE_MODE", False)
    monkeypatch.setattr(app_module, "APP_BUILD", 100)

    def serve(**over):
        feed = {"version": "1.0.0.1", "build": 101, "downloadUrl": "https://egerena.com/apps/EGMd.zip",
                "_version_notes": ["A fix"], "_checksums": {"sha256": "ab" * 32}}
        feed.update(over)
        payload = json.dumps(feed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signed = dict(feed, signature=base64.b64encode(key.sign(payload)).decode("ascii"))
        monkeypatch.setattr(app_module, "_safe_urlopen", lambda req, t: _Resp(json.dumps(signed).encode()))
        return _get(app_module, "/api/check-app-update").get_json()
    return serve


# ── the size the signed feed gives ──────────────────────────────────────────────────────────────

def test_the_update_check_passes_the_signed_size_on(feed_of):
    d = feed_of(size_bytes=134217728)
    assert d["up_to_date"] is False and d["size_bytes"] == 134217728, d


@pytest.mark.parametrize("size", [0, -5, "134217728", 1.5, True, None, [1]])
def test_a_size_that_is_not_a_positive_whole_number_is_not_passed_on(feed_of, size):
    d = feed_of(size_bytes=size)
    assert d["up_to_date"] is False and "size_bytes" not in d, d


def test_a_feed_without_a_size_gives_none(feed_of):
    d = feed_of()
    assert d["up_to_date"] is False and "size_bytes" not in d, d


# ── the download stops at that size ─────────────────────────────────────────────────────────────

class _Stream:
    """A download: hands out the bytes in the sizes asked for and records every read."""
    def __init__(self, data, content_length="exact"):
        self.data, self.pos, self.reads = data, 0, []
        self.url = "https://egerena.com/apps/EGMd.zip"
        self.headers = {} if content_length is None else {
            "Content-Length": str(len(data) if content_length == "exact" else content_length)}

    def read(self, n=-1):
        self.reads.append(n)
        if n is None or n < 0:
            n = len(self.data) - self.pos
        chunk = self.data[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _zip(size_hint=0):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("egm-setup.exe", b"installer bytes " * 64 + bytes(size_hint))
    return buf.getvalue()


@pytest.fixture
def updater(app_module, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPDATE_TMP_DIR", tmp_path / "egm-update")
    monkeypatch.setattr(app_module, "PORTABLE_MODE", False)
    monkeypatch.setattr(app_module, "APP_BUILD", 100)
    return app_module


def _post(mod, body):
    return mod.app.test_client().post("/api/download-update", json=body, headers={"X-EGM-Token": mod._API_TOKEN})


def _ask(data, **over):
    body = {"zip_url": "https://egerena.com/apps/EGMd.zip", "expected_checksum": hashlib.sha256(data).hexdigest(),
            "expected_size": len(data), "latest_build": 101}
    body.update(over)
    return {k: v for k, v in body.items() if v is not _ask.NONE}


_ask.NONE = object()


def _left(mod):
    d = mod.UPDATE_TMP_DIR
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


@pytest.mark.parametrize("size", [_ask.NONE, None, 0, -1, "1234", 12.5, True, [1234]])
def test_a_download_without_a_positive_size_is_refused_before_any_fetch(updater, monkeypatch, size):
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: pytest.fail("fetched without a size"))
    r = _post(updater, _ask(_zip(), expected_size=size))
    assert r.status_code == 400 and "size" in r.get_json()["error"], r.get_json()
    assert _left(updater) == []


def test_a_server_announcing_more_than_the_size_is_refused_before_reading(updater, monkeypatch):
    data = _zip()
    stream = _Stream(data + b"more", content_length="exact")
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: stream)
    r = _post(updater, _ask(data))
    assert r.status_code >= 400 and "larger" in r.get_json()["error"], r.get_json()
    assert stream.reads == [], "nothing is read once the announced size is too large"
    assert _left(updater) == []


@pytest.mark.parametrize("announced", [None, "small"])
def test_a_download_passing_the_size_stops_there_and_its_partial_file_goes(updater, monkeypatch, announced):
    """No Content-Length, or one that is smaller than what comes: the bytes read decide."""
    data = _zip()
    big = data + bytes(50 * 1024 * 1024)
    stream = _Stream(big, content_length=None if announced is None else len(data))
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: stream)
    r = _post(updater, _ask(data))
    assert r.status_code >= 400 and "larger" in r.get_json()["error"], r.get_json()
    assert stream.pos <= len(data) + 1024 * 1024, f"read {stream.pos} bytes for a {len(data)} byte update"
    assert _left(updater) == []


def test_a_download_of_exactly_the_size_is_taken(updater, monkeypatch):
    data = _zip()
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: _Stream(data))
    r = _post(updater, _ask(data))
    assert r.status_code == 200 and r.get_json()["installer_path"].endswith("egm-setup.exe"), r.get_json()


def test_the_download_is_read_and_hashed_in_blocks(updater, monkeypatch):
    data = _zip(size_hint=3 * 1024 * 1024)
    stream = _Stream(data)
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: stream)
    whole = []
    real = pathlib.Path.read_bytes
    monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: whole.append(self.name) or real(self))
    r = _post(updater, _ask(data))
    assert r.status_code == 200, r.get_json()
    assert whole == [], f"read whole: {whole}"
    assert stream.reads and all(0 < n <= 1024 * 1024 for n in stream.reads), stream.reads[:5]


def test_the_hash_of_a_file_is_computed_in_blocks(app_module, tmp_path, monkeypatch):
    f = tmp_path / "big.zip"
    f.write_bytes(bytes(range(256)) * (12 * 1024))   # 3 MB
    sizes = []

    class _Recorder:
        def __init__(self, fh):
            self.fh = fh

        def read(self, n=-1):
            sizes.append(n)
            return self.fh.read(n)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.fh.close()

    real_open = open
    monkeypatch.setattr(app_module, "open", lambda *a, **k: _Recorder(real_open(*a, **k)), raising=False)
    assert app_module._sha256_file(f) == hashlib.sha256(f.read_bytes()).hexdigest()
    assert len(sizes) > 3 and all(0 < n <= 1024 * 1024 for n in sizes), sizes
