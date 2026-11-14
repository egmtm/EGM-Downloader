"""Every pip the backends run gets _pip_env(): none of the person's PIP_ variables, no pip config
file, no pip cache.

--isolated covers the pip the backend starts. A source build (the yt-dlp nightly is a source
archive) makes that pip start a second pip for the build requirements, and the second one gets
neither --isolated nor --no-cache-dir: it read the person's PIP_ variables, pip config files and
pip cache. It inherits the environment, so a clean environment closes that.

* A scan: every backend pip run passes env=_pip_env(), and the helper is the same on the three.
* The runs Update Plugins builds, captured: each gets an environment without the person's PIP_
  variables.
* A real pip, offline: a local source tree whose build needs one requirement from a local folder.
  A setting of the person's that the second pip obeys (require-hashes) fails the build with the
  person's environment as it is, and does not reach it with _pip_env()."""
import ast
import os
import subprocess
import sys
import zipfile

import pytest

from conftest import read_source
from test_pip_runs_isolated import APP_FILES, _pip_calls, _update_plugins_pips, backend_module  # noqa: F401


def _helper_source(rel):
    src = read_source(rel)
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_pip_env")
    return ast.get_source_segment(src, fn)


def test_the_helper_is_the_same_on_the_three_platforms():
    assert _helper_source("mac/app.py") == _helper_source("app.py") == _helper_source("linux/app.py")


@pytest.mark.parametrize("rel", APP_FILES)
def test_every_backend_pip_run_passes_the_clean_environment(rel):
    calls = _pip_calls(read_source(rel))
    assert len(calls) >= 5, f"{rel}: only {len(calls)} pip runs found"
    for line, _, _ in calls:
        node = next(n for n in ast.walk(ast.parse(read_source(rel)))
                    if isinstance(n, ast.Call) and n.lineno == line)
        env = [k.value for k in node.keywords if k.arg == "env"]
        assert env and isinstance(env[0], ast.Call) and getattr(env[0].func, "id", None) == "_pip_env", \
            f"{rel}:{line} runs pip without env=_pip_env()"


def test_the_clean_environment_drops_the_persons_pip_settings(app_module, monkeypatch):
    monkeypatch.setenv("PIP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("PIP_INDEX_URL", "http://127.0.0.1:9/simple")
    monkeypatch.setenv("PIP_CACHE_DIR", "/somewhere")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "") or "/bin")
    env = app_module._pip_env()
    assert {k for k in env if k.upper().startswith("PIP_")} == {
        "PIP_CONFIG_FILE", "PIP_NO_CACHE_DIR", "PIP_DISABLE_PIP_VERSION_CHECK"}
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_NO_CACHE_DIR"] == "1"
    assert env["PATH"] == os.environ["PATH"]                    # everything else stays


def test_the_runs_update_plugins_builds_get_the_clean_environment(backend_module, tmp_path, monkeypatch):
    monkeypatch.setenv("PIP_PROXY", "http://127.0.0.1:9")
    envs = []
    pips = _update_plugins_pips(backend_module, tmp_path, monkeypatch, envs)
    assert len(pips) >= 3 and len(envs) == len(pips), pips
    for cmd, env in zip(pips, envs):
        assert env is not None and "PIP_PROXY" not in env, cmd
        assert env["PIP_CONFIG_FILE"] == os.devnull and env["PIP_NO_CACHE_DIR"] == "1", cmd


# ── A real pip, offline ──────────────────────────────────────────────────────────────────────────

def _wheel(path, name, files):
    dist = f"{name}-1.0.dist-info"
    with zipfile.ZipFile(path, "w") as z:
        for rel, text in files.items():
            z.writestr(rel, text)
        z.writestr(f"{dist}/METADATA", f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
        z.writestr(f"{dist}/WHEEL", "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{dist}/RECORD", "")


BACKEND = '''import zipfile
def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    name = "egm_demo-1.0-py3-none-any.whl"
    dist = "egm_demo-1.0.dist-info"
    with zipfile.ZipFile(wheel_directory + "/" + name, "w") as z:
        z.writestr("egm_demo.py", "")
        z.writestr(dist + "/METADATA", "Metadata-Version: 2.1\\nName: egm-demo\\nVersion: 1.0\\n")
        z.writestr(dist + "/WHEEL", "Wheel-Version: 1.0\\nGenerator: test\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n")
        z.writestr(dist + "/RECORD", "")
    return name
'''


@pytest.fixture
def source_build(tmp_path):
    """A source tree whose build needs egm-build-dep, which only a local folder has."""
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _wheel(wheels / "egm_build_dep-1.0-py3-none-any.whl", "egm_build_dep", {"egm_build_dep.py": ""})
    src = tmp_path / "egm-demo-1.0"
    src.mkdir()
    (src / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["egm-build-dep"]\nbuild-backend = "backend"\nbackend-path = ["."]\n'
        '[project]\nname = "egm-demo"\nversion = "1.0"\n')
    (src / "backend.py").write_text(BACKEND)
    return tmp_path, wheels, src


def _install(env, tmp_path, wheels, src):
    out = tmp_path / "out"
    cmd = [sys.executable, "-m", "pip", "install", "--isolated", "--disable-pip-version-check",
           "--no-index", "--find-links", str(wheels), "--target", str(out), str(src)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)


def _persons_settings(kind, tmp_path, monkeypatch):
    if kind == "variable":
        monkeypatch.setenv("PIP_REQUIRE_HASHES", "1")
    else:                                                       # the person's own pip config file
        home = tmp_path / "home"
        (home / ".config" / "pip").mkdir(parents=True)
        (home / ".config" / "pip" / "pip.conf").write_text("[install]\nrequire-hashes = true\n")
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))


@pytest.mark.skipif(sys.platform == "win32", reason="the config file case uses the Linux and Mac location")
@pytest.mark.parametrize("kind", ["variable", "config file"])
def test_a_source_build_no_longer_reads_the_persons_pip_settings(kind, app_module, source_build, monkeypatch):
    tmp_path, wheels, src = source_build
    _persons_settings(kind, tmp_path, monkeypatch)
    before = _install(dict(os.environ), tmp_path, wheels, src)
    assert before.returncode != 0 and "hash" in (before.stdout + before.stderr).lower(), \
        "the person's setting should reach the second pip without the clean environment"
    after = _install(app_module._pip_env(), tmp_path, wheels, src)
    assert after.returncode == 0, after.stdout + after.stderr
