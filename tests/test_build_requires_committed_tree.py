"""The Windows, Linux and Mac builds come from a commit, and never make one.

windows/BUILD.sh and linux/BUILD.sh used to end by committing whatever tracked change the checkout
had and pushing it to main, before the installer and the feeds were signed. That step is gone.
Instead every phase starts by refusing a checkout with uncommitted work (a modified or staged file,
or an untracked file that is not ignored), and prints the commit it builds, at the start and in the
banner it ends with, so a build can be traced to one commit.

mac/BUILD.sh never committed anything; it gets the same check and the same commit line so that its build can be
traced too. The Mac build is also run from the source zip, which has no git folder, so there the check is
skipped and the banner says no commit is recorded (a zip unpacked inside some other repository counts as
having no checkout too: that repository's commit and changes are not this build's).

The check is cut out of each script and run against a throwaway repository."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import read_source

SCRIPTS = ["windows/BUILD.sh", "linux/BUILD.sh", "mac/BUILD.sh"]


def _commands(rel):
    return "\n".join(l for l in read_source(rel).splitlines() if not l.lstrip().startswith("#"))


def _check_block(rel):
    """From the section header to the line that prints the commit."""
    lines = read_source(rel).split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("# ── The checkout must be committed"))
    end = next(i for i in range(start, len(lines)) if l_is_commit_echo(lines[i]))
    return "\n".join(lines[start:end + 1])


def l_is_commit_echo(line):
    return line.strip() == 'echo "   Commit: $HEAD_LINE"'


def _clean_env():
    """Git exports GIT_DIR and friends into hooks (this suite runs from the commit hook), and
    any of them would point the commands at the real repository instead of the temporary one."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return env


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=_clean_env())
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture
def work(tmp_path):
    """A committed checkout with one tracked file and an ignored build folder."""
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "config", "user.name", "test")
    _git(work, "config", "user.email", "test@example.invalid")
    (work / "tracked.txt").write_text("one\n")
    (work / ".gitignore").write_text("dist/\n*.exe\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "the subject line")
    return work


def _run(rel, work, **env_extra):
    script = f'set -e\nREPO_ROOT="{work}"\n{_check_block(rel)}\n'
    env = {**_clean_env(), **env_extra}
    return subprocess.run(["bash", "-c", script], cwd=work, capture_output=True, text=True, env=env)


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_automatic_commit_and_push_are_gone(rel):
    cmds = _commands(rel)
    for forbidden in ("git push", "git commit", "git add"):
        assert forbidden not in cmds, f"{rel} still runs '{forbidden}'"
    assert "Pushing to GitHub" not in read_source(rel)


@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_committed_checkout_passes_and_the_commit_is_printed(rel, work):
    r = _run(rel, work)
    assert r.returncode == 0, r.stdout + r.stderr
    head = _git(work, "rev-parse", "HEAD")
    assert f"Commit: {head} the subject line" in r.stdout, r.stdout


@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_modified_tracked_file_stops_the_build_and_is_named(rel, work):
    (work / "tracked.txt").write_text("two\n")
    r = _run(rel, work)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "tracked.txt" in r.stdout and "uncommitted" in r.stdout.lower(), r.stdout
    assert "Commit:" not in r.stdout


@pytest.mark.parametrize("rel", SCRIPTS)
def test_an_untracked_file_stops_the_build(rel, work):
    (work / "note.txt").write_text("a stray note\n")
    r = _run(rel, work)
    assert r.returncode == 1
    assert "note.txt" in r.stdout


@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_staged_new_file_stops_the_build(rel, work):
    (work / "new.txt").write_text("staged\n")
    _git(work, "add", "new.txt")
    r = _run(rel, work)
    assert r.returncode == 1
    assert "new.txt" in r.stdout


@pytest.mark.parametrize("rel", SCRIPTS)
def test_ignored_build_outputs_do_not_stop_the_build(rel, work):
    (work / "dist").mkdir()
    (work / "dist" / "EGMd.zip").write_text("zip")
    (work / "EGM Downloader.exe").write_text("exe")
    r = _run(rel, work)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_mac_build_from_a_source_zip_with_no_git_passes_and_says_no_commit_is_recorded(tmp_path):
    folder = tmp_path / "egm"
    folder.mkdir()
    r = _run("mac/BUILD.sh", folder, GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Commit: not recorded" in r.stdout, r.stdout
    assert "fatal" not in r.stderr


def test_the_mac_build_in_a_zip_unpacked_inside_another_repository_is_not_taken_for_that_repository(work):
    folder = work / "downloads" / "egm"
    folder.mkdir(parents=True)
    (folder / "file.txt").write_text("from the zip\n")      # untracked in the outer repository
    r = _run("mac/BUILD.sh", folder)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Commit: not recorded" in r.stdout, r.stdout
    assert _git(work, "rev-parse", "HEAD") not in r.stdout


def test_the_real_mac_script_gets_past_the_git_check_in_an_unzipped_folder_with_no_git(tmp_path):
    """The folder a person unzips the source zip into: the script itself, from its first line, with
    only git and dirname on the PATH. It must go on to the prerequisites, where it stops because this
    PATH has no python3 (a stop with its own message, not git's fatal error)."""
    folder = tmp_path / "egm"
    (folder / "mac").mkdir(parents=True)
    (folder / "mac" / "BUILD.sh").write_text(read_source("mac/BUILD.sh"))
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in ("dirname", "git"):
        (tools / name).symlink_to(shutil.which(name))
    env = {**_clean_env(), "PATH": str(tools), "GIT_CEILING_DIRECTORIES": str(tmp_path)}
    r = subprocess.run([shutil.which("bash"), "mac/BUILD.sh"], cwd=folder, capture_output=True, text=True, env=env)
    assert "fatal" not in r.stderr, r.stderr
    assert "Commit: not recorded" in r.stdout, r.stdout
    assert "Python 3 not found" in r.stdout, r.stdout
    assert r.returncode == 1


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_check_runs_before_anything_is_built_or_removed(rel):
    src = read_source(rel)
    check = src.index("# ── The checkout must be committed")
    for later in ("Checking prerequisites", "Cleaning old"):
        assert check < src.index(later), f"{rel}: the committed tree check must come before '{later}'"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_every_banner_the_script_ends_with_prints_the_commit(rel):
    lines = read_source(rel).splitlines()
    banners = [i for i, l in enumerate(lines) if re.search(r"STOP —|BUILD DONE!", l)]
    assert banners, f"{rel}: no stop or done banner found"
    for i in banners:
        assert any(l_is_commit_echo(l) for l in lines[i:i + 8]), f"{rel}:{i + 1}: the banner does not print the commit"
