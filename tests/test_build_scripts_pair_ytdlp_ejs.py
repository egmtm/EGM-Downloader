"""The Mac and Linux builds bundle yt-dlp and its solver package as a pair.

yt-dlp takes its YouTube solver script from the yt-dlp-ejs package only at the version it names (a ==
requirement for its default extra in its metadata). requirements.txt asks for "yt-dlp-ejs>=0.8.0", on
purpose: the range must not be narrowed, or the pairing would break the other way when yt-dlp moves to
its next ejs. But a range takes the newest release, so a build made after yt-dlp-ejs publishes a new
minor and before yt-dlp stable names it would bundle a package yt-dlp refuses, and the script would
come from GitHub until the person ran Update Plugins (an independent privacy review, R2).

So mac/BUILD.sh and linux/BUILD.sh, right after "pip install -r requirements.txt", read the pin from
the bundled Python (the same reading as the backend's _ytdlp_ejs_pin and the Windows launcher's) and
install exactly that version. The same step as the launcher and Update Plugins, so all three pair alike.

* a yt-dlp that names none (or a line that is not a plain version) leaves the GitHub fallback and the
  build goes on, with a warning;
* a failed read or a failed install stops the build: a bundle that cannot be paired is not shipped quietly;
* Linux keeps PYTHONNOUSERSITE=1 on the new calls, so the host's ~/.local packages are never read.

The block is cut out of each script and run in bash against a stand-in bundled Python whose metadata
and pip are fakes. Nothing is installed or downloaded.
"""
import re
import stat
import subprocess
import sys

import pytest

from conftest import read_source

SCRIPTS = ("mac/BUILD.sh", "linux/BUILD.sh")
PLAIN = "yt-dlp-ejs==0.8.0; extra == \"default\""


def _block(rel):
    m = re.search(r"^# yt-dlp-ejs: .*?^fi$", read_source(rel), re.S | re.M)
    assert m, f"{rel} has no yt-dlp-ejs pairing step"
    return m.group(0)


