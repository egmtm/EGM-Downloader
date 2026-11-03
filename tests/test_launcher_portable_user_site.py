"""Windows launcher, portable edition: the private Python never reads a user packages folder,
and never reads PYTHONPATH or PYTHONHOME.

The Python that starts the first run (the system Python the launcher finds) can hand the embedded
Python its own user packages folder: the Microsoft Store Python 3.12 does, and its folder showed up in
the embedded Python's search path. pip then counted the app's packages there as installed, left the
portable's own site-packages empty, and the app ran on the user's copies; the next start found nothing
on disk and ran pip for about 20 s. PYTHONNOUSERSITE=1, set in the portable branch before anything is
started, stops that: the pip steps, Electron and the backend inherit it. The installer edition keeps
using the system Python and its user packages on purpose, so the setting must not reach it.
"""
import importlib.util
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
    for name in ("_py_version", "_python_has_pip", "_pip_install"):
        assert "env=" not in _function(name), name
    assert 'env = {**os.environ, "PATH"' in _function("launch_electron")


def test_the_private_python_does_not_inherit_search_path_variables_from_the_user():
    """The python.org embeddable zip ignored PYTHONPATH and PYTHONHOME; the full Python the portable
    runs on now honours them, so they are cleared in the portable branch, before anything is started
    (the pip steps, Electron and the backend inherit the environment from this process)."""
    portable, installer = _branches()
    for name in ("PYTHONPATH", "PYTHONHOME"):
        clear = f'os.environ.pop("{name}", None)'
        assert portable.count(clear) == 1, name
        assert clear not in installer, name
        for later in ("py_exe = ensure_python()", "ensure_python_deps_embedded(py_exe)"):
            assert portable.index(clear) < portable.index(later), (name, later)


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


def test_the_native_launcher_clears_them_for_the_private_python_only():
    """On a warm start the native launcher runs launch.py on the private Python itself, before
    launch.py can clear anything, so the launcher clears PYTHONHOME and PYTHONPATH for that child
    and puts them back before it falls through to a system Python."""
    src = (LAUNCH.parent / "launcher.c").read_text(encoding="utf-8")
    start = src.index("if (attrs != INVALID_FILE_ATTRIBUTES")
    branch = src[start:src.index("/* First-run / installer / fallback", start)]
    for name in ("PYTHONHOME", "PYTHONPATH"):
        assert f'L"{name}"' in branch, name
    clear = branch.index("SetEnvironmentVariableW(names[i], NULL)")
    launch = branch.index("try_launch(embedded_py, PRIVATE_PY_FLAGS, script_path)")
    restore = branch.index("SetEnvironmentVariableW(names[i], saved[i])")
    assert clear < launch < restore
    # the system Python attempts below are left as they were
    rest = src[src.index("/* First-run / installer / fallback"):]
    assert "SetEnvironmentVariableW" not in rest


# ── the private Python's own start: -s -E, for the private Python only ────────
# The native launcher starts python\\python.exe launch.py, and launch.py hands over to pythonw.exe.
# PYTHONNOUSERSITE is only set later, in the portable branch, so without flags both of those
# processes start with the user's packages folder on, and a .pth file in it (a line starting with
# "import" runs at start) would run inside the launcher. -s stops that, -E stops PYTHON* variables.
# The installer edition runs on the system Python, whose packages may live in that user folder, so
# the flags must reach the private Python only.

def _load_launch():
    spec = importlib.util.spec_from_file_location("egm_launch_flags_under_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("exe", ["python.exe", "pythonw.exe"])
def test_the_hop_keeps_the_flags_on_the_private_python(monkeypatch, exe):
    mod = _load_launch()
    monkeypatch.setattr(sys, "executable", str(LAUNCH.parent / "python" / exe))
    assert mod._private_python_flags() == ["-s", "-E"]


@pytest.mark.parametrize("where", ["system/Python311/python.exe", "windows/python311/python.exe",
                                   "windows/embedded/python/python.exe", "python.exe"])
def test_the_hop_gives_the_system_python_no_flags(monkeypatch, tmp_path, where):
    # the installer edition, and a folder that only looks like the private one
    mod = _load_launch()
    exe = tmp_path / where
    exe.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert mod._private_python_flags() == []


def test_the_hop_passes_the_flags_and_only_that_hop_does():
    src = _source()
    assert src.count("_private_python_flags") == 2, "the definition and the pythonw hop, nothing else takes the flags"
    start = src.index("# Re-exec under pythonw.exe")
    hop = src[start:src.index("import shutil, zipfile", start)]
    assert "[str(pw)] + _private_python_flags() + [str(__file__)] + sys.argv[1:]" in hop
    # the hand over to a newer system Python (the version gate) is not the private Python
    gate = src[src.index("_newer = None if"):src.index("_msg = (")]
    assert "_private_python_flags" not in gate


def test_the_native_launcher_passes_the_flags_to_the_private_python_only():
    src = (LAUNCH.parent / "launcher.c").read_text(encoding="utf-8")
    assert 'PRIVATE_PY_FLAGS = L"-s -E ";' in src
    start = src.index("if (attrs != INVALID_FILE_ATTRIBUTES")
    private = src[start:src.index("/* First-run / installer / fallback", start)]
    system = src[src.index("/* First-run / installer / fallback"):]
    assert private.count("try_launch(embedded_py, PRIVATE_PY_FLAGS, script_path)") == 1
    assert "PRIVATE_PY_FLAGS" not in system
    assert system.count('try_launch(candidates[i], L"", script_path)') == 1
    # the command line is  "python" <flags>"script"  with the flags empty or ending in a space
    assert 'L"\\"%s\\" %s\\"%s\\"", py_cmd, py_flags, script_path' in src
    assert src.count("try_launch(") == 3          # the definition and the two calls


def test_s_keeps_a_pth_file_in_the_user_packages_folder_from_running(tmp_path):
    """The risk the flag answers: a .pth file there runs code when Python starts."""
    base_env = {k: v for k, v in os.environ.items() if k not in ("PYTHONNOUSERSITE", "PYTHONUSERBASE", "PYTHONPATH")}
    base_env["PYTHONUSERBASE"] = str(tmp_path / "userbase")
    (user_site,) = _child("import site; print(site.getusersitepackages())", base_env)
    Path(user_site).mkdir(parents=True)
    (Path(user_site) / "egm_probe.pth").write_text("import os; os.environ['EGM_PTH_RAN'] = '1'\n")
    probe = "import os; print(os.environ.get('EGM_PTH_RAN', 'no'))"
    if _child(probe, base_env) != ["1"]:
        pytest.skip("this interpreter does not use a user site folder (virtual environment)")
    r = subprocess.run([sys.executable, "-s", "-c", probe], env=base_env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.split() == ["no"], r.stderr


def test_E_makes_the_interpreter_ignore_pythonpath(tmp_path):
    (tmp_path / "egm_probe_module.py").write_text("VALUE = 1\n")
    env = {**{k: v for k, v in os.environ.items() if k != "PYTHONHOME"}, "PYTHONPATH": str(tmp_path)}
    probe = "import egm_probe_module; print('imported')"
    assert _child(probe, env) == ["imported"]
    r = subprocess.run([sys.executable, "-E", "-c", probe], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "egm_probe_module" in r.stderr
