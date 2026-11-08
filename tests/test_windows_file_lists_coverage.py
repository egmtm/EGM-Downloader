"""
More of windows/app-files.txt and the checks built on it:

* every static file the Windows shell or a page loads is in the list (a file left out is missing from
  both editions, and the built-folder check cannot see it once the folder is built from the list);
* the list check covers every language file and every script partial, and refuses a path that climbs
  out of the repo;
* validate-version-sync.py reports a broken installer folder through its exit code;
* uninstall_list.py refuses a folder that is not an installer folder and a name it cannot write safely
  into the uninstaller.
"""
import importlib.util
import re
import shutil
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def val():
    spec = importlib.util.spec_from_file_location("egm_validate_lists_more", ROOT / "scripts/validate-version-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_root(tmp_path, val, monkeypatch):
    for rel in ("windows/app-files.txt", "windows/BUILD.sh"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    for f in val.read_app_files():
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / f, tmp_path / f)
    monkeypatch.setattr(val, "ROOT", tmp_path)
    monkeypatch.setattr(val, "APP_FILES_LIST", tmp_path / "windows" / "app-files.txt")
    return tmp_path


def _static_files_loaded():
    """static/<name> the Windows shell joins with 'static' and the pages request as /static/<name>."""
    main = read_source("windows/electron/main.js")
    names = set(re.findall(r"path\.join\(APP_DIR, 'static', '([^'$`]+)'\)", main))
    if "`badge-${name}.png`" in main:     # the taskbar count badges: 1 to 9 and 9plus
        names |= {f"badge-{n}.png" for n in [*range(1, 10), "9plus"]}
    for page in sorted((ROOT / "templates").rglob("*.html")):
        names |= set(re.findall(r"""/static/([\w.\-]+\.(?:png|ico|svg|jpg|webp))""", page.read_text(encoding="utf-8")))
    return names


def test_every_static_file_the_shell_or_a_page_loads_is_listed(val):
    names = _static_files_loaded()
    assert {"icon.ico", "icon-64.png", "badge-9plus.png"} <= names, names
    listed = set(val.read_app_files())
    missing = sorted(f"static/{n}" for n in names if f"static/{n}" not in listed)
    assert missing == [], f"loaded but not shipped: {missing}"


@pytest.mark.parametrize("left_out", ["languages/ja.json", "templates/js/_quality.html"])
def test_a_language_file_or_script_partial_left_out_of_the_list_is_seen(fake_root, val, left_out):
    lst = fake_root / "windows/app-files.txt"
    lst.write_text(lst.read_text(encoding="utf-8").replace(f"{left_out}\n", ""), encoding="utf-8")
    errors = val.check_app_files_list()
    assert any(left_out in e for e in errors), errors


@pytest.mark.parametrize("entry", ["../README.md", "/etc/hosts", "static\\icon.ico"])
def test_a_path_out_of_the_repo_is_refused(fake_root, val, entry):
    lst = fake_root / "windows/app-files.txt"
    lst.write_text(lst.read_text(encoding="utf-8") + entry + "\n", encoding="utf-8")
    errors = val.check_app_files_list()
    assert any("not a plain relative path" in e and entry in e for e in errors), errors


def test_a_broken_installer_folder_fails_the_validator_run(val, monkeypatch, capsys):
    assert val.main() == 0
    monkeypatch.setattr(val, "check_installer_folder", lambda folder=None: ["win-unpacked: broken on purpose"])
    assert val.main() == 1
    assert "broken on purpose" in capsys.readouterr().err


# ── uninstall_list.py ─────────────────────────────────────────────────────────

def _uninstall_list():
    spec = importlib.util.spec_from_file_location("egm_uninstall_list_more", ROOT / "windows/installer/uninstall_list.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _folder(tmp_path, extra=None):
    d = tmp_path / "win-unpacked"
    for rel in ("EGM Downloader.exe", "resources/app.asar", "locales/en-US.pak", *(extra or [])):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(b"x")
    return d


@pytest.mark.parametrize("remove", ["EGM Downloader.exe", "resources/app.asar"])
def test_a_folder_that_is_not_the_installer_folder_is_refused(tmp_path, remove):
    d = _folder(tmp_path)
    (d / remove).unlink()
    with pytest.raises(SystemExit, match="not an installer folder"):
        _uninstall_list().render(d)


@pytest.mark.parametrize("name", ["a$b.dll", 'q"uote.dll'])
def test_a_name_that_cannot_be_written_into_the_uninstaller_is_refused(tmp_path, name):
    d = _folder(tmp_path, [name])
    with pytest.raises(SystemExit, match="unexpected name"):
        _uninstall_list().render(d)
