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

    # version-badge visible text
    m = re.search(r'id="version-badge"[^>]*>v([\d.]+)<', content, re.DOTALL)
    if not m:
        errors.append(f"{rel}: version-badge visible text not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: version-badge text is 'v{m.group(1)}', expected 'v{v}'")

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

    # version-badge visible text
    m = re.search(r'id="version-badge"[^>]*>v([\d.]+)<', content, re.DOTALL)
    if not m:
        errors.append(f"{rel}: version-badge visible text not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: version-badge text is 'v{m.group(1)}', expected 'v{v}'")

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

    # Templates that must stay in lock-step
    template_files = ['index.html', 'history.html', 'themes.html', 'theme_styles.html']
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
                if term in note_lower:
                    errors.append(
                        f"dist/{feed}: cross-platform leak — bullet contains '{term}': "
                        f"'{note[:80]}{'...' if len(note) > 80 else ''}'"
                    )
                    break  # one error per bullet is enough
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
    feeds_present = any((dist / f).exists() for f in FEED_BANNED_TERMS)
    if feeds_present:
        print("   Validating JSON feeds (parse validity)...")
        all_errors.extend(check_json_feeds_parse())
        print("   Validating JSON feeds (required keys)...")
        all_errors.extend(check_json_feeds_keys())
        print("   Validating JSON feeds (cross-platform purity)...")
        all_errors.extend(check_json_feeds_purity())
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
