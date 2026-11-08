"""The Mac build's pip runs see only the bundled Python's own packages, like the Linux build's.

Without PYTHONNOUSERSITE=1 a package in the build machine's user site (~/Library/Python/3.11 or
~/.local) counts as "already installed" and is left out of the bundle, and the solver pin could be read
from a yt-dlp that is not the bundled one. linux/BUILD.sh sets it on its pip runs and on the pin read;
mac/BUILD.sh now does the same. The pairing block runs in bash against a stand in Python (the harness of
tests/test_build_scripts_pair_ytdlp_ejs.py)."""
import re

import pytest

from conftest import read_source
from test_build_scripts_pair_ytdlp_ejs import PLAIN, _run

PIP_RUN = re.compile(r'"\$PYTHON_DIR/bin/python3" -m pip\b')


@pytest.mark.parametrize("rel", ["mac/BUILD.sh", "linux/BUILD.sh"])
def test_every_pip_run_of_the_build_ignores_the_user_site(rel):
    runs = [l.strip() for l in read_source(rel).splitlines() if PIP_RUN.search(l)]
    assert len(runs) >= 2, f"{rel}: the pip runs were not found"
    for line in runs:
        assert line.startswith('PYTHONNOUSERSITE=1 "$PYTHON_DIR/bin/python3" -m pip'), f"{rel}: {line}"


def test_the_mac_pin_read_and_pairing_install_ignore_it_too(tmp_path):
    r, calls = _run("mac/BUILD.sh", tmp_path, [PLAIN])
    assert r.returncode == 0, r.stdout + r.stderr
    assert [c.split("|")[:2] for c in calls] == [["read", "1"], ["pip", "1"]], calls
