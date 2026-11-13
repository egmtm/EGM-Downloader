"""
The Windows installer writes the language chosen on its first screen to first-run-language.txt in the
install folder. In the installer edition app.py runs from resources\\app with EGM_INSTALL_DIR set to that
folder, so it must read the file there (and not beside app.py), use it once and delete it.

app.py is imported in a fresh process from its own folder, because these values are read at import.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROBE = r"""
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("egm_language_probe", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
c = m.app.test_client()
s = c.get("/api/settings", headers={"X-EGM-Token": os.environ["EGM_API_TOKEN"]}).get_json()
print(json.dumps({"language": s.get("language")}))
"""


def _run(tmp_path, install_dir, beside_app=False):
    app_dir = tmp_path / "resources" / "app"
    app_dir.mkdir(parents=True)
    shutil.copy(ROOT / "app.py", app_dir / "app.py")
    install_dir.mkdir(parents=True, exist_ok=True)
    hand_off = (app_dir if beside_app else install_dir) / "first-run-language.txt"
    hand_off.write_text("de", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("EGM_INSTALL_DIR", "LANGUAGE", "LC_MESSAGES")}
    env.update(EGM_API_TOKEN="hand-off-test-token", HOME=str(tmp_path), PYTHONDONTWRITEBYTECODE="1",
               EGM_INSTALL_DIR=str(install_dir), LC_ALL="C", LANG="C")
    r = subprocess.run([sys.executable, "-c", PROBE, str(app_dir / "app.py")], cwd=tmp_path,
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1]), hand_off


def test_the_installer_language_is_read_from_the_install_folder_once(tmp_path):
    inst = tmp_path / "EGM Downloader"
    out, hand_off = _run(tmp_path, inst)
    assert out["language"] == "de"
    assert not hand_off.exists(), "the hand-off file is used once and deleted"
    saved = json.loads((inst / "egm_settings.json").read_text(encoding="utf-8"))
    assert saved.get("language") == "de"


def test_a_file_beside_app_py_is_not_the_installers(tmp_path):
    """Only the install folder is the installer's: resources\\app is replaced on every upgrade."""
    out, hand_off = _run(tmp_path, tmp_path / "EGM Downloader", beside_app=True)
    assert out["language"] == "en"
    assert hand_off.exists()
