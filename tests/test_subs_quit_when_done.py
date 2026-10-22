"""Guards for "Quit when done" (Subscriptions toggle and the main window checkbox).

The behaviour itself is covered by tests/frontend/subs_quit.test.mjs,
main_quit.test.mjs and quit_app_handler.test.mjs (jsdom and the real main.js
handlers). This pins the things those cannot: the Subscriptions toggle reuses
the main UI strings and is never persisted, and the main window no longer quits
on its own timer. The countdown string in every language is checked by
test_locale_keys_table.py."""
import glob
import os
import re

from conftest import ROOT, read_source

SUBS = ("templates/subscriptions.html", "linux/templates/subscriptions.html")
MAINS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")


def test_toggle_reuses_the_main_ui_strings():
    for p in SUBS:
        src = read_source(p)
        assert "i18nAttr('advanced.toggle.quit_when_done'" in src, p
        assert "i18nAttr('tooltip.quit_when_done'" in src, p


def test_choice_is_never_persisted():
    for p in SUBS:
        src = read_source(p)
        assert "quit_on_done" not in src, f"{p}: the saved main window setting must not be touched"
        # The page may store other things; quitWhenDone itself must stay in memory.
        for m in re.finditer(r"(localStorage|sessionStorage|/api/settings/save)[^\n]*", src):
            assert "quitWhenDone" not in m.group(0) and "quit" not in m.group(0).lower(), (
                f"{p}: quit-when-done must not be persisted: {m.group(0)[:100]}"
            )


def test_main_handlers_support_when_idle_and_stay_gated():
    for p in MAINS:
        src = read_source(p)
        m = re.search(r"ipcMain\.handle\('quit-app'[\s\S]*?\n\}\);", src)
        assert m, p
        body = m.group(0)
        assert "opts.whenIdle" in body and "_activityBySender" in body, p
        assert body.index("isTrustedSender(event)") < body.index("opts.whenIdle"), (
            f"{p}: the sender gate must run before whenIdle is looked at"
        )


MAIN_JS = ("templates/js/_core.html", "templates/js/_download.html", "templates/js/_bulk.html")


def test_main_window_quits_only_through_the_countdown():
    for base in ("", "linux/"):
        for name in ("_download.html", "_bulk.html"):
            src = read_source(f"{base}templates/js/{name}")
            assert "quitWhenDoneCheck()" in src, f"{base}{name}: must start the shared countdown"
            assert "electronAPI.quit(" not in src and "QUIT_DELAY_MS" not in src, (
                f"{base}{name}: no direct timed quit; it would skip the wait, the failure rule and Cancel"
            )


def test_both_windows_show_the_same_30_second_centered_card():
    """The main window and the Subscriptions window are separate pages, so each has
    its own few lines; this keeps the number and the look from drifting apart."""
    main_js = read_source("templates/js/_core.html")
    styles = read_source("templates/index_styles.html")
    for subs_path in SUBS:
        subs = read_source(subs_path)
        for name, src in (("main window", main_js), (subs_path, subs)):
            assert re.search(r"const QUIT_COUNTDOWN_S = 30;", src), f"{name}: the countdown must be 30 seconds"
            assert "quit-bar" not in src and "_qodToast" not in src, f"{name}: the corner bar/toast is gone"

        def rule(src, selector):
            m = re.search(re.escape(selector) + r"\s*\{[^}]*\}", src)
            assert m, selector
            return re.sub(r"\s+", " ", m.group(0))

        assert rule(styles, ".quit-card") == rule(subs, ".quit-card"), "same card look in both windows"
        assert rule(styles, "@keyframes quit-card-in") == rule(subs, "@keyframes quit-card-in")
        card = rule(styles, ".quit-card")
        assert "left: 50%" in card and "top: 50%" in card, "centered, like the What's New dialog"
        # The page behind the card is dimmed and locked (the script makes it inert): one dim layer, the same in both windows.
        assert rule(styles, ".quit-lock") == rule(subs, ".quit-lock"), "same dim layer in both windows"
        assert rule(styles, "@keyframes quit-lock-in") == rule(subs, "@keyframes quit-lock-in")
        lock = rule(styles, ".quit-lock")
        assert "position: fixed" in lock and "inset: 0" in lock, "covers the whole window"
        assert "color-mix(in srgb, var(--modal-overlay) 70%, transparent)" in lock, (
            "the theme's own dialog overlay, a little lighter than What's New"
        )


def _z(rule_text):
    return int(re.search(r"z-index:\s*(\d+)", rule_text).group(1))


def test_quit_lock_sits_above_every_other_layer_and_under_its_card():
    styles = read_source("templates/index_styles.html")
    lock = re.search(r"\.quit-lock\s*\{[^}]*\}", styles).group(0)
    card = re.search(r"\.quit-card\s*\{[^}]*\}", styles).group(0)
    assert _z(lock) < _z(card), "the card is above its own dim layer"
    others = []
    for path in glob.glob(os.path.join(ROOT, "templates", "**", "*.html"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if "quit-lock" in line or "quit-card" in line or "z-index:99999" in line.replace(" ", ""):
                    continue   # the countdown itself, and the Konami easter egg screen
                others += [int(n) for n in re.findall(r"z-index\s*:\s*(\d+)", line)]
    assert others and max(others) < _z(lock), (
        f"something is layered at {max(others)}, which would paint over the dim layer of the countdown"
    )


def test_inert_is_only_used_by_the_quit_countdown():
    """The countdown unlocks the page by clearing `inert` from every top level element,
    which is only safe while nothing else in the app sets it."""
    users = set()
    for path in glob.glob(os.path.join(ROOT, "templates", "**", "*.html"), recursive=True):
        with open(path, encoding="utf-8") as fh:
            if re.search(r"(?:set|remove|toggle)Attribute\(\s*['\"]inert|\.inert\s*=|\[inert\]|<[^>]*\binert\b", fh.read()):
                users.add(os.path.relpath(path, os.path.join(ROOT, "templates")))
    assert users == {os.path.join("js", "_core.html"), "subscriptions.html"}, users
