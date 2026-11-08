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


# ── the processor ─────────────────────────────────────────────────────────────

def _arch(native, win11):
    return {"IsNativeAMD64": native == "AMD64", "IsNativeARM64": native == "ARM64", "IsNativeIA32": native == "IA32",
            "AtLeastWin11": win11}


@pytest.mark.parametrize("arch, runs", [
    (_arch("AMD64", False), True),     # x64 Windows 10
    (_arch("AMD64", True), True),      # x64 Windows 11
    (_arch("ARM64", True), True),      # Windows 11 on ARM
    (_arch("ARM64", False), False),    # Windows 10 on ARM
    (_arch("IA32", False), False),     # 32 bit Windows 10
    (_arch("other", False), False),    # any other processor
])
def test_the_installer_runs_only_where_the_app_can(arch, runs):
    for silent in (True, False):
        r = Run(set(), silent=silent, answers=["IDOK"], arch=arch).run(statements(function(".onInit")))
        if runs:
            assert r.outcome == "end" and not r.boxes, (arch, r.boxes)
        else:
            assert r.outcome == "aborted", arch
            assert r.boxes == [("$(EGM_ARCH_UNSUPPORTED)", "IDOK")]


def test_the_check_comes_first_in_on_init():
    init = function(".onInit")
    check = init.index("${IsNativeAMD64}")
    for later in ("MUI_LANGDLL_DISPLAY", "ReadRegStr", "StrCpy $INSTDIR"):
        assert check < init.index(later), later
    assert '!include "x64.nsh"' in NSI and '!include "WinVer.nsh"' in NSI
