"""A backend that cannot listen on its port exits with code 3 instead of waiting forever.

Before, the server thread ended (werkzeug: "Address already in use") but the process kept
waiting with no server: the shell's crash message never came, and it either waited out its three
minutes or loaded whatever program held the port. Each backend runs here from a copy in a temporary
folder, with empty ffmpeg files in place so start-up downloads nothing.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX start-up path")


@pytest.mark.parametrize("rel", ["app.py", "linux/app.py", "mac/app.py"])
def test_a_taken_port_makes_the_backend_exit_with_code_3(rel, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shutil.copy(ROOT / rel, app_dir / "app.py")
    home = tmp_path / "home"
    for folder, names in ((app_dir / "ffmpeg_bin", ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe")),
                          (home / ".local" / "share" / "egm-downloader" / "ffmpeg_bin", ("ffmpeg", "ffprobe"))):
        folder.mkdir(parents=True)
        for n in names:
            (folder / n).write_text("")
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in ("EGM_ELECTRON", "EGM_DEV_MODE")}
    env.update(HOME=str(home), XDG_DATA_HOME=str(home), TMP=str(tmp_path), TEMP=str(tmp_path),
               PORT=str(port), EGM_API_TOKEN="ci-test-token-not-secret")
    proc = subprocess.Popen([sys.executable, str(app_dir / "app.py")], cwd=app_dir, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail(f"{rel}: the backend kept running with no server on a taken port")
    finally:
        holder.close()
    assert code == 3, code
