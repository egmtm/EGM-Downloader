"""The Mac and Linux builds stop when the yt-dlp-ejs pairing step fails, and pair in the bundle itself.

test_build_scripts_pair_ytdlp_ejs.py runs the step with its own "set -e" in front, so the step stopping
the build there proved nothing about the script: a failed read relies on the script's set -e. And the
packages must go into the bundled Python itself, not some other folder it never reads.
"""
import re

import pytest

from conftest import read_source

SCRIPTS = ("mac/BUILD.sh", "linux/BUILD.sh")
STEP = "# yt-dlp-ejs: "


def _code_lines(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


@pytest.mark.parametrize("rel", SCRIPTS)
def test_errexit_is_on_from_the_top_and_never_turned_off_before_the_step(rel):
    src = read_source(rel)
    before = src[:src.index(STEP)]
    code = _code_lines(before)
    assert code and code[0] == "set -e", f"{rel}: the first command must be set -e, it is {code[:1]}"
    off = [l for l in code if re.search(r"\bset\s+(\+e|\+o\s+errexit)\b", l)]
    assert not off, f"{rel} turns errexit off before the pairing step: {off}"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_step_installs_nothing_and_stops_the_build_on_a_wrong_pair(rel):
    m = re.search(r"^# yt-dlp-ejs: .*?^fi$", read_source(rel), re.S | re.M)
    assert m, rel
    code = _code_lines(m.group(0))
    assert not [l for l in code if "pip" in l], f"{rel}: the pairing step only checks, the lock installs"
    assert "exit 1" in code, f"{rel}: a wrong pair must stop the build"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_lock_installs_into_the_bundled_python_itself(rel):
    installs = [l for l in _code_lines(read_source(rel)) if "pip install" in l]
    assert len(installs) == 1, installs
    (line,) = installs
    assert line.startswith('PYTHONNOUSERSITE=1 "$PYTHON_DIR/bin/python3" -m pip install '), line
    for flag in ("--target", "--prefix", "--root", "--user", "-t "):
        assert flag not in line, f"{rel}: {line}"
