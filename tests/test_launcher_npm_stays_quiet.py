"""The portable launcher's npm runs fetch the packages and nothing else.

By default npm also sends the dependency tree to the registry for an audit report, prints a funding
notice and asks the registry whether a newer npm exists: the same kind of contact as pip's version
check, which the launcher already turns off. windows/installer/build-folder.sh passes --no-audit
--no-fund; the launcher's npm runs (first run, Electron update, Reinstall Electron) get the same
through the environment, which reaches every npm command it starts.
"""
import importlib.util
import types

import pytest

from conftest import ROOT


@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_npm_quiet", f"{ROOT}/windows/launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_find_npm", lambda node: ["npm"])
    return mod


def test_npm_is_told_not_to_audit_fund_or_look_for_a_newer_npm(launcher, monkeypatch):
    monkeypatch.setenv("npm_config_audit", "true")       # a user's own setting does not turn it back on
    _, env = launcher._npm_env("node.exe")
    assert env["npm_config_audit"] == "false"
    assert env["npm_config_fund"] == "false"
    assert env["npm_config_update_notifier"] == "false"


@pytest.mark.parametrize("lock", [True, False])
def test_every_npm_run_of_the_electron_install_gets_that_environment(launcher, monkeypatch, tmp_path, lock):
    if lock:
        (tmp_path / "package-lock.json").write_text("{}")
    runs = []

    def fake_run(cmd, **kw):
        runs.append((list(cmd), kw.get("env") or {}))
        return types.SimpleNamespace(returncode=1, stdout=b"EUSAGE", stderr=b"")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher, "_gui_msg", lambda *a, **k: None)
    launcher._npm_install_electron("node.exe", tmp_path)
    assert runs and all(c[0] == "npm" for c, _ in runs)
    for _, env in runs:
        assert env.get("npm_config_audit") == "false" and env.get("npm_config_update_notifier") == "false"
