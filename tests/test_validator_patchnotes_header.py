"""scripts/validate-version-sync.py: the top patchnotes header carries the app's exact version.

What's New shows the patchnotes block whose header equals the app's version. A well formed header
with a wrong number still gives full feeds and a clean validator, and the app then shows an empty
What's New until a new build. So the first header must be 'v<version> - NAME (MM/DD/YYYY)', or
'vTBD - ...' while the release is not cut (the form testing/next carries between releases).

The validator is loaded as a module with ROOT pointed at a temporary tree."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
V = "1.5.3.2"


@pytest.fixture(scope="module")
def val():
    spec = importlib.util.spec_from_file_location("egm_validate_patchnotes_header", ROOT / "scripts/validate-version-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _errors(val, tmp_path, monkeypatch, header):
    monkeypatch.setattr(val, "ROOT", tmp_path)
    (tmp_path / "patchnotes.txt").write_text(
        f"\n{header}\n-----------------------------------------\n\n  • [ALL] Fixed: a thing.\n", encoding="utf-8")
    return val.check_patchnotes_header(V)


@pytest.mark.parametrize("header", [
    "v1.5.3.2 - THE TOTAL PACKAGE (11/13/2026)",
    "v1.5.3.2 - CITIUS · أصيل: Reloaded (10/26/2026)",
    "vTBD - TBD (TBD)",
])
def test_the_released_form_and_the_tbd_form_pass(val, tmp_path, monkeypatch, header):
    assert _errors(val, tmp_path, monkeypatch, header) == []


@pytest.mark.parametrize("header", [
    "v1.5.3 - THE TOTAL PACKAGE (11/13/2026)",          # a wrong number, the case nothing else catches
    "v1.5.3.2.0 - THE TOTAL PACKAGE (11/13/2026)",
    "v1.5.2.3 - SNAKE EYES PART II (11/05/2026)",       # the block below left on top
    "v1.5.3.2 – THE TOTAL PACKAGE (11/13/2026)",        # en dash
    "v1.5.3.2 - THE TOTAL PACKAGE (TBD)",
    "v1.5.3.2 - THE TOTAL PACKAGE",
    "1.5.3.2 - THE TOTAL PACKAGE (11/13/2026)",
])
def test_any_other_first_header_fails_and_names_what_it_expected(val, tmp_path, monkeypatch, header):
    errors = _errors(val, tmp_path, monkeypatch, header)
    assert len(errors) == 1 and header in errors[0] and f"v{V} - NAME (MM/DD/YYYY)" in errors[0]


def test_a_missing_file_is_an_error(val, tmp_path, monkeypatch):
    monkeypatch.setattr(val, "ROOT", tmp_path)
    assert val.check_patchnotes_header(V) == ["patchnotes.txt not found"]


def test_the_repository_passes_and_main_runs_the_check(val):
    version = val.load_version()["version"]
    assert val.check_patchnotes_header(version) == []
    assert "check_patchnotes_header(v, b)" in Path(val.__file__).read_text(encoding="utf-8").split("def main():")[1]


# Once the build is bumped past the last released build, the release is being cut: 'vTBD' is refused
# (review of 32190d3c; EGM, Nov 14). The header goes into the bump commit.

def _tbd_errors(val, tmp_path, monkeypatch, build, last="177\n"):
    monkeypatch.setattr(val, "ROOT", tmp_path)
    (tmp_path / "patchnotes.txt").write_text("vTBD - TBD (TBD)\n-----\n\n  • [ALL] Fixed: a thing.\n", encoding="utf-8")
    if last is not None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "last-released-build.txt").write_text(last, encoding="utf-8")
    return val.check_patchnotes_header(V, build)


def test_tbd_passes_while_the_build_is_the_last_released_one(val, tmp_path, monkeypatch):
    assert _tbd_errors(val, tmp_path, monkeypatch, 177) == []


def test_tbd_fails_once_the_build_is_bumped(val, tmp_path, monkeypatch):
    errors = _tbd_errors(val, tmp_path, monkeypatch, 178)
    assert len(errors) == 1 and "vTBD - TBD (TBD)" in errors[0] and "build 178" in errors[0] and "177" in errors[0]
    assert f"v{V} - NAME (MM/DD/YYYY)" in errors[0]


@pytest.mark.parametrize("last", [None, "not a number\n"])
def test_tbd_passes_when_there_is_no_last_released_build_to_compare(val, tmp_path, monkeypatch, last):
    assert _tbd_errors(val, tmp_path, monkeypatch, 178, last=last) == []


def test_main_passes_the_build_to_the_header_check(val, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(val, "check_patchnotes_header", lambda *a: calls.append(a) or [])
    val.main()
    version = val.load_version()
    assert calls == [(version["version"], version["build"])]
