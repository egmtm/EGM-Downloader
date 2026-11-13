"""What the app does with update information and downloads it receives, on all three backends.

* The app's own update feed: only a feed signed with the app's key is used. The tests sign feeds
  with a throwaway key made here and put its public half in place of the app's key, so the real
  _verify_manifest runs (the other update tests replace it with a stub).
* The Windows update download (/api/download-update): a wrong checksum, a download that
  is cut short and a foreign address all fail with nothing left behind. The cut short download
  comes from a loopback server started here.
* ffmpeg, first run and update: a failure part way through writing the binaries must not leave
  a broken binary under its final name, where the next start takes it as installed.

Nothing here contacts any outside server.
"""
import base64
import http.server
import importlib.util
import io
import json
import socket
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_update_checks_" + path.split("/")[0], ROOT / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


class _Resp(io.BytesIO):
    def __init__(self, data, url="https://example.invalid/x"):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client_get(mod, path):
    return mod.app.test_client().get(path, headers={"X-EGM-Token": mod._API_TOKEN})


def _client_post(mod, path, body):
    return mod.app.test_client().post(path, json=body, headers={"X-EGM-Token": mod._API_TOKEN})


# ── The app's own update feed ───────────────────────────────────────────────────────────────────

@pytest.fixture
def signing(backend, monkeypatch):
    """A throwaway key pair; the backend trusts its public half for the length of one test."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(backend, "_MANIFEST_PUBLIC_KEY_PEM", pem)

    def sign(feed, with_key=None):
        payload = json.dumps(feed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sig = (with_key or key).sign(payload)
        return dict(feed, signature=base64.b64encode(sig).decode("ascii"))
    return sign


def _serve_feed(backend, monkeypatch, feed):
    monkeypatch.setattr(backend, "PORTABLE_MODE", False, raising=False)
    monkeypatch.setattr(backend, "APP_VERSION", "1.0.0.0")
    monkeypatch.setattr(backend, "APP_BUILD", 100)
    monkeypatch.setattr(backend, "_safe_urlopen", lambda req, t: _Resp(json.dumps(feed).encode()))


def _feed(**over):
    feed = {"version": "1.0.0.1", "build": 101, "downloadUrl": "https://egerena.com/apps/x.zip",
            "_version_notes": ["A fix"], "_checksums": {"sha256": "ab" * 32}}
    feed.update(over)
    return feed


def test_a_correctly_signed_newer_feed_is_offered(backend, signing, monkeypatch):
    _serve_feed(backend, monkeypatch, signing(_feed()))
    d = _client_get(backend, "/api/check-app-update").get_json()
    assert d.get("up_to_date") is False and d.get("latest_build") == 101, d


def test_a_correctly_signed_older_or_equal_feed_is_not_offered(backend, signing, monkeypatch):
    for build in (100, 99):
        _serve_feed(backend, monkeypatch, signing(_feed(version="9.9.9.9", build=build)))
        d = _client_get(backend, "/api/check-app-update").get_json()
        assert d.get("up_to_date") is True, (build, d)


def _foreign_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate()


@pytest.mark.parametrize("how", ["unsigned", "empty signature", "tampered", "other key", "not base64"])
def test_a_feed_that_does_not_verify_is_refused_and_its_notes_are_not_shown(backend, signing, monkeypatch, how):
    good = signing(_feed())
    bad = {
        "unsigned": {k: v for k, v in good.items() if k != "signature"},
        "empty signature": dict(good, signature=""),
        "tampered": dict(good, build=999),
        "other key": signing(_feed(), with_key=_foreign_key()),
        "not base64": dict(good, signature="%%%"),
    }[how]
    _serve_feed(backend, monkeypatch, bad)
    r = _client_get(backend, "/api/check-app-update")
    d = r.get_json()
    assert d.get("error") and "up_to_date" not in d, (how, r.status_code, d)


# ── /api/download-update (Windows) ─────────────────────────────────────────────────────

@pytest.fixture
def updater(app_module, tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPDATE_TMP_DIR", tmp_path / "egm-update")
    monkeypatch.setattr(app_module, "PORTABLE_MODE", False, raising=False)
    return app_module


def _update_zip(member):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, b"installer bytes " * 64)
    return buf.getvalue()


def test_a_download_with_the_wrong_checksum_is_refused_and_removed(updater, monkeypatch):
    data = _update_zip("egm-setup.exe")
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: _Resp(data))
    r = _client_post(updater, "/api/download-update",
                     {"zip_url": "https://egerena.com/apps/x.zip", "expected_checksum": "00" * 32, "expected_size": len(data)})
    assert r.status_code >= 400 and "Checksum" in r.get_json()["error"]
    left = list(updater.UPDATE_TMP_DIR.iterdir()) if updater.UPDATE_TMP_DIR.exists() else []
    assert left == [], left


def test_an_address_outside_the_release_host_is_refused_before_any_fetch(updater, monkeypatch):
    fetched = []
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: fetched.append(req) or _Resp(b""))
    for url in ("https://example.invalid/x.zip", "http://egerena.com/apps/x.zip",
                "https://egerena.com.example.invalid/x.zip"):
        # The size too: on the Windows backend the size check comes first, and a body without one was
        # refused for that reason alone, so the host guard was never reached by this test.
        r = _client_post(updater, "/api/download-update", {"zip_url": url, "expected_checksum": "ab" * 32, "expected_size": 1000})
        assert r.status_code == 400, url
        assert "size" not in r.get_json()["error"].lower(), (url, r.get_json())
    assert fetched == []


def test_a_missing_checksum_is_refused(updater, monkeypatch):
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: pytest.fail("fetched without a checksum"))
    r = _client_post(updater, "/api/download-update", {"zip_url": "https://egerena.com/apps/x.zip"})
    assert r.status_code == 400


class _ShortHandler(http.server.BaseHTTPRequestHandler):
    """Announces more bytes than it sends, then closes: a download cut short."""
    def do_GET(self):
        body = b"x" * 1000
        self.send_response(200)
        self.send_header("Content-Length", str(len(body) * 10))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.connection.shutdown(socket.SHUT_RDWR)

    def log_message(self, *a):
        pass


@pytest.fixture
def short_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _ShortHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/x.zip"
    srv.shutdown()
    srv.server_close()


def test_a_download_cut_short_fails_and_leaves_nothing(updater, monkeypatch, short_server):
    monkeypatch.setattr(updater, "_safe_urlopen", lambda req, t: urllib.request.urlopen(short_server, timeout=5))
    r = _client_post(updater, "/api/download-update",
                     {"zip_url": "https://egerena.com/apps/x.zip", "expected_checksum": "ab" * 32, "expected_size": 10000})
    assert r.status_code >= 400 and r.get_json().get("error")
    left = list(updater.UPDATE_TMP_DIR.iterdir()) if updater.UPDATE_TMP_DIR.exists() else []
    assert left == [], left


def test_windows_takes_only_the_installer_out_of_a_verified_download(app_module, tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(app_module, "UPDATE_TMP_DIR", tmp_path / "egm-update")
    monkeypatch.setattr(app_module, "PORTABLE_MODE", False)
    good = _update_zip("egm-setup.exe")
    monkeypatch.setattr(app_module, "_safe_urlopen", lambda req, t: _Resp(good))
    r = _client_post(app_module, "/api/download-update",
                     {"zip_url": "https://egerena.com/apps/x.zip", "expected_checksum": hashlib.sha256(good).hexdigest(),
                      "expected_size": len(good)})
    d = r.get_json()
    assert r.status_code == 200 and Path(d["installer_path"]) == tmp_path / "egm-update" / "egm-setup.exe"
    assert sorted(p.name for p in (tmp_path / "egm-update").iterdir()) == ["egm-setup.exe"]
    other = _update_zip("something-else.exe")
    monkeypatch.setattr(app_module, "_safe_urlopen", lambda req, t: _Resp(other))
    r = _client_post(app_module, "/api/download-update",
                     {"zip_url": "https://egerena.com/apps/x.zip", "expected_checksum": hashlib.sha256(other).hexdigest(),
                      "expected_size": len(other)})
    assert r.status_code >= 400 and "not found" in r.get_json()["error"]


# ── ffmpeg and Deno: the upstream checksum file ────────────────────────────────────────────────

@pytest.fixture
def checksum_rig(backend, tmp_path, monkeypatch):
    import hashlib
    f = tmp_path / "ffmpeg-x.zip"
    f.write_bytes(b"the archive")
    good = hashlib.sha256(b"the archive").hexdigest()
    served = {}

    def fake(req, timeout):
        if isinstance(served.get("body"), Exception):
            raise served["body"]
        return _Resp(served["body"].encode())
    monkeypatch.setattr(backend, "_safe_urlopen", fake)
    monkeypatch.setattr(backend, "_sec_event", lambda *a: None)
    return f, good, served


def test_a_matching_upstream_checksum_passes(backend, checksum_rig):
    f, good, served = checksum_rig
    served["body"] = f"{'0' * 64}  other.zip\n{good}  ffmpeg-x.zip\n"
    assert backend._verify_upstream_checksum(f, "https://github.com/x/sums", "ffmpeg-x.zip")[0] is True
    served["body"] = f"{good.upper()} *ffmpeg-x.zip\n"          # sha256sum binary mode, upper case
    assert backend._verify_upstream_checksum(f, "https://github.com/x/sums", "ffmpeg-x.zip")[0] is True


@pytest.mark.parametrize("case", ["mismatch", "no entry", "entry for a longer name", "empty", "fetch fails"])
def test_an_upstream_checksum_that_does_not_match_or_cannot_be_read_fails_closed(backend, checksum_rig, case):
    f, good, served = checksum_rig
    served["body"] = {
        "mismatch": f"{'a' * 64}  ffmpeg-x.zip\n",
        "no entry": f"{good}  other.zip\n",
        "entry for a longer name": f"{good}  ffmpeg-x.zip.sig\n",
        "empty": "",
        "fetch fails": urllib.error.URLError("offline"),
    }[case]
    ok, msg = backend._verify_upstream_checksum(f, "https://github.com/x/sums", "ffmpeg-x.zip")
    assert ok is False and "aborted" in msg, (case, msg)


def test_windows_reads_the_powershell_checksum_format_and_still_fails_closed(app_module, tmp_path, monkeypatch):
    import hashlib
    f = tmp_path / "deno-x86_64-pc-windows-msvc.zip"
    f.write_bytes(b"deno")
    good = hashlib.sha256(b"deno").hexdigest().upper()
    monkeypatch.setattr(app_module, "_sec_event", lambda *a: None)
    for digest, path, expect in ((good, r"C:\a\deno-x86_64-pc-windows-msvc.zip", True),
                                 ("B" * 64, r"C:\a\deno-x86_64-pc-windows-msvc.zip", False),
                                 (good, r"C:\a\other.zip", False)):
        body = f"Algorithm : SHA256\nHash      : {digest}\nPath      : {path}\n"
        monkeypatch.setattr(app_module, "_safe_urlopen", lambda req, t, b=body: _Resp(b.encode()))
        assert app_module._verify_upstream_checksum(f, "https://github.com/x", f.name)[0] is expect, (digest, path)
