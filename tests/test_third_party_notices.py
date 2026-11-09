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
session 6 report named, so a new gap shows here: the six it named are filled (from the upstream files at the
tags the build uses), and GAPS is empty.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

from conftest import ROOT, read_source

NOTICES = Path(ROOT) / "THIRD_PARTY_NOTICES.txt"
COMMON = Path("/usr/share/common-licenses")
GAPS = set()   # numbers of the "[GAP n: ...]" markers the file may carry; none is open (the six of the session 6 report are filled)


def _text():
    return NOTICES.read_text(encoding="utf-8")


def _section(text, title, next_title):
    """The licence text between a part 5 heading and the next one (or the end)."""
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
    "yt-dlp-ejs", "meriyah 6.1.4", "astring 1.9.0", "ISC License",
    # the copyright lines and the revision filled from the upstream files (the six gaps of the session 6 report)
    "Copyright (c) 2026 curl_cffi developers", "Copyright (c) 1996 - 2026, Daniel Stenberg",
    "156c7b75ae9b8c3b3f847acf264f17594c3859fb", "Tatsuhiro Tsujikawa", "Copyright (c) 2016 ngtcp2 contributors",
    "Copyright (c) 2019 nghttp3 contributors", "libidn2-2.3.7.tar.gz",
    "The long licence texts are in part 5.",
    "Apache License\n                           Version 2.0, January 2004",
    "GNU LESSER GENERAL PUBLIC LICENSE\n                       Version 3, 29 June 2007",
])
def test_the_notices_name_every_part_and_carry_its_licence(marker):
    assert marker in _text(), f"THIRD_PARTY_NOTICES.txt has no {marker.splitlines()[0]!r}"


# The hosts the file means to name: the projects' own repositories and package pages, and the places the
# licence texts themselves point to.
HOSTS = {"github.com", "pypi.org", "boringssl.googlesource.com", "hg.mozilla.org", "mozilla.org",
         "www.gnu.org", "ftp.gnu.org", "fsf.org", "www.apache.org", "www.unicode.org"}


def test_every_link_goes_to_a_host_the_file_means_to_name():
    """Three links once went to a proxy host instead of github.com: a reader would be sent somewhere
    nobody chose. A new host has to be added to HOSTS on purpose."""
    found = {urlparse(u).hostname for u in re.findall(r"https?://[^\s)\"<>,;]+", _text())}
    assert found, "THIRD_PARTY_NOTICES.txt names no link at all"
    assert found <= HOSTS, f"THIRD_PARTY_NOTICES.txt links to hosts that are not on the list: {sorted(found - HOSTS)}"


def test_every_part_the_text_points_to_exists():
    """The long licence texts moved from part 4 to part 5 when yt-dlp-ejs was added: a pointer left behind
    would send a reader to the wrong text."""
    text = _text()
    pointers = set(re.findall(r"\bpart (\d+(?:\.\d+)?)\b", text))
    assert pointers, "THIRD_PARTY_NOTICES.txt points to no part"
    for number in pointers:
        assert re.search(rf"^{re.escape(number)}\.? \S", text, re.M), f"the text points to part {number}, which has no heading"
    # part 5 holds the long texts the other parts point to
    assert re.search(r"^5\. Licence texts$", text, re.M)


def test_the_boringssl_revision_is_the_same_in_both_places():
    """The revision is named twice (as the revision and in the archive address); one edited alone would pass a marker check."""
    assert _text().count("156c7b75ae9b8c3b3f847acf264f17594c3859fb") == 2


def test_the_only_gaps_are_the_ones_the_report_lists():
    found = [int(n) for n in re.findall(r"\[GAP (\d+):", _text())]
    assert sorted(found) == sorted(GAPS), f"gaps in the file: {found}, listed: {sorted(GAPS)}"
    assert "GAP" not in re.sub(r"\[GAP \d+:[^\]]*\]", "", _text()).replace("A line marked GAP", ""), \
        "a gap marker that does not follow the [GAP n: ...] form"


@pytest.mark.parametrize("title, next_title, common", [
    ("5.1 GNU General Public License version 3", "5.2 Mozilla Public License 2.0", "GPL-3"),
    ("5.2 Mozilla Public License 2.0", "5.3 BoringSSL licence file", "MPL-2.0"),
    ("5.4 GNU Lesser General Public License version 3", None, "LGPL-3"),
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
    ("yt-dlp-ejs", "Version:   {}"),
])
def test_the_versions_named_are_the_ones_the_windows_installer_ships(package, how):
    """The Windows lock decides what the installer ships: a lock that moves on must take the
    notices with it (curl_cffi decides which libcurl-impersonate, and so which libraries, ship)."""
    assert how.format(_lock_version(package)) in _text(), \
        f"THIRD_PARTY_NOTICES.txt does not name {package} {_lock_version(package)}, the version the lock installs"


