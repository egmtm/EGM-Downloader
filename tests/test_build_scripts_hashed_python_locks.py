"""The Linux and Mac builds install the bundled Python's packages from a hashed lock, like Windows.

requirements.txt gives floors and ranges, so a plain "pip install -r requirements.txt" takes the newest
release on the build day: two builds of the same commit one day apart bundled different packages. Each
platform now has a lock made by uv (the command is on the lock's second line) with every file's hash,
and its build installs it with --require-hashes, so every build of a commit bundles the same files and a
changed file stops the build. The three locks are regenerated together, in every bump commit and
whenever requirements.txt changes, so they pin the same versions.
"""
import re

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from conftest import read_source

LOCKS = {
    "linux": ("linux/requirements-linux-lock.txt", "x86_64-manylinux_2_17", "linux/BUILD.sh"),
    "mac": ("mac/requirements-mac-lock.txt", "aarch64-apple-darwin", "mac/BUILD.sh"),
    "windows": ("windows/requirements-win-lock.txt", "x86_64-pc-windows-msvc", None),
}


def _pins(rel):
    pins, hashes, name = {}, {}, None
    for line in read_source(rel).splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", line)
        if m:
            name = canonicalize_name(m.group(1))
            pins[name], hashes[name] = m.group(2), []
        hashes.setdefault(name, []).extend(re.findall(r"--hash=sha256:([0-9a-f]{64})", line))
    return pins, hashes


@pytest.mark.parametrize("plat", ["linux", "mac"])
def test_the_lock_is_for_its_platform_and_every_pin_is_hashed(plat):
    rel, platform, _ = LOCKS[plat]
    text = read_source(rel)
    assert text.splitlines()[1] == (f"#    uv pip compile requirements.txt --python-platform {platform} "
                                    "--python-version 3.11 --generate-hashes --only-binary :all:")
    assert " ; " not in text, "a lock resolved for one platform carries no environment markers"
    pins, hashes = _pins(rel)
    assert pins
    for name in pins:
        assert hashes[name], f"{name} has no hash"


@pytest.mark.parametrize("plat", ["linux", "mac"])
def test_the_lock_satisfies_requirements_txt(plat):
    pins, _ = _pins(LOCKS[plat][0])
    for line in read_source("requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        req = Requirement(line)
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is not in {LOCKS[plat][0]}"
        assert Version(pins[name]) in req.specifier, f"{name} {pins[name]} does not satisfy {req.specifier}"


def test_the_three_locks_pin_the_same_versions():
    """Regenerated together, so Linux, Mac and Windows bundle the same versions."""
    win, _ = _pins(LOCKS["windows"][0])
    for plat in ("linux", "mac"):
        assert _pins(LOCKS[plat][0])[0] == win, f"{plat} and Windows locks pin different versions: regenerate all three"


@pytest.mark.parametrize("plat", ["linux", "mac"])
def test_the_build_installs_only_hashed_binary_wheels_from_its_lock(plat):
    rel, _, script = LOCKS[plat]
    sh = read_source(script)
    lock_var = re.findall(r'^LOCK="\$(?:LINUX|MAC)_DIR/([^"]+)"$', sh, re.M)
    assert lock_var == [rel.split("/")[1]], lock_var
    installs = [l.strip() for l in sh.splitlines() if "pip install" in l and not l.strip().startswith("#")]
    floor = ' PYTHONPATH="$LINUX_DIR/pip_glibc_floor"' if plat == "linux" else ""
    assert installs == [f'PYTHONNOUSERSITE=1{floor} "$PYTHON_DIR/bin/python3" -m pip install --quiet '
                        '--require-hashes --no-deps --only-binary :all: -r "$LOCK"'], installs


@pytest.mark.parametrize("plat", ["linux", "mac"])
def test_the_build_never_installs_from_requirements_txt_or_falls_back(plat):
    sh = read_source(LOCKS[plat][2])
    code = [l for l in sh.splitlines() if l.strip() and not l.strip().startswith("#")]
    pip_lines = [l for l in code if " -m pip " in l]
    assert not [l for l in pip_lines if "requirements.txt" in l], pip_lines
    assert not [l for l in pip_lines if "||" in l or l.rstrip().endswith("\\")], "a failed install must stop the build"


CHECK = 'PYTHONNOUSERSITE=1 "$PYTHON_DIR/bin/python3" -m pip check'


@pytest.mark.parametrize("plat", ["linux", "mac"])
def test_pip_check_runs_right_after_the_locked_install(plat):
    """--no-deps installs only what the lock lists: pip check stops the build when the lock lacks a
    package another one needs."""
    code = [l.strip() for l in read_source(LOCKS[plat][2]).splitlines() if l.strip() and not l.strip().startswith("#")]
    at = next(i for i, l in enumerate(code) if "--require-hashes" in l)
    assert code[at + 1] == CHECK, code[at + 1]
    assert code.count(CHECK) == 1
    assert code[0] == "set -e", "the script stops on the first failing command, pip check included"

