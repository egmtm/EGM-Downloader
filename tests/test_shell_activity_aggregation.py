"""Multi-window shell activity aggregation guards.

set-activity used to be single-sender: whichever window's poll tick landed
last silently overwrote the taskbar/badge/sleep-blocker state. Wiring the
subscriptions window into the same channel needed per-sender tracking so
neither window's report can clobber the other's -- summed active count,
averaged progress across both.

Also replaced the Windows overlay badge mechanism: it used to be a
renderer-drawn canvas data URL (couldn't represent an aggregate of two
windows' counts without one window knowing the other's numbers). Now
main.js picks a pre-rendered PNG from the aggregate count it already
computed -- simpler, and sidesteps needing canvas support entirely (jsdom,
used elsewhere in this suite, has none).
"""
import re

from conftest import read_source

MAIN_JS = [
    "windows/electron/main.js",
    "mac/electron/main.js",
    "linux/electron/main.js",
]


def test_activity_tracked_per_sender_on_all_platforms():
    """set-activity must key state by the sending BrowserWindow, not
    overwrite a single shared value -- that's the exact bug being fixed."""
    for p in MAIN_JS:
        src = read_source(p)
        assert "_activityBySender" in src, f"{p}: missing per-sender activity tracking"
        assert "BrowserWindow.fromWebContents(event.sender)" in src, (
            f"{p}: set-activity must identify which window sent the report"
        )


def test_aggregate_sums_active_and_averages_progress():
    """The aggregation function must sum active counts (total downloads
    app-wide) and average progress only across senders that reported one
    (a sender with progress -1 -- nothing running -- must not drag the
    average toward 0)."""
    for p in MAIN_JS:
        src = read_source(p)
        i = src.index("function _applyAggregateActivity")
        block = src[i:i + 700]
        assert "active += st.active" in block, f"{p}: must sum active counts"
        assert "st.progress >= 0" in block, (
            f"{p}: must exclude non-reporting senders (progress -1) from "
            f"the progress average, not average them in as 0"
        )


def test_subscriptions_close_clears_its_slot_and_reaggregates():
    """A closed subscriptions window must not leave a permanent phantom
    entry in the aggregate -- confirmed by requiring BOTH the delete and an
    immediate re-aggregate call in the same handler, not just one or the
    other."""
    for p in MAIN_JS:
        src = read_source(p)
        i = src.index("subsWindow.on('closed'")
        block = src[i:i + 200]
        assert "_activityBySender.delete(subsWindow)" in block, (
            f"{p}: subscriptions close handler must clear its activity slot"
        )
        assert "_applyAggregateActivity()" in block, (
            f"{p}: subscriptions close handler must re-aggregate immediately "
            f"after clearing its slot -- otherwise the stale combined state "
            f"lingers until the next set-activity call, which may never come"
        )


def test_powersaveblocker_explicitly_released_on_quit():
    """Belt-and-braces alongside OS-level cleanup on process death: the
    established 'single cleanup point for every quit path' handler
    (before-quit) must also stop the blocker explicitly."""
    for p in MAIN_JS:
        src = read_source(p)
        i = src.index("app.on('before-quit'")
        block = src[i:i + 400]
        assert "powerSaveBlocker.stop(_psbId)" in block, (
            f"{p}: before-quit must explicitly release the power save "
            f"blocker, not rely solely on implicit OS cleanup"
        )


def test_windows_badge_uses_prerendered_assets_not_canvas_dataurl():
    """Windows-only: the overlay badge must come from a pre-rendered PNG
    selected by the aggregate count, not a renderer-supplied data URL --
    a single renderer-drawn badge can't represent two windows' combined
    count without cross-window coordination."""
    src = read_source("windows/electron/main.js")
    assert "function _badgeIconForCount" in src
    assert "data:image/png;base64," not in src, (
        "the old data-URL badge path should be fully removed, not left "
        "dead alongside the new one"
    )
    i = src.index("function _badgeIconForCount")
    block = src[i:i + 300]
    assert "badge-${name}.png" in block or "badge-" in block, (
        "badge picker must load from the pre-rendered static/badge-*.png assets"
    )


def test_all_ten_badge_assets_exist_and_are_shipped():
    """1 through 9 plus the 9+ overflow icon must exist on disk and be
    shipped by both packaging paths -- validate-version-sync.py's own
    portable/NSIS sync check catches a mismatch between the two, but not a
    file silently missing from both."""
    import os
    names = [f"badge-{n}.png" for n in list(range(1, 10)) + ["9plus"]]
    for name in names:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", name)
        assert os.path.exists(path), f"static/{name} is missing from disk"

    build_sh = read_source("windows/BUILD.sh")
    nsi = read_source("windows/setup.nsi")
    for name in names:
        assert name in build_sh, f"windows/BUILD.sh doesn't ship static/{name}"
        assert name in nsi, f"windows/setup.nsi doesn't ship static/{name}"
