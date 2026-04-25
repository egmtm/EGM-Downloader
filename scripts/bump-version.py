#!/usr/bin/env python3
"""
EGM Downloader — Universal Build Bump Script
============================================
Increments build number and syncs version info across ALL platform files.

This script is the single source of truth for version management. It updates:

  Shared / Windows (root):
    - version.json                       (master record)
    - app.py                             (APP_VERSION, APP_BUILD)
    - templates/index.html               (title, version badge, footer)
    - windows/electron/package.json      (version field)

  Linux:
    - linux/app.py                       (APP_VERSION, APP_BUILD)
    - linux/templates/index.html         (title, header + footer spans)
    - linux/electron/package.json        (version, with ".0" suffix)
    - linux/INSTRUCTIONS.txt             (header line)

  Mac:
    - mac/electron/package.json          (version + buildVersion, ".0" suffix)
    - mac/BUILD.sh                       (VERSION banner + DMG filename example)

  README.md:
    - All three "Latest:" lines in the Download section
    - Project Stats block (Version + Build)

Usage:
    # Standard workflow - bump build number before every build
    python scripts/bump-version.py

    # Bump version string (e.g., from v0.91 to v0.92) + build number
    python scripts/bump-version.py --version 0.92

    # Preview changes without writing files
    python scripts/bump-version.py --dry-run

    # Preview version bump
    python scripts/bump-version.py --version 0.92 --dry-run

Examples:
    # Regular build workflow
    $ python scripts/bump-version.py
    # Output: v0.93 Build 93 -> v0.93 Build 94

    # Version bump workflow
    $ python scripts/bump-version.py --version 0.94
    # Output: v0.93 Build 93 -> v0.94 Build 94

Important:
    - Always run this BEFORE building any platform
    - Never manually edit version numbers in individual files
    - Build number auto-increments (never goes backwards)
    - Timestamps are in America/New_York timezone (EST)
    - Historical patchnotes entries and docstring examples are NOT touched

Next Steps:
    After running this script:
    1. python scripts/add-patchnote.py "Your changes here"
    2. Build your platform(s)
    3. python scripts/gen-update-json.py --notes "Your changes"
"""

import json
import re
import argparse
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _tz = ZoneInfo("America/New_York")
except ImportError:
    _tz = None

ROOT = Path(__file__).parent.parent


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

def load_version():
    with open(ROOT / "version.json") as f:
        return json.load(f)


def save_version(data, dry_run=False):
    content = json.dumps(data, indent=2) + "\n"
    if dry_run:
        print(f"  [DRY] version.json -> build {data['build']}")
    else:
        (ROOT / "version.json").write_text(content)
        print(f"  [OK]  version.json -> build {data['build']}")


def now_est():
    if _tz:
        dt = datetime.now(_tz)
    else:
        dt = datetime.utcnow()
    hour = dt.strftime("%I").lstrip("0") or "12"
    minute = dt.strftime("%M")
    ampm = dt.strftime("%p")
    date = f"{dt.month}/{dt.day}/{dt.year}"
    time_str = f"{hour}:{minute} {ampm} EST"
    return date, time_str


def patch(path, label, pattern, replacement, dry_run,
          flags=re.MULTILINE, count=1):
    """Regex replace helper. `count=0` means replace all matches."""
    if not path.exists():
        print(f"  [skip] {label} -- file not found")
        return
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(pattern, replacement, text, count=count, flags=flags)
    if n == 0:
        print(f"  [warn] {label} -- pattern not matched")
        return
    if dry_run:
        print(f"  [DRY] {label} ({n} replacement{'s' if n != 1 else ''})")
    else:
        path.write_text(new_text, encoding="utf-8")
        print(f"  [OK]  {label} ({n} replacement{'s' if n != 1 else ''})")


def patch_json(path, label, mutator, dry_run):
    """Read JSON, apply mutator(data) in-place, write back."""
    if not path.exists():
        print(f"  [skip] {label} -- file not found")
        return
    data = json.loads(path.read_text())
    mutator(data)
    if dry_run:
        print(f"  [DRY] {label}")
    else:
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"  [OK]  {label}")


# --------------------------------------------------------------------------
# Platform updaters -- ROOT / WINDOWS
# --------------------------------------------------------------------------

def update_root_app_py(v, b, dry_run):
    path = ROOT / "app.py"
    patch(path, "app.py -> APP_VERSION",
          r'(APP_VERSION\s*=\s*")[^"]*(")',
          rf'\g<1>{v}\g<2>', dry_run)
    patch(path, "app.py -> APP_BUILD",
          r'(APP_BUILD\s*=\s*)\d+',
          rf'\g<1>{b}', dry_run)


