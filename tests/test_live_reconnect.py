"""Live recordings carry on after the stream drops.

When a stream's server errors for even a few seconds, ffmpeg's HLS reader gives
up and exits as if the stream had ended (usually exit code 0), so the recording
used to stop early. After every live run the app now asks yt-dlp whether the
stream is still live and, if so, records again (up to 4 more times) and joins
the pieces into one file. These tests pin the helpers, the driver loop (with
the yt-dlp runs replaced by stand ins), and the join against real ffmpeg."""
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


# ── the driver loop, with the yt-dlp runs replaced ───────────────────────────
class _Rig:
    """Stands in for yt-dlp: `lives` answers the probes in order, `captures` says what each
    new run records (a file name, or None when it records nothing)."""
    def __init__(self, app_module, monkeypatch, tmp_path, lives, captures, first="j.mp4", attempt_rc=0, join_ok=True):
        self.am, self.tmp, self.lives, self.captures = app_module, tmp_path, list(lives), list(captures)
        self.waits, self.probes, self.attempts, self.joined, self.job = [], 0, [], [], {"live_time": "00:00:15", "live_size": "594KiB"}
        self.first, self.attempt_rc, self.join_ok = first, attempt_rc, join_ok
        monkeypatch.setattr(app_module, "_live_wait", self.wait)
        monkeypatch.setattr(app_module, "_live_is_still_live", self.probe)
        monkeypatch.setattr(app_module, "_run_live_attempt", self.attempt)
        monkeypatch.setattr(app_module, "_live_collect", self.collect)
        monkeypatch.setattr(app_module, "_live_join", self.join)

    def wait(self, job, secs):
        self.waits.append(secs)
        return not (job.get("cancelled") or job.get("stop_keep"))

    def probe(self, job, url):
        self.probes += 1
        return self.lives.pop(0) if self.lives else True

    def attempt(self, job, job_id, cmd, base_s, base_kib):
        self.attempts.append((cmd, base_s, base_kib, dict(job)))
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
    assert job_then["live_reconnecting"] == 1 and job_then["live_retries_max"] == 4
    assert rig.joined == [[str(tmp_path / "j.mp4"), str(tmp_path / "j_r2.mp4")]]
    assert rig.job["warning_key"] == "download.warning.live_gap"
    assert "live_reconnecting" not in rig.job and "live_retries_max" not in rig.job, "the card status is cleared"


def test_it_gives_up_after_four_more_runs(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True] * 20, captures=[f"j_r{i}.mp4" for i in range(2, 9)])
    assert rig.run() == "saved"
    assert len(rig.attempts) == 4 and len(rig.joined[0]) == 5
    assert [a[0][2].endswith(f"j_r{i}.%(ext)s") for a, i in zip(rig.attempts, range(2, 6))] == [True] * 4, "each run has its own piece name"


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


def test_a_failed_join_still_keeps_the_first_piece_and_says_so(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"], join_ok=False)
    assert rig.run() == "saved"
    assert rig.job["warning_key"] == "download.warning.live_partial"


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


def test_cleanup_also_removes_the_extra_pieces():
    for p in PLATFORM_APP_FILES:
        s = read_source(p)
        body = s[s.index("def _cleanup("):]
        body = body[:body.index("\ndef ", 10)]
        assert '{job_id}_*' in body, f"{p}: Cancel must remove the _r2, _r3 pieces too"


def test_the_reconnect_and_gap_strings_exist_in_every_locale():
    import glob, os
    from conftest import ROOT
    files = sorted(glob.glob(os.path.join(ROOT, "languages", "*.json")))
    assert len(files) >= 10
    for f in files:
        with open(f, encoding="utf-8") as fh:
            strings = json.load(fh)["strings"]
        assert "{0}" in strings["card.status.reconnecting"] and "{1}" in strings["card.status.reconnecting"], f
        assert strings["download.warning.live_gap"].strip(), f
