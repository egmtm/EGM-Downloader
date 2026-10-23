"""Windows launcher, portable edition: attrib +h is not spawned for a file that is hidden.

The portable edition hides its internal files with `attrib +h` at the end of every start.
Once a file is hidden, attrib would change nothing, so the launcher reads the attribute
first and skips the process spawn. On any doubt (no attribute support, as on Linux, or a
path that cannot be read) it runs attrib exactly as before, so the end state is the same.

windows/launch.py is import safe, so these tests drive the real _hidden().
"""
import importlib.util
import os
import stat
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


def _load():
    spec = importlib.util.spec_from_file_location("egm_launch_portable_hide_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _St:
    def __init__(self, attrs=None):
        if attrs is not None:
            self.st_file_attributes = attrs


def test_hidden_is_true_only_for_the_hidden_attribute(monkeypatch, tmp_path):
    mod = _load()
    monkeypatch.setattr(os, "stat", lambda p, **kw: _St(stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_DIRECTORY))
    assert mod._hidden(tmp_path) is True
    monkeypatch.setattr(os, "stat", lambda p, **kw: _St(stat.FILE_ATTRIBUTE_HIDDEN))
    assert mod._hidden(tmp_path) is True
    monkeypatch.setattr(os, "stat", lambda p, **kw: _St(stat.FILE_ATTRIBUTE_DIRECTORY))
    assert mod._hidden(tmp_path) is False
    monkeypatch.setattr(os, "stat", lambda p, **kw: _St(0))
    assert mod._hidden(tmp_path) is False


def test_hidden_is_false_on_any_doubt(monkeypatch, tmp_path):
    """No attribute support (the stat result has no st_file_attributes, as on Linux), or a
    path that cannot be read: attrib runs as before."""
    mod = _load()
    assert mod._hidden(tmp_path) is False                   # the real os.stat on this platform
    monkeypatch.setattr(os, "stat", lambda p, **kw: _St(None))
    assert mod._hidden(tmp_path) is False
    def boom(p, **kw): raise PermissionError(13, "denied")
    monkeypatch.setattr(os, "stat", boom)
    assert mod._hidden(tmp_path) is False
    assert mod._hidden(tmp_path / "missing") is False


def test_hide_loop_checks_the_attribute_before_spawning_attrib():
    src = LAUNCH.read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    block = main[main.index("_to_hide = ["):]
    check, call = block.index("if _hidden(_p):"), block.index('["attrib", "+h", str(_p)]')
    assert check < call
    assert "continue" in block[check:call]
    assert block.count('["attrib", "+h", str(_p)]') == 1   # the same single attrib call as before
    assert "creationflags=0x08000000, check=False" in block  # spawned the same way as before


@pytest.mark.parametrize("name", ["app.py", "launch.bat", "launch.py", ".portable", "rcedit-x64.exe", "electron",
                                  "static", "templates", "python", "data", "ffmpeg_bin", "node_bin", "runtime",
                                  "electron-data"])
def test_hide_list_is_unchanged(name):
    src = LAUNCH.read_text(encoding="utf-8")
    start = src.index("_to_hide = [")
    block = src[start:src.index("]", start)]
    assert f'"{name}"' in block
