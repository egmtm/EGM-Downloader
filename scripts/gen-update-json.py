#!/usr/bin/env python3
"""
EGM Downloader — Update JSON Generator
=======================================
Generates platform update JSONs from version.json.

Usage:
    python scripts/gen-update-json.py
    python scripts/gen-update-json.py --notes "Fixed X; Added Y"
    python scripts/gen-update-json.py --platform windows
    python scripts/gen-update-json.py --dry-run
"""

import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _tz = ZoneInfo("America/New_York")
except ImportError:
    _tz = None

ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"


def load_version():
    with open(ROOT / "version.json") as f:
        return json.load(f)


def now_iso():
    if _tz:
        dt = datetime.now(_tz)
        return dt.strftime("%Y-%m-%dT%H:%M:%S-05:00")
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def build_label(data):
    return f"v{data['version']} - Build {data['build']} - {data['date']} {data['time']}"


def write_json(filename, payload, dry_run, label):
    content = json.dumps(payload, indent=2) + "\n"
    out = DIST / filename
    if dry_run:
        print(f"\n  [DRY] {label} → {filename}:\n{content}")
    else:
        DIST.mkdir(exist_ok=True)
        out.write_text(content)
        print(f"  ✅  {label} → dist/{filename}")
    return out


def gen_windows(data, notes, dry_run):
    p = data["platforms"]["windows"]
    return write_json(p["updateJson"], {
        "_comment":       "EGM Downloader Windows update feed. Upload to egerena.com/apps/egm-version.json",
        "_version_notes": notes,
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    p["downloadUrl"],
        "installer":      p["installer"],
        "zip":            p["zip"],
    }, dry_run, "Windows")


def gen_mac(data, notes, dry_run):
    p = data["platforms"]["mac"]
    return write_json(p["updateJson"], {
        "_comment":       "EGM Downloader Mac update feed. Upload to egerena.com/apps/egmac-update.json",
        "_version_notes": notes,
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    p["downloadUrl"],
        "zip":            p["zip"],
    }, dry_run, "Mac")


def gen_linux(data, notes, dry_run):
    p = data["platforms"]["linux"]
    return write_json(p["updateJson"], {
        "_comment":       "EGM Downloader Linux — informational, no auto-update. Upload to egerena.com/apps/egmlinux-update.json",
        "_version_notes": notes,
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    p["downloadUrl"],
        "zip":            p["zip"],
    }, dry_run, "Linux")


def main():
    parser = argparse.ArgumentParser(description="Generate platform update JSONs")
    parser.add_argument("--notes", default="", help="Change notes, semicolon-separated")
    parser.add_argument("--platform", choices=["windows", "mac", "linux"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data  = load_version()
    notes = [n.strip() for n in args.notes.split(";") if n.strip()] if args.notes else []
    plats = [args.platform] if args.platform else ["windows", "mac", "linux"]

    print(f"\n  Generating update JSONs — v{data['version']} Build {data['build']}\n")

    outputs = []
    if "windows" in plats: outputs.append(gen_windows(data, notes, args.dry_run))
    if "mac"     in plats: outputs.append(gen_mac(data, notes, args.dry_run))
    if "linux"   in plats: outputs.append(gen_linux(data, notes, args.dry_run))

    if not args.dry_run:
        print(f"\n  Upload these to egerena.com/apps/:")
        for o in outputs:
            print(f"    {o.name}")
    print()


if __name__ == "__main__":
    main()
