"""Livestream recordings: Stop and save, rescue after a failure, live progress.

Cancel (and any failed download) used to delete the partial file, so a long
recording was lost the moment it errored or was cancelled. For live streams
yt-dlp writes a single MPEG-TS .part file that stays playable even when the
process is killed, so the app now turns it into a normal file instead.
These tests pin the backend pieces in all three platform copies, the helper
against a real ffmpeg-made recording, and the strings."""
import glob
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import PLATFORM_APP_FILES, ROOT, read_source

FFMPEG = shutil.which("ffmpeg")
KEYS = ("card.badge.live", "card.status.recording", "card.btn.stop_save", "download.warning.live_partial")


def _helper_source(path):
    s = read_source(path)
    a = s.index("def _salvage_live_part(")
    return s[a:s.index("def _cleanup(", a)]


def test_each_platform_backend_has_the_live_pieces():
    for p in PLATFORM_APP_FILES:
        s = read_source(p)
        assert '@app.route("/api/stop/<job_id>"' in s, p
        assert '"is_live": bool(info.get("is_live"))' in s, f"{p}: /api/info must report is_live"
        assert '"live": bool(data.get("is_live"))' in s, f"{p}: the job must remember the live flag"
        assert 'resp["live_time"]' in s and 'resp["warning_key"]' in s, p
        # Rescue only ever runs for live jobs, and the old exit code test is gone
        assert 'if job.get("live") and (job.get("stop_keep") or rc != 0):' in s, p
        assert "if proc.returncode != 0:" not in s, p


def test_salvage_helper_is_identical_on_all_platforms():
    base = _helper_source("app.py")
    for p in PLATFORM_APP_FILES[1:]:
        assert _helper_source(p) == base, p


def test_frontend_sends_the_live_flag_and_has_the_button():
    for base in ("templates", "linux/templates"):
        dl = read_source(f"{base}/js/_download.html")
        bulk = read_source(f"{base}/js/_bulk.html")
        assert "is_live: !!item.info?.is_live" in dl and "is_live: !!item.info?.is_live" in bulk, base
        assert "addStopSave(item, n, cancelBtn)" in dl and "addStopSave(item, n, cancelBtn)" in bulk, base
        assert "/api/stop/${item.jobId}" in dl, base
    for f in ("js/_download.html", "js/_bulk.html", "index_styles.html"):
        assert read_source(f"templates/{f}") == read_source(f"linux/templates/{f}"), f


def test_new_strings_exist_in_every_locale():
    files = sorted(glob.glob(os.path.join(ROOT, "languages", "*.json")))
    assert len(files) >= 10
    for f in files:
        with open(f, encoding="utf-8") as fh:
            strings = json.load(fh)["strings"]
        for k in KEYS:
            assert isinstance(strings.get(k), str) and strings[k].strip(), f"{os.path.basename(f)}: missing {k}"


# ── routes ──────────────────────────────────────────────────────────────────
def _post(app_module, path):
    with app_module.app.test_client() as client:
        return client.post(path, headers={"X-EGM-Token": app_module._API_TOKEN})


def test_stop_route_refuses_unknown_and_non_live_jobs(app_module):
    assert _post(app_module, "/api/stop/nope_live").status_code == 404
    app_module.jobs["t_not_live"] = {"status": "downloading", "live": False, "proc": None}
    assert _post(app_module, "/api/stop/t_not_live").status_code == 400
    app_module.jobs["t_live_done"] = {"status": "done", "live": True, "proc": None}
    assert _post(app_module, "/api/stop/t_live_done").status_code == 400
    assert not app_module.jobs["t_not_live"].get("stop_keep")


def test_stop_route_flags_a_live_download_and_leaves_cancel_alone(app_module):
    app_module.jobs["t_live"] = {"status": "downloading", "live": True, "proc": None, "cancelled": False}
    assert _post(app_module, "/api/stop/t_live").status_code == 200
    job = app_module.jobs["t_live"]
    assert job["stop_keep"] is True and job["cancelled"] is False, "stop keeps the recording, cancel discards it"


