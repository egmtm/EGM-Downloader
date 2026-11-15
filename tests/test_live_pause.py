"""Live recordings: Pause and Resume.

A pause ends the run like Stop and save and keeps its piece, but the worker then waits with no process
running (status "paused", time and size kept) until Resume, Stop and save or Cancel. Resume asks
whether the stream is still live and records from what is live now; if it is over, the recording is
saved with its own note. Manual pauses are not reconnects: they never count against the reconnect cap.
Pause shows only while the card reads Recording, not while it reconnects."""
import threading

import pytest

from conftest import PLATFORM_APP_FILES, read_source
from test_live_reconnect import _Rig


def _pausing_attempt(rig, resume=True, then=None):
    """A new run that ends because the user pressed Pause (and, for the test, already pressed Resume or
    something else for the wait that follows)."""
    real = rig.attempt
    def attempt(job, *a):
        rc = real(job, *a)
        job["pause_req"] = True
        if resume:
            job["resume_req"] = True
        if then:
            job.update(then)
        return 1
    return attempt


def test_a_pause_after_the_first_run_then_resume_records_again_and_joins_with_the_pause_note(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"])
    rig.job.update(pause_req=True, resume_req=True)
    assert rig.run(rc=1) == "saved"
    cmd, base_s, base_kib, job_then = rig.attempts[0]
    assert "live_reconnecting" not in job_then, "a resumed run is not a reconnect"
    assert (base_s, base_kib) == (15, 594), "time and size carry on from the first piece"
    assert rig.waits == [2], "no two second wait before checking a resumed stream, only before the reconnect check after it"
    assert rig.joined == [[str(tmp_path / "j.mp4"), str(tmp_path / "j_r2.mp4")]]
    assert rig.job["warning_key"] == "download.warning.live_paused"


def test_resume_when_the_stream_ended_while_paused_saves_what_was_recorded_with_its_note(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[False], captures=[])
    rig.job.update(pause_req=True, resume_req=True)
    assert rig.run(rc=1) == "saved"
    assert rig.probes == 1 and rig.attempts == [] and rig.joined == []
    assert rig.job["warning_key"] == "download.warning.live_ended_paused", "not the ended early note: the user paused it"


def test_the_stream_ended_while_paused_after_several_pieces_keeps_that_note_after_the_join(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, False], captures=["j_r2.mp4"])
    monkeypatch.setattr(app_module, "_run_live_attempt", _pausing_attempt(rig))
    assert rig.run(rc=0) == "saved"
    assert len(rig.joined) == 1 and rig.job["warning_key"] == "download.warning.live_ended_paused"


def test_stop_and_save_while_paused_saves_without_asking_or_recording_again(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True], captures=["j_r2.mp4"])
    rig.job.update(pause_req=True, stop_keep=True)
    assert rig.run(rc=1) == "saved"
    assert rig.probes == 0 and rig.attempts == [] and "warning_key" not in rig.job


def test_cancel_while_paused_discards_the_recording(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True], captures=["j_r2.mp4"])
    rig.job.update(pause_req=True, cancelled=True)
    assert rig.run(rc=1) == "cancelled"
    assert rig.probes == 0 and rig.attempts == [] and rig.joined == []


def test_manual_pauses_never_count_against_the_reconnect_cap(app_module, monkeypatch, tmp_path):
    n = app_module._LIVE_MAX_RETRIES + 3
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True] * n + [False],
               captures=[f"j_r{i}.mp4" for i in range(2, n + 3)])
    monkeypatch.setattr(app_module, "_run_live_attempt", _pausing_attempt(rig))
    rig.job.update(pause_req=True, resume_req=True)        # paused during the first run too
    assert rig.run(rc=1) == "saved"
    assert len(rig.attempts) == n, "every resume recorded again, past the reconnect cap"
    assert all("live_reconnecting" not in a[3] for a in rig.attempts)


def test_a_reconnect_and_a_pause_in_one_recording_keep_the_gap_note(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, False], captures=["j_r2.mp4", "j_r3.mp4"])
    real = rig.attempt
    def attempt(job, *a):                         # every run is cut by the site: a reconnect follows
        real(job, *a)
        return 1
    rig.job.update(pause_req=True, resume_req=True)
    monkeypatch.setattr(app_module, "_run_live_attempt", attempt)
    assert rig.run(rc=1) == "saved"
    assert "live_reconnecting" not in rig.attempts[0][3] and rig.attempts[1][3]["live_reconnecting"] == 1
    assert rig.job["warning_key"] == "download.warning.live_gap"


