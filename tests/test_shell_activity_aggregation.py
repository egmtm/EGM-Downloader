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


# ── Taskbar/dock updates must reach whichever window actually has one ────────
# main.js hides mainWindow while subscriptions is open ("sub-app mode" --
# subsWindow is a normal, un-parented BrowserWindow with its own independent
# taskbar button). _applyAggregateActivity used to write setProgressBar/
# setOverlayIcon to mainWindow only, so a download started from Subscriptions
# updated the shell state correctly internally, but the visible window (the
# one with the actual taskbar button on screen) never received the update --
# the hidden mainWindow did, invisibly. Reported as: works from the main
# window, silently doesn't from Subscriptions.

def test_progress_bar_reaches_every_existing_window_on_all_platforms():
    for p in MAIN_JS:
        src = read_source(p)
        i = src.index("function _applyAggregateActivity")
        j = src.index("\nipcMain.on('set-activity'", i)
        block = src[i:j]
        assert "for (const win of [mainWindow, subsWindow])" in block, (
            f"{p}: setProgressBar must be applied to every existing "
            f"top-level window, not just mainWindow -- mainWindow is "
            f"hidden while Subscriptions is open, so targeting it alone "
            f"means the update never reaches the window actually visible "
            f"on screen"
        )
        assert "win.setProgressBar(active > 0 ? prog : -1)" in block, (
            f"{p}: the per-window loop must call setProgressBar on `win`, "
            f"not still be hardcoded to `mainWindow`"
        )
        # The old single-window-only pattern must be gone, not just
        # supplemented -- otherwise this could regress to double-guarding
        # (loop present but old mainWindow-only call still there too).
        assert "mainWindow.setProgressBar(active > 0 ? prog : -1)" not in block, (
            f"{p}: leftover mainWindow-only setProgressBar call alongside "
            f"the new per-window loop"
        )


def test_windows_overlay_icon_reaches_every_existing_window():
    p = "windows/electron/main.js"
    src = read_source(p)
    i = src.index("function _applyAggregateActivity")
    j = src.index("\nipcMain.on('set-activity'", i)
    block = src[i:j]
    assert "win.setOverlayIcon(icon, `${active} active`)" in block, (
        f"{p}: setOverlayIcon must be applied per-window (win), same "
        f"reasoning as setProgressBar -- the overlay badge has the "
        f"identical hidden-mainWindow problem"
    )
    assert "mainWindow.setOverlayIcon" not in block, (
        f"{p}: leftover mainWindow-only setOverlayIcon call"
    )


def test_mac_linux_badge_count_is_not_gated_behind_mainwindow_existing():
    """app.setBadgeCount() is app-level (dock/launcher badge, not tied to
    any specific window) -- it must fire unconditionally whenever activity
    changes, not be nested inside the per-window loop or an
    if (mainWindow...) guard the way setProgressBar legitimately is."""
    for p in ("mac/electron/main.js", "linux/electron/main.js"):
        src = read_source(p)
        i = src.index("function _applyAggregateActivity")
        j = src.index("\nipcMain.on('set-activity'", i)
        block = src[i:j]

        loop_start = block.index("for (const win of [mainWindow, subsWindow])")
        loop_end = block.index("}", block.index("continue", loop_start)) + 1
        loop_body = block[loop_start:loop_end]
        assert "setBadgeCount" not in loop_body, (
            f"{p}: setBadgeCount must not be inside the per-window loop -- "
            f"it's an app-level call, calling it once per window is "
            f"redundant and couples it to window existence for no reason"
        )

        after_loop = block[loop_end:]
        assert "app.setBadgeCount(active)" in after_loop, (
            f"{p}: app.setBadgeCount(active) must be called unconditionally "
            f"after the per-window loop, not nested inside any window-"
            f"existence guard -- it previously only fired when mainWindow "
            f"existed and wasn't destroyed, even though the badge itself "
            f"has nothing to do with mainWindow specifically"
        )


def test_hidden_or_destroyed_window_in_the_loop_is_a_harmless_skip():
    """Executes the real per-window loop body (extracted from source)
    against a mix of a live mock window, a destroyed one, and None --
    confirms only the live window gets the calls, and nothing raises."""
    for p in MAIN_JS:
        src = read_source(p)
        i = src.index("for (const win of [mainWindow, subsWindow])")
        open_brace = src.index("{", i)
        depth = 0
        k = open_brace
        while True:
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        loop_src = src[i:k + 1]

        node_script = f"""
        const calls = [];
        function makeWin(destroyed) {{
          return {{
            isDestroyed: () => destroyed,
            setProgressBar: (v) => calls.push(['setProgressBar', v]),
            setOverlayIcon: (icon, desc) => calls.push(['setOverlayIcon', icon, desc]),
          }};
        }}
        const active = 3;
        const prog = 0.5;
        const icon = 'FAKE_ICON';
        const mainWindow = makeWin(true);   // destroyed -- must be skipped
        const subsWindow = makeWin(false);  // live -- must receive the calls
        {loop_src}
        console.log(JSON.stringify(calls));
        """
        result = __import__("subprocess").run(
            ["node", "-e", node_script],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"{p}: loop raised: {result.stderr}"
        import json
        calls = json.loads(result.stdout.strip())
        targets = [c[0] for c in calls]
        assert "setProgressBar" in targets, (
            f"{p}: the live (non-destroyed) window must receive setProgressBar"
        )
        # Exactly one setProgressBar call -- the destroyed mainWindow must
        # not have been touched, and there must be no duplicate for the
        # live window either.
        assert targets.count("setProgressBar") == 1, (
            f"{p}: expected exactly 1 setProgressBar call (destroyed "
            f"window skipped), got {targets.count('setProgressBar')}"
        )



# ── Hardening added in the delta review of 069675e ───────────────────────────

def _extract_per_window_loop(path):
    """The real `for (const win of [mainWindow, subsWindow]) { ... }` body,
    brace-matched out of source (same technique as the test above)."""
    src = read_source(path)
    i = src.index("for (const win of [mainWindow, subsWindow])")
    k = src.index("{", i)
    depth = 0
    while True:
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1]


