"""Live recordings carry on after the stream drops.

When a stream's server errors for even a few seconds, ffmpeg's HLS reader gives
up and exits as if the stream had ended (usually exit code 0), so the recording
used to stop early. After every live run the app now asks yt-dlp whether the
stream is still live and, if so, records again (up to 5 more times) and joins
the pieces into one file. These tests pin the helpers, the driver loop (with
the yt-dlp runs replaced by stand ins), and the join against real ffmpeg."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import PLATFORM_APP_FILES, read_source

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg not installed")


# ── small helpers ────────────────────────────────────────────────────────────
def test_size_and_time_helpers(app_module):
    f = app_module._live_size_kib
    assert (f("364544KiB"), f("512kB"), f("1.5MiB"), f("2GiB")) == (364544, 512, 1536, 2 * 1024 * 1024)
    assert f("N/A") is None and f("") is None and f(None) is None
    assert app_module._live_hms_to_s("01:02:05") == 3725
    assert app_module._live_s_to_hms(3725) == "01:02:05"
    assert app_module._live_s_to_hms(app_module._live_hms_to_s("00:00:00")) == "00:00:00"


def test_console_notes_never_carry_a_stream_link(app_module):
    note = app_module._live_note("[hls @ 0x1] keepalive request failed for 'https://cdn.example/a/seg1.ts?token=SECRET' with error: x")
    assert "SECRET" not in note and "https://" not in note and "<url>" in note
    assert app_module._live_note("Opening 'https://cdn.example/seg.ts' for reading") == "", "segment opens are noise"
    assert app_module._live_note("frame=1 fps=25 q=-1.0 size=1kB time=00:00:01") == "", "not an error line"
    assert app_module._live_note("   ") == ""


def test_console_notes_keep_each_input_start_time_without_the_link(app_module):
    # with a separate video and audio input, the difference of the two start values is the A/V offset
    a = app_module._live_note("Input #0, hls, from 'https://cdn.example/v/index.m3u8?token=SECRET':")
    assert a.startswith("Input #0") and "SECRET" not in a and "https://" not in a and "<url>" in a
    b = app_module._live_note("  Duration: N/A, start: 5273.250000, bitrate: N/A")
    assert b == "Duration: N/A, start: 5273.250000, bitrate: N/A"
    assert app_module._live_note("  Stream #0:0: Video: h264 (High), yuv420p(tv), 1280x720, 30 fps") == "", "stream lines stay out"
    assert app_module._live_note("Output #0, mpegts, to 'D:\\x.part':") == "", "only the inputs"


# ── is the stream still live ─────────────────────────────────────────────────
class _Proc:
    def __init__(self, out="", err="", rc=0, hang=False):
        self.out, self.err, self.returncode, self.hang, self.killed = out, err, rc, hang, False

    def communicate(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("yt-dlp", timeout)
        return self.out, self.err

    def kill(self):
        self.killed = True


def _probe(app_module, monkeypatch, proc, job=None):
    job = job if job is not None else {}
    monkeypatch.setattr(app_module, "_popen_yt", lambda *a, **k: proc)
    monkeypatch.setattr(app_module, "_kill_proc", lambda p: p.kill())
    return app_module._live_is_still_live(job, "https://example.com/live"), job


@pytest.mark.parametrize("out,err,rc,want", [
    (json.dumps({"is_live": True}), "", 0, True),
    (json.dumps({"is_live": False}), "", 0, False),
    ("", "ERROR: [youtube] abc: Private video. Sign in if you have been granted access", 1, False),
    ("", "ERROR: X is not currently live", 1, False),
    ("", "ERROR: Unable to download webpage: Connection reset by peer", 1, None),
    ("", "ERROR: HTTP Error 503", 1, None),
    ("not json", "", 0, None),
    ("", "", 0, None),
])
def test_probe_answers(app_module, monkeypatch, out, err, rc, want):
    answer, job = _probe(app_module, monkeypatch, _Proc(out, err, rc))
    assert answer is want
    assert job["proc"] is None, "the probe must not stay registered as the job's process"


def test_probe_ends_at_once_when_the_user_cancels(app_module, monkeypatch):
    proc = _Proc(hang=True)
    answer, job = _probe(app_module, monkeypatch, proc, {"cancelled": True})
    assert answer is None and proc.killed and job["proc"] is None


class _Run:
    stdout, stderr, returncode = [], ["size=  10kB time=00:00:02.00 bitrate=1kbits/s\n", "keepalive request failed for https://cdn.example/s.ts?t=SECRET\n"], 0

    def wait(self):
        pass


def test_new_runs_get_their_own_process_group_so_cancel_cannot_take_the_app_down(app_module, monkeypatch):
    """Cancel and Stop and save kill a run's whole process group (Linux and macOS). A run sharing the
    app's own group would SIGTERM Flask and Electron with it; the first end to end test of this
    feature died exactly like that at Stop."""
    seen = []
    monkeypatch.setattr(app_module, "_popen_yt", lambda *a, **k: seen.append(k) or (_Proc(json.dumps({"is_live": True})) if "-j" in a else _Run()))
    app_module._live_is_still_live({}, "https://example.com/live")
    job = {}
    app_module._run_live_attempt(job, "jx", ["yt-dlp", "u"], 0, 0)
    assert len(seen) == 2 and all(k.get("start_new_session") is True for k in seen)


def test_a_new_run_carries_the_time_and_size_on_and_logs_no_links(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "_popen_yt", lambda *a, **k: _Run())
    logged = []
    monkeypatch.setattr(app_module, "_yt_log", logged.append)
    job = {"live_reconnecting": 1}
    assert app_module._run_live_attempt(job, "jy", ["yt-dlp", "u"], 15, 600) == 0
    assert job["live_time"] == "00:00:17" and job["live_size"] == "610KiB"
    assert "live_reconnecting" not in job and job["proc"] is None
    assert logged and all("SECRET" not in m and "https://" not in m for m in logged)


# ── collecting and joining pieces (real ffmpeg) ──────────────────────────────
def _make_mp4(path, secs=2, freq=440):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                    "-f", "lavfi", "-i", f"sine=frequency={freq}", "-t", str(secs), "-c:v", "libx264",
                    "-c:a", "aac", "-movflags", "+faststart", str(path)], check=True)


def _duration(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


@needs_ffmpeg
def test_collect_prefers_a_finished_file_and_skips_leftovers(app_module, tmp_path):
    _make_mp4(tmp_path / "j_r2.mp4")
    _make_mp4(tmp_path / "j_r2.f137.mp4"); (tmp_path / "j_r2.temp.mp4").write_bytes(b"x" * 10)
    assert app_module._live_collect("j_r2", tmp_path, FFMPEG, ".mp4", False) == str(tmp_path / "j_r2.mp4")
    assert app_module._live_collect("nothing", tmp_path, FFMPEG, ".mp4", False) is None


@needs_ffmpeg
def test_join_adds_the_durations_and_leaves_one_file(app_module, tmp_path):
    a, b, c = (tmp_path / n for n in ("j.mp4", "j_r2.mp4", "j_r3.mp4"))
    _make_mp4(a, 2); _make_mp4(b, 3, 550); _make_mp4(c, 1, 660)
    assert app_module._live_join("j", tmp_path, [str(a), str(b), str(c)], FFMPEG) is True
    assert 5.5 < _duration(a) < 6.6, "the first piece's file now holds all three"
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith("j_r")) == ["j.mp4"], "no list or temp file left"


@needs_ffmpeg
def test_join_refuses_mixed_extensions_and_a_missing_ffmpeg_and_changes_nothing(app_module, tmp_path):
    a, b = tmp_path / "j.mp4", tmp_path / "j_r2.mkv"
    _make_mp4(a, 2); _make_mp4(b, 2)
    before = a.read_bytes()
    assert app_module._live_join("j", tmp_path, [str(a), str(b)], FFMPEG) is False
    b2 = tmp_path / "j_r2.mp4"; _make_mp4(b2, 2)
    assert app_module._live_join("j", tmp_path, [str(a), str(b2)], tmp_path / "no-such-ffmpeg") is False
    b2.write_bytes(b"not a video" * 20)
    assert app_module._live_join("j", tmp_path, [str(a), str(b2)], FFMPEG) is False, "a broken piece"
    assert a.read_bytes() == before, "the first piece is untouched when a join fails"
    assert not (tmp_path / "j_join.mp4").exists() and not (tmp_path / "j_join.txt").exists()


@needs_ffmpeg
def test_join_fails_when_the_result_is_shorter_than_the_pieces(app_module, monkeypatch, tmp_path):
    """The concat reader exits 0 even when it silently skips a piece, so the length is checked."""
    a, b = tmp_path / "j.mp4", tmp_path / "j_r2.mp4"
    _make_mp4(a, 2); _make_mp4(b, 2)
    before = a.read_bytes()
    lengths = {"j.mp4": 2.0, "j_r2.mp4": 2.0, "j_join.mp4": 2.0}   # the joined file holds only one piece's worth
    monkeypatch.setattr(app_module, "_media_duration_s", lambda probe, path: lengths[Path(path).name])
    assert app_module._live_join("j", tmp_path, [str(a), str(b)], FFMPEG) is False
    assert a.read_bytes() == before and not (tmp_path / "j_join.mp4").exists()
    lengths["j_join.mp4"] = 3.9
    assert app_module._live_join("j", tmp_path, [str(a), str(b)], FFMPEG) is True


@needs_ffmpeg
def test_av_note_logs_each_streams_start_and_length_and_never_raises(app_module, monkeypatch, tmp_path):
    _make_mp4(tmp_path / "a.mp4", 2)
    logged = []
    monkeypatch.setattr(app_module, "_egm_log", logged.append)
    app_module._live_av_note(FFMPEG, "saved", tmp_path / "a.mp4")
    assert len(logged) == 1 and "(saved," in logged[0] and "video|" in logged[0] and "audio|" in logged[0]
    app_module._live_av_note(FFMPEG, "x", tmp_path / "missing.mp4")
    app_module._live_av_note(tmp_path / "no-ffmpeg", "x", tmp_path / "a.mp4")
    assert len(logged) == 1, "nothing logged when there is nothing to report, and no exception"


def _make_mp4_sized(path, size, rate=25):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(path)], check=True)


@needs_ffmpeg
def test_join_refuses_pieces_whose_video_size_or_codec_changed(app_module, tmp_path):
    """A stream copy writes one header for the whole file; the first piece's size would be declared
    for a later piece that is bigger. (Measured: ffmpeg joins them without complaint.)"""
    a, b = tmp_path / "j.mp4", tmp_path / "j_r2.mp4"
    _make_mp4_sized(a, "320x180"); _make_mp4_sized(b, "640x360")
    before = a.read_bytes()
    assert app_module._live_join("j", tmp_path, [str(a), str(b)], FFMPEG) is False
    assert a.read_bytes() == before and not (tmp_path / "j_join.mp4").exists()
    _make_mp4_sized(b, "320x180")
    assert app_module._live_join("j", tmp_path, [str(a), str(b)], FFMPEG) is True


@needs_ffmpeg
def test_join_signature_ignores_cover_art_but_sees_audio_changes(app_module, tmp_path):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=1", "-frames:v", "1", str(tmp_path / "c.png")], check=True)
    plain, art, stereo = tmp_path / "a.m4a", tmp_path / "b.m4a", tmp_path / "c.m4a"
    base = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1"]
    subprocess.run(base + ["-c:a", "aac", str(plain)], check=True)
    subprocess.run(base + ["-i", str(tmp_path / "c.png"), "-map", "0:a", "-map", "1:v", "-c:a", "aac", "-c:v", "copy",
                           "-disposition:v:0", "attached_pic", str(art)], check=True)
    subprocess.run(base + ["-ac", "2", "-c:a", "aac", str(stereo)], check=True)
    sig = lambda p: app_module._live_signature(FFMPEG, p)
    assert sig(plain) and sig(plain) == sig(art), "a cover picture is not a stream difference"
    assert sig(plain) != sig(stereo)
    assert sig(tmp_path / "missing.m4a") is None


# ── the driver loop, with the yt-dlp runs replaced ───────────────────────────
class _Rig:
    """Stands in for yt-dlp: `lives` answers the probes in order, `captures` says what each
    new run records (a file name, or None when it records nothing). `run_s` is how many
    seconds each new run records (one number, or one per run, the last one repeating)."""
    def __init__(self, app_module, monkeypatch, tmp_path, lives, captures, first="j.mp4", attempt_rc=0, join_ok=True, run_s=0):
        self.am, self.tmp, self.lives, self.captures = app_module, tmp_path, list(lives), list(captures)
        self.waits, self.probes, self.attempts, self.joined, self.job = [], 0, [], [], {"live_time": "00:00:15", "live_size": "594KiB"}
        self.first, self.attempt_rc, self.join_ok = first, attempt_rc, join_ok
        self.run_s = list(run_s) if isinstance(run_s, (list, tuple)) else [run_s]
        monkeypatch.setattr(app_module, "_live_wait", self.wait)
        monkeypatch.setattr(app_module, "_live_is_still_live", self.probe)
        monkeypatch.setattr(app_module, "_run_live_attempt", self.attempt)
        monkeypatch.setattr(app_module, "_live_collect", self.collect)
        monkeypatch.setattr(app_module, "_live_join", self.join)
        self.notes = []
        monkeypatch.setattr(app_module, "_live_av_note", lambda ff, label, path: self.notes.append(label))

    def wait(self, job, secs):
        self.waits.append(secs)
        return not (job.get("cancelled") or job.get("stop_keep"))

    def probe(self, job, url):
        self.probes += 1
        return self.lives.pop(0) if self.lives else True

    def attempt(self, job, job_id, cmd, base_s, base_kib):
        self.attempts.append((cmd, base_s, base_kib, dict(job)))
        secs = self.run_s[min(len(self.attempts), len(self.run_s)) - 1]
        if secs:
            job["live_time"] = self.am._live_s_to_hms(base_s + secs)
        return self.attempt_rc

    def collect(self, sid, out_dir, ffmpeg, want_ext, audio_only):
        if sid == "j":
            return str(self.tmp / self.first) if self.first else None
        n = len(self.attempts)
        name = self.captures[n - 1] if n <= len(self.captures) else None
        return str(self.tmp / name) if name else None

    def join(self, job_id, out_dir, segs, ffmpeg):
        self.joined.append(list(segs))
        return self.join_ok

    def run(self, rc=0):
        out_tmpl = str(self.tmp / "j.%(ext)s")
        cmd = ["yt-dlp", "-o", out_tmpl, "https://example.com/live"]
        self.result = self.am._live_finish(self.job, "j", self.tmp, cmd, out_tmpl, "https://example.com/live", FFMPEG, ".mp4", False, rc)
        return self.result


def test_a_clean_end_of_stream_is_not_retried(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[False], captures=[])
    assert rig.run(rc=0) == "saved"
    assert rig.notes == ["saved"]
    assert rig.attempts == [] and rig.joined == [] and "warning_key" not in rig.job


def test_an_error_exit_on_a_finished_stream_keeps_the_recording_with_the_partial_note(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[False], captures=[])
    assert rig.run(rc=1) == "saved"
    assert rig.job["warning_key"] == "download.warning.live_partial" and rig.attempts == []


def test_a_cut_stream_is_recorded_again_and_the_pieces_are_joined(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"])
    assert rig.run(rc=0) == "saved"
    cmd, base_s, base_kib, job_then = rig.attempts[0]
    assert str(tmp_path / "j_r2.%(ext)s") in cmd and str(tmp_path / "j.%(ext)s") not in cmd, "the new run writes its own piece"
    assert (base_s, base_kib) == (15, 594), "time and size carry on from the first piece"
    assert job_then["live_reconnecting"] == 1 and job_then["live_retries_max"] == 5
    assert rig.joined == [[str(tmp_path / "j.mp4"), str(tmp_path / "j_r2.mp4")]]
    assert rig.job["warning_key"] == "download.warning.live_gap"
    assert rig.notes == ["piece 1", "piece 2", "saved"], "the A/V numbers are logged for each piece and for the result"
    assert "live_reconnecting" not in rig.job and "live_retries_max" not in rig.job, "the card status is cleared"


def test_it_gives_up_after_five_more_runs(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True] * 20, captures=[f"j_r{i}.mp4" for i in range(2, 9)])
    assert rig.run() == "saved"
    assert len(rig.attempts) == 5 and len(rig.joined[0]) == 6
    assert [a[0][2].endswith(f"j_r{i}.%(ext)s") for a, i in zip(rig.attempts, range(2, 7))] == [True] * 5, "each run has its own piece name"


def test_a_reconnect_that_keeps_recording_starts_the_count_again(app_module, monkeypatch, tmp_path):
    # Six drops over a long recording, each followed by a run that lasts the full minute:
    # every one is "1 of 5" again, and no piece name is used twice.
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True] * 6 + [False],
               captures=[f"j_r{i}.mp4" for i in range(2, 8)], run_s=60)
    assert rig.run() == "saved"
    assert [a[3]["live_reconnecting"] for a in rig.attempts] == [1] * 6
    assert [a[0][2].endswith(f"j_r{i}.%(ext)s") for a, i in zip(rig.attempts, range(2, 8))] == [True] * 6
    assert len(rig.joined[0]) == 7


def test_only_a_run_that_lasted_a_minute_starts_the_count_again(app_module, monkeypatch, tmp_path):
    # One good run resets the count; then five runs just under a minute (59 s) use it up.
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True] * 20,
               captures=[f"j_r{i}.mp4" for i in range(2, 12)], run_s=[120, 59])
    assert rig.run() == "saved"
    assert [a[3]["live_reconnecting"] for a in rig.attempts] == [1, 1, 2, 3, 4, 5]
    assert len(rig.joined[0]) == 7


def test_an_unclear_answer_is_asked_again_a_few_times_then_the_recording_is_kept(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[None, None, None, None, True], captures=["j_r2.mp4"])
    assert rig.run() == "saved"
    assert rig.attempts == [] and rig.probes == 4, "no endless asking"
    assert rig.waits == [2, 2, 4, 8]


def test_an_unclear_answer_that_clears_up_carries_on_recording(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[None, True, False], captures=["j_r2.mp4"])
    rig.run()
    assert len(rig.attempts) == 1 and len(rig.joined) == 1


def test_a_run_that_records_nothing_ends_the_retries(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, True], captures=[None], attempt_rc=1)
    assert rig.run() == "saved"
    assert len(rig.attempts) == 1 and rig.joined == [], "one piece, nothing to join"
    assert rig.job["warning_key"] == "download.warning.live_partial"


def test_a_failed_join_keeps_every_piece_and_says_so(app_module, monkeypatch, tmp_path):
    for n, body in (("j.mp4", b"first"), ("j_r2.mp4", b"second"), ("j_r2.mp4.part", b"")):
        (tmp_path / n).write_bytes(body)
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"], join_ok=False)
    rig.job["title"] = "My Stream"
    assert rig.run() == "saved"
    assert rig.job["warning_key"] == "download.warning.live_parts"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["My Stream (part 2).mp4", "j.mp4"], \
        "the second piece survives under a readable name, the empty leftover is cleaned"
    assert (tmp_path / "My Stream (part 2).mp4").read_bytes() == b"second"


def test_kept_parts_never_overwrite_a_file_that_is_already_there(app_module, tmp_path):
    for n, body in (("j.mp4", b"1"), ("j_r2.mp4", b"2"), ("j_r3.mp4", b"3"), ("Title (part 2).mp4", b"not ours")):
        (tmp_path / n).write_bytes(body)
    app_module._live_keep_parts({"title": "Title"}, "j", tmp_path, [str(tmp_path / n) for n in ("j.mp4", "j_r2.mp4", "j_r3.mp4")])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Title (part 2) (1).mp4", "Title (part 2).mp4", "Title (part 3).mp4", "j.mp4"]
    assert (tmp_path / "Title (part 2).mp4").read_bytes() == b"not ours"
    assert (tmp_path / "Title (part 2) (1).mp4").read_bytes() == b"2"


def test_a_retry_that_records_nothing_leaves_nothing_behind_in_the_download_folder(app_module, monkeypatch, tmp_path):
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


def test_stop_and_save_never_asks_or_retries(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True], captures=["j_r2.mp4"])
    rig.job["stop_keep"] = True
    assert rig.run() == "saved"
    assert rig.probes == 0 and rig.attempts == [] and "warning_key" not in rig.job


def test_cancel_during_a_new_run_discards_everything(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True], captures=["j_r2.mp4"])
    monkeypatch.setattr(app_module, "_run_live_attempt", lambda job, *a: job.update(cancelled=True) or 1)
    assert rig.run() == "cancelled"
    assert rig.joined == []


def test_stop_and_save_during_a_new_run_keeps_and_joins_what_was_recorded(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True], captures=["j_r2.mp4"])
    rig.attempt = lambda job, *a: job.update(stop_keep=True) or 1
    monkeypatch.setattr(app_module, "_run_live_attempt", rig.attempt)
    assert rig.run() == "saved"
    assert len(rig.joined) == 1 and rig.job["warning_key"] == "download.warning.live_gap"


def test_nothing_recorded_in_the_first_run_is_reported_as_such(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True], captures=[], first=None)
    assert rig.run(rc=1) is None
    assert rig.probes == 0 and rig.attempts == []


# ── status route and the three backends ──────────────────────────────────────
def test_status_shows_the_reconnect_counter_only_while_reconnecting(app_module):
    app_module.jobs["t_rc"] = {"status": "downloading", "live": True, "live_time": "00:00:15", "live_size": "1KiB",
                               "live_reconnecting": 2, "live_retries_max": 4}
    app_module.jobs["t_rc_off"] = {"status": "downloading", "live": True, "live_time": "00:00:15", "live_size": "1KiB"}
    with app_module.app.test_client() as client:
        h = {"X-EGM-Token": app_module._API_TOKEN}
        on = client.get("/api/status/t_rc", headers=h).get_json()
        off = client.get("/api/status/t_rc_off", headers=h).get_json()
    assert on["live_reconnecting"] == 2 and on["live_retries_max"] == 4
    assert "live_reconnecting" not in off and "live_retries_max" not in off


def test_cleanup_removes_the_job_files_and_the_extra_pieces_only(app_module, tmp_path):
    for n in ("j.mp4", "j.mp4.part", "j_r2.mp4", "j_r3.mp4.part", "j_join.txt", "jj.mp4", "other.mp4"):
        (tmp_path / n).write_bytes(b"x")
    app_module._cleanup("j", tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["jj.mp4", "other.mp4"]


def test_cleanup_also_removes_the_extra_pieces():
    for p in PLATFORM_APP_FILES:
        s = read_source(p)
        body = s[s.index("def _cleanup("):]
        body = body[:body.index("\ndef ", 10)]
        assert '{job_id}_*' in body, f"{p}: Cancel must remove the _r2, _r3 pieces too"


@needs_ffmpeg
def test_a_run_that_printed_no_time_is_measured_by_its_piece(app_module, monkeypatch, tmp_path):
    # ffmpeg's stats line never arrived (run_s=0), yet each piece holds over a minute:
    # the count starts again and the time on the card carries on from the pieces.
    for i in (2, 3, 4):
        _make_mp4(tmp_path / f"j_r{i}.mp4", secs=61)
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, True, False],
               captures=[f"j_r{i}.mp4" for i in (2, 3, 4)])
    assert rig.run() == "saved"
    assert [a[3]["live_reconnecting"] for a in rig.attempts] == [1, 1, 1]
    assert [a[1] for a in rig.attempts] == [15, 76, 137], "each run starts where the pieces before it ended"


def test_a_run_that_printed_its_time_is_not_probed_again(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, False], captures=["j_r2.mp4", "j_r3.mp4"], run_s=60)
    probed = []
    monkeypatch.setattr(app_module, "_media_duration_s", lambda probe, path: probed.append(path) or 0)
    rig.run()
    assert probed == []


def test_a_first_run_that_ended_cleanly_does_not_leave_the_card_on_converting(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"])
    rig.job["progress"] = 100.0   # yt-dlp prints 100 % when ffmpeg exits 0, and the card reads Converting at 100
    rig.run(rc=0)
    assert "progress" not in rig.attempts[0][3]


def test_each_reconnect_piece_leaves_a_log_line_with_its_length_and_the_count(app_module, monkeypatch, tmp_path):
    # The line support asks for when the counter looks wrong: how long the piece was and where the count stood.
    lines = []
    monkeypatch.setattr(app_module, "_egm_log", lines.append)
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, False], captures=["j_r2.mp4", "j_r3.mp4"], run_s=[61, 10])
    rig.run()
    assert [l for l in lines if l.startswith("live piece")] == [
        "live piece 2: 61s recorded after reconnect 1/5",
        "live piece 3: 10s recorded after reconnect 1/5",
    ]


def test_a_long_run_that_printed_no_time_does_not_leave_the_old_count_on_the_card(app_module, monkeypatch, tmp_path):
    # The run printed no stats line (nothing popped the label), but its piece was long:
    # between that run and the next question the card must not read "Reconnecting 2/5".
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, False], captures=["j_r2.mp4", "j_r3.mp4"], run_s=[0, 0])
    monkeypatch.setattr(app_module, "_media_duration_s", lambda probe, path: 90.0)
    seen = []
    real_wait = rig.wait
    def wait(job, secs):
        seen.append(job.get("live_reconnecting"))
        return real_wait(job, secs)
    monkeypatch.setattr(app_module, "_live_wait", wait)
    rig.run()
    assert seen == [None, None, None], seen


# ── audio and video start times of live recordings (sites that need the timestamps kept) ──
_SYNC_ARGS = ["--downloader-args", "ffmpeg:-copyts -avoid_negative_ts make_zero"]


def _list_one_site(app_module, monkeypatch, host="listed.example"):
    """The shipped list holds fingerprints, not names, so the tests list a made up site."""
    monkeypatch.setattr(app_module, "_LIVE_SYNC_HOSTS", (hashlib.sha256(host.encode()).hexdigest(),))
    return host


def test_the_shipped_list_holds_fingerprints_only(app_module):
    assert app_module._LIVE_SYNC_HOSTS, "at least one site is listed"
    for h in app_module._LIVE_SYNC_HOSTS:
        assert len(h) == 64 and set(h) <= set("0123456789abcdef"), "a SHA-256 in lowercase hex, never a site name"


def test_sync_args_go_only_to_listed_sites(app_module, monkeypatch):
    host = _list_one_site(app_module, monkeypatch)
    for url in (f"https://{host}/room", f"https://www.{host}/room", f"https://a.b.{host}/room",
                f"https://XX.{host.upper()}:8443/a?b=c"):
        assert app_module._live_sync_args(url) == _SYNC_ARGS, url
    for url in (f"https://not{host}/room", f"https://{host}.example.org/room", f"https://example.org/{host}",
                "https://example", "https://example.com/live", "not a link", "", "https://[bad/room"):
        assert app_module._live_sync_args(url) == [], url


def test_sync_args_are_a_new_list_each_time(app_module, monkeypatch):
    url = f"https://{_list_one_site(app_module, monkeypatch)}/room"
    first = app_module._live_sync_args(url)
    first.append("x")
    assert app_module._live_sync_args(url) == _SYNC_ARGS


class _NoOutputProc:
    returncode = 0
    def __init__(self): self.stdout, self.stderr = iter(()), iter(())
    def wait(self): return 0


@pytest.mark.parametrize("live, listed, want", [(True, True, True), (False, True, False), (True, False, False)])
def test_only_a_live_recording_from_a_listed_site_gets_the_sync_args(app_module, monkeypatch, tmp_path, live, listed, want):
    m = app_module
    url = f"https://{_list_one_site(m, monkeypatch)}/room" if listed else "https://example.org/room"
    logs, cmds = [], []
    monkeypatch.setattr(m, "_egm_log", lambda msg, *a, **k: logs.append(msg))
    monkeypatch.setattr(m, "_append_history", lambda *a, **k: None)
    monkeypatch.setattr(m, "_live_finish", lambda *a, **k: None)
    monkeypatch.setattr(m, "_popen_yt", lambda *c, **k: (cmds.append(list(c)), _NoOutputProc())[1])
    job_id = "synctest01"
    m.jobs[job_id] = {"status": "queued", "url": url, "title": "", "proc": None, "cancelled": False, "live": live}
    try:
        m.run_download(job_id, url, "video", None, str(tmp_path))
        marked = m.jobs[job_id].get("_live_sync")
    finally:
        m.jobs.pop(job_id, None)
    assert marked is want, "the job says whether the recording keeps the source timestamps (the finish step cuts a silent opening only then)"
    cmd = cmds[0]
    has = "--downloader-args" in cmd
    assert has == want, cmd
    if want:
        i = cmd.index("--downloader-args")
        assert cmd[i:i + 2] == _SYNC_ARGS and i < len(cmd) - 1 and cmd[-1] == url, "the flags sit before the link"
        assert any("keeps the source timestamps" in l for l in logs)
    else:
        assert not any("keeps the source timestamps" in l for l in logs)


def test_a_reconnect_run_keeps_the_sync_args(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"])
    out_tmpl = str(tmp_path / "j.%(ext)s")
    cmd = ["yt-dlp", *_SYNC_ARGS, "-o", out_tmpl, "https://example.com/live"]
    app_module._live_finish(rig.job, "j", tmp_path, cmd, out_tmpl, "https://example.com/live", FFMPEG, ".mp4", False, 0)
    assert rig.attempts and rig.attempts[0][0][1:3] == _SYNC_ARGS, rig.attempts[0][0]


# ── cutting the silent opening (audio that starts a few seconds after the video) ──
def _make_late_audio_mp4(path, gap=3.3, secs=12, gop=50, audio=True, video=True):
    """A white flash at 6.0 s and a 1 kHz beep at 6.0 s on the same timeline; the audio track starts `gap` s late."""
    cmd = [FFMPEG, "-v", "error", "-y"]
    maps = []
    if video:
        cmd += ["-f", "lavfi", "-i", "color=c=black:s=160x90:r=25,drawbox=x=0:y=0:w=160:h=90:color=white:t=fill:enable='between(t,6,6.2)'"]
    if audio:
        cmd += ["-itsoffset", str(gap), "-f", "lavfi", "-i", f"aevalsrc=if(between(t\\,{6 - gap}\\,{6.2 - gap})\\,0.8*sin(2*PI*1000*t)\\,0):s=44100"]
    cmd += ["-t", str(secs), "-c:v", "libx264", "-g", str(gop), "-sc_threshold", "0", "-c:a", "aac", "-movflags", "+faststart", str(path)]
    subprocess.run(cmd, check=True)


def _starts(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,start_time", "-of", "compact=nk=1:p=0", str(path)],
                       capture_output=True, text=True)
    return {row.split("|")[0]: float(row.split("|")[1]) for row in r.stdout.split()}


def _flash_and_beep(path):
    """When the flash and the beep happen on the file's own timeline (copyts keeps each stream's real position)."""
    import re
    v = subprocess.run([FFMPEG, "-v", "error", "-copyts", "-i", str(path), "-an", "-vf",
                        "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
                       capture_output=True, text=True).stdout
    t = flash = None
    for line in v.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m: t = float(m.group(1))
        m = re.search(r"YAVG=([\d.]+)", line)
        if m and float(m.group(1)) > 128 and flash is None: flash = t
    a = subprocess.run([FFMPEG, "-v", "info", "-copyts", "-i", str(path), "-vn", "-af", "silencedetect=n=-30dB:d=0.05", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    beep = float(re.findall(r"silence_end: ([\d.]+)", a)[0])
    return flash, beep


def _video_packet_sizes(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=size", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return [int(x) for x in r.stdout.split()]


def _first_video_packet_is_a_keyframe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=flags", "-of", "csv=p=0",
                        "-read_intervals", "%+0.5", str(path)], capture_output=True, text=True)
    return r.stdout.split()[0].startswith("K")


@needs_ffmpeg
def test_trim_cuts_the_silent_opening_at_a_keyframe_and_keeps_the_sync(app_module, monkeypatch, tmp_path):
    p = tmp_path / "j.mp4"
    _make_late_audio_mp4(p)
    s = _starts(p)
    assert s["audio"] - s["video"] > 3.0, "the test file opens with video and no sound"
    flash, beep = _flash_and_beep(p)
    assert abs(flash - beep) < 0.05, "and it is in sync"
    before = _video_packet_sizes(p)
    logged, job = [], {}
    monkeypatch.setattr(app_module, "_egm_log", logged.append)
    assert app_module._live_trim_silent_start(job, FFMPEG, p) is True
    after = _video_packet_sizes(p)
    s = _starts(p)
    assert s["video"] < 0.1 and s["audio"] < 0.1, "both streams now open together"
    assert _first_video_packet_is_a_keyframe(p)
    assert 7.5 < _duration(p) < 8.5, "12 s minus the cut at the keyframe after 3.3 s (4.0 s)"
    flash, beep = _flash_and_beep(p)
    assert abs(flash - 2.0) < 0.1 and abs(beep - flash) < 0.05, (flash, beep)
    assert after == before[-len(after):] and len(after) > 150, "the video packets are the original ones (a stream copy, no re-encode)"
    assert job["status"] == "converting" and len(logged) == 1 and "cut the first" in logged[0]
    assert sorted(x.name for x in tmp_path.iterdir()) == ["j.mp4"], "no temp file left"


@needs_ffmpeg
def test_trim_leaves_everything_else_alone(app_module, tmp_path):
    def untouched(p):
        before = p.read_bytes()
        assert app_module._live_trim_silent_start({}, FFMPEG, p) is False
        assert p.read_bytes() == before and [x.name for x in tmp_path.iterdir()] == [p.name]
        p.unlink()
    _make_late_audio_mp4(_p := tmp_path / "short.mp4", gap=0.5); untouched(_p)   # a gap below the minimum
    _make_late_audio_mp4(_p := tmp_path / "video.mp4", audio=False); untouched(_p)
    _make_late_audio_mp4(_p := tmp_path / "audio.mp4", video=False); untouched(_p)
    _make_late_audio_mp4(_p := tmp_path / "longgop.mp4", gop=2000); untouched(_p)           # no keyframe within reach
    (_p := tmp_path / "broken.mp4").write_bytes(b"not a video" * 50); untouched(_p)
    _make_late_audio_mp4(_p := tmp_path / "ok.mp4")
    assert app_module._live_trim_silent_start({}, tmp_path / "no-such-ffmpeg", _p) is False


@needs_ffmpeg
def test_a_failed_cut_keeps_the_file_and_leaves_no_temp_file(app_module, monkeypatch, tmp_path):
    p = tmp_path / "j.mp4"
    _make_late_audio_mp4(p)
    before = p.read_bytes()
    real = app_module._run
    def failing(*a, **k):
        if "-ss" not in a:
            return real(*a, **k)
        Path(a[-1]).write_bytes(p.read_bytes())   # a full length output, but ffmpeg says it failed
        return subprocess.CompletedProcess(a, 1, "", "boom")
    monkeypatch.setattr(app_module, "_run", failing)
    assert app_module._live_trim_silent_start({}, FFMPEG, p) is False
    assert p.read_bytes() == before and [x.name for x in tmp_path.iterdir()] == ["j.mp4"]
    lengths = iter([12.0, 5.0])   # a cut that came out far too short is not used either
    monkeypatch.setattr(app_module, "_run", real)
    monkeypatch.setattr(app_module, "_media_duration_s", lambda probe, path: next(lengths))
    assert app_module._live_trim_silent_start({}, FFMPEG, p) is False
    assert p.read_bytes() == before and [x.name for x in tmp_path.iterdir()] == ["j.mp4"]


def test_the_cut_runs_once_on_the_final_file_and_only_for_sites_that_keep_the_source_timestamps(app_module, monkeypatch, tmp_path):
    def finish(sync, audio_only=False, cancelled=False):
        rig = _Rig(app_module, monkeypatch, tmp_path, lives=[False], captures=[])
        rig.job["_live_sync"] = sync
        rig.job["cancelled"] = cancelled
        monkeypatch.setattr(app_module, "_live_trim_silent_start", lambda job, ff, path: rig.notes.append(("trim", Path(path).name)))
        out_tmpl = str(tmp_path / "j.%(ext)s")
        res = app_module._live_finish(rig.job, "j", tmp_path, ["yt-dlp", out_tmpl, "u"], out_tmpl, "u", FFMPEG, ".mp4", audio_only, 0)
        return res, rig.notes
    assert finish(True) == ("saved", [("trim", "j.mp4"), "saved"]), "cut first, then the A/V numbers are logged for the result"
    assert finish(False) == ("saved", ["saved"])
    assert finish(True, audio_only=True) == ("saved", ["saved"])
    assert finish(True, cancelled=True) == ("cancelled", [])


# ── round 3 review ───────────────────────────────────────────────────────────
def test_cancel_pressed_during_the_join_or_the_cut_still_discards(app_module, monkeypatch, tmp_path):
    # Neither ffmpeg step is registered to be killed, so Cancel only sets the flag while it runs:
    # the finish step must look at it again before it reports the recording as saved.
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[False], captures=[])
    rig.job["_live_sync"] = True
    monkeypatch.setattr(app_module, "_live_trim_silent_start", lambda job, ff, path: job.__setitem__("cancelled", True))
    out_tmpl = str(tmp_path / "j.%(ext)s")
    assert app_module._live_finish(rig.job, "j", tmp_path, ["yt-dlp", out_tmpl, "u"], out_tmpl, "u", FFMPEG, ".mp4", False, 0) == "cancelled"


@needs_ffmpeg
@pytest.mark.parametrize("gap, cut", [(0.8, False), (1.3, True)])
def test_the_cut_starts_at_a_one_second_gap(app_module, tmp_path, gap, cut):
    p = tmp_path / "j.mp4"
    _make_late_audio_mp4(p, gap=gap)
    assert app_module._live_trim_silent_start({}, FFMPEG, p) is cut


@needs_ffmpeg
def test_the_cut_file_opens_without_reading_to_its_end(app_module, tmp_path):
    p = tmp_path / "j.mp4"
    _make_late_audio_mp4(p)
    assert app_module._live_trim_silent_start({}, FFMPEG, p) is True
    data = p.read_bytes()
    assert data.find(b"moov") < data.find(b"mdat"), "the index sits before the media (+faststart), as for every saved mp4"


def test_the_card_clock_ignores_jumps_in_the_source_timestamps(app_module, monkeypatch):
    # With -copyts, time= follows the source: a timestamp restart jumps it a day ahead and a wrap
    # sends it back to 0. The card shows recorded time, so only plausible steps count.
    class Jumpy(_Run):
        stderr = [f"size=  10kB time={t}.00 bitrate=1kbits/s\n" for t in
                  ("00:00:01", "00:00:05", "23:56:59", "23:57:04", "00:00:02", "00:00:03")]
    monkeypatch.setattr(app_module, "_popen_yt", lambda *a, **k: Jumpy())
    job = {}
    app_module._run_live_attempt(job, "jz", ["yt-dlp", "u"], 100, 0)
    assert job["live_time"] == "00:01:51", job["live_time"]   # 100 + 1 + 4 + (jump) + 5 + (wrap) + 1
    clock = app_module._live_clock(0)
    assert [clock(t) for t in ("00:00:00", "00:00:30", "00:01:20", "00:04:20", "00:04:21")] == [0, 30, 80, 80, 81]


def test_sync_args_also_for_a_fully_qualified_host(app_module, monkeypatch):
    host = _list_one_site(app_module, monkeypatch)
    assert app_module._live_sync_args(f"https://{host}./room") == _SYNC_ARGS
    assert app_module._live_sync_args(f"https://user:pw@www.{host}.:443/room") == _SYNC_ARGS
    assert app_module._live_sync_args("https://./room") == [] and app_module._live_sync_args("https://[::1]/room") == []


def _stream_kinds(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return r.stdout.split()


@needs_ffmpeg
def test_the_cut_keeps_a_second_audio_track(app_module, tmp_path):
    # The cut replaces the original, so a track it dropped would be lost for good.
    one, p = tmp_path / "one.mp4", tmp_path / "j.mp4"
    _make_late_audio_mp4(one)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(one), "-i", str(one), "-map", "0", "-map", "1:a", "-c", "copy", str(p)], check=True)
    assert _stream_kinds(p) == ["video", "audio", "audio"]
    assert app_module._live_trim_silent_start({}, FFMPEG, p) is True
    assert _stream_kinds(p) == ["video", "audio", "audio"]


@needs_ffmpeg
def test_the_cut_works_for_mkv_and_leaves_other_containers_alone(app_module, tmp_path):
    src = tmp_path / "src.mp4"
    _make_late_audio_mp4(src)
    mkv, mov = tmp_path / "j.mkv", tmp_path / "j.mov"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-c", "copy", str(mkv)], check=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(src), "-c", "copy", str(mov)], check=True)
    before = mov.read_bytes()
    assert app_module._live_trim_silent_start({}, FFMPEG, mkv) is True
    # A Matroska file can only be entered at its cluster starts, so the cut may land on an earlier keyframe than in an mp4:
    # the silent opening gets shorter (3.3 s here, 1.3 s after), and the sync is untouched.
    s = _starts(mkv)
    assert s["audio"] - s["video"] < 2.0 and _stream_kinds(mkv) == ["video", "audio"]
    flash, beep = _flash_and_beep(mkv)
    assert abs(flash - beep) < 0.05, (flash, beep)
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=format_name", "-of", "csv=p=0", str(mkv)], capture_output=True, text=True)
    assert "matroska" in r.stdout, "still a Matroska file"
    assert app_module._live_trim_silent_start({}, FFMPEG, mov) is False and mov.read_bytes() == before, "a container the app never writes"


@needs_ffmpeg
def test_a_crash_in_the_middle_of_the_cut_leaves_only_a_file_the_startup_sweep_removes(app_module, monkeypatch, tmp_path):
    p = tmp_path / "abcdef1234.mp4"      # a job id, as in the download folder
    _make_late_audio_mp4(p)
    before = p.read_bytes()
    real = app_module._run
    def dying(*a, **k):
        if "-ss" in a:
            Path(a[-1]).write_bytes(b"half a file")
            raise SystemExit                      # the app is shut down in the middle of the copy
        return real(*a, **k)
    monkeypatch.setattr(app_module, "_run", dying)
    with pytest.raises(SystemExit):
        app_module._live_trim_silent_start({}, FFMPEG, p)
    assert sorted(x.name for x in tmp_path.iterdir()) == ["abcdef1234.mp4", "abcdef1234.trim.part"]
    assert p.read_bytes() == before, "the recording itself is untouched"
    app_module._cleanup_orphan_partials(str(tmp_path))
    assert [x.name for x in tmp_path.iterdir()] == ["abcdef1234.mp4"], "the start up sweep collects the half file"


def test_the_first_runs_card_clock_ignores_jumps_in_the_source_timestamps_too(app_module, monkeypatch, tmp_path):
    # The first yt-dlp run has its own stderr reader (the reconnect runs use _run_live_attempt); both feed the card's clock.
    m = app_module
    lines = [f"size=  10kB time={t}.00 bitrate=1kbits/s\n" for t in ("00:00:01", "00:00:05", "23:56:59", "23:57:04", "00:00:02")]

    class Proc(_NoOutputProc):
        def __init__(self):
            super().__init__()
            self.stderr = iter(lines)
    seen = {}
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_append_history", lambda *a, **k: None)
    monkeypatch.setattr(m, "_popen_yt", lambda *c, **k: Proc())
    monkeypatch.setattr(m, "_live_finish", lambda job, *a, **k: seen.update(t=job.get("live_time")))
    job_id = "clocktest1"
    m.jobs[job_id] = {"status": "queued", "url": "https://example.org/room", "title": "", "proc": None, "cancelled": False, "live": True}
    try:
        m.run_download(job_id, "https://example.org/room", "video", None, str(tmp_path))
    finally:
        m.jobs.pop(job_id, None)
    assert seen["t"] == "00:00:10", seen    # 1 + 4, (jump), + 5, (wrap)


def test_cancel_during_the_finish_step_also_removes_the_parts_of_a_failed_join(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"], join_ok=False)
    for name in ("j.mp4", "j_r2.mp4"):
        (tmp_path / name).write_bytes(b"x")
    rig.job["title"] = "Show"
    rig.job["_live_sync"] = True
    monkeypatch.setattr(app_module, "_live_trim_silent_start", lambda job, ff, path: job.__setitem__("cancelled", True))
    assert rig.run() == "cancelled"
    assert not any("part 2" in p.name for p in tmp_path.iterdir()), sorted(p.name for p in tmp_path.iterdir())


def test_the_card_clock_never_counts_a_step_backwards(app_module):
    # A small step back in the source timestamps (a restart a second behind) is skipped, not added.
    clock = app_module._live_clock(0)
    assert [clock(t) for t in ("00:10:05", "00:10:04", "00:10:06")] == [605, 605, 607]
