"""
Windows launcher: the Node.js it uses must be new enough for the Electron it installs.

Electron 45's installer (@electron/get 5) needs Node 22.12 or newer, and Node 20 is past
end of life. The launcher therefore refuses anything older (a system Node, a cached
detection, or the portable node_bin from an earlier release) and downloads the pinned
version instead. windows/launch.py is import safe, so these tests drive the real
ensure_node() with a fake node version probe and a fake download. Nothing is downloaded.
"""
import importlib.util
import json
import re
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "windows" / "launch.py"
LOCK = ROOT / "windows" / "electron" / "package-lock.json"


def _tuple(version: str):
    return tuple(int(x) for x in version.split(".")[:3])


@pytest.fixture
def env(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_node_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    node_dir = tmp_path / "node_bin"
    monkeypatch.setattr(mod, "NODE_DIR", node_dir)
    monkeypatch.setattr(mod, "NODE_EXE", node_dir / "node.exe")
    monkeypatch.setattr(mod, "VERSION_CACHE", node_dir / ".node_version")
    msgs = []
    monkeypatch.setattr(mod, "_gui_msg", lambda m="", *a, **k: msgs.append(m))
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)

    class Env:
        pass

    e = Env()
    e.mod, e.dir, e.msgs, e.downloads = mod, node_dir, msgs, []
    e.versions = {}          # exe name or path -> version tuple; missing = not installed

    monkeypatch.setattr(mod, "_node_version", lambda exe: e.versions.get(str(exe), (0, 0, 0)))
    monkeypatch.setattr(mod, "_verify_node_zip", lambda p: True)

    def fake_download(url, dest, reporthook=None):
        e.downloads.append(url)
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr(f"{mod.NODE_ZIP_DIR}/node.exe", "new node")
        # once extracted, the new portable node reports the pinned version
        e.versions[str(mod.NODE_EXE)] = _tuple(mod.NODE_VERSION)

    monkeypatch.setattr(mod.urllib.request, "urlretrieve", fake_download)
    return e


def test_floor_covers_every_node_requirement_of_the_shipped_lockfile():
    """The launcher's minimum Node must satisfy the engines.node of everything npm installs."""
    mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location("egm_launch_floor", LAUNCH))
    mod.__spec__.loader.exec_module(mod)
    floors = []
    for pkg in json.loads(LOCK.read_text(encoding="utf-8"))["packages"].values():
        m = re.match(r"^>=\s*(\d+(?:\.\d+){0,2})\s*$", str((pkg.get("engines") or {}).get("node", "")))
        if m:
            parts = [int(x) for x in m.group(1).split(".")]
            floors.append(tuple(parts + [0] * (3 - len(parts))))
    assert floors, "lockfile lists no Node requirements; this guard would pass for nothing"
    assert mod.NODE_MIN >= max(floors), (mod.NODE_MIN, max(floors))


def test_downloaded_node_meets_the_floor(env):
    assert _tuple(env.mod.NODE_VERSION) >= env.mod.NODE_MIN
    assert env.mod.NODE_ZIP_NAME == f"node-v{env.mod.NODE_VERSION}-win-x64.zip"


def test_node_20_is_not_good_enough(env):
    assert env.mod.NODE_MIN > (20, 19, 1)


def test_system_node_at_the_floor_is_used_without_download(env):
    env.versions["node"] = env.mod.NODE_MIN
    assert env.mod.ensure_node() == "node"
    assert env.downloads == []


def test_system_node_below_the_floor_is_not_used(env):
    env.versions["node"] = (20, 19, 1)
    assert env.mod.ensure_node() == str(env.mod.NODE_EXE)
    assert len(env.downloads) == 1
    assert any("too old" in m for m in env.msgs)


def test_old_portable_node_is_replaced(env):
    env.dir.mkdir()
    (env.dir / "node.exe").write_text("old node")
    (env.dir / "leftover.txt").write_text("from the old release")
    env.versions[str(env.mod.NODE_EXE)] = (20, 19, 1)
    assert env.mod.ensure_node() == str(env.mod.NODE_EXE)
    assert (env.dir / "node.exe").read_text() == "new node"
    assert not (env.dir / "leftover.txt").exists()
    assert len(env.downloads) == 1
    assert any("outdated" in m for m in env.msgs)


def test_cached_old_detection_is_ignored(env):
    """A .node_version written by an earlier release (Node 20) must not short circuit the check."""
    env.dir.mkdir()
    (env.dir / "node.exe").write_text("old node")
    env.versions[str(env.mod.NODE_EXE)] = (20, 19, 1)
    env.mod.VERSION_CACHE.write_text(json.dumps({"exe": str(env.mod.NODE_EXE), "ver": [20, 19, 1]}))
    assert env.mod.ensure_node() == str(env.mod.NODE_EXE)
    assert len(env.downloads) == 1


def test_current_portable_node_is_kept(env):
    env.dir.mkdir()
    (env.dir / "node.exe").write_text("current node")
    env.versions[str(env.mod.NODE_EXE)] = _tuple(env.mod.NODE_VERSION)
    assert env.mod.ensure_node() == str(env.mod.NODE_EXE)
    assert env.downloads == []
    assert (env.dir / "node.exe").read_text() == "current node"
