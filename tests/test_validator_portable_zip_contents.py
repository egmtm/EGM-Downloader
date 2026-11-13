"""scripts/validate-version-sync.py: the built portable zip holds exactly the portable stage's files.

check_portable_stage reads the cp lines of windows/BUILD.sh with a regex; nothing looked at the zip
the build wrote. When dist/EGMd-portable.zip exists, its members must be exactly the app files of
windows/app-files.txt plus the portable edition's own files. With no zip in dist/ nothing is checked.

The validator is loaded as a module with ROOT pointed at a temporary tree."""
import importlib.util
import inspect
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def val():
    spec = importlib.util.spec_from_file_location("egm_validate_portable_zip", ROOT / "scripts/validate-version-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dist(tmp_path, val, monkeypatch):
    monkeypatch.setattr(val, "ROOT", tmp_path)
    d = tmp_path / "dist"
    d.mkdir()
    return d


def _portable_zip(dist, val, drop=None, add=None):
    names = set(val.read_app_files()) | val.PORTABLE_ONLY | {f"electron/{n}" for n in val.SHELL_FILES}
    names -= {drop} if drop else set()
    names |= {add} if add else set()
    with zipfile.ZipFile(dist / "EGMd-portable.zip", "w") as zf:
        for n in sorted(names):
            zf.writestr(n, "x")


def test_no_portable_zip_means_nothing_is_checked(dist, val):
    assert val.check_portable_zip_contents() == []


def test_a_portable_zip_with_exactly_the_stage_files_passes(dist, val):
    _portable_zip(dist, val)
    assert val.check_portable_zip_contents() == []


def test_a_portable_zip_missing_a_member_fails(dist, val):
    _portable_zip(dist, val, drop="launch.py")
    errors = val.check_portable_zip_contents()
    assert any("missing" in e and "launch.py" in e for e in errors), errors


def test_a_portable_zip_with_an_extra_member_fails(dist, val):
    _portable_zip(dist, val, add="electron/node_modules/electron/package.json")
    errors = val.check_portable_zip_contents()
    assert any("electron/node_modules/electron/package.json" in e for e in errors), errors


def test_the_zip_and_the_stage_are_held_to_the_same_list(val):
    """One list for both checks, so they cannot drift apart."""
    assert "portable_files_wanted()" in inspect.getsource(val.check_portable_stage)
    assert "portable_files_wanted()" in inspect.getsource(val.check_portable_zip_contents)


def test_the_check_runs_in_main(val):
    assert "check_portable_zip_contents()" in inspect.getsource(val.main)
