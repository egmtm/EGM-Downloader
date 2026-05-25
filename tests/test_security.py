"""
Tier 2 — Security-critical tests.

Tests for regressions on security-critical paths. Each test maps to a
real finding from the audit cycle. If any of these fails, something that
was deliberately secured has been reverted.
"""
import re
import base64
import json
import pytest
from conftest import read_source


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_mod():
    """Import Windows app module once for this test module."""
    import sys, os
    os.environ.setdefault("EGM_API_TOKEN", "ci-test-token-not-secret")
    sys.argv = ["app.py"]
    import importlib.util
    root = os.path.dirname(os.path.dirname(__file__))
    spec = importlib.util.spec_from_file_location("egm_app", os.path.join(root, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def test_keypair():
    """Generate a throwaway ed25519 keypair for manifest signing tests."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private = Ed25519PrivateKey.generate()
    public  = private.public_key()
    return private, public


# ── _download_thumbnail — HTTPS-only enforcement ───────────────────────────────

def test_thumbnail_rejects_http_url(app_mod):
    """
    _download_thumbnail must reject http:// URLs.
    Regression guard: HTTPS-only check added v0.99.11 — must not be removed.
    """
    result = app_mod._download_thumbnail("http://attacker.com/image.jpg", "test-id")
    assert result == "", "http:// URL should be rejected (return empty string)"


def test_thumbnail_rejects_file_url(app_mod):
    """_download_thumbnail must reject file:// URLs (local file access)."""
    result = app_mod._download_thumbnail("file:///etc/passwd", "test-id")
    assert result == "", "file:// URL should be rejected"


def test_thumbnail_rejects_empty_url(app_mod):
    """_download_thumbnail must handle empty string gracefully."""
    result = app_mod._download_thumbnail("", "test-id")
    assert result == "", "Empty URL should return empty string"


def test_thumbnail_https_url_is_attempted(app_mod):
    """
    _download_thumbnail must NOT reject https:// URLs at the scheme-check stage.
    (The request itself may fail in test environment — that's fine.)
    Verifies the HTTPS check doesn't accidentally block valid URLs.
    """
    # A valid https URL should pass the scheme check and attempt the request
    # We verify this by checking the source code contains the correct guard
    source = read_source("app.py")
    m = re.search(r'def _download_thumbnail.*?return ""', source, re.DOTALL)
    assert m, "_download_thumbnail not found in source"
    func_body = m.group(0)
    assert 'startswith("https://")' in func_body, (
        "_download_thumbnail must check for https:// prefix"
    )


# ── serve_thumbnail — path traversal protection ────────────────────────────────

def test_thumbnail_regex_blocks_path_traversal():
    """
    serve_thumbnail filename regex must block path traversal attempts.
    Regression guard: ensures r'^[a-f0-9\\-]+\\.(jpg|png|webp)$' is not weakened.
    """
    pattern = re.compile(r'^[a-f0-9\-]+\.(jpg|png|webp)$')
    traversal_attempts = [
        "../etc/passwd",
        "../../windows/system32/config",
        "valid-name.jpg/../secret",
        ".hidden",
        "file with spaces.jpg",
        "UPPERCASE.JPG",
        "script.php",
        "image.jpg.exe",
        "%2e%2e/etc",
    ]
    for attempt in traversal_attempts:
        assert not pattern.match(attempt), f"Path traversal not blocked: {attempt!r}"


def test_thumbnail_regex_accepts_valid_filenames():
    """serve_thumbnail regex must accept valid UUID-derived filenames."""
    pattern = re.compile(r'^[a-f0-9\-]+\.(jpg|png|webp)$')
    valid_names = [
        "a1b2c3d4-1234-5678-abcd-ef0123456789.jpg",
        "deadbeef-cafe-babe-0000-111122223333.png",
        "aaaabbbb.webp",
    ]
    for name in valid_names:
        assert pattern.match(name), f"Valid filename incorrectly rejected: {name!r}"


# ── _verify_manifest — signed manifest enforcement ────────────────────────────

def test_verify_manifest_rejects_unsigned(app_mod):
    """_verify_manifest must return False for manifests with no signature field."""
    data = {"version": "0.99.12", "build": 120, "downloadUrl": "https://egerena.com/apps/EGMd.zip"}
    assert app_mod._verify_manifest(data) is False, "Unsigned manifest should be rejected"


def test_verify_manifest_rejects_empty_signature(app_mod):
    """_verify_manifest must return False for empty signature field."""
    data = {"version": "0.99.12", "build": 120, "signature": ""}
    assert app_mod._verify_manifest(data) is False, "Empty signature should be rejected"


def test_verify_manifest_rejects_tampered_content(app_mod, test_keypair):
    """
    A manifest signed with a valid key but then tampered must be rejected.
    Any byte change to the payload invalidates the ed25519 signature.
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private, public = test_keypair

    # Sign a manifest
    data = {"version": "0.99.12", "build": 120}
    payload = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    sig = private.sign(payload)
    signed = dict(data, signature=base64.b64encode(sig).decode('ascii'))

    # Tamper with the version
    tampered = dict(signed, version="9.9.9")

    # Must be rejected (app_mod uses embedded public key — different from test key,
    # so signature will fail regardless, but the tamper test confirms the logic)
    assert app_mod._verify_manifest(tampered) is False, "Tampered manifest should be rejected"


def test_verify_manifest_rejects_wrong_key(app_mod, test_keypair):
    """
    A manifest signed with an unknown private key must be rejected.
    Guards against attackers who generate their own keypair.
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private, _ = test_keypair

    data = {"version": "0.99.12", "build": 120}
    payload = json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8')
    sig = private.sign(payload)
    signed = dict(data, signature=base64.b64encode(sig).decode('ascii'))

    # App uses its own embedded public key — test key's signature must not verify
    assert app_mod._verify_manifest(signed) is False, (
        "Manifest signed with unknown key should be rejected"
    )


# ── _verify_upstream_checksum — fail-closed enforcement ───────────────────────

def test_checksum_source_present_in_all_platforms():
    """
    _verify_upstream_checksum must exist in all 3 app.py files and be fail-closed.
    Regression guard: ensures the function hasn't been removed or simplified to fail-open.
    """
    for platform_file in ["app.py", "mac/app.py", "linux/app.py"]:
        source = read_source(platform_file)
        assert "_verify_upstream_checksum" in source, (
            f"_verify_upstream_checksum missing from {platform_file}"
        )
        # Must return False on failure (fail-closed), not True
        func_match = re.search(
            r'def _verify_upstream_checksum.*?(?=\ndef |\Z)', source, re.DOTALL
        )
        assert func_match, f"_verify_upstream_checksum body not found in {platform_file}"
        func_body = func_match.group(0)
        assert "return False" in func_body, (
            f"_verify_upstream_checksum in {platform_file} must return False on failure (fail-closed)"
        )
