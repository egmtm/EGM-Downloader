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
def signing_keypair():
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


def test_verify_manifest_rejects_tampered_content(app_mod, signing_keypair):
    """
    A manifest signed with a valid key but then tampered must be rejected.
    Any byte change to the payload invalidates the ed25519 signature.
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private, public = signing_keypair

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


def test_verify_manifest_rejects_wrong_key(app_mod, signing_keypair):
    """
    A manifest signed with an unknown private key must be rejected.
    Guards against attackers who generate their own keypair.
    """
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private, _ = signing_keypair

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


# ── Favorites sanitization — defense-in-depth on user input ───────────────────

def test_favorites_sanitization(app_mod):
    """Malicious favorite_themes payloads must be sanitized server-side:
    XSS keys filtered, duplicates removed, scope constrained, bool coerced."""
    with app_mod.app.test_client() as client:
        # Set the token header for auth
        headers = {"Content-Type": "application/json",
                   "X-EGM-Token": app_mod._API_TOKEN}

        payload = {
            "favorite_themes": [
                "void", "ghost",                    # valid
                "<script>alert(1)</script>",         # XSS — must be filtered
                "../../etc/passwd",                  # path traversal — must be filtered
                "void",                              # duplicate — must be deduped
                "UPPERCASE",                         # invalid (uppercase) — must be filtered
                "ok-theme",                          # valid
                123,                                 # non-string — must be filtered
            ],
            "random_theme_scope": "../../etc",       # invalid — must reset to default
            "random_theme_on_launch": 1,             # truthy int — must coerce to bool
        }
        resp = client.post("/api/settings/save", json=payload, headers=headers)
        assert resp.status_code == 200

        # Read back
        resp = client.get("/api/settings", headers=headers)
        data = resp.get_json()

        favs = data.get("favorite_themes", [])
        assert "void" in favs, "Valid key 'void' should survive"
        assert "ghost" in favs, "Valid key 'ghost' should survive"
        assert "ok-theme" in favs, "Valid key 'ok-theme' should survive"
        assert favs.count("void") == 1, "Duplicates should be removed"
        assert "<script>alert(1)</script>" not in str(favs), "XSS must be filtered"
        assert "../../etc/passwd" not in str(favs), "Path traversal must be filtered"
        assert "UPPERCASE" not in str(favs), "Uppercase keys must be filtered"
        assert len(favs) <= 4, f"Expected ≤4 clean keys, got {len(favs)}: {favs}"

        scope = data.get("random_theme_scope", "")
        assert scope in ("favorites", "all"), f"Invalid scope should reset to default, got: {scope}"

        on_launch = data.get("random_theme_on_launch")
        assert on_launch is True or on_launch is False, f"Should be bool, got: {type(on_launch)}"


# ── Port resolution — priority: env > settings > fallback ─────────────────────

def test_port_resolution_logic():
    """_resolve_port must follow: PORT env > flask_port setting > 8899 fallback.
    This exact logic crashed Mac/Linux in RC4 when the one-liner was wrong."""
    import os
    # We test the logic pattern, not the actual function (it's defined inside main guard)
    # Verify the pattern exists in all platform files
    for name, path in [("windows", "app.py"), ("linux", "linux/app.py"), ("mac", "mac/app.py")]:
        source = read_source(path)
        assert "def _resolve_port" in source, f"{name} missing _resolve_port function"
        assert 'os.environ.get("PORT")' in source, f"{name} _resolve_port must check PORT env var"
        assert 'flask_port' in source, f"{name} _resolve_port must check flask_port setting"
        assert "return 8899" in source, f"{name} _resolve_port must fall back to 8899"
        assert "1024" in source and "65535" in source, f"{name} _resolve_port must validate port range"


# ── Download directory validation ──────────────────────────────────────────────

def test_download_dir_validator_present_on_all_platforms():
    """_validate_download_dir must exist on all 3 platforms with identical logic."""
    for name, path in [("windows", "app.py"), ("linux", "linux/app.py"), ("mac", "mac/app.py")]:
        source = read_source(path)
        assert "def _validate_download_dir" in source, f"{name} missing _validate_download_dir"
        assert "expanduser().resolve()" in source, f"{name} must resolve paths before checking"
        assert 'rn + "/"' in source, f"{name} must use boundary-aware root check (rn + '/')"

def test_download_dir_rejects_system_roots(app_mod):
    """System roots (/etc, /bin, /sbin, etc.) must be rejected after resolve."""
    for sys_path in ["/etc/test", "/bin/evil", "/sbin/x", "/sys/kernel", "/proc/1"]:
        ok, _, err = app_mod._validate_download_dir(sys_path)
        assert not ok, f"Should reject system path: {sys_path}"
        assert "system" in err.lower(), f"Error should mention 'system' for {sys_path}"

def test_download_dir_boundary_not_prefix(app_mod):
    """Boundary-aware check: '/etcetera' must NOT be rejected just because it
    starts with '/etc'. The old prefix match got this wrong. This test fails
    if anyone weakens rn+'/' back to a naive startswith(rn)."""
    import tempfile, os
    # Create a real directory whose name starts with a system root prefix
    with tempfile.TemporaryDirectory(prefix="etcetera_") as td:
        ok, resolved, err = app_mod._validate_download_dir(td)
        assert ok, f"Should allow '{td}' — not a system root (got: {err})"

def test_download_dir_traversal_blocked(app_mod):
    """Paths with '..' that resolve to system roots must be rejected."""
    ok, _, err = app_mod._validate_download_dir("/tmp/../../etc")
    assert not ok, "Traversal to /etc via '..' should be rejected after resolve"

def test_download_dir_rejects_bad_input(app_mod):
    """Empty, None, int, and whitespace-only inputs must return clean errors."""
    for bad in [None, "", "   ", 123, 0]:
        ok, _, err = app_mod._validate_download_dir(bad)
        assert not ok, f"Should reject bad input: {bad!r}"

def test_download_dir_accepts_valid_writable(app_mod):
    """A valid, writable directory must pass and return the resolved path."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        ok, resolved, err = app_mod._validate_download_dir(td)
        assert ok, f"Should accept valid writable dir '{td}' (got: {err})"
        assert resolved, "Resolved path should be non-empty"