def update_root_index_html(v, b, date, time_str, dry_run):
    path = ROOT / "templates" / "index.html"

    patch(path, "templates/index.html -> <title>",
          r'(<title>EGM Downloader )v[\d.]+(</title>)',
          rf'\g<1>v{v}\g<2>', dry_run)

    # version-badge title attr — simplified (no build# shown to users)
    patch(path, "templates/index.html -> version-badge title=",
          r'(id="version-badge"[^>]*?title=")[^"]*(")',
          rf'\g<1>v{v}\g<2>', dry_run, flags=re.DOTALL)

    # data-build-title attr
    patch(path, "templates/index.html -> data-build-title=",
          r'(data-build-title=")[^"]*(")',
          rf'\g<1>v{v}\g<2>', dry_run)

    # version-badge visible text
    patch(path, "templates/index.html -> version-badge text",
          r'(id="version-badge"[^>]*>)v[\d.]+(<)',
          rf'\g<1>v{v}\g<2>', dry_run, flags=re.DOTALL)

    # footer span title attr — matches simplified title="vX.XX" or old long format
    patch(path, "templates/index.html -> footer span title=",
          r'(cursor:help[^>]*title=")[^"]*(")',
          rf'\g<1>v{v}\g<2>', dry_run)

    # footer span visible text
    patch(path, "templates/index.html -> footer span text",
          r'(cursor:help[^>]*>[^<]*)v[\d.]+(</span>)',
          rf'\g<1>v{v}\g<2>', dry_run)


def update_windows_package_json(v, dry_run):
    path = ROOT / "windows" / "electron" / "package.json"
    patch_json(path, f"windows/electron/package.json -> version {v}",
               lambda d: d.__setitem__("version", v), dry_run)


# --------------------------------------------------------------------------
# Platform updaters -- LINUX
# --------------------------------------------------------------------------

def update_linux_app_py(v, b, dry_run):
    path = ROOT / "linux" / "app.py"
    patch(path, "linux/app.py -> APP_VERSION",
          r'(APP_VERSION\s*=\s*")[^"]*(")',
          rf'\g<1>{v}\g<2>', dry_run)
    patch(path, "linux/app.py -> APP_BUILD",
          r'(APP_BUILD\s*=\s*)\d+',
          rf'\g<1>{b}', dry_run)


def update_linux_index_html(v, b, date, time_str, dry_run):
    path = ROOT / "linux" / "templates" / "index.html"

    # <title> tag
    patch(path, "linux/templates/index.html -> <title>",
          r'(<title>EGM Downloader )v[\d.]+(</title>)',
          rf'\g<1>v{v}\g<2>', dry_run)

    # version-badge title attr (Linux now has id="version-badge")
    patch(path, "linux/templates/index.html -> version-badge title=",
          r'(id="version-badge"[^>]*?title=")[^"]*(")',
          rf'\g<1>v{v}\g<2>', dry_run, flags=re.DOTALL)

    # version-badge visible text
    patch(path, "linux/templates/index.html -> version-badge text",
          r'(id="version-badge"[^>]*>)v[\d.]+(<)',
          rf'\g<1>v{v}\g<2>', dry_run, flags=re.DOTALL)

    # footer span title attr
    patch(path, "linux/templates/index.html -> footer span title=",
          r'(cursor:help[^>]*title=")[^"]*(")',
          rf'\g<1>v{v}\g<2>', dry_run)

    # footer span visible text
    patch(path, "linux/templates/index.html -> footer span text",
          r'(cursor:help[^>]*>[^<]*)v[\d.]+(</span>)',
          rf'\g<1>v{v}\g<2>', dry_run)


def update_linux_package_json(v, dry_run):
    # Mac & Linux electron package.json use "X.Y.Z" semver (extra ".0" suffix).
    path = ROOT / "linux" / "electron" / "package.json"
    patch_json(path, f"linux/electron/package.json -> version {v}.0",
               lambda d: d.__setitem__("version", f"{v}.0"), dry_run)


def update_linux_instructions(v, dry_run):
    path = ROOT / "linux" / "INSTRUCTIONS.txt"
    # First line: "EGM Downloader v0.xx -- Linux" (with em-dash U+2014)
    patch(path, "linux/INSTRUCTIONS.txt -> header line",
          r'(EGM Downloader )v[\d.]+(\s+\u2014\s+Linux)',
          rf'\g<1>v{v}\g<2>', dry_run)


# --------------------------------------------------------------------------
# Platform updaters -- MAC
# --------------------------------------------------------------------------

