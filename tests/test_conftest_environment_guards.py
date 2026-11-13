"""conftest.py keeps the test process's EGM_ variables what they were.

* EGM_INSTALL_DIR from the developer's shell is cleared before any module under test is imported.
* A test that leaves an EGM_ variable changed after it ran fails, and the variable is put back, so the
  next test does not run with it. monkeypatch.setenv is undone in time and passes.

Each case runs pytest in a child process on a copy of this conftest.py and a small test file.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

LEAKY = '''
import os

def test_leaks():
    os.environ["EGM_LEAK_PROBE"] = "1"

def test_runs_after_the_leak():
    assert "EGM_LEAK_PROBE" not in os.environ

def test_uses_monkeypatch(monkeypatch):
    monkeypatch.setenv("EGM_DEV_MODE", "1")
    monkeypatch.delenv("EGM_SILENT", raising=False)

def test_install_dir_is_cleared():
    assert "EGM_INSTALL_DIR" not in os.environ
'''


def _run(tmp_path, env_extra):
    shutil.copy(HERE / "conftest.py", tmp_path / "conftest.py")
    (tmp_path / "test_probe.py").write_text(LEAKY, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("EGM_")}
    env.update(env_extra)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-rA", "-p", "no:cacheprovider", "test_probe.py"],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def test_a_test_that_leaves_an_egm_variable_set_fails_and_the_next_one_does_not_see_it(tmp_path):
    r = _run(tmp_path, {"EGM_INSTALL_DIR": str(tmp_path / "elsewhere")})
    out = r.stdout
    assert r.returncode != 0, out
    assert "ERROR test_probe.py::test_leaks" in out and "EGM_LEAK_PROBE" in out, out
    for name in ("test_runs_after_the_leak", "test_uses_monkeypatch", "test_install_dir_is_cleared"):
        assert f"PASSED test_probe.py::{name}" in out, out
    assert not (tmp_path / "elsewhere").exists()
