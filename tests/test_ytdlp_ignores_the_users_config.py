"""Every yt-dlp command line the backends build carries --ignore-config.

yt-dlp runs through its command line on all three platforms, and on its own it reads the person's
configuration files (%APPDATA%\\yt-dlp\\config.txt, ~/.config/yt-dlp/config, a yt-dlp.conf beside it
...). A proxy, an output template or a format set there for the person's own use would change what the
app does. --ignore-config makes yt-dlp read none of them.

* A scan: every "-m", "yt_dlp" in the three backends is followed by "--ignore-config".
* Commands built for real by the backends' own functions.
* The real yt-dlp, with a user config that holds an unknown option: without the flag it refuses to
  start, with the command the backend builds (asked to list its extractors) it runs (skipped where
  yt-dlp is not installed)."""
import ast
import importlib.util
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from conftest import ROOT, read_source

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")


def _yt_dlp_calls(src):
    """Every argument list in src with "-m", "yt_dlp" in it, as lists of the constants (None elsewhere)."""
    found = []
    for node in ast.walk(ast.parse(src)):
        elts = node.args if isinstance(node, ast.Call) else node.elts if isinstance(node, ast.List) else None
        if not elts:
            continue
        vals = [e.value if isinstance(e, ast.Constant) else None for e in elts]
        for i in range(len(vals) - 1):
            if vals[i] == "-m" and vals[i + 1] == "yt_dlp":
                found.append((node.lineno, vals[i + 2] if i + 2 < len(vals) else None))
    return found


@pytest.mark.parametrize("rel", APP_FILES)
def test_every_yt_dlp_command_line_ignores_the_users_config(rel):
    calls = _yt_dlp_calls(read_source(rel))
    assert len(calls) >= 5, f"{rel}: only {len(calls)} yt-dlp command lines found"
    missing = [line for line, nxt in calls if nxt != "--ignore-config"]
    assert not missing, f"{rel}: yt-dlp started without --ignore-config at lines {missing}"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_ignorecfg_" + path.split("/")[0], Path(ROOT) / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend_module(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


@pytest.fixture
def built(backend_module, monkeypatch):
    """The commands the backend's own helpers build, captured instead of run."""
    cmds = []

    def capture(*cmd, **kw):
        cmds.append([str(c) for c in cmd])
        return types.SimpleNamespace(returncode=0, stdout="2026.10.26\n", stderr="")

    monkeypatch.setattr(backend_module, "_run_yt", capture)
    monkeypatch.setattr(backend_module, "_run", capture)
    backend_module._ytdlp("--list-extractors")
    backend_module._get_ytdlp_version()
    return cmds


def test_the_commands_the_backend_builds_carry_it(built):
    yt = [c for c in built if c[1:3] == ["-m", "yt_dlp"]]
    assert len(yt) == 2, built
    for cmd in yt:
        assert cmd[3] == "--ignore-config", cmd


def _have_yt_dlp():
    return subprocess.run([sys.executable, "-c", "import yt_dlp"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _have_yt_dlp(), reason="yt-dlp is not installed")
def test_a_users_config_does_not_reach_the_apps_yt_dlp(built, tmp_path):
    (tmp_path / "yt-dlp").mkdir()
    (tmp_path / "yt-dlp" / "config").write_text("--proxy http://127.0.0.1:9\n--this-option-does-not-exist\n", encoding="utf-8")
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path), HOME=str(tmp_path), APPDATA=str(tmp_path))
    # --version answers before any config is read; --list-extractors reads it first
    plain = subprocess.run([sys.executable, "-m", "yt_dlp", "--list-extractors"], capture_output=True, text=True, env=env, timeout=120)
    assert plain.returncode != 0 and "this-option-does-not-exist" in plain.stderr, "the user config is not read at all here"
    cmd = next(c for c in built if c[1:3] == ["-m", "yt_dlp"])
    app = subprocess.run([sys.executable] + cmd[1:], capture_output=True, text=True, env=env, timeout=120)
    assert app.returncode == 0, app.stderr[-800:]
