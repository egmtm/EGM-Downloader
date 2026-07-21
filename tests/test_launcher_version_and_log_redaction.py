"""Guards for two future-fixes items closed together:

1. windows/launcher.rc's embedded PE version resource was never part of the
   version-sync pipeline at all -- found stuck at 0.99.11 on a live v1.3.2
   build (cosmetic only, Explorer's Properties -> Details tab). Now covered
   by scripts/bump-version.py's update_windows_launcher_rc() and
   scripts/validate-version-sync.py's check_windows_launcher_rc().

2. egm_debug.log -- the file the support field protocol asks users to email
   in -- was logging full download URLs (which can carry an access token in
   the query string for private/signed content) and finished filenames
   (which are the video title by default). Redacted to host-only and
   extension-only; full detail still reaches _yt_log()/_YT_RING, which is
   memory-only and console-only.
"""
import re

from conftest import PLATFORM_APP_FILES, read_source

ROOT_RC = "windows/launcher.rc"


def test_launcher_rc_wired_into_bump_and_validate_scripts():
    """The launcher.rc update/check functions must exist and actually be
    called from each script's main flow, not just defined and orphaned."""
    bump_src = read_source("scripts/bump-version.py")
    assert "def update_windows_launcher_rc(" in bump_src
    assert re.search(r"^\s*update_windows_launcher_rc\(", bump_src, re.MULTILINE), (
        "update_windows_launcher_rc is defined but never called from main()"
    )

    validate_src = read_source("scripts/validate-version-sync.py")
    assert "def check_windows_launcher_rc(" in validate_src
    assert "check_windows_launcher_rc(v)" in validate_src, (
        "check_windows_launcher_rc is defined but never wired into the check list"
    )


def test_launcher_rc_current_version_matches_source_of_truth():
    """The one-time correction actually landed -- launcher.rc must currently
    show the same version as version.json, not still be stuck on something
    stale."""
    import json
    version = json.loads(read_source("version.json"))["version"]
    rc = read_source(ROOT_RC)

    parts = version.split(".")
    while len(parts) < 4:
        parts.append("0")
    comma_form = ",".join(parts[:4])

    assert re.search(rf"FILEVERSION\s+{re.escape(comma_form)}", rc), (
        f"launcher.rc FILEVERSION doesn't match version.json ({version})"
    )
    assert re.search(rf'VALUE "FileVersion",\s*"{re.escape(version)}"', rc), (
        f"launcher.rc FileVersion string doesn't match version.json ({version})"
    )


def test_download_complete_log_line_does_not_use_raw_filename():
    """The download-complete _egm_log call must use final_path.suffix (or
    similar), never final_path.name directly -- the name is the video title
    by default, and this line lands in the file support asks users to email
    in."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index('_egm_log(f"download complete:')
        line = src[i:i + 120]
        assert "final_path.name" not in line, (
            f"{p}: download-complete log line uses the raw filename (usually "
            f"the video title) -- must use final_path.suffix instead"
        )
        assert "final_path.suffix" in line, (
            f"{p}: download-complete log line should still log the extension "
            f"for diagnostic value"
        )


def test_download_started_log_line_does_not_use_raw_url():
    """The download-started _egm_log call must log the host, not the raw
    URL -- a private/signed URL can carry an access token in its query
    string. Now present and consistent on all 3 platforms (mac/linux
    previously had no download-started log at all -- closed as a platform
    parity gap, not part of the original redaction fix)."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        assert '_egm_log(f"download started' in src, (
            f"{p}: missing the download-started diagnostic log line -- "
            f"platform parity gap, should match the other 2 platforms"
        )
        i = src.index('_egm_log(f"download started')
        line = src[i:i + 120]
        assert ": {url}" not in line, (
            f"{p}: download-started log line interpolates the raw URL "
            f"directly -- must resolve to just the hostname first"
        )
        assert "_log_host" in line, (
            f"{p}: download-started log line should still log the host "
            f"for diagnostic value"
        )
