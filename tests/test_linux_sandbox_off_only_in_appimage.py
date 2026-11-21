"""Chromium's sandbox is switched off on Linux because an AppImage cannot set SUID on chrome-sandbox.
The .deb and the .rpm are installed with root rights, so their sandbox can work. The packed app is the
same folder for all three, so the two places that switch the sandbox off (main.js and the launch
wrapper written by build/after-pack.js) do it only when the AppImage runtime has set APPIMAGE.
The wrapper passes every option on, so "egm-downloader --no-sandbox" from a terminal starts the .deb
or the .rpm without the sandbox on a system where it cannot work."""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "linux" / "electron" / "main.js"
AFTER_PACK = ROOT / "linux" / "electron" / "build" / "after-pack.js"


def test_main_js_switches_the_sandbox_off_only_inside_an_appimage():
    lines = [l.strip() for l in MAIN.read_text(encoding="utf-8").splitlines() if "no-sandbox" in l and not l.strip().startswith("//")]
    assert lines == ["if (process.env.APPIMAGE) app.commandLine.appendSwitch('no-sandbox');"], lines


def test_the_launch_wrapper_adds_no_sandbox_only_inside_an_appimage():
    text = AFTER_PACK.read_text(encoding="utf-8")
    wrapper = text[text.index("const wrapper = `"):text.index("`;", text.index("const wrapper = `"))]
    code = [l.strip() for l in wrapper.splitlines()[1:] if l.strip() and not l.strip().startswith("#")]
    assert code == [
        'HERE="$(dirname "$(readlink -f "$0")")"',
        'if [ -n "$APPIMAGE" ]; then',
        'exec "$HERE/${executableName}-bin" --no-sandbox "$@"',
        'fi',
        'exec "$HERE/${executableName}-bin" "$@"',
    ], code
    assert len(re.findall(r"--no-sandbox", "\n".join(code))) == 1


def _wrapper_run(tmp_path, args, appimage):
    """Write the wrapper as after-pack.js does, beside a stand-in binary that prints its arguments."""
    text = AFTER_PACK.read_text(encoding="utf-8")
    start = text.index("const wrapper = `") + len("const wrapper = `")
    body = text[start:text.index("`;", start)].replace("${executableName}", "egm-downloader")
    wrapper, binary = tmp_path / "egm-downloader", tmp_path / "egm-downloader-bin"
    wrapper.write_text(body, encoding="utf-8")
    binary.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n', encoding="utf-8")
    wrapper.chmod(0o755)
    binary.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "APPIMAGE"}
    if appimage:
        env["APPIMAGE"] = "/tmp/EGM Downloader.AppImage"
    r = subprocess.run([str(wrapper), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


@pytest.mark.parametrize("args", [[], ["a file.mp4", "--x=1"]])
def test_the_packages_start_without_no_sandbox_and_keep_every_option(tmp_path, args):
    assert _wrapper_run(tmp_path, args, appimage=False) == args


@pytest.mark.parametrize("args", [[], ["a file.mp4", "--x=1"]])
def test_the_appimage_starts_with_no_sandbox_first_and_keeps_every_option(tmp_path, args):
    assert _wrapper_run(tmp_path, args, appimage=True) == ["--no-sandbox", *args]


def test_no_sandbox_typed_in_a_terminal_reaches_the_installed_app(tmp_path):
    """The way out where the sandbox cannot work: linux/INSTRUCTIONS.txt names this command."""
    assert _wrapper_run(tmp_path, ["--no-sandbox"], appimage=False) == ["--no-sandbox"]
    assert "egm-downloader --no-sandbox" in (ROOT / "linux" / "INSTRUCTIONS.txt").read_text(encoding="utf-8")
