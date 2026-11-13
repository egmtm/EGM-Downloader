"""The Mac and Linux builds stop when the yt-dlp-ejs pairing step fails, and pair in the bundle itself.

test_build_scripts_pair_ytdlp_ejs.py runs the step with its own "set -e" in front, so the step stopping
the build there proved nothing about the script: the step has no "|| exit" of its own and relies on the
script's set -e. And its check of the install command accepted any command that named the version, so an
install into some other folder (one the bundled Python never reads) passed too.
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
def test_the_step_installs_into_the_bundled_python_itself(rel):
    m = re.search(r"^# yt-dlp-ejs: .*?^fi$", read_source(rel), re.S | re.M)
    assert m, rel
    installs = [l for l in _code_lines(m.group(0)) if "pip install" in l]
    assert len(installs) == 1, installs
    (line,) = installs
    assert re.search(r'"\$PYTHON_DIR/bin/python3" -m pip install --quiet "yt-dlp-ejs==\$EJS_PIN"$', line), line
    for flag in ("--target", "--prefix", "--root", "--user", "-t "):
        assert flag not in line, f"{rel}: {line}"
