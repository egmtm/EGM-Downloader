#!/usr/bin/env python3
"""
EGM Downloader — Patch Notes Helper
=====================================
Prepends a new version section to patchnotes.txt.

Usage:
    python scripts/add-patchnote.py "Fixed bug" "Improved speed"
    python scripts/add-patchnote.py --dry-run "Test note"
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
