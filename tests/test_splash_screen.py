"""The splash window: one self contained page for all three platforms, a progress bar that follows
real start up steps, and a fade out before the window closes. The main-process files are not
executed by the tests, so the wiring between main.js and the page is checked from the source."""
import os
import re

from conftest import ROOT, read_source

PLATFORMS = ("windows", "mac", "linux")
SPLASH = {p: f"{p}/electron/splash.html" for p in PLATFORMS}
MAIN = {p: f"{p}/electron/main.js" for p in PLATFORMS}


def test_splash_page_is_the_same_file_on_every_platform():
    """The page draws its mark and wordmark itself, so it needs no image path and nothing differs
    between platforms. A change to one copy has to be made to all three."""
    pages = {p: read_source(SPLASH[p]) for p in PLATFORMS}
    assert pages["mac"] == pages["windows"], "mac splash.html drifted from windows"
    assert pages["linux"] == pages["windows"], "linux splash.html drifted from windows"


def test_splash_page_is_self_contained_and_offline():
    """The splash loads before the backend starts and runs sandboxed: no images, stylesheets, scripts or
    network references. The only URL allowed is the SVG namespace."""
    src = read_source(SPLASH["windows"]).replace("http://www.w3.org/2000/svg", "")
    assert "http" not in src, "the splash must not reference any URL"
    for needle in ("<img", "<link", "@import", "src=", "href="):
        assert needle not in src, f"splash.html must not use {needle!r}"


def test_splash_page_exposes_the_hooks_main_js_calls():
    """main.js calls window.setSplashProgress(percent, seconds) and window.splashOut() inside the page.
    The page must define both, and still move the bar by itself when the app reports nothing."""
    src = read_source(SPLASH["windows"])
    assert "window.setSplashProgress = function" in src
    assert "window.splashOut = function" in src
    assert "if (!reported) setBar(45, 14)" in src, "the bar needs its own slow move as a fallback"
    assert "prefers-reduced-motion" in src


def test_splash_words_cover_every_app_language():
    """The splash cannot use the app's i18n (it loads before Flask), so it carries its own "Loading"
    word per language. Adding a language to languages/ means adding its word here."""
    src = read_source(SPLASH["windows"])
    block = re.search(r"var LOADING_WORD = \{(.*?)\};", src, re.S).group(1)
    in_splash = set(re.findall(r"\b([a-z]{2}):\s*'", block))
    in_app = {f[:-5] for f in os.listdir(os.path.join(ROOT, "languages")) if f.endswith(".json")}
    assert in_splash == in_app, (sorted(in_app - in_splash), sorted(in_splash - in_app))


def test_main_js_reports_real_start_up_steps_and_fades_the_splash_out():
    """Same wiring on every platform: numbers only go into the page, calls made before the page has
    loaded are held, the bar moves when the backend process starts and when it answers, and closeSplash
    fills the bar, fades the card, then closes the window after the fade has finished."""
    for p in PLATFORMS:
        src = read_source(MAIN[p])
        assert "function splashProgress(pct, secs)" in src, p
        assert "${Number(pct) || 0}" in src and "${Number(secs) || 0}" in src, f"{p}: only numbers may reach the page"
        assert "_splashPending = [pct, secs]" in src, f"{p}: calls before the page loaded must be held"
        assert "webContents.once('did-finish-load'" in src, p
        spawn_at = src.index("flaskProc = spawn(")
        started_at = src.index("splashProgress(55, 9)")
        exit_at = src.index("flaskProc.on('exit'")
        assert spawn_at < started_at < exit_at, f"{p}: the 55% step belongs right after the backend is spawned"
        wait_at = src.index("await waitForFlask();")
        assert wait_at < src.index("splashProgress(85, 6)"), f"{p}: the 85% step belongs after the backend answers"
        close = src[src.index("function closeSplash()"):]
        close = close[:close.index("\n}\n")]
        assert "splashProgress(100," in close, p
        fade_at = close.index("setTimeout(splashFadeOut, 150)")
        shut_at = close.index("splashWindow.close()")
        assert fade_at < shut_at, f"{p}: the fade must start before the window closes"
        assert "}, 450);" in close, f"{p}: the window closes after the fade (150 ms + the page's 280 ms fade)"
