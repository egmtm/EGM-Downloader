"""Log Console window wiring guard.

Found in the v1.3.2 delta review: the Log Console button was wired as a bare
window.open('/console-page') from the renderer. That works in a dev browser,
but in the packaged app every window's webContents goes through
hardenWindow(), whose setWindowOpenHandler routes https: links to the
external browser and returns {action:'deny'} for everything else -- so the
button silently did nothing on all three platforms. The only working path to
a child window is the IPC pattern every other window already uses
(electronAPI.openXWindow -> ipcMain.handle -> BrowserWindow + loadURL), with
window.open kept strictly as the no-electronAPI dev/browser fallback.

These are the structural properties that made the bug invisible to the rest
of the suite (which exercises Flask routes and template JS, not the Electron
shell wiring):
  - every main.js registers a gated open-console-window handler that loads
    /console-page (the gating itself is enforced by
    test_parity.py::test_every_ipc_handler_is_gated)
  - every preload exposes openConsoleWindow
  - the settings button prefers the IPC path and only falls back to
    window.open when electronAPI is absent
  - console.html follows the child-window conventions the other windows
    established: applies the saved theme (and live theme changes), and
    localizes document.title on i18n:ready
"""
import re

from conftest import read_source

MAIN_JS = (
    "windows/electron/main.js",
    "linux/electron/main.js",
    "mac/electron/main.js",
)

PRELOAD_JS = (
    "windows/electron/preload.js",
    "linux/electron/preload.js",
    "mac/electron/preload.js",
)


def test_console_ipc_handler_present_on_all_platforms():
    for path in MAIN_JS:
        src = read_source(path)
        m = re.search(r"ipcMain\.handle\('open-console-window'.*?\n\}\);", src, re.DOTALL)
        assert m, f"{path}: no open-console-window ipcMain handler"
        handler = m.group(0)
        assert "isTrustedSender(event)" in handler, f"{path}: console handler not gated"
        assert "/console-page" in handler, f"{path}: console handler doesn't load /console-page"
        assert "hardenWindow(consoleWindow)" in handler, f"{path}: console window not hardened"


def test_preload_exposes_open_console_window_on_all_platforms():
    for path in PRELOAD_JS:
        src = read_source(path)
        assert re.search(r"openConsoleWindow:\s*\(\)\s*=>\s*ipcRenderer\.invoke\('open-console-window'\)", src), (
            f"{path}: preload doesn't expose openConsoleWindow"
        )


def test_settings_button_prefers_ipc_over_window_open():
    """The renderer must try electronAPI.openConsoleWindow first; a bare
    window.open is exactly the wiring hardenWindow denies in the packaged
    app. The window.open must only exist as the else-branch fallback."""
    src = read_source("templates/js/_settings.html")
    idx = src.index("adv-console-btn")
    block = src[idx:idx + 600]
    assert "window.electronAPI.openConsoleWindow" in block, (
        "console button must open via the IPC path (electronAPI.openConsoleWindow)"
    )
    assert re.search(
        r"if\s*\(window\.electronAPI\s*&&\s*window\.electronAPI\.openConsoleWindow\)",
        block,
    ), "console button must guard on electronAPI before falling back to window.open"
    # The actual window.open CALL is allowed only AFTER the electronAPI guard
    # (fallback position). Match the call, not the string "window.open" --
    # the explanatory comment above the guard mentions it too.
    guard_pos = re.search(
        r"if\s*\(window\.electronAPI\s*&&\s*window\.electronAPI\.openConsoleWindow\)", block
    ).start()
    open_call = re.search(r"window\.open\('/console-page'", block)
    assert open_call, "dev/browser fallback window.open('/console-page') missing"
    assert guard_pos < open_call.start(), (
        "window.open must be the fallback branch, not the primary path"
    )


def test_console_page_follows_child_window_conventions():
    for path in ("templates/console.html", "linux/templates/console.html"):
        src = read_source(path)
        assert "localStorage.getItem('egm-theme')" in src, (
            f"{path}: console window must apply the saved theme like every "
            f"other child window"
        )
        assert "onThemeChanged" in src, (
            f"{path}: console window must follow live theme changes"
        )
        assert re.search(r"document\.title\s*=.*i18nGet\('console\.title'\)", src), (
            f"{path}: document.title must localize via console.title on i18n:ready"
        )
