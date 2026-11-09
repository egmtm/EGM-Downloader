"""The download worker ends every job, and Cancel stops the conversion step too.

* Anything raised before run_download's own error handling (for example the cookies file
  removed at that moment) ended the worker with the job still "queued": the card spun, Cancel
  answered success but changed nothing, the job never left the list and "Quit when done" waited
  for it forever.
* Cancel pressed while ffprobe or the hardware probe ran found no process to kill, so the whole
  H.264 encode and then the upscale encode still ran, and the cancelled job showed "The H.264
  conversion failed".
yt-dlp, ffprobe and ffmpeg are fakes here; nothing runs or is fetched.
"""
import importlib.util
import io
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_worker_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


class _Proc:
    pid = 4343

    def __init__(self, out_lines=(), on_start=None, binary=False):
        if on_start:
            on_start()
        text = "".join(l + "\n" for l in out_lines)
        self.stdout = io.BytesIO(text.encode()) if binary else io.StringIO(text)
        self.stderr = io.BytesIO(b"") if binary else io.StringIO("")
        self.returncode = None

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def kill(self):
        pass


@pytest.fixture
def rig(backend, tmp_path, monkeypatch):
    out = tmp_path / "downloads"
    out.mkdir()
    ff = tmp_path / "ffmpeg_bin"
    ff.mkdir()
    exe = ".exe" if Path(backend.__file__).resolve() == ROOT / "app.py" else ""
    for n in ("ffmpeg", "ffprobe"):
        (ff / f"{n}{exe}").write_text("")
    monkeypatch.setattr(backend, "FFMPEG_DIR", ff)
    for name in ("HISTORY_FILE", "SETTINGS_FILE"):
        monkeypatch.setattr(backend, name, tmp_path / Path(getattr(backend, name)).name)
    monkeypatch.setattr(backend, "_settings_cache", {"upscale_to_quality": True})
    monkeypatch.setattr(backend, "_fetch_thumbnail", lambda *a: b"")
    monkeypatch.setattr(backend, "_detect_hw_encoder", lambda: (None, None))
    monkeypatch.setattr(backend, "_kill_proc", lambda p: None)
    job_id = "0123456789"
    job = {"status": "queued", "url": "https://example.invalid/v", "title": "T", "proc": None,
           "cancelled": False, "live": False}
    backend.jobs[job_id] = job
    yield backend, job_id, job, out
    backend.jobs.pop(job_id, None)


def test_an_error_before_the_download_starts_ends_the_job(rig, monkeypatch):
    backend, job_id, job, out = rig

    def cookies_gone():
        raise FileNotFoundError(2, "No such file or directory")
    monkeypatch.setattr(backend, "_cookies_args", cookies_gone)
    backend._run_download_slot(job_id, "https://example.invalid/v", "video", None, str(out))
    assert job["status"] == "error" and job.get("_finished_at"), job
    assert job.get("error")


def test_cancel_while_the_file_is_probed_starts_no_encode(rig, monkeypatch):
    backend, job_id, job, out = rig
    monkeypatch.setattr(backend, "_popen_yt", lambda *a, **k: _Proc(
        ["[download] 100% of 1.00MiB"], on_start=lambda: (out / f"{job_id}.mp4").write_bytes(b"x" * 5000)))

    def fake_run(*cmd, timeout=None, **kw):
        line = " ".join(map(str, cmd))
        if "codec_name" in line:
            job["cancelled"] = True           # the user presses Cancel while ffprobe runs
            return subprocess.CompletedProcess(list(cmd), 0, "vp9\n", "")
        if "width,height" in line:
            return subprocess.CompletedProcess(list(cmd), 0, "640,360\n", "")
        return subprocess.CompletedProcess(list(cmd), 0, "100.0\n", "")
    monkeypatch.setattr(backend, "_run", fake_run)
    encodes = []

    def fake_popen(*cmd, **kw):
        encodes.append(Path(cmd[-1]).name)
        return _Proc(on_start=lambda: Path(cmd[-1]).write_bytes(b"y"), binary=True)
    monkeypatch.setattr(backend, "_popen", fake_popen)
    backend.run_download(job_id, "https://example.invalid/v", "video", None, str(out),
                         video_height=1080, output_format="mp4_h264")
    assert encodes == [], f"encodes started after Cancel: {encodes}"
    assert job["status"] == "cancelled" and not job.get("warning"), job
