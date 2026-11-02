"""The Linux and Mac builds write dist/EGMdL.zip and dist/EGMdM.zip with `zip`, which adds to an
archive that is already there: the AppImage or DMG of an earlier build stayed inside next to the
new one, and that archive was then checksummed and published. Each build must remove the old zip
before the first `zip` into it (the Windows build writes its zip with Python in "w" mode)."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("script, archive", [("linux/BUILD.sh", "EGMdL.zip"), ("mac/BUILD.sh", "EGMdM.zip")])
def test_the_build_removes_the_old_archive_before_zipping_into_it(script, archive):
    lines = (ROOT / script).read_text(encoding="utf-8").splitlines()
    first_zip = next(i for i, l in enumerate(lines)
                     if re.match(r"\s*zip\b", l) and f"dist/{archive}" in l)
    removed = [i for i, l in enumerate(lines[:first_zip])
               if re.match(r"\s*rm -f\b", l) and f"dist/{archive}" in l]
    assert removed, f"{script}: no 'rm -f .../dist/{archive}' before line {first_zip + 1}"
