"""Windows two-phase launcher-signing build guard.

EGM signs the installer wrapper (egm-setup.exe) after NSIS builds it, but
NSIS packs the native launcher (windows/EGM Downloader.exe) in unsigned --
by the time the outer wrapper is signed, the launcher inside it is already
sealed in. The launcher actually running on a user's machine post-install
was never signed at all.

Fixed by splitting windows/BUILD.sh into two stops: compile the launcher
and halt by default (safe: a forgotten flag means nothing gets packaged,
not that an unsigned launcher quietly ships), then --continue verifies the
launcher is actually signed (via osslsigncode where available, else a
manual confirmation prompt) before NSIS bakes it into the installer.

This test checks the static safety properties -- that stopping by default
and gating --continue on verification are genuinely present in the script
-- not a full build invocation (that needs the real mingw/makensis
toolchain and is exercised manually/in the build session itself).
"""
import re

from conftest import read_source


def test_default_mode_stops_before_nsis_packing():
    """No --continue flag must mean the script halts after compiling the
    launcher, before it's anywhere near NSIS -- verified by confirming the
    stop/exit happens textually before the NSIS compilation step."""
    source = read_source("windows/BUILD.sh")
    stop_idx = source.index("STOP — launcher compiled, not yet signed")
    nsis_idx = source.index('Compiling NSIS installer')
    assert stop_idx < nsis_idx, (
        "the launcher-signing stop message must appear before NSIS "
        "compilation in the script -- otherwise the halt isn't actually "
        "gating the packaging step"
    )


def test_continue_flag_gates_signature_verification():
    source = read_source("windows/BUILD.sh")
    assert "--continue" in source
    assert "osslsigncode verify" in source, (
        "the --continue path must attempt real signature verification, "
        "not just trust that the user signed it"
    )
    # The verification failure path must exit non-zero -- a silent pass-
    # through here would defeat the entire point of the gate.
    # the check lives in verify_signed(): the failure branch of that function must exit
    verify_block = source[source.index("osslsigncode verify"):source.index("\n}\n", source.index("osslsigncode verify"))]
    assert re.search(r"exit 1", verify_block), (
        "a failed signature verification must exit non-zero, not continue "
        "packaging an unsigned launcher"
    )


def test_manual_fallback_when_osslsigncode_unavailable():
    """If osslsigncode isn't installed, the script must still require an
    explicit human confirmation rather than silently skipping the check."""
    source = read_source("windows/BUILD.sh")
    assert "HAVE_OSSLSIGNCODE" in source
    assert re.search(r"read -r -p.*[Ss]igned", source), (
        "no manual confirmation prompt found for the no-osslsigncode fallback path"
    )

