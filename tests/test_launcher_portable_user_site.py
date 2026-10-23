"""Windows launcher, portable edition: the embedded Python never reads a user packages folder.

The Python that starts the first run (the system Python the launcher finds) can hand the embedded
Python its own user packages folder: the Microsoft Store Python 3.12 does, and its folder showed up in
the embedded Python's search path. pip then counted the app's packages there as installed, left the
portable's own site-packages empty, and the app ran on the user's copies; the next start found nothing
on disk and ran pip for about 20 s. PYTHONNOUSERSITE=1, set in the portable branch before anything is
started, stops that: the pip steps, Electron and the backend inherit it. The installer edition keeps
using the system Python and its user packages on purpose, so the setting must not reach it.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"
SETTING = 'os.environ["PYTHONNOUSERSITE"] = "1"'


def _source():
    return LAUNCH.read_text(encoding="utf-8")


def _main_block():
    src = _source()
    return src[src.index('if __name__ == "__main__":'):]


def _branches():
    """(portable branch, installer branch) of the start-up block."""
    main = _main_block()
    start = main.index("    if _is_portable():\n")
    split = main.index("    else:\n", start)
    return main[start:split], main[split:main.index("    node_exe = ensure_node()")]


def _function(name):
    src = _source()
    start = src.index(f"def {name}(")
    return src[start:src.index("\ndef ", start + 1)]


def test_the_setting_is_made_once_in_the_portable_branch_before_anything_is_started():
    src = _source()
    assert src.count(SETTING) == 1
    assert src.count("PYTHONNOUSERSITE") == 1
    portable, installer = _branches()
    assert SETTING in portable and SETTING not in installer
    for later in ("py_exe = ensure_python()", "ensure_python_deps_embedded(py_exe)"):
        assert portable.count(later) == 1, later
        assert portable.index(SETTING) < portable.index(later), later


def test_the_processes_that_matter_inherit_the_environment():
    # none of these passes a custom env=, so the setting reaches the pip steps; Electron's env is
    # built from os.environ, and the backend inherits Electron's
    for name in ("_py_version", "_setup_embedded_pip", "_pip_install"):
        assert "env=" not in _function(name), name
    assert 'env = {**os.environ, "PATH"' in _function("launch_electron")


def _child(code, env):
    r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


def test_the_setting_really_hides_an_existing_user_packages_folder(tmp_path):
    base_env = {k: v for k, v in os.environ.items() if k not in ("PYTHONNOUSERSITE", "PYTHONUSERBASE")}
    base_env["PYTHONUSERBASE"] = str(tmp_path / "userbase")
    (user_site,) = _child("import site; print(site.getusersitepackages())", base_env)
    Path(user_site).mkdir(parents=True)

    show = "import sys; print('\\n'.join(sys.path))"
    before = _child(show, base_env)
    if user_site not in before:
        pytest.skip("this interpreter does not use a user site folder (virtual environment)")
    after = _child(show, {**base_env, "PYTHONNOUSERSITE": "1"})
    assert user_site not in after
