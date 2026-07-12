"""Cancel-during-conversion guard.

Cancelling a job while it was in the "converting" phase (H.264 compat pass
or Upscale) used to be silently ignored, at two separate layers:

1. /api/cancel only accepted status in (downloading, queued) -- a cancel
   click during "converting" got rejected with a 400 at the route itself,
   never reaching job["cancelled"] or _kill_proc. The ffmpeg process kept
   running to completion regardless of the click.
2. Even if the flag had somehow been set, run_download had no check for
   job.get("cancelled") after the conversion passes -- a cancelled job
   would still fall through to rename-and-deliver as if nothing happened.

Both fixed in the same commit, plus a bounded retry on tmp-file removal for
a Windows-specific file-handle timing issue (a just-killed process can hold
the handle for a moment after the kill signal, before cancel's cleanup
tries to remove the temp file).

Verified manually via the Flask test client at the time; this is that
verification turned into a permanent guard.
"""
from conftest import read_source


def test_cancel_route_accepts_converting_status(app_module):
    app_module.jobs["test_converting_job"] = {"status": "converting", "cancelled": False}
    with app_module.app.test_client() as client:
        headers = {"X-EGM-Token": app_module._API_TOKEN}
        resp = client.post("/api/cancel/test_converting_job", headers=headers)
    assert resp.status_code == 200, (
        "cancel during the converting phase must be accepted, not 400'd -- "
        "this is the exact regression that let cancel silently do nothing"
    )
    assert app_module.jobs["test_converting_job"]["cancelled"] is True


def test_cancel_route_still_accepts_downloading_and_queued(app_module):
    # Make sure the fix widened the accepted set rather than replacing it.
    for status in ("downloading", "queued"):
        job_id = f"test_{status}_job"
        app_module.jobs[job_id] = {"status": status, "cancelled": False}
        with app_module.app.test_client() as client:
            headers = {"X-EGM-Token": app_module._API_TOKEN}
            resp = client.post(f"/api/cancel/{job_id}", headers=headers)
        assert resp.status_code == 200, f"cancel during {status} should still work"
        assert app_module.jobs[job_id]["cancelled"] is True


def test_cancel_route_rejects_terminal_statuses(app_module):
    # A job that's already done/errored shouldn't be cancellable -- confirms
    # the fix widened to exactly (downloading, queued, converting), not to
    # everything.
    app_module.jobs["test_done_job"] = {"status": "done", "cancelled": False}
    with app_module.app.test_client() as client:
        headers = {"X-EGM-Token": app_module._API_TOKEN}
        resp = client.post("/api/cancel/test_done_job", headers=headers)
    assert resp.status_code == 400


def test_run_download_checks_cancelled_after_conversion(app_module):
    """run_download must not silently deliver a cancelled job's file after
    the conversion passes -- checked via source presence since a full
    execution of run_download needs a real download to drive it."""
    import re
    source = read_source("app.py")
    m = re.search(r"^def run_download\(", source, re.MULTILINE)
    assert m, "run_download not found"
    next_def = re.search(r"^def ", source[m.end():], re.MULTILINE)
    body = source[m.start():m.end() + next_def.start()] if next_def else source[m.start():]
    assert 'job.get("cancelled")' in body, (
        "run_download has no post-conversion cancelled check -- a set "
        "cancelled flag could fall through to rename-and-deliver again"
    )


def test_cancel_fix_present_on_all_platforms():
    for platform_file in ("app.py", "mac/app.py", "linux/app.py"):
        source = read_source(platform_file)
        assert '"downloading", "queued", "converting"' in source, (
            f"{platform_file}: /api/cancel no longer accepts the converting "
            "status -- cancel-during-conversion may be silently broken again"
        )
