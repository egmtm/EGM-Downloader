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
    assert "check_patchnotes_header(v)" in Path(val.__file__).read_text(encoding="utf-8").split("def main():")[1]
