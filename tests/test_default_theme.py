"""Void is the default theme, and its look is the :root block of index_styles.html (navy).

There is no body.void block: every apply path skips the class for 'void', so the :root values are
what users get. THEME_DATA's swatches for Void must match them, and every window that loads
theme_styles.html must carry the same default colours itself, or it shows no theme at all for a
user on the default theme.

Windows and Mac read templates/, Linux reads linux/templates/ (kept byte identical elsewhere).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TREES = ("templates", "linux/templates")
WINDOWS = ("themes.html", "history.html", "console.html", "subscriptions.html")


def _root_colours(path):
    css = path.read_text(encoding="utf-8")
    m = re.search(r":root\s*\{([^}]*)\}", css)
    assert m, f"{path}: no :root block"
    return {k: v.lower() for k, v in re.findall(r"--(bg|surf|acc)\s*:\s*(#[0-9a-fA-F]{3,8})", m.group(1))}


@pytest.mark.parametrize("tree", TREES)
def test_void_swatches_match_what_users_get(tree):
    data = (ROOT / tree / "theme_data.html").read_text(encoding="utf-8")
    m = re.search(r"^\s*void:\s*\{label:'[^']*',\s*bg:'(#\w+)',\s*surf:'(#\w+)',\s*acc:'(#\w+)'", data, re.M)
    assert m, f"{tree}: no void entry in THEME_DATA"
    expected = _root_colours(ROOT / tree / "index_styles.html")
    assert set(expected) == {"bg", "surf", "acc"}, f"{tree}: index_styles.html :root lacks bg, surf or acc"
    assert dict(zip(("bg", "surf", "acc"), (g.lower() for g in m.groups()))) == expected, (
        f"{tree}: THEME_DATA void swatches differ from the :root default")


@pytest.mark.parametrize("tree", TREES)
@pytest.mark.parametrize("window", WINDOWS)
def test_every_window_carries_the_default_colours(tree, window):
    expected = _root_colours(ROOT / tree / "index_styles.html")
    assert _root_colours(ROOT / tree / window) == expected, f"{tree}/{window}: :root bg, surf and acc differ from the default"
