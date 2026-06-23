#!/usr/bin/env python3
"""
EGM Downloader — Version Sync Validator
========================================
Validates that version.json is in sync with all platform files.

This script is used by GitHub Actions to ensure version numbers stay
consistent across the codebase. It checks that version.json matches:

  Shared / Windows (root):
    - app.py (APP_VERSION, APP_BUILD)
    - templates/index.html (title, version badge, footer)
    - windows/electron/package.json (version field)

  Linux:
    - linux/app.py (APP_VERSION, APP_BUILD)
    - linux/templates/index.html (title, header + footer tooltips, visible spans)
    - linux/electron/package.json (version == "X.Y.Z" where Z=0)
    - linux/INSTRUCTIONS.txt (header)

  Mac:
    - mac/app.py (APP_VERSION, APP_BUILD)
    - mac/electron/package.json (version + build.buildVersion)
    - mac/BUILD.sh (VERSION banner, DMG filename)

Exit codes:
  0 - All versions in sync
  1 - Mismatch found (prints details to stderr)

Usage:
    python scripts/validate-version-sync.py

    # In GitHub Actions:
    - name: Validate version sync
      run: python scripts/validate-version-sync.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def load_version():
    """Load version.json as source of truth."""
    with open(ROOT / "version.json") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _read_or_miss(path, label, errors):
    """Read text, or append a missing-file error and return None."""
    if not path.exists():
        errors.append(f"{label} not found")
        return None
    return path.read_text(encoding="utf-8")


def _read_json_or_miss(path, label, errors):
    if not path.exists():
        errors.append(f"{label} not found")
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"{label}: JSON parse error - {e}")
        return None


def _check_app_py(rel_path, expected_version, expected_build):
    """Shared check for root app.py and linux/app.py."""
    errors = []
    path = ROOT / rel_path
    content = _read_or_miss(path, rel_path, errors)
    if content is None:
        return errors

    m = re.search(r'APP_VERSION\s*=\s*"([^"]*)"', content)
    if not m:
        errors.append(f"{rel_path}: APP_VERSION constant not found")
    elif m.group(1) != expected_version:
        errors.append(f"{rel_path}: APP_VERSION is '{m.group(1)}', expected '{expected_version}'")

    m = re.search(r'APP_BUILD\s*=\s*(\d+)', content)
    if not m:
        errors.append(f"{rel_path}: APP_BUILD constant not found")
    elif int(m.group(1)) != expected_build:
        errors.append(f"{rel_path}: APP_BUILD is {m.group(1)}, expected {expected_build}")

    return errors


# --------------------------------------------------------------------------
# Shared / Windows checks
# --------------------------------------------------------------------------

def check_root_app_py(v, b):
    return _check_app_py("app.py", v, b)


def check_root_index_html(v, b, date, time):
    errors = []
    rel = "templates/index.html"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors

    # <title> tag
    m = re.search(r'<title>EGM Downloader v([\d.]+)</title>', content)
    if not m:
        errors.append(f"{rel}: <title> tag not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: <title> is 'v{m.group(1)}', expected 'v{v}'")


    return errors


def check_windows_package_json(v):
    errors = []
    rel = "windows/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors
    if data.get("version") != v:
        errors.append(f"{rel}: version is '{data.get('version')}', expected '{v}'")
    return errors


# --------------------------------------------------------------------------
# Mac checks
# --------------------------------------------------------------------------

def check_mac_app_py(v, b):
    return _check_app_py("mac/app.py", v, b)


# --------------------------------------------------------------------------
# Linux checks
# --------------------------------------------------------------------------

def check_linux_app_py(v, b):
    return _check_app_py("linux/app.py", v, b)


def check_linux_index_html(v, b, date, time):
    errors = []
    rel = "linux/templates/index.html"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors

    # <title> tag
    m = re.search(r'<title>EGM Downloader v([\d.]+)</title>', content)
    if not m:
        errors.append(f"{rel}: <title> tag not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: <title> is 'v{m.group(1)}', expected 'v{v}'")


    return errors


def check_linux_package_json(v):
    errors = []
    rel = "linux/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors
    expected = v
    if data.get("version") != expected:
        errors.append(f"{rel}: version is '{data.get('version')}', expected '{expected}'")
    return errors


def check_linux_instructions(v):
    errors = []
    rel = "linux/INSTRUCTIONS.txt"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors
    m = re.search(r'EGM Downloader v([\d.]+)\s+\u2014\s+Linux', content)
    if not m:
        errors.append(f"{rel}: header line 'EGM Downloader v0.xx -- Linux' not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: header version is 'v{m.group(1)}', expected 'v{v}'")
    return errors


# --------------------------------------------------------------------------
# Mac checks
# --------------------------------------------------------------------------

def check_mac_package_json(v):
    errors = []
    rel = "mac/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors

    expected = v
    if data.get("version") != expected:
        errors.append(f"{rel}: version is '{data.get('version')}', expected '{expected}'")

    build_cfg = data.get("build", {})
    bv = build_cfg.get("buildVersion") if isinstance(build_cfg, dict) else None
    if bv is None:
        # buildVersion is optional; only error if present and wrong.
        pass
    elif bv != expected:
        errors.append(f"{rel}: build.buildVersion is '{bv}', expected '{expected}'")

    return errors


def check_mac_build_sh(v):
    errors = []
    rel = "mac/BUILD.sh"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors

    m = re.search(r'VERSION: v([\d.]+)', content)
    if m and m.group(1) != v:
        errors.append(f"{rel}: VERSION banner is 'v{m.group(1)}', expected 'v{v}'")

    m = re.search(r'EGM Downloader-([\d.]+)-arm64\.dmg', content)
    expected_dmg = v
    if m and m.group(1) != expected_dmg:
        errors.append(f"{rel}: DMG filename has '{m.group(1)}', expected '{expected_dmg}'")

    return errors


# --------------------------------------------------------------------------
# Item 5 — Portable file list drift check
# --------------------------------------------------------------------------

def check_linux_drift_from_root():
    """Verify linux/templates/* matches root templates/* and linux/requirements.txt
    matches root requirements.txt.

    Bug class this catches:
      - linux/templates/theme_styles.html drifting from root → new themes
        (added to root) silently don't apply on Linux because the CSS rules
        are missing from the build.
      - linux/requirements.txt drifting from root → mutagen (or other deps)
        added to root never get installed in Linux Python bundle, so
        importlib.metadata.version() returns "not installed" forever.

    Returns errors list. Opportunistic — skips if either side doesn't exist.
    """
    errors = []
    root = ROOT

    # Templates that must stay in lock-step. index_styles.html / index_scripts.html
    # were split out of index.html (the CSS + the JS, incl. the THEMES array), so
    # they must be drift-checked too — otherwise a theme added to root but not linux
    # would slip through.
    template_files = ['index.html', 'index_styles.html', 'index_scripts.html',
                      'history.html', 'themes.html', 'theme_styles.html', 'theme_data.html',
                      'subscriptions.html', 'theme_validator.html',
                      'js/_core.html', 'js/_settings.html', 'js/_download.html',
                      'js/_bulk.html', 'js/_nav_history.html', 'js/_theme.html',
                      'js/_quality.html', 'js/_creator.html']
    for name in template_files:
        root_path = root / 'templates' / name
        linux_path = root / 'linux' / 'templates' / name
        if not root_path.exists() or not linux_path.exists():
            continue
        if root_path.read_bytes() != linux_path.read_bytes():
            errors.append(
                f"linux/templates/{name} has drifted from templates/{name} — "
                f"copy root version into linux/ to resync (root may have new "
                f"themes, fixes, or layout updates)."
            )

    # requirements.txt
    root_req  = root / 'requirements.txt'
    linux_req = root / 'linux' / 'requirements.txt'
    if root_req.exists() and linux_req.exists():
        # Compare ignoring blank lines and comments — what matters is the deps
        def normalize(p):
            return sorted(
                line.strip() for line in p.read_text().splitlines()
                if line.strip() and not line.strip().startswith('#')
            )
        if normalize(root_req) != normalize(linux_req):
            errors.append(
                "linux/requirements.txt has drifted from requirements.txt — "
                "deps differ (e.g. mutagen missing on linux means the plugin "
                "won't install, causing 'checking…' UI hang). Sync both."
            )

    return errors


def check_portable_file_list():
    """Verify the portable build's file copy list matches the NSIS installer file list.

    Parses windows/setup.nsi for File directives and windows/BUILD.sh for the
    portable stage cp commands — any drift means the portable zip would differ
    from the installer in ways that are probably unintentional.

    Opportunistic: skips gracefully if either file is missing or unparseable.
    """
    import re
    errors = []

    nsi_path = ROOT / 'windows' / 'setup.nsi'
    sh_path  = ROOT / 'windows' / 'BUILD.sh'

    if not nsi_path.exists() or not sh_path.exists():
        return errors  # can't check — skip silently

    nsi_text = nsi_path.read_text(encoding='utf-8', errors='replace')
    sh_text  = sh_path.read_text(encoding='utf-8', errors='replace')

    # Extract filenames from NSIS: File "${REPO_ROOT}/some/path/file.ext"
    nsi_files = set(re.findall(r'File\s+"[^"]*?[\\/]([^\\/\\"]+)"', nsi_text))

    # Extract filenames from portable stage cp block
    portable_section = sh_text
    start = sh_text.find('# ── Build portable variant')
    end   = sh_text.find('# ── Push to GitHub', start) if start != -1 else -1
    if start != -1 and end != -1:
        portable_section = sh_text[start:end]

    sh_files = set(re.findall(r'cp\s+"[^"]*?[\\/]([^\\/\\"]+)"\s+".*?PORTABLE_STAGE', portable_section))

    missing_from_portable = nsi_files - sh_files - {'egm-setup.exe'}  # installer-only, not in portable
    extra_in_portable     = sh_files  - nsi_files

    if missing_from_portable:
        errors.append(f"Portable build missing files that NSIS installs: {sorted(missing_from_portable)}")
    if extra_in_portable:
        errors.append(f"Portable build includes files not in NSIS installer: {sorted(extra_in_portable)}")

    return errors


# --------------------------------------------------------------------------
# Item 2 — Merge conflict marker scanner
# --------------------------------------------------------------------------

def check_merge_conflict_markers():
    """Fail if any tracked source file contains unresolved Git merge conflict markers.

    Uses git ls-files so gitignored directories (node_modules/, dist/, python/,
    linux/python/, mac/python/) are automatically excluded — no false positives
    from Chromium's LICENSES.chromium.html or pydoc_data/topics.py.
    """
    import subprocess
    errors = []
    EXTS = {'.py', '.js', '.json', '.sh', '.md', '.txt', '.html', '.nsi', '.yml', '.yaml'}
    # Split marker strings so this file doesn't trigger its own scan
    MARKERS = ('<' * 7 + ' ', '>' * 7 + ' ')

    try:
        result = subprocess.run(
            ['git', 'ls-files'],
            cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        tracked = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    except Exception:
        # git not available or not a repo — fall back to rglob with exclusions
        tracked = [
            str(p.relative_to(ROOT))
            for p in ROOT.rglob('*')
            if p.is_file()
            and p.suffix in EXTS
            and not any(part in ('node_modules', 'dist', 'python', '__pycache__') for part in p.parts)
        ]

    for rel in tracked:
        path = ROOT / rel
        if path.suffix not in EXTS:
            continue
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
            for marker in MARKERS:
                if marker in content:
                    errors.append(f"{rel}: contains merge conflict marker '{marker.strip()}'")
                    break  # one error per file is enough
        except (OSError, PermissionError):
            continue

    return errors


# --------------------------------------------------------------------------
# Item 4 — JSON feed validation (parse + required keys + cross-platform purity)
# --------------------------------------------------------------------------

FEED_REQUIRED_KEYS = [
    '_comment', '_version_notes', '_history', '_last_updated',
    'version', 'build', 'label', 'downloadUrl', 'zip',
]

FEED_BANNED_TERMS = {
    'egm-version.json':     ['mac update', 'macos', 'darwin', 'appimage', '.dmg', '.deb', '.rpm', 'snap install'],
    'egmac-update.json':    ['windows', 'win32', 'nsis', '.msi', 'appimage', 'apt-get', 'yum', 'snap install'],
    'egmlinux-update.json': ['windows', 'win32', '.exe', 'mac update', 'macos', 'darwin', '.dmg'],
}


def check_json_feeds_parse():
    """Fail loudly if any dist/ feed contains invalid JSON.

    Opportunistic: skips missing feeds (dist/ not present after non-build CI run).
    """
    errors = []
    dist = ROOT / 'dist'
    for feed in FEED_BANNED_TERMS:
        path = dist / feed
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            errors.append(f"dist/{feed}: invalid JSON — {e}")
    return errors


def check_json_feeds_keys():
    """Fail if any dist/ feed is missing a required top-level key."""
    errors = []
    dist = ROOT / 'dist'
    for feed in FEED_BANNED_TERMS:
        path = dist / feed
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue  # caught by check_json_feeds_parse
        missing = [k for k in FEED_REQUIRED_KEYS if k not in d]
        if missing:
            errors.append(f"dist/{feed}: missing required keys: {missing}")
    return errors


def check_json_feeds_purity():
    """Fail if a platform's _version_notes bullets contain language from other platforms.

    Terms are matched case-insensitively. Conservative list — only clear OS-specific
    language. Avoids terms that could legitimately appear in cross-platform bullets
    (e.g. 'Windows' is banned from Linux/Mac feeds, but 'window' is not).
    """
    errors = []
    dist = ROOT / 'dist'
    for feed, banned in FEED_BANNED_TERMS.items():
        path = dist / feed
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        for note in d.get('_version_notes', []):
            note_lower = note.lower()
            for term in banned:
                if term.startswith('.'):
                    # File extension — substring match is appropriate (.dmg, .exe, etc.)
                    hit = term in note_lower
                else:
                    # Word — use word boundary to avoid false positives
                    # (e.g. "nsis" inside "consistent", "win" inside "window")
                    hit = bool(re.search(r'\b' + re.escape(term) + r'\b', note_lower))
                if hit:
                    errors.append(
                        f"dist/{feed}: cross-platform leak — bullet contains '{term}': "
                        f"'{note[:80]}{'...' if len(note) > 80 else ''}'"
                    )
                    break  # one error per bullet is enough
    return errors


# --------------------------------------------------------------------------
# Pre-handoff feed checks (build monotonicity, notes/headline, checksums,
# size, cross-feed consistency, stale-feed) — all OPPORTUNISTIC: they run only
# when dist/ feeds are present (i.e. a release build), never on a plain CI run.
# --------------------------------------------------------------------------

# All four published feeds. The portable feed is optional (only emitted when a
# release ships the portable variant), so every check tolerates it being absent.
ALL_FEED_FILES = [
    'egm-version.json',           # Windows installer (auto-update)
    'egm-portable-version.json',  # Windows portable (optional)
    'egmac-update.json',          # Mac (informational)
    'egmlinux-update.json',       # Linux (informational)
]

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


def _load_feed(name):
    """Load a dist/ feed as JSON, or None if absent/unparseable (parse errors are
    reported by check_json_feeds_parse, so we stay silent here)."""
    path = ROOT / 'dist' / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None


def check_feed_build_monotonic():
    """Every feed's build must be strictly greater than the last released build
    (scripts/last-released-build.txt). Catches publishing a feed without bumping
    the build — the most common feed mistake. Skips if no baseline is configured."""
    errors = []
    baseline_path = ROOT / 'scripts' / 'last-released-build.txt'
    if not baseline_path.exists():
        return errors
    raw = baseline_path.read_text(encoding='utf-8').strip()
    try:
        baseline = int(raw.split()[0])
    except (ValueError, IndexError):
        errors.append(f"scripts/last-released-build.txt: not a valid integer ({raw!r})")
        return errors
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        b = d.get('build')
        if not isinstance(b, int):
            errors.append(f"dist/{name}: 'build' missing or not an integer ({b!r})")
        elif b <= baseline:
            errors.append(
                f"dist/{name}: build {b} must be > last released build {baseline} "
                f"— bump version.json build before generating feeds (and update "
                f"scripts/last-released-build.txt to {b} after this release ships)."
            )
    return errors


def check_feed_notes_and_headline():
    """Every feed's _version_notes must have >= 3 bullets, and — when a keyword list
    is configured (scripts/release-keywords.txt) — at least one bullet must mention a
    headline keyword. Catches thin notes and the v1.1 incident where feeds shipped
    with only maintenance bullets and never mentioned Subscriptions. An EMPTY keyword
    file intentionally skips the headline requirement (a pure maintenance release)."""
    errors = []
    kw_path = ROOT / 'scripts' / 'release-keywords.txt'
    keywords = []
    if kw_path.exists():
        keywords = [ln.strip().lower()
                    for ln in kw_path.read_text(encoding='utf-8').splitlines()
                    if ln.strip() and not ln.strip().startswith('#')]
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        notes = d.get('_version_notes', [])
        n = len(notes) if isinstance(notes, list) else 0
        if not isinstance(notes, list) or n < 3:
            errors.append(f"dist/{name}: _version_notes must have >= 3 bullets (has {n})")
            continue
        if keywords:
            joined = " ".join(str(x) for x in notes).lower()
            if not any(kw in joined for kw in keywords):
                errors.append(
                    f"dist/{name}: no _version_notes bullet mentions a headline keyword "
                    f"{keywords} — add the release's headline feature to the notes, or empty "
                    f"scripts/release-keywords.txt for a pure maintenance release."
                )
    return errors


def check_feed_checksums():
    """Every feed must carry _checksums.sha256 as lowercase 64-char hex. Catches the
    PowerShell uppercase-SHA256 issue, truncated hashes, and missing checksums."""
    errors = []
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        cs = d.get('_checksums')
        if not isinstance(cs, dict) or 'sha256' not in cs:
            errors.append(f"dist/{name}: missing _checksums.sha256")
            continue
        sha = cs.get('sha256', '')
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            if isinstance(sha, str) and sha.lower() != sha and _SHA256_RE.match(sha.lower()):
                reason = "uppercase — must be lowercase hex"
            elif isinstance(sha, str):
                reason = f"not 64 lowercase-hex chars (len={len(sha)})"
            else:
                reason = "not a string"
            errors.append(f"dist/{name}: _checksums.sha256 invalid ({reason}): {sha!r}")
    return errors


def check_feed_size_bytes():
    """Every feed must carry a top-level integer size_bytes > 0. (Currently the
    BUILD.sh gen-update-json calls do NOT pass --size-bytes, so this fails until the
    build is updated to pass it — that gap is exactly what this gate surfaces.)"""
    errors = []
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        sz = d.get('size_bytes')
        if not isinstance(sz, int) or isinstance(sz, bool) or sz <= 0:
            errors.append(
                f"dist/{name}: size_bytes must be an integer > 0 ({sz!r}) — pass "
                f"--size-bytes to gen-update-json.py in the build."
            )
    return errors


def check_feed_cross_consistency(v, b):
    """Every present feed must agree with version.json on BOTH version and build.
    This makes all four feeds consistent with each other (covers the case where the
    Mac feed was left stale at an old version while the others advanced)."""
    errors = []
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        fv = d.get('version')
        fb = d.get('build')
        if fv != v:
            errors.append(
                f"dist/{name}: version '{fv}' != source-of-truth '{v}' "
                f"(stale/forgotten feed — regenerate it)."
            )
        if fb != b:
            errors.append(
                f"dist/{name}: build {fb!r} != source-of-truth {b} (regenerate this feed)."
            )
    return errors


def main():
    print("Validating version sync...")
    print()

    try:
        data = load_version()
    except Exception as e:
        print(f"ERROR: Failed to load version.json: {e}", file=sys.stderr)
        return 1

    v = data.get("version")
    b = data.get("build")
    date = data.get("date")
    time = data.get("time")

    if not all([v, b, date, time]):
        print("ERROR: version.json missing required fields", file=sys.stderr)
        return 1

    print(f"   Source of truth: v{v} Build {b} @ {date} {time}")
    print()

    all_errors = []

    checks = [
        ("app.py",                              lambda: check_root_app_py(v, b)),
        ("templates/index.html",                lambda: check_root_index_html(v, b, date, time)),
        ("windows/electron/package.json",       lambda: check_windows_package_json(v)),
        ("linux/app.py",                        lambda: check_linux_app_py(v, b)),
        ("linux/templates/index.html",          lambda: check_linux_index_html(v, b, date, time)),
        ("linux/electron/package.json",         lambda: check_linux_package_json(v)),
        ("linux/INSTRUCTIONS.txt",              lambda: check_linux_instructions(v)),
        ("mac/app.py",                          lambda: check_mac_app_py(v, b)),
        ("mac/electron/package.json",           lambda: check_mac_package_json(v)),
        ("mac/BUILD.sh",                        lambda: check_mac_build_sh(v)),
    ]

    for label, fn in checks:
        print(f"   Checking {label}...")
        all_errors.extend(fn())

    # ── Item 5: Portable file list drift check ────────────────────────────────
    print("   Checking portable file list sync with NSIS installer...")
    all_errors.extend(check_portable_file_list())

    # ── Item 6: Linux/Mac copies drift check ──────────────────────────────────
    # linux/templates/* and linux/requirements.txt should track root/templates/*
    # and root/requirements.txt. Mac uses root templates + root requirements,
    # so it's only the linux side that needs explicit drift detection.
    print("   Checking linux/templates and linux/requirements for drift vs root...")
    all_errors.extend(check_linux_drift_from_root())

    # ── Item 2: Merge conflict markers ────────────────────────────────────────
    print("   Scanning for merge conflict markers...")
    all_errors.extend(check_merge_conflict_markers())

    # ── Item 4: JSON feed validation (opportunistic — skipped if dist/ absent) ─
    dist = ROOT / "dist"
    feeds_present = any((dist / f).exists() for f in ALL_FEED_FILES)
    if feeds_present:
        print("   Validating JSON feeds (parse validity)...")
        all_errors.extend(check_json_feeds_parse())
        print("   Validating JSON feeds (required keys)...")
        all_errors.extend(check_json_feeds_keys())
        print("   Validating JSON feeds (cross-platform purity)...")
        all_errors.extend(check_json_feeds_purity())
        print("   Validating JSON feeds (build > last released)...")
        all_errors.extend(check_feed_build_monotonic())
        print("   Validating JSON feeds (notes depth + headline keyword)...")
        all_errors.extend(check_feed_notes_and_headline())
        print("   Validating JSON feeds (sha256 lowercase hex)...")
        all_errors.extend(check_feed_checksums())
        print("   Validating JSON feeds (size_bytes present)...")
        all_errors.extend(check_feed_size_bytes())
        print("   Validating JSON feeds (cross-feed version/build agreement)...")
        all_errors.extend(check_feed_cross_consistency(v, b))
    else:
        print("   JSON feeds: dist/ not present — skipping feed validation")

    print()

    if all_errors:
        print("VERSION SYNC FAILED", file=sys.stderr)
        print(file=sys.stderr)
        print("Mismatches found:", file=sys.stderr)
        for error in all_errors:
            print(f"  * {error}", file=sys.stderr)
        print(file=sys.stderr)
        print("Fix by running: python scripts/bump-version.py", file=sys.stderr)
        print(file=sys.stderr)
        return 1
    else:
        print("All version strings are in sync across every platform.")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