def update_mac_app_py(v, b, dry_run):
    path = ROOT / "mac" / "app.py"
    patch(path, "mac/app.py -> APP_VERSION",
          r'(APP_VERSION\s*=\s*")[^"]*(")',
          rf'\g<1>{v}\g<2>', dry_run)
    patch(path, "mac/app.py -> APP_BUILD",
          r'(APP_BUILD\s*=\s*)\d+',
          rf'\g<1>{b}', dry_run)


def update_mac_package_json(v, dry_run):    # Mac package.json has TWO version fields: top-level "version" and
    # build.buildVersion (used by electron-builder for CFBundleVersion).
    path = ROOT / "mac" / "electron" / "package.json"

    def mutate(d):
        d["version"] = f"{v}.0"
        if "build" in d and isinstance(d["build"], dict):
            d["build"]["buildVersion"] = f"{v}.0"

    patch_json(path, f"mac/electron/package.json -> version + buildVersion {v}.0",
               mutate, dry_run)


def update_mac_build_sh(v, dry_run):
    path = ROOT / "mac" / "BUILD.sh"
    # VERSION: v0.xx
    patch(path, "mac/BUILD.sh -> VERSION banner",
          r'(VERSION: )v[\d.]+',
          rf'\g<1>v{v}', dry_run)
    # EGM Downloader-0.xx.0-arm64.dmg (filename in instructions block)
    patch(path, "mac/BUILD.sh -> DMG filename example",
          r'(EGM Downloader-)[\d.]+(-arm64\.dmg)',
          rf'\g<1>{v}.0\g<2>', dry_run)


# --------------------------------------------------------------------------
# README.md
# --------------------------------------------------------------------------

def update_readme(v, b, dry_run):
    path = ROOT / "README.md"
    # Three "Latest: v0.xx Build NN" lines -- one per platform.
    # Replace all so each platform's line gets updated.
    patch(path, "README.md -> Latest: version + build (x3)",
          r'(\*\*Latest:\*\*\s+)v[\d.]+ Build \d+',
          rf'\g<1>v{v} Build {b}', dry_run, count=0)

    # Project Stats block:
    #   - **Version:** 0.xx
    #   - **Build:** NN
    patch(path, "README.md -> Project Stats -> Version",
          r'(- \*\*Version:\*\*\s+)[\d.]+',
          rf'\g<1>{v}', dry_run)

    # The Build line has been seen in two forms historically:
    #   "- **Build:** 88 (Windows/Mac) / 92 (Linux)"
    #   "- **Build:** 93"
    # Match either -- just overwrite everything after the colon and bold.
    patch(path, "README.md -> Project Stats -> Build",
          r'(- \*\*Build:\*\*\s+)[^\n]+',
          rf'\g<1>{b}', dry_run)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="EGM build bump (all platforms)")
    parser.add_argument("--version", help="New version string e.g. 0.94")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = load_version()
    new_version = args.version or data["version"]
    new_build   = data["build"] + 1
    date, time_str = now_est()

    print(f"\n{'='*62}")
    print(f"  EGM Downloader Build Bump -- ALL PLATFORMS")
    print(f"  v{data['version']} Build {data['build']}  ->  v{new_version} Build {new_build}")
    print(f"  {date} {time_str}")
    if args.dry_run:
        print(f"  *** DRY RUN -- nothing will be written ***")
    print(f"{'='*62}\n")

    # Master record
    data["version"] = new_version
    data["build"]   = new_build
    data["date"]    = date
    data["time"]    = time_str
    save_version(data, args.dry_run)

    print("\n-- Shared / Windows (root) -------------------------------")
    update_root_app_py(new_version, new_build, args.dry_run)
    update_root_index_html(new_version, new_build, date, time_str, args.dry_run)
    update_windows_package_json(new_version, args.dry_run)

    print("\n-- Linux -------------------------------------------------")
    update_linux_app_py(new_version, new_build, args.dry_run)
    update_linux_index_html(new_version, new_build, date, time_str, args.dry_run)
    update_linux_package_json(new_version, args.dry_run)
    update_linux_instructions(new_version, args.dry_run)

    print("\n-- Mac ---------------------------------------------------")
    update_mac_app_py(new_version, new_build, args.dry_run)
    update_mac_package_json(new_version, args.dry_run)
    update_mac_build_sh(new_version, args.dry_run)

    print("\n-- README.md ---------------------------------------------")
    update_readme(new_version, new_build, args.dry_run)

    print(f"\n{'='*62}")
    if args.dry_run:
        print(f"  Dry run complete -- nothing written.")
    else:
        print(f"  Build {new_build} ready across all platforms.")
        print(f"  Next: python scripts/gen-update-json.py")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    main()
