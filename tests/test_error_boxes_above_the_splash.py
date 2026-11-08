"""A start-up error box must not open under the splash.

dialog.showErrorBox blocks the main process until it is closed, so the timers closeSplash() starts
(fill the bar, fade, then close) never run while the box is up, and the splash is always on top: the
box opens under it, out of reach, and the app looks frozen. In the installer edition that is exactly
the "Python could not start" box antivirus can cause. Every box in the three shells drops the splash
at once first (dropSplash), as the crash box already did on Windows.
"""
import re

import pytest

from conftest import read_source

SHELLS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")


@pytest.mark.parametrize("rel", SHELLS)
def test_drop_splash_destroys_the_splash_at_once(rel):
    src = read_source(rel)
    m = re.search(r"\nfunction dropSplash\(\) \{\n(.*?)\n\}\n", src, re.S)
    assert m, f"{rel}: dropSplash() is missing"
    body = m.group(1)
    assert "splashWindow.destroy()" in body and "setTimeout" not in body and "splashWindow = null" in body


@pytest.mark.parametrize("rel", SHELLS)
def test_every_error_box_drops_the_splash_first(rel):
    lines = read_source(rel).splitlines()
    boxes = [i for i, l in enumerate(lines) if "dialog.showErrorBox(" in l]
    assert boxes, f"{rel}: no error box found"
    for i in boxes:
        before = [l.strip() for l in lines[max(0, i - 6):i] if l.strip()]
        assert "dropSplash();" in before, f"{rel}:{i + 1} opens a box with the splash still up"
        assert "closeSplash();" not in before, f"{rel}:{i + 1} closes the splash on a timer before a box"
