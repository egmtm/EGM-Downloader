"""
Windows launcher: the Node.js it uses must be new enough for the Electron it installs.

Electron 45's installer (@electron/get 5) needs Node 22.12 or newer, and Node 20 is past
end of life. The launcher therefore refuses anything older (a system Node, a cached
detection, or the portable node_bin from an earlier release) and downloads the pinned
version instead. windows/launch.py is import safe, so these tests drive the real
ensure_node() with a fake node version probe and a fake download. Nothing is downloaded.

The zip it does download is checked against a SHA-256 pinned in the launcher (the pin ships
inside the signed installer), not against a manifest fetched at run time.
"""
import hashlib
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


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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
    e.real_verify = mod._verify_node_zip    # the fixture patches it out below; the pin tests use the real one

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


# ── the downloaded zip is checked against a hash built into the launcher ──────────────

def test_node_zip_is_pinned_for_the_version_it_downloads(env):
    """Bumping NODE_VERSION without adding its hash would make every fresh install fail closed."""
    pin = env.mod.NODE_ZIP_SHA256.get(env.mod.NODE_VERSION)
    assert pin and re.fullmatch(r"[0-9a-f]{64}", pin), (env.mod.NODE_VERSION, pin)


def test_pinned_zip_is_accepted_and_nothing_is_fetched(env, tmp_path, monkeypatch):
    zip_file = tmp_path / "node.zip"
    zip_file.write_bytes(b"the real zip")
    monkeypatch.setattr(env.mod, "NODE_ZIP_SHA256", {env.mod.NODE_VERSION: _sha(b"the real zip")})

    def no_network(*a, **k):
        raise AssertionError("verifying the Node zip must not touch the network")

    monkeypatch.setattr(env.mod.urllib.request, "urlopen", no_network)
    assert env.real_verify(zip_file) is True


@pytest.mark.parametrize("pin", [None, "", "f" * 63, "g" * 64], ids=["no entry", "empty", "too short", "not hex"])
def test_a_missing_or_malformed_pin_refuses_the_zip(env, tmp_path, monkeypatch, pin):
    zip_file = tmp_path / "node.zip"
    zip_file.write_bytes(b"anything")
    table = {} if pin is None else {env.mod.NODE_VERSION: pin}
    monkeypatch.setattr(env.mod, "NODE_ZIP_SHA256", table)
    assert env.real_verify(zip_file) is False


def test_a_zip_that_differs_by_one_byte_is_refused(env, tmp_path, monkeypatch):
    monkeypatch.setattr(env.mod, "NODE_ZIP_SHA256", {env.mod.NODE_VERSION: _sha(b"the real zip")})
    zip_file = tmp_path / "node.zip"
    zip_file.write_bytes(b"the real zip!")
    assert env.real_verify(zip_file) is False


def test_an_unreadable_zip_is_refused(env, tmp_path):
    assert env.real_verify(tmp_path / "missing.zip") is False


def test_a_tampered_download_is_not_extracted(env, monkeypatch):
    """ensure_node() uses the real check: a zip that is not the pinned one stops the install."""
    monkeypatch.setattr(env.mod, "_verify_node_zip", env.real_verify)
    with pytest.raises(SystemExit):
        env.mod.ensure_node()
    assert any("checksum verification failed" in m for m in env.msgs)
    assert not (env.dir / "node.exe").exists()
    assert not (env.dir / "node_tmp.zip").exists()


def test_the_pinned_download_is_extracted(env, monkeypatch):
    monkeypatch.setattr(env.mod, "_verify_node_zip", env.real_verify)
    plain_download = env.mod.urllib.request.urlretrieve      # the fixture's fake download

    def download_then_pin(url, dest, reporthook=None):
        plain_download(url, dest, reporthook)
        monkeypatch.setattr(env.mod, "NODE_ZIP_SHA256",
                            {env.mod.NODE_VERSION: _sha(Path(dest).read_bytes())})

    monkeypatch.setattr(env.mod.urllib.request, "urlretrieve", download_then_pin)
    assert env.mod.ensure_node() == str(env.mod.NODE_EXE)
    assert (env.dir / "node.exe").read_text() == "new node"
