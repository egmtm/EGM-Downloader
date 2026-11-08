"""Every pip the backends and the Windows launcher run is --isolated, and still skips its version check.

Without --isolated, PIP_* variables and the person's own pip.ini (an index, a proxy, a target, a
"user" install) change what Update Plugins and the launcher install. With it pip ignores both. It
ignores the backends' own PIP_DISABLE_PIP_VERSION_CHECK too, which is how the backends kept pip from
asking pypi.org about a newer pip: so each backend pip run now says --disable-pip-version-check
itself, as the launcher's always did. Checked with pip 25.3: with --isolated and only the variable,
the check is on again.

* A scan of the three backends and windows/launch.py.
* The commands Update Plugins builds, captured, then parsed by the pip that is installed here: pip
  accepts --isolated where it stands (after "install") and turns isolated mode on.
* The launcher's pip runs, captured (first install, repair, the pairing run)."""
import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from conftest import ROOT, read_source
from test_launcher_pairs_ytdlp_ejs import _first_install, _repair, launcher  # noqa: F401  (launcher is a fixture)

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
FLAGS = ("--isolated", "--disable-pip-version-check")


def _pip_calls(src):
    """(line, constants, call) for every call or list with "-m", "pip" in it."""
    tree = ast.parse(src)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    out = []
    for node in ast.walk(tree):
        elts = node.args if isinstance(node, ast.Call) else node.elts if isinstance(node, ast.List) else None
        if not elts:
            continue
        vals = [e.value if isinstance(e, ast.Constant) else None for e in elts]
        if any(vals[i] == "-m" and vals[i + 1] == "pip" for i in range(len(vals) - 1)):
            out.append((node.lineno, vals, parents.get(node)))
    return out


@pytest.mark.parametrize("rel", APP_FILES)
def test_every_backend_pip_run_is_isolated_and_skips_the_version_check(rel):
    calls = _pip_calls(read_source(rel))
    assert len(calls) >= 5, f"{rel}: only {len(calls)} pip runs found"
    for line, vals, _ in calls:
        for flag in FLAGS:
            assert flag in vals, f"{rel}:{line} runs pip without {flag}"


def test_every_launcher_pip_run_is_isolated():
    """The two package lists go through _pip_install, which adds both flags (checked below)."""
    calls = _pip_calls(read_source("windows/launch.py"))
    assert len(calls) >= 4
    for line, vals, parent in calls:
        through_pip_install = isinstance(parent, ast.Call) and getattr(parent.func, "id", None) == "_pip_install"
        assert "--isolated" in vals or through_pip_install, f"windows/launch.py:{line} runs pip without --isolated"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_pipiso_" + path.split("/")[0], Path(ROOT) / path)
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


def _update_plugins_pips(m, tmp_path, monkeypatch):
    pips = []

    def run(*cmd, **kw):
        cmd = [str(c) for c in cmd]
        if "pip" in cmd:
            pips.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(m, "_run", run)
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_get_latest_ytdlp_version", lambda *a, **k: "2026.10.26")
    monkeypatch.setattr(m, "_get_ytdlp_version", lambda *a, **k: "2026.10.26")
    monkeypatch.setattr(m, "_get_optlibs_versions", lambda *a, **k: {})
    monkeypatch.setattr(m, "_load_settings", lambda *a, **k: {"yt_dlp_channel": "stable"})
    monkeypatch.setattr(m, "_ytdlp_ejs_pin", lambda: "0.8.0")
    if hasattr(m, "PACKAGES_DIR"):
        (tmp_path / "packages").mkdir()
        monkeypatch.setattr(m, "PACKAGES_DIR", tmp_path / "packages")
    if "do_mutagen" in m._run_update.__code__.co_varnames:
        m._run_update(True, False, True, True)
    else:
        m._run_update(True, False, True)
    return pips


def test_the_pip_runs_update_plugins_builds_are_isolated_for_pip_itself(backend_module, tmp_path, monkeypatch):
    from pip._internal.cli.main_parser import parse_command
    from pip._internal.commands import create_command
    pips = _update_plugins_pips(backend_module, tmp_path, monkeypatch)
    assert len(pips) >= 3, pips                                # yt-dlp, its solver, the libraries
    for cmd in pips:
        args = cmd[cmd.index("pip") + 1:]
        name, cmd_args = parse_command(args)
        opts, _ = create_command(name, isolated=("--isolated" in cmd_args)).parse_args(cmd_args)
        assert opts.isolated_mode is True, cmd
        assert opts.disable_pip_version_check, cmd


def test_the_launchers_pip_runs_are_isolated(launcher, monkeypatch):
    _first_install(launcher, monkeypatch)
    _repair(launcher, monkeypatch)
    pips = [c for c in launcher.calls if "pip" in c]
    assert len(pips) >= 4, launcher.calls                     # two installs, two pairing runs
    for cmd in pips:
        for flag in FLAGS:
            assert flag in cmd, cmd
