"""The app and the tools it starts make no contact the user did not ask for.

An independent privacy review found two background contacts that were easy to close:

* Electron downloads Hunspell spellcheck dictionaries from a Google CDN at start on Windows and
  Linux, unless a window turns spellcheck off. The app's inputs already set spellcheck="false",
  so nothing is lost: every window turns it off.
* Deno asks dl.deno.land for a newer Deno once a day (yt-dlp runs it for the YouTube solver) and
  pip asks pypi.org for a newer pip after every install. Both inherit the backend's environment,
  so the backend sets DENO_NO_UPDATE_CHECK and PIP_DISABLE_PIP_VERSION_CHECK when it starts. A
  value the user already set is kept.
* The Windows launcher runs pip itself (first run, repair, a package below its floor) before the
  backend exists, so the environment variable never reaches those runs: its pip command carries
  --disable-pip-version-check.
"""
import importlib.util
import os
import re
import subprocess
import sys
import types

import pytest

from conftest import ROOT, read_source

MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")
APPS = ("app.py", "mac/app.py", "linux/app.py")


def _balanced(src, open_at):
    """The text from the bracket at open_at to its match, skipping strings and comments."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack, i, n = [], open_at, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            i = j + 1
            continue
        if src.startswith("//", i):
            i = src.find("\n", i)
            i = n if i < 0 else i
            continue
        if src.startswith("/*", i):
            i = src.find("*/", i) + 2
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return src[open_at:i + 1]
        i += 1
    raise AssertionError("unbalanced brackets")


def _windows(src):
    return [_balanced(src, m.end() - 1) for m in re.finditer(r"new BrowserWindow\(", src)]


@pytest.mark.parametrize("rel", MAIN_JS)
def test_every_window_turns_the_spellcheck_dictionary_download_off(rel):
    wins = _windows(read_source(rel))
    assert len(wins) == 6, f"{rel}: expected the six windows (splash, main, history, themes, console, subscriptions)"
    for w in wins:
        m = re.search(r"webPreferences\s*:\s*\{", w)
        assert m, f"{rel}: a window has no webPreferences"
        prefs = _balanced(w, m.end() - 1)
        assert re.search(r"\bspellcheck\s*:\s*false\b", prefs), (
            f"{rel}: a window leaves spellcheck on, which downloads a dictionary from Google:\n{prefs}")


def test_the_three_shells_have_the_same_windows_and_the_same_spellcheck_setting():
    counts = {rel: len(re.findall(r"\bspellcheck\s*:\s*false\b", read_source(rel))) for rel in MAIN_JS}
    assert set(counts.values()) == {6}, counts


# ── Deno and pip update checks ────────────────────────────────────────────────────────────────

_PROBE = r"""
import importlib.util, os, sys
path = sys.argv[1]
sys.argv = ["app.py"]
spec = importlib.util.spec_from_file_location("egm_env_probe", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print("DENO=" + repr(os.environ.get("DENO_NO_UPDATE_CHECK")))
print("PIP=" + repr(os.environ.get("PIP_DISABLE_PIP_VERSION_CHECK")))
"""


def _run_probe(rel, tmp_path, **extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("DENO_NO_UPDATE_CHECK", "PIP_DISABLE_PIP_VERSION_CHECK")}
    env.update(HOME=str(tmp_path), XDG_DATA_HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path),
               PYTHONDONTWRITEBYTECODE="1", **extra)
    r = subprocess.run([sys.executable, "-c", _PROBE, os.path.join(ROOT, rel)], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    lines = dict(l.split("=", 1) for l in r.stdout.splitlines() if l.startswith(("DENO=", "PIP=")))
    return lines["DENO"], lines["PIP"]


@pytest.mark.parametrize("rel", APPS)
def test_the_backend_turns_the_deno_and_pip_update_checks_off_for_its_children(rel, tmp_path):
    assert _run_probe(rel, tmp_path) == ("'1'", "'1'")


@pytest.mark.parametrize("rel", APPS)
def test_a_value_the_user_already_set_is_kept(rel, tmp_path):
    assert _run_probe(rel, tmp_path, DENO_NO_UPDATE_CHECK="0", PIP_DISABLE_PIP_VERSION_CHECK="0") == ("'0'", "'0'")


# ── The Windows launcher's own pip runs ───────────────────────────────────────────────────────

@pytest.fixture
def launcher(monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_pip_check", os.path.join(ROOT, "windows", "launch.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    calls = []

    def fake_run(cmd, **kw):
        if "-c" not in cmd:                                    # a pip run; the pairing read of yt-dlp's metadata is not one
            calls.append(list(cmd))
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")   # yt-dlp names no solver package here
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    mod.pip_calls = calls
    return mod


def test_the_installer_launchers_pip_install_does_not_look_for_a_newer_pip(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "_meta_version", lambda n: None)
    monkeypatch.setitem(sys.modules, "brotli", None)             # an import fails: a real install
    launcher.ensure_python_deps()
    (cmd,) = launcher.pip_calls
    assert "install" in cmd and "--disable-pip-version-check" in cmd


def test_the_installer_launchers_pip_upgrade_does_not_look_for_a_newer_pip(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "_meta_version", lambda n: (1, 0, 0) if n == "brotli" else (2026, 10, 26))
    monkeypatch.setattr(launcher, "_modules_present", lambda names: True)
    launcher.ensure_python_deps()
    (cmd,) = launcher.pip_calls
    assert "--retries" in cmd and "--disable-pip-version-check" in cmd


def test_the_portable_launchers_pip_install_does_not_look_for_a_newer_pip(launcher, monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "PY_DIR", tmp_path / "python")   # no site-packages yet: first run
    launcher.ensure_python_deps_embedded("python.exe")
    (cmd,) = launcher.pip_calls
    assert "install" in cmd and "--disable-pip-version-check" in cmd
