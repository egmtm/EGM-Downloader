"""pip writes console scripts (yt-dlp, flask, the mutagen tools and others) into the bundled Python's
bin/ folder, and each one starts with the build machine's folder. linux/BUILD.sh and mac/BUILD.sh
remove exactly those scripts, so no shipped file carries the build folder, while python3, pip's own
launchers and every other file stay. The app runs "python -m yt_dlp" and Update Plugins runs
"python -m pip", so nothing needs the removed scripts."""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = {"linux": ROOT / "linux" / "BUILD.sh", "mac": ROOT / "mac" / "BUILD.sh"}
BLOCK = re.compile(r'^PY_REAL=.*?^echo "   ✓ \$REMOVED console scripts[^\n]*\n', re.S | re.M)


def _block(name):
    found = BLOCK.findall(SCRIPTS[name].read_text(encoding="utf-8"))
    assert len(found) == 1, f"{name}/BUILD.sh must hold the removal block once"
    return found[0]


def test_linux_and_mac_remove_the_scripts_the_same_way():
    assert _block("linux") == _block("mac")


@pytest.mark.parametrize("name", ["linux", "mac"])
def test_the_scripts_go_after_the_last_pip_install_and_before_the_app_is_built(name):
    text = SCRIPTS[name].read_text(encoding="utf-8")
    at = text.index(_block(name))
    assert text.rindex("-m pip install", 0, at) < at
    assert "-m pip install" not in text[at:]
    assert at < text.index("# ── Build Electron")


def _run(python_dir):
    script = 'set -e\nPYTHON_DIR="$1"\n' + _block("linux")
    return subprocess.run(["bash", "-c", script, "bash", str(python_dir)],
                          capture_output=True, text=True, check=True)


def _make_bin(real_dir, shebang_dir):
    b = real_dir / "bin"
    b.mkdir(parents=True)
    (b / "python3.11").write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 64)
    os.symlink("python3.11", b / "python3")
    (b / "pip3").write_text("#!/bin/sh\n'''exec' \"$(dirname -- \"$(realpath -- \"$0\")\")\"/'python3.11' \"$0\" \"$@\"\n' '''\n")
    (b / "yt-dlp").write_text(f"#!{shebang_dir}/bin/python3\nimport sys\n")
    (b / "flask").write_text(f"#!{shebang_dir}/bin/python3.11\nimport sys\n")
    (b / "other").write_text("#!/usr/bin/env python3\nprint(1)\n")
    (b / "notes").mkdir()
    return b


def test_only_the_scripts_that_name_the_build_folder_are_removed(tmp_path):
    py = tmp_path / "python"
    b = _make_bin(py, py)
    out = _run(py)
    assert sorted(p.name for p in b.iterdir()) == ["notes", "other", "pip3", "python3", "python3.11"]
    assert "2 console scripts" in out.stdout


def test_a_build_folder_reached_through_a_symlink_is_matched_too(tmp_path):
    real = tmp_path / "real" / "python"
    b = _make_bin(real, real)
    (tmp_path / "link").symlink_to(tmp_path / "real")
    _run(tmp_path / "link" / "python")
    assert not (b / "yt-dlp").exists() and not (b / "flask").exists()
    assert (b / "python3.11").exists() and (b / "pip3").exists()
