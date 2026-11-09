"""
Tier 2 — Security-critical tests.

Tests for regressions on security-critical paths. Each test maps to a
real finding from the audit cycle. If any of these fails, something that
was deliberately secured has been reverted.
"""
import os
import re
import base64
from pathlib import Path
import json
import pytest
from conftest import read_source


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_mod(tmp_path_factory):
    """Import Windows app module once for this test module."""
    import sys, os
    os.environ.setdefault("EGM_API_TOKEN", "ci-test-token-not-secret")
    sys.argv = ["app.py"]
    import importlib.util
    root = os.path.dirname(os.path.dirname(__file__))
    spec = importlib.util.spec_from_file_location("egm_app", os.path.join(root, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # The Windows app keeps its data next to app.py, which in a checkout is the repository root:
    # without this, the settings tests below replaced the developer's own egm_settings.json.
    data = tmp_path_factory.mktemp("egm_data")
    for name in ("SETTINGS_FILE", "HISTORY_FILE", "SUBS_FILE", "COOKIES_FILE"):
        setattr(mod, name, data / getattr(mod, name).name)
    mod.THUMBNAILS_DIR = data / "thumbnails"
    mod._settings_cache.clear()
    return mod


def _inside(path, folder):
    """Whether path is folder or inside it, compared as paths (a sibling such as c1.pt next to c1 is not
    inside, and a different spelling of the same folder is)."""
    return Path(path).resolve().is_relative_to(Path(folder).resolve())


def test_the_data_files_these_tests_write_are_outside_the_repository(app_mod):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("SETTINGS_FILE", "HISTORY_FILE", "SUBS_FILE", "COOKIES_FILE", "THUMBNAILS_DIR"):
        assert not _inside(getattr(app_mod, name), root), name


def test_inside_compares_paths_not_text(tmp_path):
    root = tmp_path / "c1"
    assert not _inside(tmp_path / "c1.pt" / "egm_settings.json", root), "a sibling folder is not inside"
    assert _inside(root / "data" / "egm_settings.json", root)
    assert _inside(tmp_path / "other" / ".." / "c1" / "x", root), "another spelling of a path inside"


@pytest.fixture(scope="module")
def signing_keypair():
    """Generate a throwaway ed25519 keypair for manifest signing tests."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private = Ed25519PrivateKey.generate()
    public  = private.public_key()
    return private, public


# ── _fetch_thumbnail — HTTPS only enforcement ──────────────────────────────────

def test_thumbnail_rejects_http_url(app_mod):
    """
    _fetch_thumbnail must reject http:// URLs.
    Regression guard: HTTPS-only check added v0.99.11 — must not be removed.
    """
    result = app_mod._fetch_thumbnail("http://attacker.com/image.jpg", "Mozilla/5.0")
    assert result == b"", "http:// URL should be rejected (return no bytes)"


def test_thumbnail_rejects_file_url(app_mod):
    """_fetch_thumbnail must reject file:// URLs (local file access)."""
    result = app_mod._fetch_thumbnail("file:///etc/passwd", "Mozilla/5.0")
    assert result == b"", "file:// URL should be rejected"


def test_thumbnail_rejects_empty_url(app_mod):
    """_fetch_thumbnail must handle empty string gracefully."""
    result = app_mod._fetch_thumbnail("", "Mozilla/5.0")
    assert result == b"", "Empty URL should return no bytes"


def test_thumbnail_https_url_is_attempted(app_mod):
    """
    _fetch_thumbnail must NOT reject https:// URLs at the scheme check stage.
    (The request itself may fail in test environment — that's fine.)
    Verifies the HTTPS check doesn't accidentally block valid URLs.
    """
    # A valid https URL should pass the scheme check and attempt the request
    # We verify this by checking the source code contains the correct guard
    source = read_source("app.py")
    m = re.search(r'def _fetch_thumbnail.*?return b""', source, re.DOTALL)
    assert m, "_fetch_thumbnail not found in source"
    func_body = m.group(0)
    assert 'startswith("https://")' in func_body, (
        "_fetch_thumbnail must check for https:// prefix"
    )


# ── _clean_sponsorblock_categories — subprocess-arg allowlist ──────────────────
# This is the single gate every SponsorBlock category list passes through before
# it can reach a yt-dlp subprocess argument (settings save, subscription update,
# and the download route itself all call it). If this regresses, unvalidated
# client input could reach --sponsorblock-remove directly.

def test_sponsorblock_categories_rejects_unknown_values(app_mod):
    result = app_mod._clean_sponsorblock_categories(
        ["sponsor", "not_a_real_category", "intro", "; rm -rf /"]
    )
    assert result == ["sponsor", "intro"], (
        "unknown/malicious category strings must be dropped, not passed through"
    )


def test_sponsorblock_categories_rejects_non_list_input(app_mod):
    for bad in ("sponsor", {"sponsor": True}, None, 42, True):
        assert app_mod._clean_sponsorblock_categories(bad) == [], (
            f"non-list input {bad!r} must return [], not raise or coerce"
        )


def test_sponsorblock_categories_dedupes_preserving_order(app_mod):
    result = app_mod._clean_sponsorblock_categories(
        ["outro", "sponsor", "outro", "sponsor", "intro"]
    )
    assert result == ["outro", "sponsor", "intro"], (
        "duplicates must collapse to first occurrence, original order preserved"
    )


def test_sponsorblock_categories_excludes_mark_only_categories(app_mod):
    """poi_highlight and chapter exist in SponsorBlock's data but are mark-only,
    not removable via --sponsorblock-remove (verified directly against this app's
    pinned yt-dlp binary) -- must never be offered, even if requested."""
    result = app_mod._clean_sponsorblock_categories(["poi_highlight", "chapter", "sponsor"])
    assert result == ["sponsor"], (
        "poi_highlight/chapter are mark-only and must not pass this filter"
    )
    assert "poi_highlight" not in app_mod.SPONSORBLOCK_CATEGORIES
    assert "chapter" not in app_mod.SPONSORBLOCK_CATEGORIES


def test_no_unvalidated_sponsorblock_category_can_reach_the_yt_dlp_argv(app_mod, tmp_path, monkeypatch):
    """Behavioural companion to the four unit tests above, which all call
    _clean_sponsorblock_categories() directly.

    Those tests prove the gate is CORRECT; none of them proves it is INSTALLED.
    Verified by mutation: deleting the _clean_sponsorblock_categories() call from
    start_download AND the defensive re-sanitize inside run_download -- so raw
    client input is joined straight into the --sponsorblock-remove argument --
    left the whole suite green. This drives the real argv instead: whatever ends
    up after --sponsorblock-remove must be a subset of SPONSORBLOCK_CATEGORIES,
    no matter which layer did the filtering.

    (Severity bound, so this is read for what it is: the yt-dlp command is
    spawned via subprocess.Popen(list(cmd)) with no shell, so an unfiltered
    value lands as one argv element -- a malformed yt-dlp argument or a
    TypeError, not command injection. This guards the allowlist boundary, not
    an RCE.)
    """
    captured = {}

    class _StopBeforeSpawn(Exception):
        pass

    def _fake_popen_yt(*cmd, **kw):
        captured["cmd"] = list(cmd)
        raise _StopBeforeSpawn()

    monkeypatch.setattr(app_mod, "_popen_yt", _fake_popen_yt)

    # All-string poison: a non-string member would make ",".join() raise before
    # the argv is ever built, so the test would fail for the wrong reason.
    poison = ["sponsor", "chapter", "poi_highlight", "filler",
              "; rm -rf /", "--exec=curl http://example.invalid"]
    url = "https://example.invalid/watch?v=1"
    job_id = "pytest-sponsorblock-argv"
    app_mod.jobs[job_id] = {
        "status": "queued", "url": url, "title": "", "proc": None,
        "cancelled": False, "download_dir": str(tmp_path), "format": "video",
        "thumbnail": "",
    }
    try:
        try:
            app_mod.run_download(job_id, url, "video", None, str(tmp_path),
                                 sponsorblock_categories=poison)
        except _StopBeforeSpawn:
            pass
    finally:
        app_mod.jobs.pop(job_id, None)

    assert "cmd" in captured, (
        "run_download never reached the yt-dlp spawn, so this guard proved "
        "nothing -- the argv could not be inspected (an earlier exception, or "
        "the spawn helper was renamed and this monkeypatch no longer applies)"
    )
    cmd = captured["cmd"]
    assert "--sponsorblock-remove" in cmd, (
        "expected --sponsorblock-remove in the argv when categories were "
        f"requested; vacuity check for this guard. argv: {cmd}"
    )
    value = cmd[cmd.index("--sponsorblock-remove") + 1]
    passed = value.split(",")
    assert set(passed) <= set(app_mod.SPONSORBLOCK_CATEGORIES), (
        f"unvalidated categories reached the yt-dlp argv: {passed!r} -- only "
        f"{list(app_mod.SPONSORBLOCK_CATEGORIES)} may pass. The allowlist gate "
        "is missing from at least one layer of this path."
    )
    assert passed == ["sponsor"], (
        f"expected only the one legitimate category to survive, got {passed!r}"
    )


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

def test_download_dir_must_be_a_full_path(app_mod):
    """A relative path, or a Windows path read on mac or linux (which is just a relative name there),
    would resolve under the app's working directory and be accepted. Imported settings and
    subscription exports can carry such values from another computer."""
    import os
    # a drive letter path is a full path on Windows itself, so that case only applies elsewhere
    for bad in ["downloads", "./x", ".."] + ([] if os.name == "nt" else [r"C:\Users\alice\Videos"]):
        ok, resolved, err = app_mod._validate_download_dir(bad)
        assert not ok and not resolved, f"relative looking path accepted: {bad!r}"
        assert "full path" in err
    for rel in ("app.py", "linux/app.py", "mac/app.py"):
        assert "must be a full path" in read_source(rel), rel

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


def test_language_setting_allowlist(app_mod, tmp_path, monkeypatch):
    """/api/settings/save must reject language codes outside SUPPORTED_LANGUAGES
    and coerce show_language_selector to a bool."""
    monkeypatch.setattr(app_mod, "SETTINGS_FILE", tmp_path / "egm_settings.json")
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
    monkeypatch.setattr(app_mod, "SETTINGS_FILE", tmp_path / "egm_settings.json")

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
