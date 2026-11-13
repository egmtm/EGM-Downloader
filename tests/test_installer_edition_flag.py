"""
The Windows installer edition ships Electron and Python inside the app folder. Its shell starts
app.py from resources\\app with EGM_INSTALL_DIR set to the install folder (the folder of the exe).
/api/portable-status then says bundled: true and the page hides Reinstall Electron, which nothing
reads there. Unset (the launcher and the portable edition) the answer is as before, plus
bundled: false. A .portable marker in the install folder still means portable.

Each case imports app.py in a fresh process from its own folder, because these values are read
once at import.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PROBE = r"""
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("egm_edition_probe", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c = m.app.test_client()
h = {"X-EGM-Token": os.environ["EGM_API_TOKEN"]}
status = c.get("/api/portable-status", headers=h).get_json()
r = c.post("/api/electron/reinstall", headers=h, json={})
print(json.dumps({"status": status, "reinstall": r.status_code}))
"""


def _run(tmp_path, install_dir=None, portable_in=None):
    app_dir = tmp_path / "resources" / "app"
    app_dir.mkdir(parents=True)
    shutil.copy(ROOT / "app.py", app_dir / "app.py")
    env = {k: v for k, v in os.environ.items() if k != "EGM_INSTALL_DIR"}
    env.update(EGM_API_TOKEN="edition-test-token", HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1")
    if install_dir is not None:
        install_dir.mkdir(parents=True, exist_ok=True)
        env["EGM_INSTALL_DIR"] = str(install_dir)
    if portable_in is not None:
        (portable_in / ".portable").write_text("x", encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", PROBE, str(app_dir / "app.py")], cwd=tmp_path,
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1]), app_dir


def test_unset_is_the_launcher_edition_as_before(tmp_path):
    out, app_dir = _run(tmp_path)
    assert out["status"] == {"portable": False, "bundled": False, "data_dir": str(app_dir)}
    assert (app_dir / ".electron-update").is_file()


def test_set_is_the_installer_edition(tmp_path):
    inst = tmp_path / "EGM Downloader"
    out, app_dir = _run(tmp_path, install_dir=inst)
    assert out["status"] == {"portable": False, "bundled": True, "data_dir": str(inst)}
    # The route is unchanged: it still writes its marker, into the install folder (the uninstaller
    # removes it); nothing reads it in this edition, which is why the page hides the button.
    assert out["reinstall"] == 200
    assert (inst / ".electron-update").is_file()
    assert not (app_dir / ".electron-update").exists()


def test_a_portable_marker_in_the_install_folder_is_portable_not_bundled(tmp_path):
    inst = tmp_path / "EGM Downloader"
    inst.mkdir()
    out, _ = _run(tmp_path, install_dir=inst, portable_in=inst)
    assert out["status"] == {"portable": True, "bundled": False, "data_dir": str((inst / "data").resolve())}
