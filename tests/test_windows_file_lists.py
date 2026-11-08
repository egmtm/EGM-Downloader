"""
windows/app-files.txt is the one list of app files of the Windows build. The portable stage
(windows/BUILD.sh) and the installer folder (windows/installer/build-folder.sh) are both built from
it, and scripts/validate-version-sync.py checks each edition against it by relative path:
  * the list itself: real files, no duplicate, every template and language file listed;
  * the portable stage: the app files plus its own files (launcher, launch.py, instructions.txt,
    electron/package*.json, .portable, and the shell files in electron/), nothing else;
  * the built installer folder, when there is one: resources/app holds the app files,
    resources/app.asar the shell files, resources nothing but those and the bundled Python.
"""
import importlib.util
import shutil
import struct
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def val():
    spec = importlib.util.spec_from_file_location("egm_validate_lists", ROOT / "scripts/validate-version-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_root(tmp_path, val, monkeypatch):
    """A copy of the parts of the repo these checks read, to break on purpose."""
    for rel in ("windows/app-files.txt", "windows/BUILD.sh"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    for f in val.read_app_files():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, tmp_path / f)
    monkeypatch.setattr(val, "ROOT", tmp_path)
    monkeypatch.setattr(val, "APP_FILES_LIST", tmp_path / "windows" / "app-files.txt")
    return tmp_path


def test_the_repo_passes(val):
    assert val.check_app_files_list() == []
    assert val.check_portable_stage() == []


def test_the_portable_stage_is_the_app_files_plus_its_own_files(val):
    have = val.portable_stage_files((ROOT / "windows/BUILD.sh").read_text(encoding="utf-8"))
    app = set(val.read_app_files())
    assert app <= have
    assert have - app == {"EGM Downloader.exe", "launch.py", "instructions.txt", ".portable",
                          "electron/package.json", "electron/package-lock.json",
                          "electron/main.js", "electron/preload.js", "electron/splash.html"}


def test_a_template_left_out_of_the_list_is_seen(fake_root, val):
    lst = fake_root / "windows/app-files.txt"
    lst.write_text(lst.read_text().replace("templates/i18n.html\n", ""), encoding="utf-8")
    errors = val.check_app_files_list()
    assert any("templates/i18n.html" in e for e in errors), errors


def test_a_missing_or_doubled_entry_is_seen(fake_root, val):
    lst = fake_root / "windows/app-files.txt"
    lst.write_text(lst.read_text() + "static/badge-1.png\nstatic/nope.png\n", encoding="utf-8")
    errors = " ".join(val.check_app_files_list())
    assert "lists files twice: ['static/badge-1.png']" in errors
    assert "does not exist: static/nope.png" in errors


def test_a_stray_or_missing_portable_file_is_seen(fake_root, val):
    sh = fake_root / "windows/BUILD.sh"
    text = sh.read_text(encoding="utf-8")
    sh.write_text(text.replace('cp "$REPO_ROOT/windows/launch.py"             "$PORTABLE_STAGE/"\n',
                               'cp "$REPO_ROOT/README.md" "$PORTABLE_STAGE/docs/"\n'), encoding="utf-8")
    errors = " ".join(val.check_portable_stage())
    assert "missing: ['launch.py']" in errors and "docs/README.md" in errors


def test_a_portable_stage_that_skips_the_list_is_seen(fake_root, val):
    sh = fake_root / "windows/BUILD.sh"
    sh.write_text(sh.read_text(encoding="utf-8").replace('done < "$REPO_ROOT/windows/app-files.txt"', "done"),
                  encoding="utf-8")
    assert any("Portable stage is missing" in e and "app.py" in e for e in val.check_portable_stage())


# ── the built installer folder ────────────────────────────────────────────────

def _asar(path, names):
    header = json.dumps({"files": {n: {"size": 1, "offset": "0"} for n in names}}).encode()
    pickle = struct.pack("<I", len(header)) + header
    path.write_bytes(struct.pack("<II", 4, len(pickle) + 4) + struct.pack("<I", len(pickle)) + pickle + b"x")


def _folder(tmp_path, val):
    d = tmp_path / "win-unpacked"
    (d / "resources" / "python").mkdir(parents=True)
    (d / "resources" / "python" / "python.exe").write_bytes(b"MZ")
    (d / "EGM Downloader.exe").write_bytes(b"MZ")
    for f in val.read_app_files():
        p = d / "resources" / "app" / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    _asar(d / "resources" / "app.asar", ["main.js", "preload.js", "splash.html", "package.json"])
    return d


def test_a_well_formed_installer_folder_passes_also_with_runtime_bytecode(tmp_path, val):
    d = _folder(tmp_path, val)
    (d / "resources" / "app" / "__pycache__").mkdir()
    (d / "resources" / "app" / "__pycache__" / "x.cpython-311.pyc").write_bytes(b"x")
    assert val.check_installer_folder(d) == []


@pytest.mark.parametrize("damage, expect", [
    (lambda d: (d / "resources/app/templates/i18n.html").unlink(), "missing ['templates/i18n.html']"),
    (lambda d: (d / "resources/app/extra.txt").write_text("x"), "extra ['extra.txt']"),
    (lambda d: _asar(d / "resources/app.asar", ["main.js", "package.json"]), "app.asar holds"),
    (lambda d: (d / "resources/other").mkdir(), "resources holds"),
    (lambda d: (d / "EGM Downloader.exe").unlink(), "not at the top"),
    (lambda d: (d / "resources/python/python.exe").unlink(), "no python.exe"),
])
def test_a_wrong_installer_folder_is_seen(tmp_path, val, damage, expect):
    d = _folder(tmp_path, val)
    damage(d)
    errors = " ".join(val.check_installer_folder(d))
    assert expect in errors, errors


def test_the_real_installer_folder_if_built(val):
    folder = ROOT / "dist" / "win-unpacked"
    if not folder.is_dir():
        pytest.skip("dist/win-unpacked is not built")
    assert val.check_installer_folder(folder) == []


# Every .exe the installer folder may hold: the app, the bundled Python's two interpreters and pip's
# two launcher stubs for this Python (x64). Anything else is unsigned PE surface the app never runs.
ALLOWED_EXES = {
    "EGM Downloader.exe",
    "resources/python/python.exe",
    "resources/python/pythonw.exe",
    "resources/python/Lib/site-packages/pip/_vendor/distlib/t64.exe",
    "resources/python/Lib/site-packages/pip/_vendor/distlib/w64.exe",
}


def test_the_only_exes_in_the_built_folder_are_the_allowed_ones():
    folder = ROOT / "dist" / "win-unpacked"
    if not folder.is_dir():
        pytest.skip("dist/win-unpacked is not built")
    found = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".exe"}
    assert found == ALLOWED_EXES, sorted(found ^ ALLOWED_EXES)
