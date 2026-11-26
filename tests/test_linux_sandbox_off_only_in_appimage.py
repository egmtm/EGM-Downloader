"""Chromium's sandbox is switched off on Linux because an AppImage cannot set SUID on chrome-sandbox.
The .deb and the .rpm are installed with root rights, so their sandbox can work. The packed app is the
same folder for all three, so the two places that switch the sandbox off (main.js and the launch
wrapper written by build/after-pack.js) do it only inside an AppImage: its runtime sets APPIMAGE and
APPDIR (the AppImage's own folder), and the app's binary is in APPDIR, both paths resolved. A stray
APPIMAGE or APPDIR inherited from another AppImage leaves the sandbox on in the .deb and the .rpm.
The wrapper passes every option on, so "egm-downloader --no-sandbox" from a terminal starts the .deb
or the .rpm without the sandbox on a system where it cannot work."""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "linux" / "electron" / "main.js"
AFTER_PACK = ROOT / "linux" / "electron" / "build" / "after-pack.js"


def _code(text):
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(("//", "#"))]


# ── main.js ──────────────────────────────────────────────────────────────────────────────────

def test_main_js_switches_the_sandbox_off_only_through_the_appimage_check():
    lines = [l for l in _code(MAIN.read_text(encoding="utf-8")) if "no-sandbox" in l]
    assert lines == ["if (insideAppImage(process.env, process.execPath)) app.commandLine.appendSwitch('no-sandbox');"], lines


