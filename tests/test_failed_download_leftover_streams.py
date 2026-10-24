"""
A download that failed partway must not be reported as saved because one stream of it is on disk.

yt-dlp downloads a video and its audio as separate files ({job_id}.f137.mp4, {job_id}.f140.m4a)
and merges them into {job_id}.mp4 at the end. When it exits with an error, run_download looks for a
finished file to deliver anyway (the case where only a late step such as a thumbnail failed). It used
to take any {job_id}.* file with the wanted extension, so a video stream without its audio
({job_id}.f137.mp4) was delivered as a finished download, and the audio stream was left in the folder
under its temporary name. Per format files are now never taken for the finished file.

All three backends run their real run_download against a fake yt-dlp (a small Python process that
writes the files and exits with an error). Nothing is downloaded.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")
JOB = "abc1234567"
TITLE = "My Chosen Title"


@pytest.fixture(scope="module", params=APP_FILES)
def app(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    # Linux and Mac create their data folders at import: point them at a temporary home.
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_failed_download_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


def _run_failed(app, monkeypatch, tmp_path, files):
    """Run a download whose yt-dlp leaves `files` in the folder and exits with an error.
    Returns (the job, the names left in the folder)."""
    out = tmp_path / "out"
    out.mkdir()
    app.jobs[JOB] = {"status": "queued", "url": "https://example.invalid/v", "title": TITLE,
                     "proc": None, "cancelled": False, "download_dir": str(out), "format": "video"}
    code = ("import sys\n"
            f"d = {str(out)!r}\n"
            f"for f in {list(files)!r}:\n"
            "    open(d + '/' + f, 'wb').write(b'x' * 1000)\n"
            "sys.stderr.write('ERROR: unable to download video data: HTTP Error 403: Forbidden\\n')\n"
            "sys.exit(1)\n")
    keep = ("stdout", "stderr", "text", "encoding", "errors")
    monkeypatch.setattr(app, "_popen_yt", lambda *cmd, **kw: subprocess.Popen(
        [sys.executable, "-c", code], **{k: v for k, v in kw.items() if k in keep}))
    monkeypatch.setattr(app, "HISTORY_FILE", tmp_path / "history.json")   # a delivered file is logged
    try:
        app.run_download(JOB, "https://example.invalid/v", "video", "137", str(out),
                         "", 1, "320", None, False, True, "mp4_h264")
        job = dict(app.jobs[JOB])
    finally:
        app.jobs.pop(JOB, None)
    return job, sorted(p.name for p in out.iterdir())


def test_a_video_stream_without_its_audio_is_not_a_finished_download(app, monkeypatch, tmp_path):
    job, left = _run_failed(app, monkeypatch, tmp_path, [f"{JOB}.f137.mp4", f"{JOB}.f140.m4a.part"])
    assert job["status"] == "error" and "403" in job["error"]
    assert left == []


@pytest.mark.parametrize("stream", ["fhls-1080p.mp4", "fdash-video_1080p.mp4", "f1080p.0.mp4", "f137.temp.mp4"],
                         ids=["hls id", "dash id", "id with a dot", "temp piece"])
def test_a_stream_is_never_the_finished_file_whatever_its_format_id_looks_like(app, monkeypatch, tmp_path, stream):
    """The finished file is exactly {job_id}.{ext}; a format id is not always digits (hls-1080p, dash-video_1080p,
    ids with a dot), so the rule must not depend on the id's shape."""
    job, left = _run_failed(app, monkeypatch, tmp_path, [f"{JOB}.{stream}", f"{JOB}.f140.m4a"])
    assert job["status"] == "error", job
    assert left == []


def test_two_unmerged_streams_are_an_error_and_leave_nothing_behind(app, monkeypatch, tmp_path):
    job, left = _run_failed(app, monkeypatch, tmp_path, [f"{JOB}.f137.mp4", f"{JOB}.f140.m4a"])
    assert job["status"] == "error"
    assert left == [], "a stream was left in the folder under its temporary name"


def test_a_merged_file_is_still_delivered_when_only_a_late_step_failed(app, monkeypatch, tmp_path):
    """The case the branch exists for: the merge worked, the thumbnail or tags step then failed."""
    job, left = _run_failed(app, monkeypatch, tmp_path, [f"{JOB}.mp4", f"{JOB}.webp"])
    assert job["status"] == "done" and job["filename"] == f"{TITLE}.mp4"
    assert left == [f"{TITLE}.mp4"]
