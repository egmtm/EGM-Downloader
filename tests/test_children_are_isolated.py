"""Every Python the Windows backend starts is started the way the backend itself was.

Packaged, the Windows shell starts app.py with python -E -s (windows/electron/main.js). -E is not inherited,
and on Windows CPython reads the PythonPath registry entries of an installed Python 3.11 unless -E is on;
-E alone would also open the user site folder again (it ignores PYTHONNOUSERSITE). So a backend started
with -E starts its own Pythons (yt-dlp, pip, the small -c checks) with -E -s too: every command begins with
_PY_CMD. From source and in the tests the backend runs without -E, and the command lines stay as before.

* A scan of app.py: sys.executable appears only in _PY_CMD and in the frozen build's folder (Path(...)),
  so a new command that starts Python another way fails here.
* app.py imported in a Python started with -E -s and in one started without, with subprocess.run and
  Popen replaced by recorders: the commands the yt-dlp and pip helpers build.
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import ROOT, read_source

APP = Path(ROOT) / "app.py"


def test_every_python_command_of_the_windows_backend_starts_with_the_helper():
    tree = ast.parse(read_source("app.py"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    allowed, other = [], []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "executable"
                and isinstance(node.value, ast.Name) and node.value.id == "sys"):
            continue
        up = node
        while up in parents and not isinstance(up, (ast.stmt,)):
            up = parents[up]
        is_helper = isinstance(up, ast.Assign) and [t.id for t in up.targets if isinstance(t, ast.Name)] == ["_PY_CMD"]
        call = parents.get(node)
        is_folder = isinstance(call, ast.Call) and getattr(call.func, "id", None) == "Path"
        (allowed if is_helper or is_folder else other).append(node.lineno)
    assert len(allowed) >= 3, "the helper or the frozen folder line is not where the scan expects it"
    assert other == [], f"app.py lines that start Python without _PY_CMD: {other}"


def test_the_helper_follows_the_backends_own_flags():
    tree = ast.parse(read_source("app.py"))
    (helper,) = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and [getattr(t, "id", None) for t in n.targets] == ["_PY_CMD"]]
    assert ast.unparse(helper.value) == "[sys.executable, '-E', '-s'] if sys.flags.ignore_environment else [sys.executable]"


RECORDER = r"""
import importlib.util, json, subprocess, sys, types
spec = importlib.util.spec_from_file_location("app", sys.argv[1])
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
seen = []
def run(cmd, *a, **k):
    seen.append([str(c) for c in cmd])
    return types.SimpleNamespace(returncode=0, stdout="0.8.0\n", stderr="")
class Popen:
    def __init__(self, cmd, *a, **k):
        seen.append([str(c) for c in cmd]); self.stdout = iter(()); self.stderr = iter(()); self.returncode = 0
    def wait(self, *a, **k): return 0
    def communicate(self, *a, **k): return ("", "")
app.subprocess.run = run
app.subprocess.Popen = Popen
app._ytdlp("--version", timeout=5)
app._get_ytdlp_version()
app._ytdlp_ejs_pin()
app._ytdlp_ejs_paired()
app._install_ytdlp_ejs(lambda *a: None, [])
print(json.dumps({"py": app._PY_CMD, "seen": seen}))
"""


def _commands(tmp_path, flags):
    env = dict(os.environ, EGM_API_TOKEN="t", EGM_INSTALL_DIR=str(tmp_path), HOME=str(tmp_path))
    r = subprocess.run([sys.executable, *flags, "-c", RECORDER, str(APP)], capture_output=True, text=True,
                       timeout=120, env=env, cwd=tmp_path)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_a_backend_started_with_e_and_s_starts_every_python_with_them(tmp_path):
    out = _commands(tmp_path, ["-E", "-s"])
    assert out["py"] == [sys.executable, "-E", "-s"]
    pythons = [c for c in out["seen"] if c[0] == sys.executable]
    assert len(pythons) >= 5, out["seen"]
    assert all(c[1:3] == ["-E", "-s"] and c[3] in ("-m", "-c") for c in pythons), pythons


def test_a_backend_started_without_them_keeps_its_command_lines(tmp_path):
    out = _commands(tmp_path, [])
    assert out["py"] == [sys.executable]
    pythons = [c for c in out["seen"] if c[0] == sys.executable]
    assert len(pythons) >= 5 and all(c[1] in ("-m", "-c") for c in pythons), pythons