def test_the_ejs_notices_are_the_ones_in_the_packages_own_script_header():
    """yt-dlp-ejs keeps the ISC and MIT notices of the two libraries it bundles in a comment at the top of
    lib.min.js; part 4 repeats them. Compared (words only) when that package, at the version named, is installed."""
    ejs = pytest.importorskip("yt_dlp_ejs")
    from importlib.metadata import version
    if version("yt-dlp-ejs") != _lock_version("yt-dlp-ejs"):
        pytest.skip("another yt-dlp-ejs version is installed")
    header = (Path(ejs.__file__).parent / "yt" / "solver" / "lib.min.js").read_text(encoding="utf-8").split("*/")[0]
    body = "\n".join(re.sub(r"^\s*\* ?", "", line) for line in header.splitlines())
    words = lambda s: " ".join(s.split())
    for start in ("ISC License", "Copyright (c) 2015, David Bonnet"):
        piece = body[body.index(start):].split("---")[0]
        assert words(piece) in words(_text()), f"the {start!r} notice in part 4 differs from the header of lib.min.js"


# ── Windows installer: the install root ──────────────────────────────────────────────────────

BUILD_FOLDER = "windows/installer/build-folder.sh"
INSTALLER = Path(ROOT) / "windows" / "installer"


def _copy_lines():
    """The lines of build-folder.sh that put the notices into the folder, checked to come after the
    folder is in place and before its manifest is written (the manifest is what --continue packages)."""
    lines = read_source(BUILD_FOLDER).splitlines()
    placed = next(i for i, line in enumerate(lines) if line.startswith("mv ") and line.rstrip().endswith('"$OUT"'))
    manifest = next(i for i, line in enumerate(lines) if 'folder_manifest.py" write' in line)
    copies = [i for i, line in enumerate(lines) if "THIRD_PARTY_NOTICES.txt" in line and not line.lstrip().startswith("#")]
    assert copies, f"{BUILD_FOLDER} does not copy THIRD_PARTY_NOTICES.txt into the folder"
    assert all(placed < i < manifest for i in copies), "the notices are copied before the folder exists or after its manifest"
    return "\n".join(lines[i] for i in copies)


def _stand_in_folder(tmp_path):
    out = tmp_path / "win-unpacked"
    (out / "resources").mkdir(parents=True)
    for rel in ("EGM Downloader.exe", "LICENSE.electron.txt", "LICENSES.chromium.html", "resources/app.asar"):
        (out / rel).write_bytes(b"x")
    return out


def test_the_windows_installer_folder_gets_the_notices_at_its_root(tmp_path):
    out = _stand_in_folder(tmp_path)
    r = subprocess.run(["bash", "-ec", _copy_lines()], env=dict(os.environ, REPO_ROOT=str(ROOT), OUT=str(out)),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert (out / "THIRD_PARTY_NOTICES.txt").read_bytes() == NOTICES.read_bytes()
    # what derives from the folder takes it along: the uninstaller's list and the folder manifest
    nsh = tmp_path / "files.nsh"
    subprocess.run([sys.executable, str(INSTALLER / "uninstall_list.py"), str(out), str(nsh)], check=True, capture_output=True)
    assert 'Delete "$INSTDIR\\THIRD_PARTY_NOTICES.txt"' in nsh.read_text(encoding="utf-8")
    man = tmp_path / "win-unpacked.sha256"
    subprocess.run([sys.executable, str(INSTALLER / "folder_manifest.py"), "write", str(out), str(man)], check=True, capture_output=True)
    assert "THIRD_PARTY_NOTICES.txt" in man.read_text(encoding="utf-8")


def test_the_portable_edition_is_unchanged():
    """windows/app-files.txt feeds the portable zip too; the notices are not in it (the portable zip
    carries no third party package: its launcher installs them with pip on the user's machine)."""
    assert "THIRD_PARTY_NOTICES.txt" not in read_source("windows/app-files.txt")


def test_the_built_installer_folder_has_the_notices_if_built():
    folder = Path(ROOT) / "dist" / "win-unpacked"
    if not folder.is_dir():
        pytest.skip("dist/win-unpacked is not built")
    assert (folder / "THIRD_PARTY_NOTICES.txt").read_bytes() == NOTICES.read_bytes()


# ── macOS and Linux: inside the app, beside Electron's notices ───────────────────────────────

# macOS: extraResources lands in Contents/Resources, where electron-builder moves LICENSE.electron.txt
# and LICENSES.chromium.html (they would sit outside the .app otherwise). Linux: extraFiles lands in
# the app root, beside LICENSE.electron.txt, which is the root of the AppImage.
SHELL_CONFIG = {"mac/electron/package.json": "extraResources", "linux/electron/package.json": "extraFiles"}


@pytest.mark.parametrize("rel, key", sorted(SHELL_CONFIG.items()))
def test_the_mac_and_linux_apps_carry_the_notices_beside_electrons(rel, key):
    build = json.loads(read_source(rel))["build"]
    entries = [e for e in build.get(key, []) if isinstance(e, dict) and e.get("from", "").endswith("THIRD_PARTY_NOTICES.txt")]
    assert len(entries) == 1, f"{rel}: build.{key} has no single entry for THIRD_PARTY_NOTICES.txt"
    (entry,) = entries
    assert entry["to"] == "THIRD_PARTY_NOTICES.txt" and "filter" not in entry, entry
    assert (Path(ROOT) / rel).parent.joinpath(entry["from"]).resolve() == NOTICES.resolve(), \
        f"{rel}: {entry['from']} is not the repository's notices file"
