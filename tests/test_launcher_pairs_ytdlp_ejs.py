"""The Windows launcher's first pip install leaves yt-dlp and its solver package as a pair.

yt-dlp accepts the solver script package (yt-dlp-ejs) only at its own major.minor version, and it
names that version in its metadata (a == requirement for its default extra). The launcher installed
"yt-dlp-ejs>=0.8.0", which takes the newest release on PyPI: if yt-dlp-ejs published a new minor
before yt-dlp stable caught up, a fresh install got a package yt-dlp refuses and fell back to
downloading the script from GitHub until the person ran Update Plugins (an independent privacy
review, R2).

So after each pip run of the launcher (first run, repair, a package below its floor), the interpreter
that was just used is asked which yt-dlp-ejs version the installed yt-dlp names, and exactly that
version is installed. Same reading as the backend's _ytdlp_ejs_pin. Where yt-dlp names none, or
anything fails, nothing more is done and the app keeps the GitHub fallback: it is never fatal.

Nothing here installs or downloads anything: subprocess.run is replaced by a fake.
"""
import importlib.util
import subprocess
import sys
import types

import pytest

from conftest import ROOT

NAMED = "certifi>=2026.10.19; extra == 'default'\nyt-dlp-ejs==0.8.0; extra == \"default\"\n"
PIP_LIST_PIN = "yt-dlp-ejs>=0.8.0"


@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_ejs_pair", f"{ROOT}/windows/launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.calls = []
    mod.requires = NAMED          # what the installed yt-dlp's metadata says
    mod.fail = {}                 # "read" / "pair" / "main": an exception to raise there
    mod.logged = []

    def fake_run(cmd, **kw):
        cmd = list(cmd)
        mod.calls.append(cmd)
        kind = "read" if "-c" in cmd else "pair" if f"yt-dlp-ejs=={_pinned(cmd)}" in cmd and _pinned(cmd) else "main"
        if kind in mod.fail:
            raise mod.fail[kind]
        return types.SimpleNamespace(returncode=0, stdout=mod.requires if kind == "read" else "", stderr="")

    def _pinned(cmd):
        return next((a.split("==", 1)[1] for a in cmd if a.startswith("yt-dlp-ejs==")), "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_py_log", lambda m: mod.logged.append(m))
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def _first_install(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "_meta_version", lambda n: None)
    monkeypatch.setitem(sys.modules, "brotli", None)             # an import fails: a real install
    launcher.ensure_python_deps()


def _repair(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "_meta_version", lambda n: (1, 0, 0) if n == "brotli" else (2026, 10, 26))
    monkeypatch.setattr(launcher, "_modules_present", lambda names: True)
    launcher.ensure_python_deps()


def _portable(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "PY_DIR", tmp_path / "python")   # no site-packages yet: first run
    launcher.ensure_python_deps_embedded("python.exe")


def _kinds(launcher):
    return ["read" if "-c" in c else "pair" if any(a.startswith("yt-dlp-ejs==") for a in c) else "main"
            for c in launcher.calls]


# ── The pair is installed after the launcher's own pip run ───────────────────────────────────

def test_a_first_install_is_followed_by_the_version_yt_dlp_names(launcher, monkeypatch):
    _first_install(launcher, monkeypatch)
    assert _kinds(launcher) == ["main", "read", "pair"]
    main, read, pair = launcher.calls
    assert PIP_LIST_PIN in main
    assert read[0] == pair[0] == sys.executable, "the pair must be read and installed with the interpreter pip just used"
    assert pair[1:4] == ["-m", "pip", "install"] and "yt-dlp-ejs==0.8.0" in pair
    assert "--disable-pip-version-check" in pair, "every pip run of the launcher keeps pip from asking PyPI for a newer pip"


def test_the_exact_version_yt_dlp_names_is_installed_not_the_newest(launcher, monkeypatch):
    """The point of the fix: a yt-dlp that names 0.8.2 gets 0.8.2, whatever PyPI has newer."""
    launcher.requires = "yt-dlp-ejs==0.8.2; extra == 'default'\n"
    _first_install(launcher, monkeypatch)
    assert "yt-dlp-ejs==0.8.2" in launcher.calls[-1]


def test_the_portable_first_run_does_the_same_with_the_embedded_python(launcher, monkeypatch, tmp_path):
    _portable(launcher, monkeypatch, tmp_path)
    assert _kinds(launcher) == ["main", "read", "pair"]
    assert {c[0] for c in launcher.calls} == {"python.exe"}
    assert "yt-dlp-ejs==0.8.0" in launcher.calls[-1]


def test_a_repair_run_pairs_them_too(launcher, monkeypatch):
    _repair(launcher, monkeypatch)
    assert _kinds(launcher) == ["main", "read", "pair"]


# ── It is never fatal and never guesses ──────────────────────────────────────────────────────

@pytest.mark.parametrize("requires", [
    "", "certifi>=1\n", "yt-dlp-ejs>=0.8.0; extra == 'default'\n", "yt-dlp-ejs; extra == 'default'\n",
    "yt-dlp-ejs==0.8.0; extra == 'pin'\n", "yt-dlp-ejs==0.8.0 && echo x; extra == 'default'\n",
    "yt-dlp-ejs==../x; extra == 'default'\n",
])
def test_a_yt_dlp_that_names_no_plain_version_leaves_the_fallback(launcher, monkeypatch, requires):
    launcher.requires = requires
    _first_install(launcher, monkeypatch)
    assert _kinds(launcher) == ["main", "read"]


@pytest.mark.parametrize("exc", [OSError("no python"), subprocess.TimeoutExpired("python", 30)])
def test_a_failed_read_does_not_stop_the_start(launcher, monkeypatch, exc):
    launcher.fail["read"] = exc
    _first_install(launcher, monkeypatch)
    assert _kinds(launcher) == ["main", "read"]


@pytest.mark.parametrize("exc", [OSError("gone"), subprocess.CalledProcessError(1, "pip"), subprocess.TimeoutExpired("pip", 120)])
def test_a_failed_pair_install_does_not_stop_the_start_and_is_logged(launcher, monkeypatch, exc):
    launcher.fail["pair"] = exc
    _first_install(launcher, monkeypatch)          # must not raise
    assert _kinds(launcher) == ["main", "read", "pair"]
    assert any("yt-dlp-ejs" in m for m in launcher.logged), "a failed pairing is logged, not hidden"


def test_a_failed_main_install_stays_fatal_and_nothing_is_paired(launcher, monkeypatch):
    launcher.fail["main"] = subprocess.CalledProcessError(1, "pip")
    with pytest.raises(subprocess.CalledProcessError):
        _first_install(launcher, monkeypatch)
    assert _kinds(launcher) == ["main"]


# ── Same reading as the backend ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stdout", [
    NAMED, "", "certifi>=1\n", "yt-dlp-ejs==0.9.1; extra == 'default'\n", "yt-dlp-ejs>=0.8.0; extra == 'default'\n",
    "yt-dlp-ejs==0.8.0; extra == 'pin'\n", "yt-dlp-ejs==0.8.0 && echo x; extra == 'default'\n",
    "yt-dlp-ejs==../x; extra == 'default'\n", "  yt-dlp-ejs==0.8.0 ; extra == \"default\"  \n",
])
def test_the_launcher_reads_the_same_pin_as_the_backend(launcher, app_module, monkeypatch, stdout):
    monkeypatch.setattr(app_module, "_run_yt", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=stdout, stderr=""))
    launcher.requires = stdout
    assert launcher._ytdlp_ejs_pin(sys.executable) == app_module._ytdlp_ejs_pin()