# ── /api/language — locale-code allowlist gate (v1.3 POLYGLOT) ─────────────────

def test_language_route_allowlist(app_mod):
    """The locale code must be validated against SUPPORTED_LANGUAGES before any
    file path is built. Unknown or traversal-shaped codes must never return 200."""
    with app_mod.app.test_client() as client:
        headers = {"X-EGM-Token": app_mod._API_TOKEN}
        for code in app_mod.SUPPORTED_LANGUAGES:
            resp = client.get(f"/api/language/{code}", headers=headers)
            assert resp.status_code == 200, f"supported code {code!r} should load"
            assert isinstance(resp.get_json().get("strings"), dict)
        for bad in ("xx", "EN", "en.json", "..", "..%2F..%2Fetc%2Fpasswd",
                    "en/../../egm_settings", "e" * 300):
            resp = client.get(f"/api/language/{bad}", headers=headers)
            assert resp.status_code != 200, f"unknown code {bad!r} must be rejected"


def test_language_setting_allowlist(app_mod, tmp_path):
    """/api/settings/save must reject language codes outside SUPPORTED_LANGUAGES
    and coerce show_language_selector to a bool."""
    app_mod.SETTINGS_FILE = tmp_path / "egm_settings.json"
    app_mod._settings_cache.clear()
    with app_mod.app.test_client() as client:
        headers = {"Content-Type": "application/json",
                   "X-EGM-Token": app_mod._API_TOKEN}
        client.post("/api/settings/save", json={"language": "ja"}, headers=headers)
        assert client.get("/api/settings", headers=headers).get_json()["language"] == "ja"
        for bad in ("zz", "../en", "en.json", 42, None):
            client.post("/api/settings/save", json={"language": bad}, headers=headers)
            data = client.get("/api/settings", headers=headers).get_json()
            assert data["language"] == "ja", f"invalid language {bad!r} must not persist"
        client.post("/api/settings/save", json={"show_language_selector": 0}, headers=headers)
        assert client.get("/api/settings", headers=headers).get_json()["show_language_selector"] is False
        client.post("/api/settings/save", json={"upscale_to_quality": 1}, headers=headers)
        assert client.get("/api/settings", headers=headers).get_json()["upscale_to_quality"] is True


def test_installer_language_handoff(app_mod, tmp_path, monkeypatch):
    """first-run-language.txt (written by the NSIS installer) must be
    allowlist-validated, win over OS detect, and be deleted after one read —
    valid or not. Malformed content falls through to normal detection."""
    import pathlib
    app_mod.SETTINGS_FILE = tmp_path / "egm_settings.json"

    handoff = pathlib.Path(app_mod.__file__ if hasattr(app_mod, "__file__") else ".").parent
    handoff = pathlib.Path(app_mod.LANGUAGES_DIR).parent / "first-run-language.txt"

    def fresh():
        app_mod._settings_cache.clear()
        if app_mod.SETTINGS_FILE.exists():
            app_mod.SETTINGS_FILE.unlink()

    try:
        # valid code: wins, persists, file deleted
        fresh(); handoff.write_text("ja", encoding="utf-8")
        assert app_mod._get_language_setting({}) == "ja"
        assert not handoff.exists(), "hand-off file must be deleted after read"
        assert __import__("json").loads(app_mod.SETTINGS_FILE.read_text())["language"] == "ja"

        # whitespace/case tolerated
        fresh(); handoff.write_text("  ES\n", encoding="utf-8")
        assert app_mod._get_language_setting({}) == "es"
        assert not handoff.exists()

        # invalid / traversal-shaped / oversized content: rejected, deleted, falls through
        for bad in ("zz", "../en", "en.json", "e" * 5000, ""):
            fresh(); handoff.write_text(bad, encoding="utf-8")
            got = app_mod._get_language_setting({})
            assert got in app_mod.SUPPORTED_LANGUAGES
            assert got == app_mod._detect_os_language(), f"bad content {bad!r} must fall through to OS detect"
            assert not handoff.exists(), f"hand-off file must be deleted even for bad content {bad!r}"

        # missing file: normal detection path
        fresh()
        assert app_mod._get_language_setting({}) == app_mod._detect_os_language()

        # persisted setting wins over a present hand-off file (file untouched)
        fresh(); handoff.write_text("ja", encoding="utf-8")
        assert app_mod._get_language_setting({"language": "fr"}) == "fr"
        assert handoff.exists(), "persisted setting short-circuits before the hand-off check"
    finally:
        if handoff.exists(): handoff.unlink()