def _inside(env, exec_path):
    """main.js's own insideAppImage, run under node."""
    src = MAIN.read_text(encoding="utf-8")
    start = src.index("function insideAppImage(")
    end = src.index("\n}\n", start) + 3
    script = ("const fs = require('fs'); const path = require('path');\n" + src[start:end] +
              f"console.log(JSON.stringify(insideAppImage({json.dumps(env)}, {json.dumps(str(exec_path))})));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def _app(tmp_path):
    appdir = tmp_path / "mount"
    appdir.mkdir()
    (appdir / "egm-downloader-bin").write_text("", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    return appdir, other


def test_main_js_appimage_and_its_own_appdir_turn_the_sandbox_off(tmp_path):
    appdir, _ = _app(tmp_path)
    assert _inside({"APPIMAGE": "/x.AppImage", "APPDIR": str(appdir)}, appdir / "egm-downloader-bin") is True


@pytest.mark.parametrize("env", [
    {}, {"APPIMAGE": "/x.AppImage"}, {"APPDIR": "MOUNT"}, {"APPIMAGE": "", "APPDIR": "MOUNT"},
    {"APPIMAGE": "/x.AppImage", "APPDIR": "OTHER"}, {"APPIMAGE": "/x.AppImage", "APPDIR": "PARENT"},
    {"APPIMAGE": "/x.AppImage", "APPDIR": "/no/such/folder"}, {"APPIMAGE": "/x.AppImage", "APPDIR": ""},
])
def test_main_js_keeps_the_sandbox_on_without_a_matching_appdir(tmp_path, env):
    appdir, other = _app(tmp_path)
    names = {"MOUNT": str(appdir), "OTHER": str(other), "PARENT": str(tmp_path)}
    env = {k: names.get(v, v) for k, v in env.items()}
    assert _inside(env, appdir / "egm-downloader-bin") is False


def test_main_js_matches_through_symlinks(tmp_path):
    appdir, _ = _app(tmp_path)
    (tmp_path / "link").symlink_to(appdir)
    env = {"APPIMAGE": "/x.AppImage", "APPDIR": str(tmp_path / "link")}
    assert _inside(env, appdir / "egm-downloader-bin") is True
    assert _inside({"APPIMAGE": "/x.AppImage", "APPDIR": str(appdir)}, tmp_path / "link" / "egm-downloader-bin") is True


# ── the launch wrapper ───────────────────────────────────────────────────────────────────────

def _wrapper_body():
    text = AFTER_PACK.read_text(encoding="utf-8")
    start = text.index("const wrapper = `") + len("const wrapper = `")
    return text[start:text.index("`;", start)].replace("${executableName}", "egm-downloader")


def test_the_wrapper_adds_no_sandbox_only_through_the_appimage_check():
    code = _code(_wrapper_body())
    assert code == [
        'HERE="$(dirname "$(readlink -f "$0")")"',
        'if [ -n "$APPIMAGE" ] && [ "$HERE" = "$(readlink -f "$APPDIR")" ]; then',
        'exec "$HERE/egm-downloader-bin" --no-sandbox "$@"',
        'fi',
        'exec "$HERE/egm-downloader-bin" "$@"',
    ], code


def _wrapper_run(tmp_path, args, env_extra, via=None):
    """Write the wrapper as after-pack.js does into a folder, beside a stand-in binary that prints its
    arguments. via: run it through this symlink instead."""
    appdir = tmp_path / "mount"
    appdir.mkdir(exist_ok=True)
    wrapper, binary = appdir / "egm-downloader", appdir / "egm-downloader-bin"
    wrapper.write_text(_wrapper_body(), encoding="utf-8")
    binary.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n', encoding="utf-8")
    wrapper.chmod(0o755)
    binary.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in ("APPIMAGE", "APPDIR")}
    env.update(env_extra)
    r = subprocess.run([str(via or wrapper), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


ARGS = [[], ["a file.mp4", "--x=1"], ["--no-sandbox"]]


@pytest.mark.parametrize("args", ARGS)
def test_the_packages_start_without_no_sandbox_and_keep_every_option(tmp_path, args):
    assert _wrapper_run(tmp_path, args, {}) == args


@pytest.mark.parametrize("args", ARGS)
def test_the_appimage_starts_with_no_sandbox_first_and_keeps_every_option(tmp_path, args):
    env = {"APPIMAGE": "/x.AppImage", "APPDIR": str(tmp_path / "mount")}
    assert _wrapper_run(tmp_path, args, env) == ["--no-sandbox", *args]


@pytest.mark.parametrize("env", [
    {"APPIMAGE": "/x.AppImage"}, {"APPDIR": "MOUNT"}, {"APPIMAGE": "", "APPDIR": "MOUNT"},
    {"APPIMAGE": "/x.AppImage", "APPDIR": "OTHER"}, {"APPIMAGE": "/x.AppImage", "APPDIR": "PARENT"},
    {"APPIMAGE": "/x.AppImage", "APPDIR": "/no/such/folder"}, {"APPIMAGE": "/x.AppImage", "APPDIR": ""},
])
def test_a_stray_appimage_or_appdir_keeps_the_sandbox_on(tmp_path, env):
    other = tmp_path / "other"
    other.mkdir()
    names = {"MOUNT": str(tmp_path / "mount"), "OTHER": str(other), "PARENT": str(tmp_path)}
    env = {k: names.get(v, v) for k, v in env.items()}
    assert _wrapper_run(tmp_path, ["a"], env) == ["a"]


def test_the_wrapper_matches_through_symlinks(tmp_path):
    (tmp_path / "mount").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "mount")
    env = {"APPIMAGE": "/x.AppImage", "APPDIR": str(tmp_path / "link")}
    assert _wrapper_run(tmp_path, ["a"], env) == ["--no-sandbox", "a"]
    env = {"APPIMAGE": "/x.AppImage", "APPDIR": str(tmp_path / "mount")}
    assert _wrapper_run(tmp_path, ["a"], env, via=tmp_path / "link" / "egm-downloader") == ["--no-sandbox", "a"]


def test_no_sandbox_typed_in_a_terminal_reaches_the_installed_app(tmp_path):
    """The way out where the sandbox cannot work: linux/INSTRUCTIONS.txt names this command."""
    assert _wrapper_run(tmp_path, ["--no-sandbox"], {}) == ["--no-sandbox"]
    assert "egm-downloader --no-sandbox" in (ROOT / "linux" / "INSTRUCTIONS.txt").read_text(encoding="utf-8")
