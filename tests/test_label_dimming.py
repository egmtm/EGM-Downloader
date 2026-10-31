"""Small labels take their dimming from the theme colour alone.

Each of these used to carry an extra CSS opacity on top of --text2 or --acc (0.65 or 0.7), so the
label was dimmed twice and fell under 3:1 in many themes. The extra opacity is gone; size,
capitals and letter spacing keep the hierarchy. The download folder field also follows the
theme for its hint text instead of the browser's grey.

Windows and Mac read templates/, Linux reads linux/templates/ (kept byte identical elsewhere).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TREES = ("templates", "linux/templates")

# (file, selector, colour variable) of the rules that must not set an opacity of their own
LABEL_RULES = (
    ("index_styles.html", ".qual-label", "--text2"),
    ("index_styles.html", ".opt-label", "--text2"),
    ("history.html", ".th", "--text2"),
    ("themes.html", ".cat-count", "--text2"),
    ("themes.html", ".cat-section", "--acc"),
    ("themes.html", ".section-caret", "--acc"),
)


def _rule(tree, name, selector):
    css = (ROOT / tree / name).read_text(encoding="utf-8")
    m = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{tree}/{name}: no {selector} rule"
    return m.group(1)


@pytest.mark.parametrize("tree", TREES)
@pytest.mark.parametrize("name,selector,colour", LABEL_RULES)
def test_label_is_not_dimmed_twice(tree, name, selector, colour):
    body = _rule(tree, name, selector)
    assert f"color: var({colour})" in body or f"color:var({colour})" in body, f"{tree}/{name}: {selector} left {colour}"
    assert not re.search(r"(?<![\w-])opacity\s*:", body), f"{tree}/{name}: {selector} sets an opacity on top of --text2"
    assert "opacity" not in body, f"{tree}/{name}: {selector} still names opacity (a transition on it does nothing now)"


@pytest.mark.parametrize("tree", TREES)
def test_download_folder_hint_follows_the_theme(tree):
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    m = re.search(r"#dl-dir::placeholder\s*\{([^}]*)\}", css)
    assert m, f"{tree}: #dl-dir has no ::placeholder rule, so it shows the browser grey"
    assert "var(--text2)" in m.group(1)


@pytest.mark.parametrize("tree", TREES)
def test_section_heading_hover_tints_the_row(tree):
    """With no opacity left to lift, hovering a Themes section heading tints its row; the text stays on --acc."""
    body = _rule(tree, "themes.html", ".cat-section:hover")
    assert re.search(r"(?<![\w-])background\s*:\s*var\(--acc-dim\)", body), f"{tree}: .cat-section:hover does not tint with --acc-dim"
    assert "opacity" not in body, f"{tree}: .cat-section:hover sets an opacity"


@pytest.mark.parametrize("tree", TREES)
def test_history_headers_are_not_styled_as_clickable(tree):
    """Nothing handles a click on a History table header (sorting is the sort button), so a pointer
    cursor or a hover cue would promise a click that never comes. Bring both back with a click handler."""
    css = (ROOT / tree / "history.html").read_text(encoding="utf-8")
    assert not re.search(r"(?m)^\s*\.th:hover\b", css), f"{tree}: .th has a hover rule"
    assert "cursor" not in _rule(tree, "history.html", ".th"), f"{tree}: .th sets a cursor"
