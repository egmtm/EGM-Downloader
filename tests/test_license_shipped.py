"""
Every download carries the LICENSE file (AGPL asks that people who receive the
program get a copy of the license with it): the Windows installer (installed
next to the app and removed by the uninstaller), the Windows zip and the
portable zip, the Linux zip and the Mac zip. The in-app updater only extracts
egm-setup.exe from the Windows zip, so the extra entry is harmless there.
"""
import os
import re
from conftest import read_source, ROOT


def test_license_file_exists_in_the_repo():
    assert os.path.getsize(os.path.join(ROOT, "LICENSE")) > 30000


def test_windows_installer_installs_and_uninstalls_the_license():
    nsi = read_source("windows/setup.nsi")
    assert 'File "${REPO_ROOT}/LICENSE"' in nsi
    assert 'Delete "$INSTDIR\\LICENSE"' in nsi


def test_windows_zip_and_portable_zip_include_the_license():
    sh = read_source("windows/BUILD.sh")
    assert 'zf.write(lic_path, "LICENSE")' in sh
    assert '{"egm-setup.exe", "instructions.txt", "LICENSE"}' in sh
    assert re.search(r'cp "\$REPO_ROOT/LICENSE"\s+"\$PORTABLE_STAGE/"', sh)
    # the build refuses to start if it is missing
    assert re.search(r"patchnotes\.txt README\.md LICENSE \\", sh)


def test_linux_and_mac_zips_include_the_license():
    assert re.search(r'zip -j "\$REPO_ROOT/dist/EGMdL\.zip" "\$LINUX_DIR/INSTRUCTIONS\.txt" "\$REPO_ROOT/LICENSE"', read_source("linux/BUILD.sh"))
    mac = read_source("mac/BUILD.sh")
    assert 'cp "$REPO_ROOT/LICENSE" LICENSE' in mac
    assert re.search(r'zip -r "\$REPO_ROOT/dist/EGMdM\.zip" "\$\(basename "\$DMG"\)" INSTRUCTIONS\.txt LICENSE', mac)
