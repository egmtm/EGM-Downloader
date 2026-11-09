"""THIRD_PARTY_NOTICES.txt: the notices the installed app needs beyond the licence files its parts carry.

The Windows installer folder carried no GPL-3.0 text for bgutil-ytdlp-pot-provider (its package ships no
licence file), no notices for the libraries built into curl_cffi's libcurl-impersonate (curl_cffi ships
only its own MIT text) and no MPL-2.0 text for certifi (its package ships only a short notice). The Mac
and Linux bundles install the same packages and had the same gaps. One file in the repository root holds
those notices; every build copies it into the app, next to Electron's own notices:

* Windows installer: the install root (windows/installer/build-folder.sh), beside LICENSE.electron.txt;
* Linux AppImage: the app root (extraFiles), beside LICENSE.electron.txt;
* macOS: Contents/Resources (extraResources), where electron-builder moves LICENSE.electron.txt and
  LICENSES.chromium.html.

The file's licence texts are copied from authoritative sources. Where the long texts come from Debian's
/usr/share/common-licenses they are compared with those files when the machine has them (CI runs on
Ubuntu). Information that could not be confirmed is marked "[GAP n: ...]"; GAPS lists the ones the
session 6 report names, so a new gap, or a filled one, shows here.
"""
import json
import re
from pathlib import Path

import pytest

from conftest import ROOT, read_source

NOTICES = Path(ROOT) / "THIRD_PARTY_NOTICES.txt"
COMMON = Path("/usr/share/common-licenses")
GAPS = {1, 2, 3, 4, 5, 6}   # the session 6 report lists each one; fill them, then remove them here


def _text():
    return NOTICES.read_text(encoding="utf-8")


def _section(text, title, next_title):
    """The licence text between a part 4 heading and the next one (or the end)."""
    start = text.index(title)
    body = text[start:text.index(next_title, start)] if next_title else text[start:]
    # skip the heading, its rule and the "(text: ...)" line, then one empty line
    lines = body.split("\n")
    i = next(k for k, line in enumerate(lines) if line.startswith("(text: "))
    return "\n".join(lines[i + 2:]).rstrip("\n").rstrip("-").rstrip("\n")


def test_the_notices_file_is_in_the_repository():
    assert NOTICES.is_file(), "THIRD_PARTY_NOTICES.txt is missing from the repository root"


def test_the_notices_file_has_one_kind_of_line_end():
    assert b"\r" not in NOTICES.read_bytes(), "THIRD_PARTY_NOTICES.txt mixes Windows line ends into its Unix ones"


@pytest.mark.parametrize("marker", [
    "bgutil-ytdlp-pot-provider",
    "GNU GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007",
    "libcurl-impersonate", "curl_cffi 0.17.0",
    "curl 8.23.0", "BoringSSL", "nghttp2 1.63.0", "ngtcp2 1.20.0", "nghttp3 1.15.0", "brotli 1.2.1",
    "zstd 1.5.7", "zlib 1.3.1", "c-ares 1.34.9", "libidn2 2.3.7",
    "certifi", "Mozilla Public License Version 2.0",
    "Apache License\n                           Version 2.0, January 2004",
    "GNU LESSER GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007",
])
def test_the_notices_name_every_part_and_carry_its_licence(marker):
    assert marker in _text(), f"THIRD_PARTY_NOTICES.txt has no {marker.splitlines()[0]!r}"


def test_the_only_gaps_are_the_ones_the_report_lists():
    found = [int(n) for n in re.findall(r"\[GAP (\d+):", _text())]
    assert sorted(found) == sorted(GAPS), f"gaps in the file: {found}, listed: {sorted(GAPS)}"
    assert "GAP" not in re.sub(r"\[GAP \d+:[^\]]*\]", "", _text()).replace("A line marked GAP", ""), \
        "a gap marker that does not follow the [GAP n: ...] form"


@pytest.mark.parametrize("title, next_title, common", [
    ("4.1 GNU General Public License version 3", "4.2 Mozilla Public License 2.0", "GPL-3"),
    ("4.2 Mozilla Public License 2.0", "4.3 BoringSSL licence file", "MPL-2.0"),
    ("4.4 GNU Lesser General Public License version 3", None, "LGPL-3"),
])
def test_the_long_licence_texts_are_the_authoritative_ones(title, next_title, common):
    source = COMMON / common
    if not source.is_file():
        pytest.skip(f"{source} is not on this machine")
    assert _section(_text(), title, next_title) == source.read_text(encoding="utf-8").rstrip("\n"), \
        f"the {common} text differs from {source}"


def _lock_version(name):
    m = re.search(rf"^{re.escape(name)}==([^ \\\n]+)", read_source("windows/requirements-win-lock.txt"), re.M)
    assert m, f"{name} is not in the Windows lock"
    return m.group(1)


@pytest.mark.parametrize("package, how", [
    ("bgutil-ytdlp-pot-provider", "Version:   {}"),
    ("curl-cffi", "curl_cffi {}"),
    ("certifi", "https://pypi.org/project/certifi/{}/"),
])
def test_the_versions_named_are_the_ones_the_windows_installer_ships(package, how):
    """The Windows lock decides what the installer ships: a lock that moves on must take the
    notices with it (curl_cffi decides which libcurl-impersonate, and so which libraries, ship)."""
    assert how.format(_lock_version(package)) in _text(), \
        f"THIRD_PARTY_NOTICES.txt does not name {package} {_lock_version(package)}, the version the lock installs"