def test_pause_waits_with_the_card_on_paused_and_returns_what_the_user_chose(app_module, monkeypatch):
    seen = []
    def sleep(_):
        seen.append(dict(job))
        job["resume_req"] = True
    job = {"status": "converting", "_live_check": True, "speed": "1MiB/s", "eta": "1", "progress": 100,
           "live_reconnecting": 2, "live_time": "00:06:03", "live_size": "117504KiB"}
    monkeypatch.setattr(app_module.time, "sleep", sleep)
    assert app_module._live_pause(job) is True
    assert seen[0]["status"] == "paused" and "_live_check" not in seen[0] and "progress" not in seen[0]
    assert "live_reconnecting" not in seen[0] and seen[0]["live_time"] == "00:06:03", "the time and size stay"
    assert job["status"] == "converting" and job["_live_check"], "Converting while the stream is checked, Stop and save allowed"
    assert "resume_req" not in job
    for flag in ("stop_keep", "cancelled"):
        job = {"status": "downloading", flag: True}
        assert app_module._live_pause(job) is False


# ── routes ──────────────────────────────────────────────────────────────────
def _post(app_module, path):
    with app_module.app.test_client() as client:
        return client.post(path, headers={"X-EGM-Token": app_module._API_TOKEN})


RECORDING = {"status": "downloading", "live": True, "live_time": "00:01:00", "proc": None}


@pytest.mark.parametrize("job, code", [
    (None, 404),
    ({**RECORDING, "live": False}, 400),
    ({**RECORDING, "live_time": ""}, 400),                         # nothing recorded yet
    ({**RECORDING, "live_reconnecting": 2}, 400),                  # reconnecting: no Pause (EGM)
    ({**RECORDING, "status": "converting", "_live_check": True}, 400),
    ({**RECORDING, "status": "paused"}, 400),
    ({**RECORDING, "pause_req": True}, 400),
    ({**RECORDING, "stop_keep": True}, 400),
    ({**RECORDING, "cancelled": True}, 400),
    (dict(RECORDING), 200),
])
def test_pause_only_while_recording(app_module, job, code):
    if job is not None:
        app_module.jobs["t_pause"] = job
    path = "/api/pause/t_pause" if job is not None else "/api/pause/nope"
    assert _post(app_module, path).status_code == code
    if job is not None:
        assert bool(app_module.jobs["t_pause"].get("pause_req")) == (code == 200 or job.get("pause_req", False))


def test_resume_only_while_paused(app_module):
    app_module.jobs["t_res"] = {"status": "paused", "live": True}
    assert _post(app_module, "/api/resume/t_res").status_code == 200 and app_module.jobs["t_res"]["resume_req"]
    app_module.jobs["t_res2"] = {"status": "downloading", "live": True}
    assert _post(app_module, "/api/resume/t_res2").status_code == 400 and "resume_req" not in app_module.jobs["t_res2"]
    assert _post(app_module, "/api/resume/nope").status_code == 404


def test_stop_and_cancel_accept_a_paused_recording(app_module):
    app_module.jobs["t_ps"] = {"status": "paused", "live": True, "proc": None}
    assert _post(app_module, "/api/stop/t_ps").status_code == 200 and app_module.jobs["t_ps"]["stop_keep"]
    app_module.jobs["t_pc"] = {"status": "paused", "live": True, "proc": None}
    assert _post(app_module, "/api/cancel/t_pc").status_code == 200 and app_module.jobs["t_pc"]["cancelled"]


def test_live_jobs_lists_recording_paused_and_saving_live_jobs_only(app_module):
    for k in list(app_module.jobs):
        app_module.jobs.pop(k)
    app_module.jobs.update({
        "a": {"status": "downloading", "live": True}, "b": {"status": "paused", "live": True},
        "c": {"status": "converting", "live": True}, "d": {"status": "done", "live": True},
        "e": {"status": "queued", "live": True}, "f": {"status": "downloading", "live": False},
    })
    with app_module.app.test_client() as client:
        got = client.get("/api/live-jobs", headers={"X-EGM-Token": app_module._API_TOKEN}).get_json()
        assert client.get("/api/live-jobs").status_code in (401, 403), "the token is required like every route"
    assert sorted(j["id"] for j in got["jobs"]) == ["a", "b", "c"]


def test_the_three_backends_have_the_pause_routes():
    for p in PLATFORM_APP_FILES:
        s = read_source(p)
        for route in ('"/api/pause/<job_id>"', '"/api/resume/<job_id>"', '"/api/live-jobs"'):
            assert route in s, (p, route)


