"""Windows launcher: the pythonw.exe hand-over happens before the heavier imports.

The launcher re-runs itself under pythonw.exe so no console window shows. The first
interpreter only hands over, and pythonw.exe imports everything again, so the first one
must not load the heavier standard-library modules before it hands over. The hand-over
block must therefore sit after the Python version gate and above those imports, and its
text must be exactly what it always was (same command line, same EGM_SILENT marker).

windows/launch.py is import safe, so the module is also loaded for real to show that every
name the other launcher tests drive is still there.
"""
import importlib.util
import re
from pathlib import Path

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"

REEXEC_BLOCK = (
    'if sys.platform == "win32" and not os.environ.get("EGM_SILENT"):\n'
    '    pw = Path(sys.executable).with_name("pythonw.exe")\n'
    '    if pw.exists():\n'
    '        subprocess.Popen([str(pw), str(__file__)] + sys.argv[1:],\n'
    '                         env={**os.environ, "EGM_SILENT":"1"})\n'
    '        sys.exit(0)\n'
)

HEAVY_IMPORTS = ("import shutil, zipfile, urllib.request", "import errno, http.client", "import socket, threading")


def test_reexec_block_is_unchanged():
    src = LAUNCH.read_text(encoding="utf-8")
    assert src.count(REEXEC_BLOCK) == 1


def test_reexec_sits_after_the_version_gate_and_before_the_heavy_imports():
    src = LAUNCH.read_text(encoding="utf-8")
    gate, reexec = src.index("if sys.version_info < _PY_MIN:"), src.index(REEXEC_BLOCK)
    assert gate < reexec
    for imp in HEAVY_IMPORTS:
        assert src.count(imp) == 1, imp
        assert reexec < src.index(imp), f"{imp!r} is imported before the pythonw hand-over"


def test_only_what_the_handover_needs_is_imported_before_it():
    src = LAUNCH.read_text(encoding="utf-8")
    head = src[:src.index(REEXEC_BLOCK)]
    imports = re.findall(r"^(?:import|from) .*$", head, re.M)
    assert imports == ["import os, sys, subprocess", "from pathlib import Path"], imports


def test_module_still_exposes_everything_the_other_tests_drive():
    spec = importlib.util.spec_from_file_location("egm_launch_reexec_order_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("shutil", "zipfile", "urllib", "json", "time", "hashlib", "re", "errno", "http", "socket", "threading"):
        assert hasattr(mod, name), name
    assert mod.ROOT == LAUNCH.parent.resolve()
