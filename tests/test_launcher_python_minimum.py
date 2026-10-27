"""Windows launcher: the Python the launcher accepts, per edition.

yt-dlp dropped Python 3.10 (its newest builds say Requires-Python >=3.11). The installer
edition runs the app on the user's own Python, so a 3.10 machine would quietly stop getting
yt-dlp updates; its minimum is therefore 3.11. The portable edition only uses the system
Python to bootstrap and then runs on its own embedded Python 3.12, so it keeps accepting
3.10 (nothing would be gained by turning those users away).

The gate in windows/launch.py is run here for real, with a stand in for `sys` and `ctypes`
so no dialog can open on any operating system.
"""
import io
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "windows"
LAUNCH = WINDOWS / "launch.py"


def _gate_source():
    """The gate block of launch.py: the `_PY_MIN` line through the `sys.exit(1)` that ends it."""
    src = LAUNCH.read_text(encoding="utf-8")
    start = src.index("_PY_MIN = ")
    end_marker = "    sys.exit(1)\n"
    return src[start:src.index(end_marker, start) + len(end_marker)]


def _run_gate(tmp_path, monkeypatch, version, portable):
    """Run the gate as if launch.py sat in `tmp_path` on a Python of `version`.
    Returns (exit_code or None, dialog_text or None)."""
    (tmp_path / "launch.py").write_text("", encoding="utf-8")
    if portable:
        (tmp_path / ".portable").write_text("marker", encoding="utf-8")
    dialogs = []
    fake_ctypes = types.SimpleNamespace(
        windll=types.SimpleNamespace(
            user32=types.SimpleNamespace(MessageBoxW=lambda _h, text, *_a: dialogs.append(text))
        )
    )
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    def fake_exit(code=0):
        raise SystemExit(code)

    fake_sys = types.SimpleNamespace(
        version_info=version + ("final", 0), stderr=io.StringIO(), exit=fake_exit
    )
    # No newer Python on this PC: the hand over (tests/test_launcher_newer_python_handover.py) finds nothing,
    # so the gate ends in the dialog, as it always did.
    namespace = {"__file__": str(tmp_path / "launch.py"), "sys": fake_sys, "Path": Path,
                 "os": os, "subprocess": subprocess, "_find_newer_python": lambda minimum: None}
    try:
        exec(compile(_gate_source(), "launch_gate", "exec"), namespace)
    except SystemExit as stop:
        return stop.code, (dialogs[0] if dialogs else fake_sys.stderr.getvalue())
    return None, None


@pytest.mark.parametrize("version", [(3, 9, 13), (3, 10, 0), (3, 10, 11)])
def test_installer_edition_turns_away_python_below_3_11(tmp_path, monkeypatch, version):
    code, text = _run_gate(tmp_path, monkeypatch, version, portable=False)
    assert code == 1
    assert "needs Python 3.11 or newer" in text
    assert "Install Python 3.11+" in text
    assert "Detected: Python %d.%d.%d" % version in text


@pytest.mark.parametrize("version", [(3, 11, 0), (3, 11, 9), (3, 12, 10), (3, 13, 1)])
def test_installer_edition_accepts_3_11_and_newer(tmp_path, monkeypatch, version):
    assert _run_gate(tmp_path, monkeypatch, version, portable=False) == (None, None)


@pytest.mark.parametrize("version", [(3, 10, 0), (3, 10, 11), (3, 11, 9), (3, 12, 10)])
def test_portable_edition_still_bootstraps_from_3_10(tmp_path, monkeypatch, version):
    assert _run_gate(tmp_path, monkeypatch, version, portable=True) == (None, None)


@pytest.mark.parametrize("version", [(3, 9, 13), (3, 8, 10)])
def test_portable_edition_still_needs_3_10(tmp_path, monkeypatch, version):
    code, text = _run_gate(tmp_path, monkeypatch, version, portable=True)
    assert code == 1
    assert "needs Python 3.10 or newer" in text


def test_every_place_that_states_the_minimum_agrees_with_the_gate():
    """The words users read must match what the launcher enforces. The installer says 3.11
    (instructions file, the installer's welcome page in all ten languages, the launcher's
    "no Python found" box and the Windows shell's own "Python not found" message); the
    portable instructions keep 3.10 for the first launch."""
    instructions = (WINDOWS / "instructions.txt").read_text(encoding="utf-8")
    assert "Python 3.11 or newer" in instructions and "3.10" not in instructions

    nsi_lines = [
        line for line in (WINDOWS / "setup.nsi").read_text(encoding="utf-8").splitlines()
        if line.startswith("LangString EGM_WELCOME_TEXT ")
    ]
    assert len(nsi_lines) == 10, "expected one welcome text per installer language"
    for line in nsi_lines:
        assert "3.11" in line and "3.10" not in line, line[:90]

    launcher_c = (WINDOWS / "launcher.c").read_text(encoding="utf-8")
    assert "Python 3.11+ is required" in launcher_c and "3.10" not in launcher_c

    main_js = (WINDOWS / "electron" / "main.js").read_text(encoding="utf-8")
    assert "'Python 3.11+ is required." in main_js and "Python 3.10" not in main_js

    build_sh = (WINDOWS / "BUILD.sh").read_text(encoding="utf-8")
    assert "Python 3.10 or newer — for the FIRST launch only" in build_sh


@pytest.mark.parametrize("platform", ["mac", "linux"])
def test_mac_and_linux_fallback_message_names_the_same_minimum(platform):
    """Mac and Linux ship their own Python 3.11; the message shown when that bundled copy
    is missing and no system Python is found must not promise that 3.10 would do."""
    main_js = (ROOT / platform / "electron" / "main.js").read_text(encoding="utf-8")
    assert "no system Python 3.11+ available" in main_js and "Python 3.10" not in main_js
