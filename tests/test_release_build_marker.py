"""last-released-build.txt premature-bump guard.

Both windows/BUILD.sh and linux/BUILD.sh used to write the CURRENT build
number to scripts/last-released-build.txt unconditionally whenever a build
produced something new to commit+push -- which fires for test builds just
as much as the real release build, since the script has no way to tell
them apart. That meant running a single test build could mark that build
number as "released," which then blocked the real release's own feed
validation later (gen-update-json's monotonicity check requires the
current build to be strictly greater than last-released, and a test build
had already claimed that number).

Found live during the actual v1.3.0 Build 141 release cut: Windows' test
build earlier in the day had already written 141 to the marker, so
Linux's real release build failed validation with "build 141 must be >
last released build 141" -- correct behavior from the validator, wrong
input from the build scripts.

Fixed by removing the write from both scripts entirely. Bumping the
marker is now a deliberate, separate, LAST step of the actual release
process (see the release-cut checklist), not an automatic side effect of
running a build.
"""
from conftest import read_source


def test_last_released_build_not_bumped_by_windows_build_script():
    source = read_source("windows/BUILD.sh")
    assert "> \"$REPO_ROOT/scripts/last-released-build.txt\"" not in source, (
        "windows/BUILD.sh writes to last-released-build.txt again -- this is "
        "exactly the bug that let a test build block the real release's feed "
        "validation. Bumping this file must stay a deliberate, separate step."
    )


def test_last_released_build_not_bumped_by_linux_build_script():
    source = read_source("linux/BUILD.sh")
    assert "> scripts/last-released-build.txt" not in source, (
        "linux/BUILD.sh writes to last-released-build.txt again -- this is "
        "exactly the bug that let a test build block the real release's feed "
        "validation. Bumping this file must stay a deliberate, separate step."
    )


def test_last_released_build_is_a_plain_integer():
    # Sanity check on the file's own contents -- validate-version-sync.py
    # already enforces this at release time, but cheap to also assert here.
    content = read_source("scripts/last-released-build.txt").strip()
    assert content.isdigit(), (
        f"scripts/last-released-build.txt must contain a plain integer, "
        f"got {content!r}"
    )
