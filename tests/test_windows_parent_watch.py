"""The Windows backend ends itself when Electron is gone.

Mac and Linux poll for a change of parent (test_process_lifecycle_parity.py starts a real process and
kills its parent). Windows has no change of parent, so root app.py waits on the parent's process
handle. This cannot start a real Windows process here, so the Windows API is a stand-in; what the
function asks of it, and what it does with each answer, is what is checked. A real Windows run is
still needed once.
"""
import ctypes
import re
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYNCHRONIZE, INFINITE = 0x00100000, 0xFFFFFFFF


class _Exit(Exception):
    def __init__(self, code):
        self.code = code


@pytest.fixture
def rig(app_module, monkeypatch):
    killed, calls = [], []
    monkeypatch.setattr(app_module, "_kill_proc", lambda p: killed.append(p))
    monkeypatch.setattr(app_module, "_active_procs", {"a": "yt-dlp a", "b": "yt-dlp b"})
    monkeypatch.setattr(app_module.os, "getppid", lambda: 4321)

    def fake_exit(code):
        raise _Exit(code)
    monkeypatch.setattr(app_module.os, "_exit", fake_exit)

    def windows_api(handle, wait, error=0):
        def OpenProcess(access, inherit, pid):
            calls.append(("open", access, inherit, pid))
            return handle

        def WaitForSingleObject(h, ms):
            calls.append(("wait", h, ms))
            return wait
        k32 = types.SimpleNamespace(OpenProcess=OpenProcess, WaitForSingleObject=WaitForSingleObject)
        monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error=False: k32, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: error, raising=False)
    return app_module, windows_api, killed, calls


def test_when_the_parent_ends_the_tracked_downloads_are_killed_and_the_backend_exits(rig):
    app, windows_api, killed, calls = rig
    windows_api(handle=77, wait=0)                       # WAIT_OBJECT_0: the process has ended
    with pytest.raises(_Exit) as e:
        app._exit_when_electron_is_gone()
    assert e.value.code == 0
    assert sorted(killed) == ["yt-dlp a", "yt-dlp b"]
    assert calls == [("open", SYNCHRONIZE, False, 4321), ("wait", 77, INFINITE)]


def test_a_wait_that_fails_leaves_everything_running(rig):
    app, windows_api, killed, calls = rig
    windows_api(handle=77, wait=0xFFFFFFFF)              # WAIT_FAILED
    app._exit_when_electron_is_gone()
    assert killed == []


def test_a_parent_that_cannot_be_opened_is_not_taken_for_gone(rig):
    app, windows_api, killed, calls = rig
    windows_api(handle=0, wait=0, error=5)               # ERROR_ACCESS_DENIED
    app._exit_when_electron_is_gone()
    assert killed == [] and [c[0] for c in calls] == ["open"]


def test_a_parent_that_no_longer_exists_ends_the_backend(rig):
    app, windows_api, killed, calls = rig
    windows_api(handle=0, wait=0, error=87)              # ERROR_INVALID_PARAMETER: no such process
    with pytest.raises(_Exit) as e:
        app._exit_when_electron_is_gone()
    assert e.value.code == 0 and sorted(killed) == ["yt-dlp a", "yt-dlp b"]
    assert [c[0] for c in calls] == ["open"]


def test_the_watch_is_started_only_under_electron():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    assert re.search(r'if os\.environ\.get\("EGM_ELECTRON"\) == "1":\n\s+threading\.Thread\(target=_exit_when_electron_is_gone, daemon=True',
                     main), "the parent watch is not started under EGM_ELECTRON=1"
    assert main.count("_exit_when_electron_is_gone") == 1
