"""Hardware-encode concurrency guard: 'busy' must never be treated as 'broken'.

Consumer GPU encoders (NVENC especially) hard-limit concurrent encode
sessions (historically 2, raised over driver generations). This app allows
up to 24 concurrent downloads, so a burst of conversions can genuinely
exceed that cap. The original hardware-acceleration implementation treated
ANY encode failure -- including simply losing the race for a GPU session
slot -- as "this encoder is broken", permanently demoting to libx264-only
for the rest of the app session. One busy burst could quietly recreate the
exact CPU/thermal problem hardware acceleration exists to prevent.

Fixed via _HW_ENCODE_SLOTS, a BoundedSemaphore(2): jobs that can't get a
slot skip the hardware attempt for that one encode and leave the shared
cache alone. Verified by manual test harness at the time (round 9); this
is that harness turned into a permanent, mutation-proven guard.
"""
import os
import threading
import time

from conftest import read_source


def test_hw_encode_slots_is_bounded_semaphore_of_two(app_module):
    assert isinstance(app_module._HW_ENCODE_SLOTS, type(threading.BoundedSemaphore()))
    # A BoundedSemaphore(2) allows exactly 2 non-blocking acquires, then refuses a 3rd.
    a1 = app_module._HW_ENCODE_SLOTS.acquire(blocking=False)
    a2 = app_module._HW_ENCODE_SLOTS.acquire(blocking=False)
    a3 = app_module._HW_ENCODE_SLOTS.acquire(blocking=False)
    try:
        assert a1 and a2, "expected exactly 2 slots to be acquirable"
        assert not a3, "a 3rd non-blocking acquire must fail -- slot cap is not 2"
    finally:
        if a1: app_module._HW_ENCODE_SLOTS.release()
        if a2: app_module._HW_ENCODE_SLOTS.release()
        if a3: app_module._HW_ENCODE_SLOTS.release()


def test_busy_slot_does_not_demote_hw_encoder_cache(app_module, monkeypatch, tmp_path):
    """The core regression: run more concurrent jobs than there are slots,
    confirm the ones that lose the race take the software path WITHOUT
    touching the shared cache -- busy, not broken."""
    app_module._HW_ENCODER_CACHE = ("fake_hw", ["-c:v", "fake_hw"])

    class FakeProc:
        def __init__(self, *a, **kw):
            self.pid = os.getpid()
            self.returncode = 0
        def wait(self):
            time.sleep(0.2)

    monkeypatch.setattr(app_module, "_popen", lambda *a, **kw: FakeProc())
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os.path, "getsize", lambda p: 100)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "rename", lambda a, b: None)

    max_concurrent = []
    lock = threading.Lock()
    concurrent = []
    orig_acquire = app_module._HW_ENCODE_SLOTS.acquire

    def tracked_acquire(blocking=True):
        got = orig_acquire(blocking=blocking)
        if got:
            with lock:
                concurrent.append(1)
                max_concurrent.append(len(concurrent))
        return got
    monkeypatch.setattr(app_module._HW_ENCODE_SLOTS, "acquire", tracked_acquire)

    orig_release = app_module._HW_ENCODE_SLOTS.release
    def tracked_release():
        with lock:
            if concurrent: concurrent.pop()
        orig_release()
    monkeypatch.setattr(app_module._HW_ENCODE_SLOTS, "release", tracked_release)

    results = []
    def run_job(i):
        job = {}
        r = app_module._run_h264_encode(f"job{i}", job, app_module.FFMPEG_DIR / "ffmpeg",
                                          "/fake/in.mp4", "/fake/tmp.mp4", "4.0")
        results.append(r)

    threads = [threading.Thread(target=run_job, args=(i,)) for i in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert all(results), "every job should succeed (falls back to software when busy)"
    assert max(max_concurrent) == 2, f"more than 2 concurrent hardware slots were held: {max(max_concurrent)}"
    assert app_module._HW_ENCODER_CACHE[0] == "fake_hw", (
        "cache was demoted by a merely-busy job -- this is the exact 'busy treated "
        "as broken' regression the slot cap exists to prevent"
    )
    assert len(concurrent) == 0, "slot leak: not all acquired slots were released"


def test_cancellation_releases_the_slot(app_module, monkeypatch):
    app_module._HW_ENCODER_CACHE = ("fake_hw", ["-c:v", "fake_hw"])

    class CancelProc:
        def __init__(self, *a, **kw):
            self.pid = 1
            self.returncode = -15
        def wait(self): pass

    monkeypatch.setattr(app_module, "_popen", lambda *a, **kw: CancelProc())
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os.path, "getsize", lambda p: 100)
    monkeypatch.setattr(os, "remove", lambda p: None)

    job = {"cancelled": True}
    r = app_module._run_h264_encode("j1", job, app_module.FFMPEG_DIR / "ffmpeg",
                                      "/in.mp4", "/tmp.mp4", "4.0")
    assert r is False

    # Both slots must be free again -- prove it by acquiring both.
    a1 = app_module._HW_ENCODE_SLOTS.acquire(blocking=False)
    a2 = app_module._HW_ENCODE_SLOTS.acquire(blocking=False)
    try:
        assert a1 and a2, "slot was not released after a cancelled job"
    finally:
        if a1: app_module._HW_ENCODE_SLOTS.release()
        if a2: app_module._HW_ENCODE_SLOTS.release()


def test_genuine_hardware_failure_still_demotes_cache(app_module, monkeypatch):
    """Contrast case: a job that DID hold a slot and genuinely failed should
    still demote the cache and recover via libx264 -- only 'busy' is exempt."""
    app_module._HW_ENCODER_CACHE = ("fake_hw", ["-c:v", "fake_hw"])
    call_count = [0]

    class FailThenSucceed:
        def __init__(self, *a, **kw):
            call_count[0] += 1
            self.pid = call_count[0]
            self.returncode = 1 if call_count[0] == 1 else 0
        def wait(self): pass

    monkeypatch.setattr(app_module, "_popen", lambda *a, **kw: FailThenSucceed())
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    monkeypatch.setattr(os.path, "getsize", lambda p: 100)
    monkeypatch.setattr(os, "remove", lambda p: None)
    monkeypatch.setattr(os, "rename", lambda a, b: None)

    job = {}
    r = app_module._run_h264_encode("j2", job, app_module.FFMPEG_DIR / "ffmpeg",
                                      "/in.mp4", "/tmp.mp4", "4.0")
    assert r is True, "job should recover via libx264 after a genuine hw failure"
    assert app_module._HW_ENCODER_CACHE == (None, None), (
        "a genuine failure (by a job that held a slot) must still demote the cache"
    )


def test_slot_cap_present_on_all_platforms():
    for platform_file in ("mac/app.py", "linux/app.py"):
        source = read_source(platform_file)
        assert "_HW_ENCODE_SLOTS = threading.BoundedSemaphore(2)" in source, (
            f"{platform_file}: hardware-encode slot cap not found"
        )


def test_hw_attempt_is_gated_on_a_held_slot():
    """The load-bearing line: the hardware attempt must be conditional on BOTH a
    healthy encoder AND a held slot. Dropping the hw_slot half (while leaving
    the semaphore plumbing in place) reintroduces uncapped concurrent hardware
    encodes -- a partial regression the behavioral tests above cannot see,
    because they instrument slot acquisition rather than encoder invocations."""
    for name, path in (("windows", "app.py"), ("mac", "mac/app.py"), ("linux", "linux/app.py")):
        source = read_source(path)
        assert "if (hw_name and hw_slot) else" in source, (
            f"{name}/app.py: the hardware attempt is no longer gated on a held slot"
        )
