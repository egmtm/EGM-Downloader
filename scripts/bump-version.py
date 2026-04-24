#!/usr/bin/env python3
"""
EGM Downloader — Universal Build Bump Script
============================================
Increments build number and syncs version info across all platform files.

Usage:
    python scripts/bump-version.py                    # bump build only
    python scripts/bump-version.py --version 0.92     # bump version + build
    python scripts/bump-version.py --dry-run          # preview, no writes
"""

import json
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _tz = ZoneInfo("America/New_York")
except ImportError:
    _tz = None

ROOT = Path(__file__).parent.parent


def load_version():
    with open(ROOT / "version.json") as f:
        return json.load(f)


def save_version(data, dry_run=False):
    content = json.dumps(data, indent=2) + "\n"
    if dry_run:
        print(f"  [DRY] version.json → build {data['build']}")
    else:
        (ROOT / "version.json").write_text(content)
        print(f"  ✅  version.json → build {data['build']}")


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


def patch(path, label, pattern, replacement, dry_run, flags=re.MULTILINE):
    if not path.exists():
        print(f"  ⚠️  {label} — file not found, skipping")
        return
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(pattern, replacement, text, count=1, flags=flags)
    if n == 0:
        print(f"  ⚠️  {label} — pattern not matched, skipping")
        return
    if dry_run:
        print(f"  [DRY] {label}")
    else:
        path.write_text(new_text, encoding="utf-8")
        print(f"  ✅  {label}")


def update_app_py(v, b, dry_run):
    path = ROOT / "app.py"
    # APP_VERSION = "0.91"   (with optional extra spaces for alignment)
    patch(path, "app.py → APP_VERSION",
          r'(APP_VERSION\s*=\s*")[^"]*(")',
          rf'\g<1>{v}\g<2>', dry_run)
    # APP_BUILD = 88
    patch(path, "app.py → APP_BUILD",
          r'(APP_BUILD\s*=\s*)\d+',
          rf'\g<1>{b}', dry_run)


def update_index_html(v, b, date, time_str, dry_run):
    path = ROOT / "templates" / "index.html"
    tooltip = f"v{v} - Build {b} - {date} {time_str}"

    # <title>EGM Downloader v0.91</title>
    patch(path, "index.html → <title>",
          r'(<title>EGM Downloader )v[\d.]+(<\/title>)',
          rf'\g<1>v{v}\g<2>', dry_run)

    # id="version-badge" ... title="..." data-build-title="..."
    # Update the title= attribute on version-badge
    patch(path, "index.html → version-badge title=",
          r'(id="version-badge"[^>]*?title=")[^"]*(")',
          rf'\g<1>{tooltip}\g<2>', dry_run, flags=re.DOTALL)

    # data-build-title="..."
    patch(path, "index.html → data-build-title=",
          r'(data-build-title=")[^"]*(")',
          rf'\g<1>{tooltip}\g<2>', dry_run)

    # version-badge visible text: >v0.91<
    patch(path, "index.html → version-badge text",
          r'(id="version-badge"[^>]*>)v[\d.]+(<)',
          rf'\g<1>v{v}\g<2>', dry_run, flags=re.DOTALL)

    # Footer span title= (the one that contains the build tooltip)
    # Pattern: title="v0.91 - Build 88 - ..." followed by >v0.91<
    patch(path, "index.html → footer span title=",
          r'(cursor:help[^>]*title=")v[\d.]+ - Build \d+ - [^"]*(")',
          rf'\g<1>{tooltip}\g<2>', dry_run)

    # Footer span visible text
    patch(path, "index.html → footer span text",
          r'(cursor:help[^>]*>[^<]*)v[\d.]+(<\/span>)',
          rf'\g<1>v{v}\g<2>', dry_run)


def update_package_json(v, b, dry_run):
    path = ROOT / "electron" / "package.json"
    if not path.exists():
        print(f"  ⚠️  electron/package.json — not found, skipping")
        return
    data = json.loads(path.read_text())
    data["version"] = v
    if dry_run:
        print(f"  [DRY] electron/package.json → version {v}")
    else:
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"  ✅  electron/package.json → version {v}")


def main():
    parser = argparse.ArgumentParser(description="EGM build bump")
    parser.add_argument("--version", help="New version string e.g. 0.92")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = load_version()
    new_version = args.version or data["version"]
    new_build   = data["build"] + 1
    date, time_str = now_est()

    print(f"\n{'='*54}")
    print(f"  EGM Downloader Build Bump")
    print(f"  v{data['version']} Build {data['build']}  →  v{new_version} Build {new_build}")
    print(f"  {date} {time_str}")
    if args.dry_run:
        print(f"  *** DRY RUN — nothing will be written ***")
    print(f"{'='*54}\n")

    # Update master record
    data["version"] = new_version
    data["build"]   = new_build
    data["date"]    = date
    data["time"]    = time_str
    save_version(data, args.dry_run)

    print()
    update_app_py(new_version, new_build, args.dry_run)
    update_index_html(new_version, new_build, date, time_str, args.dry_run)
    update_package_json(new_version, new_build, args.dry_run)

    print(f"\n{'='*54}")
    if args.dry_run:
        print(f"  Dry run complete — nothing written.")
    else:
        print(f"  Build {new_build} ready.")
        print(f"  Next: python scripts/gen-update-json.py")
    print(f"{'='*54}\n")


if __name__ == "__main__":
    main()