def _run(rel, tmp_path, requires, pip_fails=False, read_fails=False):
    """Run the script's pairing block with a fake bundled Python. Returns (result, calls)."""
    py_dir = tmp_path / "python"
    (py_dir / "bin").mkdir(parents=True)
    meta = tmp_path / "meta"
    dist = meta / "yt_dlp-2026.10.26.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: yt-dlp\nVersion: 2026.10.26\n" + "".join(f"Requires-Dist: {l}\n" for l in requires),
        encoding="utf-8")
    log = tmp_path / "calls.log"
    fake = py_dir / "bin" / "python3"
    fake.write_text(f"""#!/bin/bash
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  echo "pip|$PYTHONNOUSERSITE|$*" >> "{log}"
  exit {1 if pip_fails else 0}
fi
echo "read|$PYTHONNOUSERSITE" >> "{log}"
{"exit 3" if read_fails else ""}
PYTHONPATH="{meta}" exec "{sys.executable}" "$@"
""", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    script = f'set -e\nPYTHON_DIR="{py_dir}"\n{_block(rel)}\necho BUILD-GOES-ON\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return r, calls


def _installs(calls):
    return [c.split("|", 2)[2] for c in calls if c.startswith("pip|")]


# ── Where it sits, and what stays ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_step_comes_right_after_the_requirements_install_and_before_anything_is_stripped(rel):
    src = read_source(rel)
    after_install = src.index("pip install --quiet -r", src.index("Installing Python dependencies"))
    assert src.count("# yt-dlp-ejs: ") == 1
    step = src.index("# yt-dlp-ejs: ")
    assert after_install < step < src.index("Stripping unused Python packages"), rel


@pytest.mark.parametrize("rel", ("requirements.txt", "linux/requirements.txt"))
def test_the_range_in_the_requirements_is_not_narrowed(rel):
    """Narrowing it would break the pairing the other way when yt-dlp moves to its next ejs."""
    lines = [l.strip() for l in read_source(rel).splitlines()]
    assert "yt-dlp-ejs>=0.8.0" in lines and not any(l.startswith("yt-dlp-ejs==") for l in lines)


# ── What the step does ───────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_version_yt_dlp_names_is_installed_with_the_bundled_python(rel, tmp_path):
    r, calls = _run(rel, tmp_path, ["certifi>=2026.10.19; extra == 'default'", PLAIN])
    assert r.returncode == 0 and "BUILD-GOES-ON" in r.stdout, r.stderr[-800:]
    assert [c.split("|")[0] for c in calls] == ["read", "pip"], "read the pin first, then install"
    (cmd,) = _installs(calls)
    assert "yt-dlp-ejs==0.8.0" in cmd.split(), cmd
    assert "0.8.0" in r.stdout, "the build log says which version was paired"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_exact_named_version_is_installed_not_the_newest(rel, tmp_path):
    r, calls = _run(rel, tmp_path, ["yt-dlp-ejs==0.8.2; extra == \"default\""])
    (cmd,) = _installs(calls)
    assert "yt-dlp-ejs==0.8.2" in cmd.split()


@pytest.mark.parametrize("requires", [
    [], ["certifi>=1"], ["yt-dlp-ejs>=0.8.0; extra == 'default'"], ["yt-dlp-ejs; extra == 'default'"],
    ["yt-dlp-ejs==0.8.0; extra == 'pin'"], ["yt-dlp-ejs==0.8.0 && echo x; extra == 'default'"],
    ["yt-dlp-ejs==../x; extra == 'default'"],
])
@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_yt_dlp_that_names_no_plain_version_leaves_the_fallback_and_the_build_goes_on(rel, tmp_path, requires):
    r, calls = _run(rel, tmp_path, requires)
    assert r.returncode == 0 and "BUILD-GOES-ON" in r.stdout, r.stderr[-800:]
    assert _installs(calls) == [], "nothing may be installed when no plain version is named"
    assert "names no yt-dlp-ejs" in r.stdout, "the build log says why nothing was paired"


@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_failed_install_stops_the_build(rel, tmp_path):
    r, calls = _run(rel, tmp_path, [PLAIN], pip_fails=True)
    assert r.returncode != 0 and "BUILD-GOES-ON" not in r.stdout


@pytest.mark.parametrize("rel", SCRIPTS)
def test_a_failed_read_stops_the_build(rel, tmp_path):
    r, calls = _run(rel, tmp_path, [PLAIN], read_fails=True)
    assert r.returncode != 0 and "BUILD-GOES-ON" not in r.stdout
    assert _installs(calls) == []


def test_linux_keeps_the_hosts_user_packages_out_of_both_new_calls(tmp_path):
    r, calls = _run("linux/BUILD.sh", tmp_path, [PLAIN])
    assert [c.split("|")[1] for c in calls] == ["1", "1"], "the read and the install both need PYTHONNOUSERSITE=1"


# ── Same reading as the backend and the launcher ─────────────────────────────────────────────

@pytest.mark.parametrize("lines", [
    [PLAIN], [], ["yt-dlp-ejs==0.9.1; extra == 'default'"], ["yt-dlp-ejs>=0.8.0; extra == 'default'"],
    ["yt-dlp-ejs==0.8.0; extra == 'pin'"], ["yt-dlp-ejs==0.8.0 && echo x; extra == 'default'"],
    ["yt-dlp-ejs==../x; extra == 'default'"], ["yt-dlp-ejs==0.8.0 ; extra == \"default\""],
])
@pytest.mark.parametrize("rel", SCRIPTS)
def test_the_build_reads_the_same_pin_as_the_backend(rel, tmp_path, app_module, monkeypatch, lines):
    import types
    stdout = "".join(l + "\n" for l in lines)
    monkeypatch.setattr(app_module, "_run_yt", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
    want = app_module._ytdlp_ejs_pin()
    _, calls = _run(rel, tmp_path, lines)
    got = next((a.split("yt-dlp-ejs==")[1].split()[0] for a in _installs(calls) if "yt-dlp-ejs==" in a), None)
    assert got == want
