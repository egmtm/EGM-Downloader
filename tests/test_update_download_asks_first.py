"""The Windows app update (app.py): nothing is downloaded before the user asks for it, and the
download is bounded by the size the signed feed gives.

* /api/check-app-update passes the feed's size_bytes on to the page, only when the signed feed holds
  a positive whole number, so the update dialog can show it before Update Now.

The feed is signed with a throwaway key made here, whose public half replaces the app's key, so the
real signature check runs. Nothing here contacts any outside server.
"""
import base64
import io
import json

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
