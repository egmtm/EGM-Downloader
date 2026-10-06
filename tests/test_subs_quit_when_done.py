"""Guards for "Quit when done" (Subscriptions toggle and the main window checkbox).

The behaviour itself is covered by tests/frontend/subs_quit.test.mjs,
main_quit.test.mjs and quit_app_handler.test.mjs (jsdom and the real main.js
handlers). This pins the things those cannot: the countdown string exists in
every locale, the Subscriptions toggle reuses the main UI strings and is never
persisted, and the main window no longer quits on its own timer."""
import glob
import json
import os
import re

from conftest import ROOT, read_source

SUBS = ("templates/subscriptions.html", "linux/templates/subscriptions.html")
MAINS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")


def test_subscriptions_template_mirrors_are_identical():
    assert read_source(SUBS[0]) == read_source(SUBS[1])


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


def test_countdown_string_exists_with_one_count_placeholder_in_every_locale():
    files = sorted(glob.glob(os.path.join(ROOT, "languages", "*.json")))
    assert len(files) >= 10
    for f in files:
        with open(f, encoding="utf-8") as fh:
            value = json.load(fh)["strings"].get("subscriptions.queue.quitting_in")
        name = os.path.basename(f)
        assert isinstance(value, str) and value.strip(), f"{name}: missing subscriptions.queue.quitting_in"
        assert value.count("{0}") == 1, f"{name}: needs the {{0}} seconds count exactly once, got {value!r}"


MAIN_JS = ("templates/js/_core.html", "templates/js/_download.html", "templates/js/_bulk.html")


def test_main_window_scripts_mirror_linux():
    for p in MAIN_JS:
        assert read_source(p) == read_source("linux/" + p), p


def test_main_window_quits_only_through_the_countdown():
    for base in ("", "linux/"):
        for name in ("_download.html", "_bulk.html"):
            src = read_source(f"{base}templates/js/{name}")
            assert "quitWhenDoneCheck()" in src, f"{base}{name}: must start the shared countdown"
            assert "electronAPI.quit(" not in src and "QUIT_DELAY_MS" not in src, (
                f"{base}{name}: no direct timed quit; it would skip the wait, the failure rule and Cancel"
            )