def _run_loop_under_node(loop_src, decl):
    """Execute the real loop against mock windows and return the calls made."""
    import json
    import subprocess

    script = f"""
    const calls = [];
    function makeWin(destroyed) {{
      return {{
        isDestroyed: () => destroyed,
        setProgressBar: (v) => calls.push(['setProgressBar', v]),
        setOverlayIcon: (icon, desc) => calls.push(['setOverlayIcon', icon, desc]),
      }};
    }}
    const active = 3, prog = 0.5, icon = 'FAKE_ICON';
    {decl}
    {loop_src}
    console.log(JSON.stringify(calls));
    """
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, f"loop raised: {r.stderr}"
    return json.loads(r.stdout.strip())


def test_per_window_loop_tolerates_a_null_window():
    """The `!win` half of the guard, which nothing else exercises.

    test_hidden_or_destroyed_window_in_the_loop_is_a_harmless_skip says it
    covers "a live mock window, a destroyed one, and None", but both its
    mocks are objects -- the null branch is never taken. That branch is not
    an edge case: `subsWindow` is declared `let subsWindow = null` and is
    null whenever Subscriptions isn't open, i.e. during every ordinary
    main-window download. Dropping `!win ||` therefore throws a TypeError
    on the most common path, where the set-activity handler's outer
    try/catch swallows it and the taskbar progress silently stops working
    altogether -- with the suite still green.
    """
    for p in MAIN_JS:
        loop = _extract_per_window_loop(p)

        # subsWindow null (Subscriptions closed) -- the normal case.
        calls = _run_loop_under_node(
            loop, "const mainWindow = makeWin(false); const subsWindow = null;")
        assert [c[0] for c in calls].count("setProgressBar") == 1, (
            f"{p}: with subsWindow null, mainWindow alone must be updated"
        )

        # mainWindow null (pre-creation / post-teardown) -- subs still updated.
        calls = _run_loop_under_node(
            loop, "const mainWindow = null; const subsWindow = makeWin(false);")
        assert [c[0] for c in calls].count("setProgressBar") == 1, (
            f"{p}: with mainWindow null, subsWindow alone must be updated"
        )

        # Both absent -- no calls, no throw.
        assert _run_loop_under_node(
            loop, "const mainWindow = null; const subsWindow = null;") == []

        # And the guard itself must still be there.
        assert "if (!win || win.isDestroyed()) continue;" in loop, (
            f"{p}: the per-window loop must guard on `!win` as well as "
            f"isDestroyed() -- subsWindow is null whenever Subscriptions "
            f"is closed"
        )


def test_subs_close_clears_state_before_reaggregating_and_cannot_strand_the_user():
    """The subsWindow 'closed' handler must clear its own state BEFORE
    calling _applyAggregateActivity(), and must not let that call throw.

    mainWindow is hidden while Subscriptions is open ("sub-app mode"), and
    this handler is what shows it again. Since 069675e the aggregate call
    reaches into window objects, so an exception there would abort the
    handler before mainWindow.show() -- leaving the user with no visible
    window at all. Clearing first also means the loop never iterates the
    window currently being torn down.
    """
    for p in MAIN_JS:
        src = read_source(p)
        i = src.index("subsWindow.on('closed'")
        j = src.index("});", i)
        # Strip comments first: the handler's own explanatory comment names
        # mainWindow.show(), and an index search over raw source would match
        # that prose instead of the call -- the exact failure mode this
        # file's other guards have been bitten by.
        block = "\n".join(
            ln for ln in src[i:j].split("\n") if not ln.lstrip().startswith("//")
        )

        null_at = block.index("subsWindow = null;")
        agg_at = block.index("_applyAggregateActivity()")
        assert null_at < agg_at, (
            f"{p}: `subsWindow = null` must come before the "
            f"_applyAggregateActivity() call, so the per-window loop does "
            f"not touch the window being torn down"
        )

        assert re.search(r"try\s*\{\s*_applyAggregateActivity\(\);\s*\}\s*catch", block), (
            f"{p}: the _applyAggregateActivity() call in the subs 'closed' "
            f"handler must be wrapped -- a throw here skips the "
            f"mainWindow.show() below and leaves no visible window"
        )

        show_at = block.index("mainWindow.show()")
        assert agg_at < show_at, (
            f"{p}: mainWindow.show() must come after the aggregate update, "
            f"so restoring the UI is never blocked by it"
        )
