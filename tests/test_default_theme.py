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


def _root_vars(path):
    """Every variable the file's first :root block declares, comments dropped and spacing normalised."""
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    m = re.search(r":root\s*\{([^}]*)\}", css)
    assert m, f"{path}: no :root block"
    return {k: re.sub(r"\s+", " ", v.strip()).lower() for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1))}


@pytest.mark.parametrize("tree", TREES)
def test_void_swatches_match_what_users_get(tree):
    data = (ROOT / tree / "theme_data.html").read_text(encoding="utf-8")
    m = re.search(r"^\s*void:\s*\{label:'[^']*',\s*bg:'(#\w+)',\s*surf:'(#\w+)',\s*acc:'(#\w+)'", data, re.M)
    assert m, f"{tree}: no void entry in THEME_DATA"
    root = _root_vars(ROOT / tree / "index_styles.html")
    expected = {"bg": root["--bg"], "surf": root["--surf"], "acc": root["--acc"]}
    assert dict(zip(("bg", "surf", "acc"), (g.lower() for g in m.groups()))) == expected, (
        f"{tree}: THEME_DATA void swatches differ from the :root default")


@pytest.mark.parametrize("tree", TREES)
@pytest.mark.parametrize("window", WINDOWS)
def test_every_window_carries_the_default_colours(tree, window):
    """Each variable a window declares in :root must equal index_styles.html's, so the windows show one default look."""
    root = _root_vars(ROOT / tree / "index_styles.html")
    theirs = _root_vars(ROOT / tree / window)
    assert {"--bg", "--surf", "--acc"} <= set(theirs), f"{tree}/{window}: :root lacks bg, surf or acc"
    differ = {k: (v, root.get(k)) for k, v in theirs.items() if root.get(k) != v}
    assert not differ, f"{tree}/{window}: :root differs from the default (window, index_styles): {differ}"


def _all_root_vars(path):
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    return {k for m in re.finditer(r":root\s*\{([^}]*)\}", css) for k in re.findall(r"(--[\w-]+)\s*:", m.group(1))}


@pytest.mark.parametrize("tree", TREES)
@pytest.mark.parametrize("window", WINDOWS)
def test_every_colour_a_window_uses_is_declared(tree, window):
    """A var(--x) with no fallback shows nothing when --x is not declared for the default theme.
    A window can use only what its own :root declares (plus the texture pair theme_styles.html declares)."""
    path = ROOT / tree / window
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    used = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", css))
    declared = _all_root_vars(path) | _all_root_vars(ROOT / tree / "theme_styles.html")
    assert not used - declared, f"{tree}/{window}: used with no fallback but not declared in :root: {sorted(used - declared)}"

