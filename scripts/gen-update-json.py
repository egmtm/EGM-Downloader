#!/usr/bin/env python3
"""
EGM Downloader — Update JSON Generator
=======================================
Generates platform update JSONs from version.json for website distribution.

This script creates the JSON files that the website uses to display version
information and download links. Each platform gets its own JSON file:
  - Windows: egm-version.json (has auto-update capability)
  - Mac: egmac-update.json (no auto-update, informational only)
  - Linux: egmlinux-update.json (no auto-update, informational only)

Output files are created in dist/ directory and must be uploaded to:
  https://egerena.com/apps/

Usage:
    # Generate all platforms with default notes
    python scripts/gen-update-json.py
    
    # Generate with custom release notes (bullets separated by '|||')
    python scripts/gen-update-json.py --notes "Fixed bug|||Improved speed|||Added X"
    
    # Generate single platform only
    python scripts/gen-update-json.py --platform windows --notes "Windows-specific fix"
    
    # Preview without creating files
    python scripts/gen-update-json.py --dry-run

Examples:
    # Standard workflow (after building all platforms)
    $ python scripts/gen-update-json.py --notes "Bug fixes|||Performance improvements"
    # Creates: dist/egm-version.json, dist/egmac-update.json, dist/egmlinux-update.json
    
    # Windows-only release
    $ python scripts/gen-update-json.py --platform windows --notes "Fixed installer"
    # Creates: dist/egm-version.json only

Notes Format:
    Use '|||' (triple pipe) to separate multiple changes. This delimiter was
    chosen over semicolons because bullet text often contains semicolons
    (e.g. "A; B" as natural punctuation) which would be incorrectly split.
    --notes "First change|||Second change|||Third change"
    
    These become bullet points on the website:
    • First change
    • Second change  
    • Third change

Typical Workflow:
    1. python scripts/bump-version.py
    2. Build platform(s)
    3. python scripts/gen-update-json.py --notes "What changed"
    4. Upload dist/*.json files to egerena.com/apps/
    5. Upload platform binaries (EGMd.zip, EGMdM.zip, etc.)
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

ROOT      = Path(__file__).parent.parent
DIST      = ROOT / "dist"
PATCHNOTES = ROOT / "patchnotes.txt"


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


def parse_history(platform, max_versions=5):
    """Parse patchnotes.txt and return the last N version blocks filtered by platform.

    Only parses entries using the tagged bullet format (v0.93+):
        v0.94 - Build 96 (4/25/2026 9:30 AM EST)
        -----------------------------------------
          • [ALL] description
          • [WINDOWS] description

    Older entries without tags are skipped (no tagged bullets → nothing added).
    Returns newest-first list of {"version", "date", "notes"} dicts.
    """
    try:
        text = PATCHNOTES.read_text(encoding="utf-8")
    except Exception:
        return []

    platform_tag = platform.upper()       # WINDOWS, MAC, LINUX
    header_re = re.compile(
        r'^v(\d+\.\d+(?:\.\d+)?)\s+-\s+Build\s+\d+\s+\(([^)]+)\)'
    )
    # Match one or more consecutive tags, then the note text
    bullet_re = re.compile(
        r'^\s+•\s+((?:\[(?:ALL|WINDOWS|MAC|LINUX)\]\s*)+)(.+)$'
    )
    tag_re = re.compile(r'\[(ALL|WINDOWS|MAC|LINUX)\]')

    blocks   = []
    current  = None

    for line in text.splitlines():
        # Check for a version header line
        m = header_re.match(line.strip())
        if m:
            # Save previous block if it had any matching bullets
            if current is not None and current["notes"]:
                blocks.append(current)
            current = {"version": m.group(1), "date": m.group(2), "notes": []}
            continue

        if current is not None:
            bm = bullet_re.match(line)
            if bm:
                tags = set(tag_re.findall(bm.group(1)))
                note = bm.group(2).strip()
                if "ALL" in tags or platform_tag in tags:
                    current["notes"].append(note)

    # Flush the last block
    if current is not None and current["notes"]:
        blocks.append(current)

    # patchnotes.txt is newest-first — return up to max_versions
    return blocks[:max_versions]


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


def gen_windows_portable(data, notes, dry_run, checksum=""):
    """Generate update JSON for the Windows portable variant."""
    return write_json("egm-portable-version.json", {
        "_comment":       "EGM Downloader Windows Portable update feed. Upload to egerena.com/apps/egm-portable-version.json",
        "_version_notes": notes,
        "_history":       parse_history("windows"),
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    "https://egerena.com/apps/EGMd-portable.zip",
        "zip":            "EGMd-portable.zip",
        **({"_checksums": {"sha256": checksum, "algorithm": "SHA-256", "file": "EGMd-portable.zip"}} if checksum else {}),
    }, dry_run, "Windows Portable")


def gen_windows(data, notes, dry_run, checksum=""):
    p = data["platforms"]["windows"]
    payload = {
        "_comment":       "EGM Downloader Windows update feed. Upload to egerena.com/apps/egm-version.json",
        "_version_notes": notes,
        "_history":       parse_history("windows"),
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    p["downloadUrl"],
        "installer":      p["installer"],
        "zip":            p["zip"],
    }
    if checksum:
        payload["_checksums"] = {"sha256": checksum, "algorithm": "SHA-256", "file": p["zip"]}
    return write_json(p["updateJson"], payload, dry_run, "Windows")


def gen_mac(data, notes, dry_run, checksum=""):
    p = data["platforms"]["mac"]
    payload = {
        "_comment":       "EGM Downloader Mac update feed. Upload to egerena.com/apps/egmac-update.json",
        "_version_notes": notes,
        "_history":       parse_history("mac"),
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    p["downloadUrl"],
        "zip":            p["zip"],
    }
    if checksum:
        payload["_checksums"] = {"sha256": checksum, "algorithm": "SHA-256", "file": p["zip"]}
    return write_json(p["updateJson"], payload, dry_run, "Mac")


def gen_linux(data, notes, dry_run, checksum=""):
    p = data["platforms"]["linux"]
    payload = {
        "_comment":       "EGM Downloader Linux — informational, no auto-update. Upload to egerena.com/apps/egmlinux-update.json",
        "_version_notes": notes,
        "_history":       parse_history("linux"),
        "_last_updated":  now_iso(),
        "version":        data["version"],
        "build":          data["build"],
        "label":          build_label(data),
        "downloadUrl":    p["downloadUrl"],
        "zip":            p["zip"],
    }
    if checksum:
        payload["_checksums"] = {"sha256": checksum, "algorithm": "SHA-256", "file": p["zip"]}
    return write_json(p["updateJson"], payload, dry_run, "Linux")


def main():
    parser = argparse.ArgumentParser(description="Generate platform update JSONs")
    parser.add_argument("--notes", default="", help="Change notes, '|||'-separated (triple pipe — chosen to avoid collision with natural punctuation)")
    parser.add_argument("--platform", choices=["windows", "windows-portable", "mac", "linux"])
    parser.add_argument("--checksum", default="", help="SHA-256 checksum of the distribution zip (hex string)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data  = load_version()
    notes = [n.strip() for n in args.notes.split("|||") if n.strip()] if args.notes else []
    plats = [args.platform] if args.platform else ["windows", "mac", "linux"]

    print(f"\n  Generating update JSONs — v{data['version']} Build {data['build']}\n")

    outputs = []
    if "windows"          in plats: outputs.append(gen_windows(data, notes, args.dry_run, args.checksum))
    if "windows-portable" in plats: outputs.append(gen_windows_portable(data, notes, args.dry_run, args.checksum))
    if "mac"              in plats: outputs.append(gen_mac(data, notes, args.dry_run, args.checksum))
    if "linux"            in plats: outputs.append(gen_linux(data, notes, args.dry_run, args.checksum))

    if not args.dry_run:
        print(f"\n  Upload these to egerena.com/apps/:")
        for o in outputs:
            print(f"    {o.name}")
    print()


if __name__ == "__main__":
    main()
