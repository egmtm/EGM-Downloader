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

    tooltip = f"v{v} - Build {b} - {date} {time}"

    m = re.search(r'<title>EGM Downloader v([\d.]+)</title>', content)
    if not m:
        errors.append(f"{rel}: <title> tag not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: <title> is 'v{m.group(1)}', expected 'v{v}'")

    m = re.search(r'id="version-badge"[^>]*?title="([^"]*)"', content, re.DOTALL)
    if not m:
        errors.append(f"{rel}: version-badge title= not found")
    elif m.group(1) != tooltip:
        errors.append(f"{rel}: version-badge title is '{m.group(1)}', expected '{tooltip}'")

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

    tooltip = f"v{v} - Build {b} - {date} {time}"

    m = re.search(r'<title>EGM Downloader v([\d.]+)</title>', content)
    if not m:
        errors.append(f"{rel}: <title> tag not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: <title> is 'v{m.group(1)}', expected 'v{v}'")

    # All build-tooltip title= attrs must match the expected tooltip.
    all_tooltips = re.findall(r'title="(v[\d.]+ - Build \d+ - [^"]*)"', content)
    if not all_tooltips:
        errors.append(f"{rel}: no build-tooltip title= attributes found")
    for t in all_tooltips:
        if t != tooltip:
            errors.append(f"{rel}: tooltip '{t}' does not match expected '{tooltip}'")

    # All cursor:help visible spans should show the current version.
    span_versions = re.findall(r'cursor:help[^>]*>v([\d.]+)</span>', content)
    if not span_versions:
        errors.append(f"{rel}: no visible version spans found")
    for sv in span_versions:
        if sv != v:
            errors.append(f"{rel}: visible span shows 'v{sv}', expected 'v{v}'")

    return errors


def check_linux_package_json(v):
    errors = []
    rel = "linux/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors
    expected = f"{v}.0"
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

    expected = f"{v}.0"
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
    expected_dmg = f"{v}.0"
    if m and m.group(1) != expected_dmg:
        errors.append(f"{rel}: DMG filename has '{m.group(1)}', expected '{expected_dmg}'")

    return errors


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

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
        ("mac/electron/package.json",           lambda: check_mac_package_json(v)),
        ("mac/BUILD.sh",                        lambda: check_mac_build_sh(v)),
    ]

    for label, fn in checks:
        print(f"   Checking {label}...")
        all_errors.extend(fn())

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
