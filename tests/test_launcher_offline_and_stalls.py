"""Windows launcher: an offline first start and a stalled download both end with a message.

* The installer edition (and the portable one) installs the app's Python packages with pip on a
  first start. When pip failed (offline), the error ended the launcher with no message: the
  progress window just closed, and under pythonw there is no console either.
* Downloads (Node, the private Python, rcedit) had no time limit, so a transfer that stopped
  sending waited forever while the launcher held its lock, and every later start quietly exited.
pip is faked and the stalled download comes from a loopback server started here.
"""
import builtins
import http.server
import importlib.util
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


@pytest.fixture
def launch(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_offline", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    msgs = []
    monkeypatch.setattr(mod, "_gui_msg", lambda m="", *a, **k: msgs.append(m))
    monkeypatch.setattr(mod, "PY_SETUP_LOG", tmp_path / "setup.log")
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)
    mod.msgs = msgs
    return mod


def _pip_fails(*a, **k):
    raise subprocess.CalledProcessError(1, a[0] if a else "pip")


def test_installer_edition_offline_package_install_says_what_to_do(launch, monkeypatch):
    real_import = builtins.__import__

    def no_yt_dlp(name, *a, **k):
        if name == "yt_dlp":
            raise ImportError(name)
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_yt_dlp)
    monkeypatch.setattr(launch, "_deps_below_floor", lambda read: False)
    monkeypatch.setattr(launch.subprocess, "run", _pip_fails)
    with pytest.raises(subprocess.CalledProcessError):      # still fatal, as before
        launch.ensure_python_deps()
    assert "internet connection" in launch.msgs[-1]


def test_portable_offline_package_install_says_what_to_do(launch, tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "PY_DIR", tmp_path / "python")
    monkeypatch.setattr(launch.subprocess, "run", _pip_fails)
    with pytest.raises(subprocess.CalledProcessError):
        launch.ensure_python_deps_embedded(tmp_path / "python" / "python.exe")
    assert "internet connection" in launch.msgs[-1]


class _Stall(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "1000000")
        self.end_headers()
        self.wfile.write(b"x" * 1000)
        self.wfile.flush()
        time.sleep(30)            # and then nothing

    def log_message(self, *a):
        pass


def test_a_download_that_stops_sending_ends_with_the_download_message(launch, tmp_path, monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Stall)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    node = tmp_path / "node_bin"
    monkeypatch.setattr(launch, "NODE_DIR", node)
    monkeypatch.setattr(launch, "NODE_EXE", node / "node.exe")
    monkeypatch.setattr(launch, "VERSION_CACHE", node / ".node_version")
    monkeypatch.setattr(launch, "_node_version", lambda exe: (0, 0, 0))
    monkeypatch.setattr(launch, "NODE_ZIP_URL", f"http://127.0.0.1:{srv.server_address[1]}/node.zip")
    before = socket.getdefaulttimeout()
    try:
        launch._limit_stalled_downloads(1)
        t0 = time.time()
        with pytest.raises(SystemExit):
            launch.ensure_node()
        assert time.time() - t0 < 15
        assert "could not be downloaded" in launch.msgs[-1]
        assert not (node / "node_tmp.zip").exists()
    finally:
        socket.setdefaulttimeout(before)
        srv.shutdown()
        srv.server_close()


def test_the_launcher_sets_the_limit_before_anything_else():
    src = LAUNCH.read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    first = [l.strip() for l in main.splitlines()[1:] if l.strip() and not l.strip().startswith("#")][0]
    assert first == "_limit_stalled_downloads()"
    assert 0 < __import__("re").search(r"^DOWNLOAD_STALL_TIMEOUT = (\d+)", src, __import__("re").M).group(1).__len__()
