"""The three phases of the Windows build run on one commit.

Phase 1 builds the launcher and the installer folder, which are then signed; --continue builds
egm-setup.exe from that folder and the repository's files; --finish packages the signed installer.
If the checkout moved to another commit in between (a version bump, say), the installer would be
built from newer files than the folder that was signed. Phase 1 therefore writes the commit it built
from, and --continue and --finish refuse to run on any other one. The check is cut out of the script
and run on its own."""
import subprocess

from conftest import read_source

HEAD = "a" * 40
OTHER = "b" * 40


def _block():
    sh = read_source("windows/BUILD.sh")
    start = sh.index("# ── The phases run on one commit")
    return sh[start:sh.index("# ── Prerequisites", start)]


def _run(tmp_path, resume, marker):
    (tmp_path / "dist").mkdir(exist_ok=True)
    if marker is not None:
        (tmp_path / "dist" / ".build-commit").write_text(marker + "\n")
    script = (f'set -e\nREPO_ROOT="{tmp_path}"\nRESUME={resume}\nHEAD_LINE="{HEAD} the subject line"\n'
              f"{_block()}\necho PASSED\n")
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)


def test_phase_one_checks_nothing(tmp_path):
    r = _run(tmp_path, resume=0, marker=None)
    assert r.returncode == 0 and "PASSED" in r.stdout, r.stdout + r.stderr


def test_a_later_phase_on_the_commit_phase_one_built_goes_ahead(tmp_path):
    r = _run(tmp_path, resume=1, marker=HEAD)
    assert r.returncode == 0 and "PASSED" in r.stdout, r.stdout + r.stderr


def test_a_later_phase_on_another_commit_is_refused_and_names_both(tmp_path):
    r = _run(tmp_path, resume=1, marker=OTHER)
    assert r.returncode == 1 and "PASSED" not in r.stdout
    assert OTHER in r.stdout and HEAD in r.stdout, r.stdout


def test_a_later_phase_without_phase_one_having_run_is_refused(tmp_path):
    r = _run(tmp_path, resume=1, marker=None)
    assert r.returncode == 1 and "PASSED" not in r.stdout
    assert "phase 1" in r.stdout, r.stdout


def test_phase_one_writes_the_commit_after_it_built_and_before_it_stops():
    sh = read_source("windows/BUILD.sh")
    built = sh.index('bash "$WIN_DIR/installer/build-folder.sh"')
    wrote = sh.index('> "$REPO_ROOT/dist/.build-commit"')
    stop = sh.index("STOP — launcher compiled, not yet signed")
    assert built < wrote < stop
