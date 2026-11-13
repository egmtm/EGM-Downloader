"""
Linux, Mac and the Windows installer bundle a python build standalone Python (it brings its own pip).
Their build scripts pin the version, the release and the SHA-256 from that release's SHA256SUMS, and
check the download before it is unpacked. All three use the same version and release (each its own
platform archive, so the SHA-256 differs). The Windows portable edition's launcher pins its own
archive of that release (tests/test_portable_python_pin.py).
"""
import re

import pytest

from conftest import read_source

SCRIPTS = {"linux": "linux/BUILD.sh", "mac": "mac/BUILD.sh"}
# The Windows installer folder build, a third target for the shape checks below
ALL_SCRIPTS = {**SCRIPTS, "windows-installer": "windows/installer/build-folder.sh"}


def _pin(name, text):
    m = re.search(rf'^{name}="([^"]+)"', text, re.M)
    assert m, f"{name} is not pinned"
    return m.group(1)


@pytest.mark.parametrize("target", ALL_SCRIPTS)
def test_pin_is_well_formed(target):
    text = read_source(ALL_SCRIPTS[target])
    assert re.fullmatch(r"3\.11\.\d+", _pin("PYTHON_VERSION", text))
    assert re.fullmatch(r"\d{8}", _pin("PYTHON_RELEASE", text))
    assert re.fullmatch(r"[0-9a-f]{64}", _pin("PYTHON_SHA256", text))
    # The URL is built from the pins, so there is no second copy of the version to forget
    url = re.search(r'^\s*PYTHON_URL="([^"]+)"', text, re.M).group(1)
    assert "${PYTHON_RELEASE}/cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-" in url


def test_linux_mac_and_the_windows_installer_pin_the_same_python():
    """Version and release only: each platform has its own archive, so its own SHA-256."""
    lin, mac, win = (read_source(p) for p in ALL_SCRIPTS.values())
    assert _pin("PYTHON_VERSION", lin) == _pin("PYTHON_VERSION", mac) == _pin("PYTHON_VERSION", win)
    assert _pin("PYTHON_RELEASE", lin) == _pin("PYTHON_RELEASE", mac) == _pin("PYTHON_RELEASE", win)


@pytest.mark.parametrize("target", ALL_SCRIPTS)
def test_download_is_checked_before_it_is_unpacked(target):
    text = read_source(ALL_SCRIPTS[target])
    download = text.index('curl -fL --progress-bar -w \'%{http_code}\' "$PYTHON_URL"')
    check = text.index('"$PYTHON_SHA256  python.tar.gz"')
    unpack = text.index("tar -xzf python.tar.gz")
    assert download < check < unpack
    assert "exit 1" in text[check:unpack]   # a mismatch stops the build
