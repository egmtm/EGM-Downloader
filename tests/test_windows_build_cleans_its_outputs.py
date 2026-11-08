"""Every phase of the Windows build removes what it regenerates, and nothing it was given signed.

Only egm-setup.exe and EGMd.zip used to be removed at the start, so a failed earlier run could leave
the feeds, the portable zip or the portable stage of another build in dist/ next to new outputs.
The order matters: --continue must keep the signed launcher, the installer folder with its signed exe
and the folder's manifest; --finish must also keep the signed egm-setup.exe it packages (and the
uninstall list, a --continue output it does not remake). The clean step is cut out of the script and
run against a fake dist/ holding every output at once."""
import subprocess

import pytest

from conftest import read_source

LAUNCHER = "windows/EGM Downloader.exe"
FOLDER = ["dist/win-unpacked/EGM Downloader.exe", "dist/win-unpacked/resources/app.asar"]
MANIFEST = "dist/win-unpacked.sha256"
UNINSTALL_LIST = "dist/win-unpacked-files.nsh"
SETUP = "dist/egm-setup.exe"
PHASE3_OUTPUTS = ["dist/EGMd.zip", "dist/EGMd-portable.zip", "dist/egm-version.json",
                  "dist/egm-portable-version.json", "dist/portable-stage/launch.py"]
EVERYTHING = [LAUNCHER, *FOLDER, MANIFEST, UNINSTALL_LIST, SETUP, *PHASE3_OUTPUTS]


def _clean_block():
    sh = read_source("windows/BUILD.sh")
    start = sh.index('echo "🧹 Cleaning old Windows build artifacts..."')
    end = sh.index('echo "   ✓ Cleaned"', start)
    return sh[start:end]


def _run(tmp_path, resume, finish):
    for rel in EVERYTHING:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x")
    script = (f'set -e\nREPO_ROOT="{tmp_path}"\nWIN_DIR="{tmp_path}/windows"\n'
              f"RESUME={resume}\nFINISH={finish}\n{_clean_block()}\n")
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return {rel for rel in EVERYTHING if (tmp_path / rel).exists()}


def test_phase_one_starts_from_nothing(tmp_path):
    assert _run(tmp_path, resume=0, finish=0) == set()


def test_continue_keeps_the_signed_launcher_and_the_signed_folder_with_its_manifest(tmp_path):
    left = _run(tmp_path, resume=1, finish=0)
    assert left == {LAUNCHER, *FOLDER, MANIFEST}, left


def test_finish_keeps_the_signed_installer_and_launcher_and_remakes_only_its_own_outputs(tmp_path):
    left = _run(tmp_path, resume=1, finish=1)
    assert left == {LAUNCHER, *FOLDER, MANIFEST, UNINSTALL_LIST, SETUP}, left


@pytest.mark.parametrize("resume, finish", [(0, 0), (1, 0), (1, 1)])
def test_a_phase_run_twice_in_a_row_finds_nothing_stale_of_its_own(tmp_path, resume, finish):
    """What a phase leaves is exactly what the next phase expects, so a rerun never packages an
    older output: a stale feed or portable zip from a run that failed half way is gone."""
    left = _run(tmp_path, resume=resume, finish=finish)
    assert not (left & set(PHASE3_OUTPUTS)), left
