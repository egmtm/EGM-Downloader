#!/usr/bin/env python3
"""
EGM Downloader — Node.js pin check
==================================
The Windows launcher pins the SHA-256 of the Node.js zip it downloads
(NODE_ZIP_SHA256 in windows/launch.py). The tests catch a missing pin but not a
mistyped one, so run this at every Node bump, right after editing the table:

    python3 scripts/check-node-pin.py             # pin vs nodejs.org's SHASUMS256.txt
    python3 scripts/check-node-pin.py --download  # also download the zip (~37 MB) and run
                                                  # the launcher's own check on it

It reads the version, URL and pin from the launcher itself, so there is nothing
to keep in sync. It needs the network, so it is not part of CI.

Exit code: 0 the pin is right, 1 it is wrong or missing, 2 nodejs.org not reachable.
"""
import importlib.util
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"
UA = os.environ.get("EGM_CHECK_UA", "EGM-Downloader-node-pin-check")


def manifest_hash(manifest, zip_name):
    """The SHA-256 a SHASUMS256.txt manifest lists for zip_name, lowercase, or None."""
    for line in manifest.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == zip_name:
            return parts[0].lower()
    return None


def fetch(url):
    """Open a URL; the result works as a context manager and has .read()."""
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60)


def check(launch, fetch=fetch, download=False, out=print):
    """Compare the launcher's Node pin with nodejs.org. Returns the exit code."""
    version, name = launch.NODE_VERSION, launch.NODE_ZIP_NAME
    pin = (launch.NODE_ZIP_SHA256.get(version) or "").strip().lower()
    base = launch.NODE_ZIP_URL.rsplit("/", 1)[0]
    out(f"Node.js {version}: {name}")
    if not pin:
        out(f"FAIL: windows/launch.py has no NODE_ZIP_SHA256 entry for {version}")
        return 1
    try:
        with fetch(base + "/SHASUMS256.txt") as r:
            listed = manifest_hash(r.read().decode("utf-8", "replace"), name)
    except OSError as e:
        out(f"Could not fetch the manifest from nodejs.org: {e}")
        return 2
    out(f"  pin in windows/launch.py : {pin}")
    out(f"  nodejs.org SHASUMS256.txt: {listed}")
    if listed is None:
        out("FAIL: the manifest has no entry for that zip")
        return 1
    if listed != pin:
        out("FAIL: the pin does not match the manifest, fix NODE_ZIP_SHA256")
        return 1
    out("OK: the pin matches nodejs.org's manifest")
    if not download:
        return 0
    try:
        with tempfile.TemporaryDirectory() as tmp, fetch(launch.NODE_ZIP_URL) as r:
            zip_path = Path(tmp) / name
            zip_path.write_bytes(r.read())
            accepted = launch._verify_node_zip(zip_path)
    except OSError as e:
        out(f"Could not download the zip from nodejs.org: {e}")
        return 2
    out("OK: the launcher accepts the real zip" if accepted else "FAIL: the launcher refuses the real zip")
    return 0 if accepted else 1


def main():
    # Loading launch.py runs its top level. On Windows that re-executes the launcher under
    # pythonw.exe and exits 0 unless EGM_SILENT is set: it would start the app and this check
    # would report success without having checked anything.
    os.environ["EGM_SILENT"] = "1"
    spec = importlib.util.spec_from_file_location("egm_launch_pin_check", LAUNCH)
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    return check(launch, download="--download" in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
