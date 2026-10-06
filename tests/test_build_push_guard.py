"""The build scripts must not push stray files to a public branch.

windows/BUILD.sh and linux/BUILD.sh end with a git step. It used to run
`git add -A`, commit and push to main whenever the folder had any change, so a
stray file (a note, a key, a test output) could end up public, and nothing
else would catch it. The step now only commits when:
  - the checkout is on main (testing branches are left alone), and
  - there are no untracked files (tracked changes are committed with
    `git add -u`; anything untracked needs a human look first).
These tests run the real step from each script against a throwaway repo with a
bare remote."""
import os
import subprocess

import pytest

from conftest import read_source

SCRIPTS = [("windows/BUILD.sh", "Windows"), ("linux/BUILD.sh", "Linux")]


def _push_block(rel):
    """The guarded git step: from the BRANCH= line to the closing fi."""
    lines = read_source(rel).split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith('BRANCH="$(git rev-parse'))
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start:end + 1])


def _clean_env():
    """Environment for the throwaway repos. Git exports GIT_DIR, GIT_INDEX_FILE
    and friends into hooks (the pre-commit and pre-push suite runs), and any of
    them would point these commands at the real repository instead of the temp
    one (this once flipped core.bare and the author name of the real repo)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return env


def _git(cwd, *args):
    env = _clean_env()
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A working repo on main with one tracked file and a bare origin."""
    remote = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    _git(work, "remote", "add", "origin", str(remote))
    (work / "tracked.txt").write_text("one\n")
    (work / ".gitignore").write_text("dist/\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "start")
    _git(work, "push", "origin", "main")
    return work, remote


def _run(rel, work):
    script = f'set -e\nVERSION=9.9.9\nBUILD_NUM=1\n{_push_block(rel)}\n'
    env = _clean_env()
    return subprocess.run(["bash", "-c", script], cwd=work, capture_output=True,
                          text=True, env=env)


def _remote_head(remote):
    return _git(remote, "rev-parse", "main")


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_clean_tree_makes_no_commit(repo, rel, osname):
    work, remote = repo
    before = _remote_head(remote)
    r = _run(rel, work)
    assert r.returncode == 0, r.stderr
    assert "No source changes" in r.stdout
    assert _remote_head(remote) == before


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_ignored_build_output_makes_no_commit(repo, rel, osname):
    work, remote = repo
    (work / "dist").mkdir()
    (work / "dist" / "EGMd.zip").write_text("binary")
    before = _remote_head(remote)
    r = _run(rel, work)
    assert r.returncode == 0, r.stderr
    assert _remote_head(remote) == before


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_tracked_change_on_main_is_committed_and_pushed(repo, rel, osname):
    work, remote = repo
    before = _remote_head(remote)
    (work / "tracked.txt").write_text("two\n")
    r = _run(rel, work)
    assert r.returncode == 0, r.stderr
    assert _remote_head(remote) != before
    assert _git(remote, "log", "-1", "--format=%s", "main") == f"{osname} v9.9.9 Build 1"
    assert _git(work, "status", "--porcelain") == ""


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_untracked_file_blocks_the_commit(repo, rel, osname):
    work, remote = repo
    before = _remote_head(remote)
    (work / "tracked.txt").write_text("two\n")
    (work / "stray_notes.txt").write_text("not for the public repo\n")
    r = _run(rel, work)
    assert r.returncode == 0, "the build must still finish"
    assert "untracked files are present" in r.stdout
    assert "stray_notes.txt" in r.stdout
    assert _remote_head(remote) == before
    assert _git(work, "log", "-1", "--format=%s") == "start"


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_non_main_branch_is_left_alone(repo, rel, osname):
    work, remote = repo
    _git(work, "checkout", "-b", "testing/v9")
    before = _remote_head(remote)
    (work / "tracked.txt").write_text("two\n")
    r = _run(rel, work)
    assert r.returncode == 0, r.stderr
    assert "not 'main'" in r.stdout
    assert _remote_head(remote) == before
    assert _git(work, "log", "-1", "--format=%s") == "start"
    assert _git(work, "status", "--porcelain") == "M tracked.txt"


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_detached_head_is_left_alone(repo, rel, osname):
    work, remote = repo
    _git(work, "checkout", "--detach")
    before = _remote_head(remote)
    (work / "tracked.txt").write_text("two\n")
    r = _run(rel, work)
    assert r.returncode == 0, r.stderr
    assert _remote_head(remote) == before


@pytest.mark.parametrize("rel,osname", SCRIPTS)
def test_script_no_longer_sweeps_everything(rel, osname):
    """`git add -A` must not come back in the build scripts."""
    assert "git add -A" not in read_source(rel)