def test_status_reports_live_progress_and_the_warning_key_only_when_present(app_module):
    app_module.jobs["t_status_live"] = {"status": "downloading", "live": True, "live_time": "00:01:05",
                                        "live_size": "512kB", "warning": "w", "warning_key": "download.warning.live_partial"}
    app_module.jobs["t_status_plain"] = {"status": "downloading", "warning": "old english only warning"}
    with app_module.app.test_client() as client:
        h = {"X-EGM-Token": app_module._API_TOKEN}
        live = client.get("/api/status/t_status_live", headers=h).get_json()
        plain = client.get("/api/status/t_status_plain", headers=h).get_json()
    assert live["live_time"] == "00:01:05" and live["live_size"] == "512kB"
    assert live["warning_key"] == "download.warning.live_partial" and live["warning"] == "w"
    assert "live_time" not in plain and "warning" not in plain, "non live jobs are unchanged"


# ── the rescue helper against a real recording ──────────────────────────────
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not installed")


def _make_ts_part(path, secs=2):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", str(secs), "-c:v", "libx264",
                    "-c:a", "aac", "-f", "mpegts", str(path)], check=True)


def _duration(path):
    r = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


@needs_ffmpeg
def test_salvage_turns_a_ts_part_into_a_playable_mp4(app_module, tmp_path):
    _make_ts_part(tmp_path / "j1.mp4.part")
    out = app_module._salvage_live_part("j1", tmp_path, FFMPEG, ".mp4")
    assert out and out.endswith("j1.mp4")
    assert 1.5 < _duration(out) < 3.5


@needs_ffmpeg
def test_salvage_survives_a_truncated_recording(app_module, tmp_path):
    # What a hard kill leaves: the file simply stops, mid packet.
    _make_ts_part(tmp_path / "j2.mp4.part", secs=4)
    p = tmp_path / "j2.mp4.part"
    p.write_bytes(p.read_bytes()[: int(p.stat().st_size * 0.6) + 77])
    out = app_module._salvage_live_part("j2", tmp_path, FFMPEG, ".mkv")
    assert out and out.endswith("j2.mkv") and _duration(out) > 1


@needs_ffmpeg
def test_salvage_audio_only_keeps_just_the_audio(app_module, tmp_path):
    _make_ts_part(tmp_path / "j3.mp4.part")
    out = app_module._salvage_live_part("j3", tmp_path, FFMPEG, ".mp4", audio_only=True)
    assert out and out.endswith("j3.m4a")
    r = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-show_entries", "stream=codec_type",
                        "-of", "csv=p=0", out], capture_output=True, text=True)
    assert r.stdout.split() == ["audio"]


@needs_ffmpeg
def test_salvage_refuses_when_there_is_nothing_safe_to_keep(app_module, tmp_path):
    assert app_module._salvage_live_part("none", tmp_path, FFMPEG, ".mp4") is None, "no .part"
    (tmp_path / "e.mp4.part").write_bytes(b"")
    assert app_module._salvage_live_part("e", tmp_path, FFMPEG, ".mp4") is None, "empty .part"
    _make_ts_part(tmp_path / "m.f1.mp4.part"); _make_ts_part(tmp_path / "m.f2.mp4.part")
    assert app_module._salvage_live_part("m", tmp_path, FFMPEG, ".mp4") is None, "separate video and audio parts cannot be rejoined"
    _make_ts_part(tmp_path / "g.mp4.part")
    assert app_module._salvage_live_part("g", tmp_path, tmp_path / "no-such-ffmpeg", ".mp4") is None, "ffmpeg missing"
    (tmp_path / "bad.mp4.part").write_bytes(b"not a video" * 50)
    assert app_module._salvage_live_part("bad", tmp_path, FFMPEG, ".mp4") is None, "garbage"
    assert not (tmp_path / "bad.mp4").exists(), "a failed attempt leaves no half written output"