def test_a_resume_whose_stream_cannot_be_checked_saves_without_the_ended_early_note(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[None] * (len(app_module._LIVE_UNKNOWN_WAITS) + 1), captures=[])
    rig.job.update(pause_req=True, resume_req=True)
    assert rig.run(rc=1) == "saved"
    assert rig.attempts == [] and "warning_key" not in rig.job, "the user paused it, it did not end early"


def test_a_pause_during_the_last_allowed_reconnect_still_pauses_instead_of_ending(app_module, monkeypatch, tmp_path):
    cap = app_module._LIVE_MAX_RETRIES
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True] * (cap + 1) + [False],
               captures=[f"j_r{i}.mp4" for i in range(2, cap + 4)])
    real = rig.attempt
    def attempt(job, *a):
        real(job, *a)
        if len(rig.attempts) == cap:              # recording again on the last reconnect, then Pause and Resume
            job.update(pause_req=True, resume_req=True)
        return 1
    monkeypatch.setattr(app_module, "_run_live_attempt", attempt)
    assert rig.run(rc=1) == "saved"
    assert len(rig.attempts) == cap + 1 and "live_reconnecting" not in rig.attempts[-1][3], "the resumed run happened"


def test_a_pause_before_the_resumed_run_recorded_anything_still_pauses(app_module, monkeypatch, tmp_path):
    # Resume, then Pause again while the new run is still starting: it has recorded nothing. Then Resume.
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, False], captures=[None, "j_r2.mp4"])
    real, left = rig.attempt, []
    def attempt(job, *a):
        real(job, *a)
        if len(rig.attempts) == 1:
            (tmp_path / "j_r2.mp4.part").write_bytes(b"cut")        # what the killed run left
            job.update(pause_req=True, resume_req=True)
        else:
            left.append(sorted(p.name for p in tmp_path.iterdir()))
        return 1
    monkeypatch.setattr(app_module, "_run_live_attempt", attempt)
    rig.job.update(pause_req=True, resume_req=True)                 # paused during the first run
    assert rig.run(rc=1) == "saved"
    assert len(rig.attempts) == 2, "the recording was paused and resumed, not ended"
    assert left == [[]], "the run that recorded nothing left no file for the next run to trip over"
    assert "j_r2." in rig.attempts[1][0][2], "the next run takes the name of the run that recorded nothing"
    assert all("live_reconnecting" not in a[3] for a in rig.attempts)
    assert rig.joined == [[str(tmp_path / "j.mp4"), str(tmp_path / "j_r2.mp4")]]
    assert rig.job["warning_key"] == "download.warning.live_paused"


def test_a_run_that_recorded_nothing_without_a_pause_still_ends_the_recording(app_module, monkeypatch, tmp_path):
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True], captures=[None])
    rig.job.update(pause_req=True, resume_req=True)
    assert rig.run(rc=1) == "saved"
    assert len(rig.attempts) == 1 and rig.joined == [] and rig.job.get("status") != "paused"


def test_a_second_resume_press_does_not_resume_the_next_pause_on_its_own(app_module, monkeypatch, tmp_path):
    # Resume pressed twice: the second press can land after the first was taken, while the card still read Paused.
    rig = _Rig(app_module, monkeypatch, tmp_path, lives=[True, True, False], captures=["j_r2.mp4", "j_r3.mp4"])
    real_probe, real_attempt, waited = rig.probe, rig.attempt, []
    def probe(job, url):
        if rig.probes == 0:
            job["resume_req"] = True                       # the late second press
        return real_probe(job, url)
    def attempt(job, *a):
        real_attempt(job, *a)
        job["pause_req"] = True                            # Pause again in the new run, and no Resume this time
        return 1
    me, real_sleep = threading.current_thread(), app_module.time.sleep
    def sleep(secs):                                       # the pause is waiting for the user: Stop and save
        if threading.current_thread() is not me or rig.job.get("status") != "paused":
            return real_sleep(secs)                        # some other wait of the app, not the pause
        waited.append(rig.job.get("status"))
        rig.job["stop_keep"] = True
    monkeypatch.setattr(app_module, "_live_is_still_live", probe)
    monkeypatch.setattr(app_module, "_run_live_attempt", attempt)
    monkeypatch.setattr(app_module.time, "sleep", sleep)
    rig.job.update(pause_req=True, resume_req=True)        # paused in the first run, Resume pressed
    assert rig.run(rc=1) == "saved"
    assert waited == ["paused"], "the second pause waited for the user"
    assert len(rig.attempts) == 1, "nothing was recorded again without a Resume"
