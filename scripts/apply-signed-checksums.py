#!/usr/bin/env python3
"""Apply EGM's post-signing checksums: generate + independently verify the
Windows/Mac/Linux update feeds in one deterministic pass.

Every release cut this cycle involved the same manual sequence: EGM pastes
checksums for the signed binaries, CODEMASTER hand-writes a one-off script to
cross-check them, calls gen-update-json.py per platform, then re-parses each
generated feed to confirm it actually matches what was given -- the same
verification, rewritten from scratch, every single release. This script does
exactly that sequence, deterministically, so the manual step that could slip
under time pressure doesn't have to be reinvented each time.

Usage:
    python3 scripts/apply-signed-checksums.py < checksums.txt
    python3 scripts/apply-signed-checksums.py checksums.txt
    pbpaste | python3 scripts/apply-signed-checksums.py   # paste EGM's message directly

Input: one line per file, whitespace-separated `<filename> <size> <sha256>`,
matching the exact format EGM has pasted every release, e.g.:

    EGMd.zip             589003 5f9a694c9b65430d730a0169d678aff7afeff8cca9f3847d686521532e1a865f
    EGMd-Portable.zip    587610 51270fa3a8e6ae511d07e08b94aa57fe5730f5c7b0ac956cfef3f8be4360f00a
    EGMdL.zip         169186390 af36bab30a47310a67206bbf24fe096366c34687111b2b1bfe4ced69c78cef35
    EGMdM.zip         140680798 51c58c3aa1f131d1eb2929b41674ca12b7357baa565730106e5a7ee2a737f54d

Extra lines/prose around the checksum lines are fine -- only lines matching
the 3-column pattern are parsed. Unrecognized filenames are reported and
skipped, not silently dropped.

Does NOT sign anything and does NOT decide when a release is ready -- it only
mechanizes the generate-and-verify step that already happens by hand.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

# filename (case-insensitive) -> (gen-update-json.py --platform value, feed filename)
FILENAME_MAP = {
    "egmd.zip":          ("windows",          "egm-version.json"),
    "egmd-portable.zip": ("windows-portable", "egm-portable-version.json"),
    "egmdm.zip":         ("mac",              "egmac-update.json"),
    "egmdl.zip":         ("linux",            "egmlinux-update.json"),
}

LINE_RE = re.compile(r"^\s*(\S+\.zip)\s+(\d+)\s+([0-9a-fA-F]{64})\s*$")


def parse_input(text: str):
    """Return list of (filename, size, sha256) for every recognized line."""
    entries = []
    for raw_line in text.splitlines():
        m = LINE_RE.match(raw_line)
        if not m:
            continue
        filename, size, sha256 = m.group(1), int(m.group(2)), m.group(3).lower()
        entries.append((filename, size, sha256))
    return entries


def main():
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text()
    else:
        text = sys.stdin.read()

    entries = parse_input(text)
    if not entries:
        print("No recognized checksum lines found (expected: '<file.zip> <size> <64-hex-sha256>').")
        sys.exit(1)

    print(f"Parsed {len(entries)} checksum line(s).\n")

    results = []  # (filename, ok, detail)
    for filename, size, sha256 in entries:
        key = filename.lower()
        mapped = FILENAME_MAP.get(key)
        if not mapped:
            print(f"⚠  {filename}: unrecognized filename, skipped (known: {', '.join(FILENAME_MAP)})")
            results.append((filename, False, "unrecognized filename"))
            continue
        platform, feed_name = mapped

        print(f"→ {filename} ({platform}): generating {feed_name} ...")
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "gen-update-json.py"),
             "--platform", platform, "--checksum", sha256, "--size-bytes", str(size)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(f"  ✗ gen-update-json.py failed:\n{proc.stderr}")
            results.append((filename, False, "generator failed"))
            continue

        # Independent re-verification: re-read the feed we just wrote and
        # confirm it actually contains what we asked for, not just that the
        # generator exited 0. This is the check that's been done by hand
        # every release -- automating the exact same check, not skipping it.
        feed_path = DIST / feed_name
        try:
            feed = json.loads(feed_path.read_text())
            actual_sha = feed.get("_checksums", {}).get("sha256", "")
            actual_size = feed.get("size_bytes", -1)
            if actual_sha == sha256 and actual_size == size:
                print(f"  ✓ verified: {feed_name} sha256 and size_bytes match exactly")
                results.append((filename, True, feed_name))
            else:
                print(f"  ✗ MISMATCH after generation — sha {actual_sha == sha256}, size {actual_size == size}")
                results.append((filename, False, "post-write mismatch"))
        except Exception as e:
            print(f"  ✗ could not re-read {feed_path}: {e}")
            results.append((filename, False, "re-read failed"))

    print()
    ok_count = sum(1 for _, ok, _ in results if ok)
    print(f"{ok_count}/{len(results)} feed(s) generated and independently verified.")

    if ok_count != len(results):
        print("Not all inputs succeeded — see ✗ lines above. Not running the validator.")
        sys.exit(1)

    print("\nRunning scripts/validate-version-sync.py ...\n")
    val = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate-version-sync.py")], cwd=ROOT)
    sys.exit(val.returncode)


if __name__ == "__main__":
    main()
