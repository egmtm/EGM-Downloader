"""
Windows portable: everything the user owns is inside the data folder, so copying that one folder
carries it all over when updating. app.py already keeps its files there; Electron's own data
(saved themes, the chosen theme, history pins, sidebar layout and the secondary window sizes) and
the main window's position used to sit next to it, in <root>\\electron-data and <root>\\egm_settings.json.

The code under test is the start of windows/electron/main.js. It is cut out of the file and run in
Node against real folders with a stand in for Electron's `app`, so what runs is the shipped text.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MAIN_JS = Path(__file__).resolve().parent.parent / "windows" / "electron" / "main.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _code():
    src = MAIN_JS.read_text(encoding="utf-8")
    block = src[src.index("const _portableMarker"):src.index("// ── Window hardening")]
    helpers = src[src.index("function loadSettings()"):src.index("// Validate that an IPC message")]
    return block + "\n" + helpers + "\nreturn { SETTINGS_FILE };"


RUNNER = """
const fs = require('fs'), path = require('path');
const root = process.argv[2];
const calls = [];
const app = { setPath: (k, v) => calls.push([k, v]) };
const run = new Function('app', 'fs', 'path', '__dirname', %s);
const res = run(app, fs, path, path.join(root, 'electron'));
console.log(JSON.stringify({ calls, settings: res.SETTINGS_FILE }));
"""


def _run(root):
    (root / "electron").mkdir(exist_ok=True)
    runner = root.parent / "runner.js"
    runner.write_text(RUNNER % json.dumps(_code()), encoding="utf-8")
    r = subprocess.run([NODE, str(runner), str(root)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture
def root(tmp_path):
    d = tmp_path / "egm"
    d.mkdir()
    return d


def _portable(root):
    (root / ".portable").write_text("x", encoding="utf-8")


def test_a_fresh_portable_folder_keeps_electron_data_and_settings_in_data(root):
    _portable(root)
    out = _run(root)
    assert out["calls"] == [["userData", str(root / "data" / "electron-data")]]
    assert out["settings"] == str(root / "data" / "egm_settings.json")
    assert (root / "data").is_dir()
    assert not (root / "electron-data").exists()


def test_electron_data_from_an_earlier_version_is_moved_into_data(root):
    _portable(root)
    old = root / "electron-data" / "Local Storage" / "leveldb"
    old.mkdir(parents=True)
    (old / "000003.log").write_text("egm-saved-themes", encoding="utf-8")
    out = _run(root)
    moved = root / "data" / "electron-data" / "Local Storage" / "leveldb" / "000003.log"
    assert moved.read_text(encoding="utf-8") == "egm-saved-themes"
    assert not (root / "electron-data").exists()
    assert out["calls"] == [["userData", str(root / "data" / "electron-data")]]


def test_electron_data_that_cannot_be_moved_is_used_where_it_is(root):
    _portable(root)
    (root / "electron-data").mkdir()
    (root / "electron-data" / "keep.txt").write_text("keep", encoding="utf-8")
    (root / "data").write_text("a file where the folder should be", encoding="utf-8")   # the move cannot happen
    out = _run(root)
    assert out["calls"] == [["userData", str(root / "electron-data")]]
    assert (root / "electron-data" / "keep.txt").exists()


def test_an_existing_new_location_wins_and_the_old_folder_is_left_alone(root):
    _portable(root)
    (root / "data" / "electron-data").mkdir(parents=True)
    (root / "data" / "electron-data" / "new.txt").write_text("new", encoding="utf-8")
    (root / "electron-data").mkdir()
    (root / "electron-data" / "old.txt").write_text("old", encoding="utf-8")
    out = _run(root)
    assert out["calls"] == [["userData", str(root / "data" / "electron-data")]]
    assert (root / "data" / "electron-data" / "new.txt").exists()
    assert (root / "electron-data" / "old.txt").exists()


def test_the_window_position_moves_into_the_data_settings_and_the_root_file_goes(root):
    _portable(root)
    (root / "data").mkdir()
    (root / "data" / "egm_settings.json").write_text(json.dumps({"language": "de"}), encoding="utf-8")
    (root / "egm_settings.json").write_text(json.dumps(
        {"window_bounds": {"x": 5, "y": 6, "width": 700, "height": 500}, "window_maximized": True}), encoding="utf-8")
    _run(root)
    merged = json.loads((root / "data" / "egm_settings.json").read_text(encoding="utf-8"))
    assert merged == {"language": "de", "window_bounds": {"x": 5, "y": 6, "width": 700, "height": 500},
                      "window_maximized": True}
    assert not (root / "egm_settings.json").exists()


def test_a_position_already_in_data_is_not_overwritten_by_the_old_one(root):
    _portable(root)
    (root / "data").mkdir()
    (root / "data" / "egm_settings.json").write_text(json.dumps({"window_bounds": {"x": 1}}), encoding="utf-8")
    (root / "egm_settings.json").write_text(json.dumps({"window_bounds": {"x": 99}}), encoding="utf-8")
    _run(root)
    assert json.loads((root / "data" / "egm_settings.json").read_text(encoding="utf-8")) == {"window_bounds": {"x": 1}}
    assert not (root / "egm_settings.json").exists()


def test_the_installed_edition_is_untouched(root):
    (root / "egm_settings.json").write_text(json.dumps({"window_maximized": True}), encoding="utf-8")
    out = _run(root)
    assert out["calls"] == []                       # Electron's default user data folder stays
    assert out["settings"] == str(root / "egm_settings.json")
    assert not (root / "data").exists()
    assert json.loads((root / "egm_settings.json").read_text(encoding="utf-8")) == {"window_maximized": True}


def test_the_launcher_still_hides_both_folders():
    # data holds the new location; electron-data stays on the list for a folder that could not be moved
    src = (MAIN_JS.parent.parent / "launch.py").read_text(encoding="utf-8")
    block = src[src.index("_to_hide = ["):]
    block = block[:block.index("]")]
    assert '"data"' in block and '"electron-data"' in block
