#!/usr/bin/env python3
"""
EGM Downloader — Patch Notes Helper
=====================================
Prepends a new version section to patchnotes.txt with bullet points.

This script maintains the changelog by adding formatted entries to the top
of patchnotes.txt. Each entry includes version, build number, timestamp,
and a list of changes.

The patchnotes.txt file is distributed with builds and shown to users,
so keep entries clear and user-focused.

Usage:
    # Add single change
    python scripts/add-patchnote.py "Fixed download bug"
    
    # Add multiple changes
    python scripts/add-patchnote.py "Fixed bug" "Improved speed" "Added feature X"
    
    # Preview without writing
    python scripts/add-patchnote.py --dry-run "Test note"

Examples:
    $ python scripts/add-patchnote.py "Fixed playlist detection" "Improved ffmpeg download"
    
    Creates entry in patchnotes.txt:
    
    v0.91 - Build 89 (4/24/2026 2:30 PM EST)
    ----------------------------------------
      • Fixed playlist detection
      • Improved ffmpeg download

Best Practices:
    - Use action verbs: "Fixed", "Improved", "Added", "Updated"
    - Be specific: "Fixed YouTube playlist bug" not "Bug fixes"
    - User-focused: What changed for the user, not technical details
    - Keep it brief: One line per bullet
    
Typical Workflow:
    1. python scripts/bump-version.py
    2. python scripts/add-patchnote.py "Change 1" "Change 2"
    3. Build platform(s)
    4. python scripts/gen-update-json.py --notes "Change 1; Change 2"
    
Note:
    The version/build/date are read from version.json automatically.
    Always run bump-version.py first to ensure correct numbers.
"""

import json
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
PATCHNOTES = ROOT / "patchnotes.txt"


def main():
    parser = argparse.ArgumentParser(description="Prepend patchnote entry")
    parser.add_argument("bullets", nargs="*", help="Change bullets")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.bullets:
        print("  ⚠️  No bullets provided. Usage: python scripts/add-patchnote.py \"Change 1\" \"Change 2\"")
        sys.exit(1)

    with open(ROOT / "version.json") as f:
        data = json.load(f)
    v, b, d, t = data["version"], data["build"], data["date"], data["time"]

    header    = f"v{v} - Build {b} ({d} {t})"
    separator = "-" * len(header)
    bullets   = "\n".join(f"  • {x}" for x in args.bullets)
    section   = f"{header}\n{separator}\n{bullets}\n"

    existing = PATCHNOTES.read_text(encoding="utf-8") if PATCHNOTES.exists() else ""
    new_content = section + "\n" + existing

    if args.dry_run:
        print(f"\n  [DRY] Would prepend to patchnotes.txt:\n\n{section}")
    else:
        PATCHNOTES.write_text(new_content, encoding="utf-8")
        print(f"\n  ✅  patchnotes.txt updated — Build {b}, {len(args.bullets)} bullet(s)\n")


if __name__ == "__main__":
    main()
