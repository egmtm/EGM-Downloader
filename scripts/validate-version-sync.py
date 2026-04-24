#!/usr/bin/env python3
"""
EGM Downloader — Version Sync Validator
========================================
Validates that version.json is in sync with all platform files.

This script is used by GitHub Actions to ensure version numbers stay
consistent across the codebase. It checks that version.json matches:
  - app.py (APP_VERSION, APP_BUILD)
  - templates/index.html (title, version badge, footer)
  - windows/electron/package.json (version field)

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


def check_app_py(expected_version, expected_build):
    """Check app.py constants."""
    errors = []
    path = ROOT / "app.py"
    
    if not path.exists():
        return ["app.py not found"]
    
    content = path.read_text()
    
    # Check APP_VERSION
    match = re.search(r'APP_VERSION\s*=\s*"([^"]*)"', content)
    if not match:
        errors.append("app.py: APP_VERSION constant not found")
    elif match.group(1) != expected_version:
        errors.append(f"app.py: APP_VERSION is '{match.group(1)}', expected '{expected_version}'")
    
    # Check APP_BUILD
    match = re.search(r'APP_BUILD\s*=\s*(\d+)', content)
    if not match:
        errors.append("app.py: APP_BUILD constant not found")
    elif int(match.group(1)) != expected_build:
        errors.append(f"app.py: APP_BUILD is {match.group(1)}, expected {expected_build}")
    
    return errors


def check_index_html(expected_version, expected_build, expected_date, expected_time):
    """Check templates/index.html version strings."""
    errors = []
    path = ROOT / "templates" / "index.html"
    
    if not path.exists():
        return ["templates/index.html not found"]
    
    content = path.read_text()
    expected_tooltip = f"v{expected_version} - Build {expected_build} - {expected_date} {expected_time}"
    
    # Check <title>
    match = re.search(r'<title>EGM Downloader v([\d.]+)</title>', content)
    if not match:
        errors.append("index.html: <title> tag not found or wrong format")
    elif match.group(1) != expected_version:
        errors.append(f"index.html: <title> version is 'v{match.group(1)}', expected 'v{expected_version}'")
    
    # Check version badge title attribute
    match = re.search(r'id="version-badge"[^>]*?title="([^"]*)"', content, re.DOTALL)
    if not match:
        errors.append("index.html: version-badge title attribute not found")
    elif match.group(1) != expected_tooltip:
        errors.append(f"index.html: version-badge title is '{match.group(1)}', expected '{expected_tooltip}'")
    
    # Check version badge visible text
    match = re.search(r'id="version-badge"[^>]*>v([\d.]+)<', content, re.DOTALL)
    if not match:
        errors.append("index.html: version-badge text not found")
    elif match.group(1) != expected_version:
        errors.append(f"index.html: version-badge text is 'v{match.group(1)}', expected 'v{expected_version}'")
    
    return errors


def check_package_json(expected_version):
    """Check windows/electron/package.json version."""
    errors = []
    path = ROOT / "windows" / "electron" / "package.json"
    
    if not path.exists():
        # This is optional - not all platforms may have this file
        return []
    
    try:
        data = json.loads(path.read_text())
        if "version" not in data:
            errors.append("windows/electron/package.json: version field not found")
        elif data["version"] != expected_version:
            errors.append(f"windows/electron/package.json: version is '{data['version']}', expected '{expected_version}'")
    except json.JSONDecodeError as e:
        errors.append(f"windows/electron/package.json: JSON parse error - {e}")
    
    return errors


def main():
    print("🔍 Validating version sync...")
    print()
    
    # Load source of truth
    try:
        data = load_version()
    except Exception as e:
        print(f"❌ ERROR: Failed to load version.json: {e}", file=sys.stderr)
        return 1
    
    version = data.get("version")
    build = data.get("build")
    date = data.get("date")
    time = data.get("time")
    
    if not all([version, build, date, time]):
        print("❌ ERROR: version.json missing required fields", file=sys.stderr)
        return 1
    
    print(f"   Source of truth: v{version} Build {build}")
    print()
    
    # Run all checks
    all_errors = []
    
    print("   Checking app.py...")
    all_errors.extend(check_app_py(version, build))
    
    print("   Checking templates/index.html...")
    all_errors.extend(check_index_html(version, build, date, time))
    
    print("   Checking windows/electron/package.json...")
    all_errors.extend(check_package_json(version))
    
    print()
    
    # Report results
    if all_errors:
        print("❌ VERSION SYNC FAILED", file=sys.stderr)
        print(file=sys.stderr)
        print("Mismatches found:", file=sys.stderr)
        for error in all_errors:
            print(f"  • {error}", file=sys.stderr)
        print(file=sys.stderr)
        print("Fix by running: python scripts/bump-version.py", file=sys.stderr)
        print(file=sys.stderr)
        return 1
    else:
        print("✅ All version strings are in sync!")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
