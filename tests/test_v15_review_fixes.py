"""Regression tests for the v1.5 delta review (live recording, Quit when done,
imported settings). Each test drives the real code path that was wrong.

  - A live AUDIO job that was stopped or interrupted is delivered as the saved
    recording, not as whatever file came first in the directory listing.
  - Retry runs that recorded nothing leave no litter in the download folder.
  - /api/settings/save validates last_folder before it touches the disk (it
    also receives the settings object of an imported export file).
  - The startup cleanup removes only the app's own partial files.
  - Console notes redact links of every scheme, not only http(s).
  - The /api/stop route is identical on all three platforms.
"""
import glob as _glob
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from conftest import PLATFORM_APP_FILES, read_source

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg not installed")


# ── live audio: the saved recording is what gets delivered ───────────────────
class _StoppedLiveRun:
    """Stands in for yt-dlp after Stop and save: what the real one leaves behind
    is the MPEG-TS .part it was recording and the thumbnail it wrote first for
    --embed-thumbnail."""
    def __init__(self, out_dir, job_id):
        part = Path(out_dir) / f"{job_id}.mp4.part"
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                        "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264",
                        "-c:a", "aac", "-f", "mpegts", str(part)], check=True)
        (Path(out_dir) / f"{job_id}.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPthumb")
        self.stdout, self.stderr, self.returncode, self.pid = [], ["size=  64KiB time=00:00:02.00 bitrate=1\n"], None, 0

    def wait(self):
        self.returncode = -15
        return -15

    def poll(self):
        return self.returncode


@needs_ffmpeg
@pytest.mark.parametrize("audio_quality", ["320", "flac", "opus_128"])
def test_stopped_live_audio_job_delivers_the_recording(app_module, monkeypatch, tmp_path, audio_quality):
    """Before the fix the salvage (.m4a) never matched the wanted extension
    (.mp3/.flac/.opus), so run_download took files[0] in directory order and
    deleted every other file -- in a measured run, 10 of 12 jobs were delivered
    as the thumbnail or the raw .part and the recording itself was deleted.
    Directory order is filesystem dependent, so the worst legal order (reverse
    sorted: .webp before .part before .m4a) is forced here."""
    ff_dir = tmp_path / "ffbin"; ff_dir.mkdir()
    os.symlink(FFMPEG, ff_dir / "ffmpeg.exe"); os.symlink(FFPROBE, ff_dir / "ffprobe.exe")
    monkeypatch.setattr(app_module, "FFMPEG_DIR", ff_dir)
    real_glob = _glob.glob
    monkeypatch.setattr(app_module.glob, "glob", lambda p, *a, **k: sorted(real_glob(p, *a, **k), reverse=True))
    out_dir = tmp_path / "dl"; out_dir.mkdir()
    job_id = uuid.uuid4().hex[:10]
    monkeypatch.setattr(app_module, "_popen_yt", lambda *c, **k: _StoppedLiveRun(out_dir, job_id))
    monkeypatch.setattr(app_module, "_live_is_still_live", lambda job, url: False)
    monkeypatch.setattr(app_module, "_append_history", lambda *a, **k: None)
    app_module.jobs[job_id] = {"status": "queued", "url": "https://example.invalid/live", "title": "My Stream",
                               "proc": None, "cancelled": False, "download_dir": str(out_dir), "format": "audio",
                               "thumbnail": "", "live": True, "stop_keep": True}
    try:
        app_module.run_download(job_id, "https://example.invalid/live", "audio", None, str(out_dir),
                                audio_quality=audio_quality)
        job = app_module.jobs[job_id]
    finally:
        app_module.jobs.pop(job_id, None)
    assert job["status"] == "done", job.get("error")
    delivered = Path(job["file"])
    assert delivered.suffix == ".m4a", f"delivered {delivered.name}, not the recording"
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(delivered)],
                       capture_output=True, text=True)
    assert r.stdout.split() == ["audio"], "the delivered file is the audio recording"
    assert sorted(p.name for p in out_dir.iterdir()) == ["My Stream.m4a"], "no .part, no thumbnail left behind"


def test_a_retry_that_records_nothing_leaves_no_litter(app_module, monkeypatch, tmp_path):
    (tmp_path / "j.m4a").write_bytes(b"x" * 100)

    def attempt(job, job_id, cmd, base_s, base_kib):
        (tmp_path / "j_r2.webp").write_bytes(b"thumb")       # audio jobs write this first
        (tmp_path / "j_r2.mp4.part").write_bytes(b"")
        return 1
    monkeypatch.setattr(app_module, "_live_wait", lambda job, s: True)
    monkeypatch.setattr(app_module, "_live_is_still_live", lambda job, url: True)
    monkeypatch.setattr(app_module, "_run_live_attempt", attempt)
    monkeypatch.setattr(app_module, "_live_av_note", lambda *a: None)
    job = {"live_time": "00:00:10", "live_size": "10KiB"}
    out_tmpl = str(tmp_path / "j.%(ext)s")
    assert app_module._live_finish(job, "j", tmp_path, ["yt-dlp", "-o", out_tmpl, "u"], out_tmpl, "u",
                                   "/nonexistent/ffmpeg", ".mp4", True, 0) == "saved"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["j.m4a"]
    assert job["_live_file"] == str(tmp_path / "j.m4a")


