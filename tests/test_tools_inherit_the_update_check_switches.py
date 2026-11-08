"""DENO_NO_UPDATE_CHECK and PIP_DISABLE_PIP_VERSION_CHECK reach the programs the backend starts.

test_no_background_contacts.py checks that the backend puts both in its own environment. They only
help if the environment the backend hands its children carries them: yt-dlp (which runs Deno) gets
_yt_env(), pip gets _run's. An environment built from a short list of names, or one that drops the
DENO_/PIP_ names, passed that test while Deno and pip went back to looking for their own updates.
"""
import importlib.util
import types
from pathlib import Path

import pytest

from conftest import ROOT

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
SWITCHES = ("DENO_NO_UPDATE_CHECK", "PIP_DISABLE_PIP_VERSION_CHECK")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_switches_" + path.split("/")[0], Path(ROOT) / path)
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
def switched(monkeypatch):
    for k in SWITCHES:
        monkeypatch.setenv(k, "1")


def test_yt_dlp_and_the_deno_it_runs_get_both_switches(backend_module, switched):
    env = backend_module._yt_env()
    assert {k: env.get(k) for k in SWITCHES} == {k: "1" for k in SWITCHES}


def test_pip_and_the_other_tools_get_them_too(backend_module, switched, monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(kw)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(backend_module.subprocess, "run", fake_run)
    backend_module._run("pip", "--version")
    backend_module._run_yt("python", "--version")
    for kw in seen:
        env = kw.get("env")             # None: the child inherits this process's environment, switches included
        if env is not None:
            assert {k: env.get(k) for k in SWITCHES} == {k: "1" for k in SWITCHES}
    assert len(seen) == 2
