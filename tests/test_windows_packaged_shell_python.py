"""
windows/electron/main.js in the packaged layout (Electron, Python and the app in one folder) and as
started by the launcher.

* The layout is told by where main.js sits (inside resources\\app.asar), not by app.isPackaged, which
  is also true for the launcher's renamed Electron. Packaged: the install folder is the folder of the
  exe and the app files are in resources\\app. Launcher: both are the parent of electron\\.
* Packaged, only the bundled Python is tried, and it runs with no user site folder and without any
  PYTHON variable of the user's environment (any spelling; only PYTHONNOUSERSITE=1 is set, for the
  Pythons app.py starts), with EGM_INSTALL_DIR set to the install folder. app.py itself runs with
  -E -s: no PYTHON variable and no user site folder, and, from -E, none of the PythonPath entries
  in the registry of a Python 3.11 installed on the machine (getpath reads them only when the
  environment is used).
* Packaged, the backend runs in the app folder (resources\\app), not in the install folder where
  Electron's DLLs sit: ffmpeg, Deno and yt-dlp inherit that working folder. Started by the launcher
  both are the same folder.
* Started by the launcher, an EGM_INSTALL_DIR from the environment never reaches app.py.
* Packaged and portable, the .portable marker is looked up in the install folder.

The functions are cut out of main.js and run in Node against stand-ins for Electron and
child_process, so what runs is the shipped text.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MAIN_JS = Path(__file__).resolve().parent.parent / "windows" / "electron" / "main.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _code():
    src = MAIN_JS.read_text(encoding="utf-8")
    folders = src[src.index("function packagedLayout()"):src.index("const APP_DIR     = appFilesDir();")]
    folders += "const APP_DIR     = appFilesDir();\n"
    python = src[src.index("function withoutEnv(env, names)"):src.index("// ── Splash window")]
    start = src.index("async function startFlask() {")
    flask = src[start:src.index("\n}\n", start) + 3]
    return folders + python + "let flaskProc = null;\n" + flask


RUNNER = r"""
const vm = require('vm');
const scenario = JSON.parse(process.argv[2]);
const probes = [], spawned = [], boxes = [];
const ctx = {
  path: require('path').win32,
  __dirname: scenario.dirname,
  process: { execPath: scenario.execPath, resourcesPath: scenario.resourcesPath, env: scenario.env },
  app: { isPackaged: true, quit() {}, isQuitting: false },
  execFileSync: (cmd, args, opts) => {
    probes.push({ cmd, env: opts && opts.env ? opts.env : null });
    if (!scenario.working.includes(cmd)) throw new Error('not found');
  },
  spawn: (cmd, args, opts) => { spawned.push({ cmd, args, cwd: opts.cwd, env: opts.env }); return { on() {} }; },
  dialog: { showErrorBox: (t) => boxes.push(t) },
  closeSplash() {}, dropSplash() {}, splashProgress() {},
  PORT: 8899, HOST: '127.0.0.1', EGM_TOKEN: 'token',
  JSON, Object, Set, String, console,
};
vm.runInNewContext(%s + `
startFlask().then(() => console.log(JSON.stringify({
  PACKAGED, INSTALL_DIR, APP_DIR, bundled: bundledPythonEnv(process.env),
})));`, Object.assign(ctx, { __report: null }));
setTimeout(() => {}, 0);
process.on('exit', () => console.log(JSON.stringify({ probes, spawned, boxes })));
"""


def _run(tmp_path, scenario):
    runner = tmp_path / "runner.js"
    runner.write_text(RUNNER % json.dumps(_code()), encoding="utf-8")
    r = subprocess.run([NODE, str(runner), json.dumps(scenario)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    lines = [json.loads(l) for l in r.stdout.splitlines() if l.startswith("{")]
    out = {}
    for d in lines:
        out.update(d)
    return out


USER_ENV = {"PATH": "C:\\Windows", "PythonHome": "C:\\Python311", "PYTHONPATH": "C:\\mine",
            "pythonnousersite": "0", "EGM_INSTALL_DIR": "C:\\elsewhere",
            "PYTHONSTARTUP": "C:\\mine\\start.py", "PythonUtf8": "0", "PYTHONINSPECT": "1",
            "PYTHONSAFEPATH": "0", "PYTHONUSERBASE": "C:\\mine\\base", "PYTHONWARNINGS": "error",
            "egm_install_dir": "C:\\another"}   # a second spelling: Windows names are not case sensitive
OTHER_PYTHON_VARS = ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUTF8", "PYTHONINSPECT",
                     "PYTHONSAFEPATH", "PYTHONUSERBASE", "PYTHONWARNINGS")
INSTALL = "C:\\Users\\u\\AppData\\Local\\EGM Downloader"


def _packaged(working=None):
    return {"dirname": INSTALL + "\\resources\\app.asar", "execPath": INSTALL + "\\EGM Downloader.exe",
            "resourcesPath": INSTALL + "\\resources", "env": USER_ENV,
            "working": working if working is not None else [INSTALL + "\\resources\\python\\python.exe", "python"]}


def _launcher():
    root = "C:\\EGM"
    return {"dirname": root + "\\electron", "execPath": root + "\\electron\\node_modules\\electron\\dist\\EGM Downloader.exe",
            "resourcesPath": root + "\\electron\\node_modules\\electron\\dist\\resources", "env": USER_ENV,
            "working": ["python"]}


def test_the_packaged_layout_is_told_by_app_asar_and_finds_its_folders(tmp_path):
    out = _run(tmp_path, _packaged())
    assert out["PACKAGED"] is True
    assert out["INSTALL_DIR"] == INSTALL
    assert out["APP_DIR"] == INSTALL + "\\resources\\app"


def test_the_launcher_layout_is_not_packaged_although_app_is_packaged_says_so(tmp_path):
    out = _run(tmp_path, _launcher())
    assert out["PACKAGED"] is False
    assert out["INSTALL_DIR"] == out["APP_DIR"] == "C:\\EGM"


def test_the_bundled_python_sees_only_its_own_packages(tmp_path):
    env = _run(tmp_path, _packaged())["bundled"]
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["EGM_INSTALL_DIR"] == INSTALL
    assert env["PATH"] == "C:\\Windows"
    upper = [k.upper() for k in env]
    assert [k for k in upper if k.startswith("PYTHON")] == ["PYTHONNOUSERSITE"], upper
    assert upper.count("EGM_INSTALL_DIR") == 1


def test_packaged_only_the_bundled_python_is_tried_and_runs_the_app_from_resources(tmp_path):
    out = _run(tmp_path, _packaged())
    bundled = INSTALL + "\\resources\\python\\python.exe"
    assert [p["cmd"] for p in out["probes"]] == [bundled]
    assert out["probes"][0]["env"]["PYTHONNOUSERSITE"] == "1" and "PYTHONHOME" not in out["probes"][0]["env"]
    (proc,) = out["spawned"]
    assert proc["cmd"] == bundled
    assert proc["args"] == ["-E", "-s", INSTALL + "\\resources\\app\\app.py"]
    assert proc["cwd"] == INSTALL + "\\resources\\app"
    assert proc["env"]["EGM_INSTALL_DIR"] == INSTALL and proc["env"]["PYTHONNOUSERSITE"] == "1"
    assert [k for k in proc["env"] if k.upper().startswith("PYTHON")] == ["PYTHONNOUSERSITE"], proc["env"]


def test_packaged_without_its_python_nothing_else_is_started(tmp_path):
    out = _run(tmp_path, _packaged(working=["python", "python3"]))
    assert out["spawned"] == [] and out["boxes"] == ["Python could not start"]


def test_started_by_the_launcher_no_install_folder_reaches_app_py(tmp_path):
    out = _run(tmp_path, _launcher())
    (proc,) = out["spawned"]
    assert proc["args"] == ["C:\\EGM\\app.py"] and proc["cwd"] == "C:\\EGM"
    assert "EGM_INSTALL_DIR" not in proc["env"]
    assert proc["env"]["PythonHome"] == "C:\\Python311", "the launcher's Python keeps the user's environment"
    assert all(k in {n.upper() for n in proc["env"]} for k in OTHER_PYTHON_VARS)


# ── the portable marker, packaged ─────────────────────────────────────────────

PORTABLE_RUNNER = """
const fs = require('fs'), path = require('path');
const root = process.argv[2];
const calls = [];
const app = { setPath: (k, v) => calls.push([k, v]) };
const fakeProcess = { execPath: path.join(root, 'EGM Downloader.exe'), resourcesPath: path.join(root, 'resources') };
const run = new Function('app', 'fs', 'path', '__dirname', 'process', %s);
run(app, fs, path, path.join(root, 'resources', 'app.asar'), fakeProcess);
console.log(JSON.stringify({ calls }));
"""


def test_packaged_the_portable_marker_is_read_from_the_install_folder(tmp_path):
    src = MAIN_JS.read_text(encoding="utf-8")
    block = src[src.index("const _portableMarker"):src.index("// ── Window hardening")]
    helpers = src[src.index("function loadSettings()"):src.index("// Validate that an IPC message")]
    root = tmp_path / "EGM Downloader"
    (root / "resources" / "app.asar").mkdir(parents=True)
    (root / ".portable").write_text("x", encoding="utf-8")
    runner = tmp_path / "portable_runner.js"
    runner.write_text(PORTABLE_RUNNER % json.dumps(block + "\n" + helpers), encoding="utf-8")
    r = subprocess.run([NODE, str(runner), str(root)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["calls"] == [["userData", str(root / "data" / "electron-data")]]
