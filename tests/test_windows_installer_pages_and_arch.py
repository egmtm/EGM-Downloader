"""windows/setup.nsi: the folder page on an upgrade or repair, and the processor check at start.

* With the app already in the folder the installer would use (InstallPath from the last install, or
  the default), the folder page is skipped: another folder would orphan that install and start
  without its settings and history. A first install, a folder without EGM Downloader.exe (an
  uninstall that kept the data, say), or a portable copy (which the install refuses) still shows it.
* .onInit lets the installer run on 64 bit Intel or AMD Windows, and on ARM64 only from Windows 11
  (which runs x64 programs); anything else is refused with a message box, and with exit code 2 when
  silent (Abort in .onInit), before the language dialog and before anything changes."""
import re

import pytest

from nsis_model import NSI, Run, function, statements


def _shown(contents):
    r = Run({f"$INSTDIR/{n}" for n in contents}).run(statements(function("DirectoryPage_Pre")))
    return r.outcome != "aborted"


def test_the_folder_page_has_the_pre_function():
    pages = NSI[NSI.index("; ── Pages"):NSI.index("!insertmacro MUI_PAGE_INSTFILES")]
    assert re.search(r"^!define MUI_PAGE_CUSTOMFUNCTION_PRE DirectoryPage_Pre\n!insertmacro MUI_PAGE_DIRECTORY$", pages, re.M)


@pytest.mark.parametrize("contents, shown", [
    (set(), True),                                                                   # first install
    ({"egm_settings.json", "thumbnails/a.jpg", "ffmpeg_bin/ffmpeg.exe"}, True),       # data kept by an uninstall
    ({"EGM Downloader.exe", "resources/app.asar", "egm_settings.json"}, False),       # upgrade or repair
    ({"EGM Downloader.exe", "launch.py", "electron/main.js", "egm_settings.json"}, False),   # the 1.5.x layout
    ({"EGM Downloader.exe", "launch.py", ".portable", "data/egm_settings.json"}, True),     # a portable copy: refused,
])                                                                                          # so another folder must be possible
def test_the_folder_page_is_skipped_only_where_the_app_is(contents, shown):
    assert _shown(contents) is shown


def test_the_folder_the_page_looks_at_is_the_recorded_one():
    init = function(".onInit")
    assert init.index('ReadRegStr $PreviousInstDir HKCU "${REGKEY}" "InstallPath"') < init.index("StrCpy $INSTDIR $PreviousInstDir")
