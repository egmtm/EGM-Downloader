"""A yt-dlp-ejs install of the Windows launcher that pip ends with an error is logged, not taken as done.

test_launcher_pairs_ytdlp_ejs.py makes its fake pip raise the exception itself, so the launcher's
check=True was never needed there: without it, a pip that exits with an error (no exception) would pass
as installed and nothing would say the solver script now comes from GitHub. This fake behaves like
subprocess.run: it returns the exit code, and raises only when asked to check it.
"""
import importlib.util
import subprocess
import sys
import types

import pytest

from conftest import ROOT

NAMED = "yt-dlp-ejs==0.8.0; extra == \"default\"\n"


@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_pair_rc", f"{ROOT}/windows/launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls, mod.logged = [], []

    def fake_run(cmd, **kw):
        cmd = list(cmd)
        mod.calls.append(cmd)
        if "-c" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=NAMED, stderr="")
        rc = 1 if "yt-dlp-ejs==0.8.0" in cmd else 0
        if rc and kw.get("check"):
            raise subprocess.CalledProcessError(rc, cmd)
        return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_py_log", lambda m: mod.logged.append(m))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def test_a_pair_install_that_exits_with_an_error_is_logged(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "_meta_version", lambda n: None)
    monkeypatch.setitem(sys.modules, "brotli", None)             # an import fails: a real install
    launcher.ensure_python_deps()                                # never fatal
    assert any("yt-dlp-ejs==0.8.0" in c for c in launcher.calls), "the pair was not attempted, so this checks nothing"
    assert any("yt-dlp-ejs" in m for m in launcher.logged), "a pip that failed was taken as a pair installed"


def test_the_portable_pair_install_that_exits_with_an_error_is_logged(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "PY_DIR", tmp_path / "python")
    launcher.ensure_python_deps_embedded("python.exe")
    assert any("yt-dlp-ejs" in m for m in launcher.logged)
