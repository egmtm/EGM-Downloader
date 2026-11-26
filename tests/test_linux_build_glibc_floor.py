"""No file of the Linux app may need a newer glibc than Electron's own binary.

pip installs the newest wheel the build machine accepts, so on a new build machine (glibc 2.39)
cryptography came as its manylinux_2_34 wheel. On older systems that Electron still runs on, that file
failed to load and the update check stopped working, without a word. Two parts keep it out:

* linux/pip_glibc_floor/_manylinux.py: while linux/BUILD.sh installs the hashed lock, pip asks it which
  manylinux wheels fit (PEP 600). It answers yes only up to glibc 2.17, the level the lock is resolved for.
* a check after electron-builder packs the app: every file of the packed folder is read with objdump,
  and the build stops if one needs a newer glibc than Electron's binary.

The check is cut out of the script and run with a stand-in objdump; nothing real is built.
"""
import importlib.util
import os
import platform
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent
HOOK_DIR = ROOT / "linux" / "pip_glibc_floor"


def _hook():
    spec = importlib.util.spec_from_file_location("_manylinux", HOOK_DIR / "_manylinux.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the pip hook ─────────────────────────────────────────────────────────────────────────────

def test_the_floor_is_the_level_the_lock_is_resolved_for():
    header = read_source("linux/requirements-linux-lock.txt").splitlines()[1]
    m = re.search(r"--python-platform x86_64-manylinux_(\d+)_(\d+) ", header)
    assert m, header
    assert _hook().GLIBC_FLOOR == (int(m.group(1)), int(m.group(2)))


@pytest.mark.parametrize("version,fits", [((2, 5), True), ((2, 12), True), ((2, 17), True),
                                          ((2, 18), False), ((2, 28), False), ((2, 34), False), ((3, 0), False)])
def test_the_hook_accepts_wheels_up_to_the_floor_only(version, fits):
    assert _hook().manylinux_compatible(*version, "x86_64") is fits


@pytest.mark.skipif(sys.platform != "linux" or platform.machine() != "x86_64", reason="manylinux tags exist only on Linux x86_64")
def test_the_packaging_library_pip_uses_honours_the_hook():
    """packaging (vendored inside pip) reads _manylinux from the path: with the hook on PYTHONPATH no
    manylinux tag above 2.17 is offered, and 2.17 still is."""
    code = ("from packaging import tags\n"
            "print('\\n'.join(sorted({t.platform for t in tags.sys_tags() if t.platform.startswith('manylinux_')})))")
    env = dict(os.environ, PYTHONPATH=str(HOOK_DIR))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    levels = {tuple(int(x) for x in re.match(r"manylinux_(\d+)_(\d+)_", p).groups()) for p in r.stdout.split()}
    assert (2, 17) in levels and max(levels) == (2, 17), sorted(levels)


def test_the_build_installs_with_the_hook_and_never_ships_it():
    sh = read_source("linux/BUILD.sh")
    installs = [l for l in sh.splitlines() if " -m pip install " in l and not l.strip().startswith("#")]
    assert len(installs) == 1 and 'PYTHONPATH="$LINUX_DIR/pip_glibc_floor" ' in installs[0], installs
    assert "pip_glibc_floor" not in read_source("linux/electron/package.json")


# ── the check after packing ──────────────────────────────────────────────────────────────────

def _block():
    sh = read_source("linux/BUILD.sh")
    m = re.search(r"^# ── glibc floor .*?^echo \"   ✓ No file needs a newer glibc than Electron's \$FLOOR\"\n", sh, re.S | re.M)
    assert m, "linux/BUILD.sh has no glibc check"
    return m.group(0)


def test_the_check_runs_after_packing_and_before_any_file_is_copied():
    sh = read_source("linux/BUILD.sh")
    at = sh.index(_block())
    assert sh.index("electron-builder --linux AppImage deb rpm") < at < sh.index("# ── Package into zip")


def test_the_build_asks_for_objdump_before_it_starts():
    sh = read_source("linux/BUILD.sh")
    loop = re.search(r"^for cmd in ([^;]+); do", sh, re.M).group(1).split()
    assert "objdump" in loop
    assert re.search(r'objdump\) echo "   Install: sudo apt install binutils', sh)


def _run(tmp_path, needs):
    """needs: {relative path: glibc versions its stand-in objdump reports}; None writes no file."""
    unpacked = tmp_path / "electron" / "dist" / "linux-unpacked"
    for rel, versions in needs.items():
        f = unpacked / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(f"need {v}\n" for v in versions), encoding="utf-8")
    tools = tmp_path / "tools"
    tools.mkdir()
    fake = tools / "objdump"
    fake.write_text('#!/bin/sh\n[ "$1" = -T ] || exit 2\n'
                    'sed -n "s/^need \\(.*\\)/0000 DF *UND* 0000 (\\1) symbol/p" "$2" 2>/dev/null\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    script = f'set -e\nELECTRON_DIR="{tmp_path / "electron"}"\n{_block()}echo BUILD-GOES-ON\n'
    env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}")
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60)


ELECTRON = ["GLIBC_2.2.5", "GLIBC_2.25", "GLIBC_2.3.4"]


def test_a_bundle_within_electrons_glibc_goes_on(tmp_path):
    r = _run(tmp_path, {"egm-downloader-bin": ELECTRON,
                        "libffmpeg.so": ["GLIBC_2.17"],
                        "libold.so": ["GLIBC_2.3"],
                        "resources/python/lib/x.so": ["GLIBC_2.3", "GLIBC_2.25", "GLIBC_PRIVATE"],
                        "resources/app.asar": []})
    assert r.returncode == 0 and "BUILD-GOES-ON" in r.stdout, r.stdout + r.stderr
    assert "No file needs a newer glibc than Electron's 2.25" in r.stdout


@pytest.mark.parametrize("where", ["resources/python/lib/python3.11/site-packages/cryptography/_rust.abi3.so",
                                   "libvk_swiftshader.so"])
@pytest.mark.parametrize("newer", ["GLIBC_2.26", "GLIBC_2.34", "GLIBC_2.25.1", "GLIBC_3.0"])
def test_a_file_that_needs_a_newer_glibc_stops_the_build_and_is_named(tmp_path, newer, where):
    r = _run(tmp_path, {"egm-downloader-bin": ELECTRON, where: ["GLIBC_2.17", newer]})
    assert r.returncode != 0 and "BUILD-GOES-ON" not in r.stdout
    assert f"{where} needs glibc {newer[6:]}, Electron needs 2.25" in r.stdout


def test_an_unreadable_electron_binary_stops_the_build(tmp_path):
    r = _run(tmp_path, {"egm-downloader-bin": [], "resources/app.asar": []})
    assert r.returncode != 0 and "BUILD-GOES-ON" not in r.stdout
    assert "could not read the glibc version Electron's binary needs" in r.stdout