# ── imported settings: last_folder ───────────────────────────────────────────
def _save(app_module, monkeypatch, payload):
    saved = {}
    monkeypatch.setattr(app_module, "_save_settings", lambda d: saved.update(d))
    with app_module.app.test_client() as c:
        r = c.post("/api/settings/save", json=payload, headers={"X-EGM-Token": app_module._API_TOKEN})
    assert r.status_code == 200
    return saved


def test_last_folder_is_validated_before_it_is_created_or_stored(app_module, monkeypatch, tmp_path):
    target = tmp_path / "nested" / "from-an-import"
    seen = []

    def reject(path):
        seen.append(path)
        return False, "", "resolves to a system path"
    monkeypatch.setattr(app_module, "_validate_download_dir", reject)
    saved = _save(app_module, monkeypatch, {"last_folder": str(target), "concurrency": 3})
    assert seen == [str(target)], "the folder goes through the download-folder check"
    assert not target.exists(), "a rejected folder must not be created"
    assert "last_folder" not in saved and saved.get("concurrency") == 3, "rejected key dropped, the rest kept"


def test_a_valid_last_folder_is_created_and_stored_resolved(app_module, monkeypatch, tmp_path):
    target = tmp_path / "new" / "downloads"
    saved = _save(app_module, monkeypatch, {"last_folder": str(target)})
    assert target.is_dir()
    assert saved["last_folder"] == str(target.resolve())


@pytest.mark.parametrize("bad", [{"x": 1}, ["/tmp"], 42])
def test_a_non_string_last_folder_is_not_stored(app_module, monkeypatch, bad):
    assert "last_folder" not in _save(app_module, monkeypatch, {"last_folder": bad})


def test_startup_cleanup_removes_only_this_apps_own_partials(app_module, tmp_path):
    ours = ["0123456789.mp4.part", "abcdef0123_r2.mp4.part", "abcdef0123.mp4.ytdl"]
    theirs = ["Firefox Setup.exe.part", "holiday.mp4.part", "notes.ytdl", "ABCDEF0123.mp4.part", "012345678.mp4.part"]
    for n in ours + theirs:
        (tmp_path / n).write_bytes(b"x")
    app_module._cleanup_orphan_partials(str(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(theirs)
    app_module._cleanup_orphan_partials({"not": "a path"})   # an imported value of the wrong type: no exception


# ── Console notes ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("line,secret", [
    ("[tcp @ 0x8] Connection to tcp://edge-SECRET.cdn.example:443 failed: Connection refused", "SECRET"),
    ("WARNING: [x] Failed to download m3u8 information: rtmp://ingest.example/app/SECRET timed out", "SECRET"),
    ("[hls @ 0x5] Error when loading first segment 'https://cdn.example/s.ts?sig=AB'SECRET'", "SECRET"),
    ("[hls @ 0x5] keepalive request failed for 'https://cdn.example/a.m3u8?token=SECRET' with error", "SECRET"),
])
def test_console_notes_redact_links_of_every_scheme(app_module, line, secret):
    note = app_module._live_note(line)
    assert note and secret not in note and "<url>" in note, note


# ── parity: the stop route ───────────────────────────────────────────────────
def _route_body(src, name):
    start = src.index(f"def {name}(")
    end = src.index("\n@app.route", start)
    return src[start:end]


def test_stop_route_is_identical_on_all_platforms():
    """The live helpers are compared across the three app.py files, the route
    was not: weakening the live/downloading guard in mac/app.py alone left the
    whole suite green."""
    base = _route_body(read_source(PLATFORM_APP_FILES[0]), "stop_and_keep")
    assert 'if not job.get("live") or job.get("status") != "downloading":' in base
    for p in PLATFORM_APP_FILES[1:]:
        assert _route_body(read_source(p), "stop_and_keep") == base, p


# ── salvage time limit ───────────────────────────────────────────────────────
def test_salvage_time_limit_grows_with_the_recording(app_module, monkeypatch, tmp_path):
    """The stream copy used a fixed 600 s limit. Measured here at ~7 s per GiB on
    a fast disk, a 10 GiB recording on a ~30 MB/s external drive needs far longer,
    and a timed-out salvage left nothing to keep, so Stop and save deleted the
    whole recording. The limit now scales with the .part size."""
    part = tmp_path / "abcdef0123.mp4.part"
    with open(part, "wb") as fh:                      # sparse: 10 GiB that costs no disk
        fh.truncate(10 * 1024 ** 3)
    ff = tmp_path / "ffmpeg"; ff.write_bytes(b"")
    seen = {}

    def fake_run(*cmd, timeout=None, **kw):
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(app_module, "_run", fake_run)
    assert app_module._salvage_live_part("abcdef0123", tmp_path, ff, ".mp4") is None
    assert seen["timeout"] >= 600 + 5000, seen
    assert part.exists(), "a failed salvage never touches the recording itself"
