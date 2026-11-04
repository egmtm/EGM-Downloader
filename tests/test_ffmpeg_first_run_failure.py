"""A download waiting for first-run ffmpeg setup that has already failed ends at once.

If the setup could not get ffmpeg (offline, a failed checksum) each download used to sit queued for
180 seconds and then say "still installing", although the setup only runs at start and waiting could
never help. Now the setup thread notes that it has ended; a waiting download that finds ffmpeg
still missing then fails at once with the code ffmpeg_failed. A setup that is still running keeps
the old behaviour (wait up to 180 s, then ffmpeg_installing).
"""
import importlib.util
import re
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module"), "ffmpeg.exe"
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_ffmpeg_failure_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod, "ffmpeg"


@pytest.fixture
def slot(backend, tmp_path, monkeypatch):
    mod, exe = backend
    monkeypatch.setattr(mod, "FFMPEG_DIR", tmp_path)
    monkeypatch.setitem(mod._ffmpeg_first_run, "finished", False)
    rig = types.SimpleNamespace(mod=mod, exe=exe, folder=tmp_path, job={"status": "queued"},
                                ran=[], sleeps=[], on_sleep=None)
    monkeypatch.setattr(mod, "run_download", lambda job_id, *a: rig.ran.append(job_id))
    monkeypatch.setitem(mod.jobs, "j1", rig.job)

    def fake_sleep(seconds):
        rig.sleeps.append(seconds)
        if rig.on_sleep:
            rig.on_sleep(len(rig.sleeps))
    monkeypatch.setattr(mod.time, "sleep", fake_sleep)
    return rig


def test_setup_ended_without_ffmpeg_fails_the_download_at_once(slot):
    mod, exe, folder, job, ran, sleeps = slot.mod, slot.exe, slot.folder, slot.job, slot.ran, slot.sleeps
    mod._ffmpeg_first_run["finished"] = True
    mod._run_download_slot("j1")
    assert job["status"] == "error" and job["error_code"] == "ffmpeg_failed"
    assert "could not be downloaded" in job["error"] and job.get("_finished_at")
    assert sleeps == [] and ran == [], "it waited, or started the download"


def test_setup_still_running_keeps_the_download_waiting_until_ffmpeg_appears(slot):
    mod, exe, folder, job, ran, sleeps = slot.mod, slot.exe, slot.folder, slot.job, slot.ran, slot.sleeps
    slot.on_sleep = lambda n: (folder / exe).write_text("x") if n == 3 else None
    mod._run_download_slot("j1")
    assert ran == ["j1"] and len(sleeps) == 3 and job["status"] == "queued"


def test_setup_that_ends_while_a_download_waits_fails_it_without_waiting_longer(slot):
    mod, exe, folder, job, ran, sleeps = slot.mod, slot.exe, slot.folder, slot.job, slot.ran, slot.sleeps
    slot.on_sleep = lambda n: mod._ffmpeg_first_run.update(finished=True) if n == 2 else None
    mod._run_download_slot("j1")
    assert job["error_code"] == "ffmpeg_failed" and len(sleeps) == 2 and ran == []


def test_setup_that_never_ends_gives_up_after_180_seconds_as_still_being_set_up(slot):
    mod, exe, folder, job, ran, sleeps = slot.mod, slot.exe, slot.folder, slot.job, slot.ran, slot.sleeps
    mod._run_download_slot("j1")
    assert len(sleeps) == 180 and ran == []
    assert job["status"] == "error" and job["error_code"] == "ffmpeg_installing"
    assert "still being set up" in job["error"]


def test_ffmpeg_in_place_downloads_whatever_the_setup_said(slot):
    mod, exe, folder, job, ran, sleeps = slot.mod, slot.exe, slot.folder, slot.job, slot.ran, slot.sleeps
    (folder / exe).write_text("x")
    mod._ffmpeg_first_run["finished"] = True
    mod._run_download_slot("j1")
    assert ran == ["j1"] and sleeps == []


def test_cancel_while_waiting_still_cancels(slot):
    mod, exe, folder, job, ran, sleeps = slot.mod, slot.exe, slot.folder, slot.job, slot.ran, slot.sleeps
    slot.on_sleep = lambda n: job.update(cancelled=True) if n == 2 else None
    mod._run_download_slot("j1")
    assert job["status"] == "cancelled" and ran == []


@pytest.mark.parametrize("outcome", ["ok", "false", "none", "raises"])
def test_the_setup_thread_notes_that_it_ended_however_it_ended(backend, monkeypatch, outcome):
    mod, exe = backend
    monkeypatch.setitem(mod._ffmpeg_first_run, "finished", False)

    def fake():
        if outcome == "raises":
            raise RuntimeError("boom")
        return {"ok": True, "false": False, "none": None}[outcome]
    monkeypatch.setattr(mod, "ensure_ffmpeg", fake)
    try:
        mod._setup_ffmpeg_at_start()
    except RuntimeError:
        assert outcome == "raises"
    assert mod._ffmpeg_first_run["finished"] is True


@pytest.mark.parametrize("path", APP_FILES)
def test_the_start_up_thread_runs_the_noting_wrapper(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    assert re.search(r'threading\.Thread\(target=_setup_ffmpeg_at_start, daemon=True, name="ffmpeg-setup"\)\.start\(\)', src)
    assert "target=ensure_ffmpeg" not in src
