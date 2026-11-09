"""The installer never deletes what the app keeps in its folder.

The app writes its settings, history, subscriptions and cookies into the install folder, and its
data (the Electron profile in data\\electron-data), thumbnails, logs, ffmpeg (ffmpeg_bin) and Deno
(runtime) folders beside them (app.py with EGM_INSTALL_DIR, windows/electron/main.js). Only the
uninstaller removes some of these, inside its two question branches. This reads every Delete and RMDir
of the installer part of windows/setup.nsi (everything but the Uninstall section and the un. functions,
so the migration macros the installer inserts are read too) and fails if one names any of them, by
name, by a wildcard that matches one, or by removing the whole folder.
"""
import fnmatch
import re

import pytest

from conftest import read_source

NSI = read_source("windows/setup.nsi")

KEPT = ("data", "electron-data", "thumbnails", "logs", "ffmpeg_bin", "runtime",
        "egm_settings.json", "egm_history.json", "egm_subscriptions.json", "cookies.txt")


def installer_part(text):
    """The script without the Uninstall section and the un. functions."""
    text = re.sub(r'^Section "Uninstall".*?^SectionEnd\b', "", text, flags=re.M | re.S)
    return re.sub(r"^Function (?:\$\{un\}|un\.).*?^FunctionEnd\b", "", text, flags=re.M | re.S)


def removals(text):
    """(statement, target) for every Delete and RMDir, in any letter case."""
    out = []
    for line in text.splitlines():
        m = re.match(r'\s*(Delete|RMDir)\b((?:\s+/\w+)*)\s+"?([^"]+)"?\s*$', line, re.I)
        if m:
            out.append((line.strip(), m.group(2).lower(), m.group(3)))
    return out


def what_it_deletes_of_the_app_data(text):
    bad = []
    for line, flags, target in removals(installer_part(text)):
        parts = [p for p in re.split(r"[\\/]", target) if p]
        root_only = len(parts) == 1
        if root_only and (line.lower().startswith("delete") or "/r" in flags):
            bad.append(line)                                    # the whole folder, or a file pattern at its root
            continue
        if any(fnmatch.fnmatch(kept, part.lower()) for part in parts[1:] for kept in KEPT):
            bad.append(line)
    return bad


def test_the_installer_part_deletes_nothing_the_app_keeps():
    found = removals(installer_part(NSI))
    assert len(found) >= 10, f"the scan sees too few removals: {found}"
    assert any("launch.py" in t for _, _, t in found), "the migration macro is not read"
    assert not what_it_deletes_of_the_app_data(NSI)


def test_the_uninstaller_part_is_left_out_and_still_removes_the_data_when_asked():
    un = re.search(r'^Section "Uninstall".*?^SectionEnd\b', NSI, re.M | re.S).group(0)
    assert 'RMDir /r "$INSTDIR\\data"' in un and 'Delete "$INSTDIR\\egm_history.json"' in un
    assert 'RMDir /r "$INSTDIR\\data"' not in installer_part(NSI)


def _with_install_line(line):
    i = NSI.index('Section "Install"')
    j = NSI.index("\n", i) + 1
    return NSI[:j] + f"  {line}\n" + NSI[j:]


@pytest.mark.parametrize("line", [
    'RMDir /r "$INSTDIR\\data"', 'RMDir /r "$INSTDIR\\thumbnails"', 'Delete "$INSTDIR\\egm_history.json"',
    'Delete "$INSTDIR\\egm_*.json"', 'rmdir /r "$INSTDIR\\Data"', "RMDir /r $INSTDIR\\ffmpeg_bin",
    'RMDir /r "$INSTDIR"', 'Delete "$INSTDIR\\*.*"', 'RMDir /r "$INSTDIR\\data\\electron-data"',
])
def test_the_scan_sees_a_delete_of_the_app_data_in_the_install_section(line):
    assert what_it_deletes_of_the_app_data(_with_install_line(line)) == [line], line


def test_the_scan_sees_one_in_the_migration_macro():
    text = NSI.replace('  RMDir /r "$INSTDIR\\electron"\n', '  RMDir /r "$INSTDIR\\electron"\n  RMDir /r "$INSTDIR\\logs"\n', 1)
    assert what_it_deletes_of_the_app_data(text) == ['RMDir /r "$INSTDIR\\logs"']
