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
    # the property only: .th still names opacity in its transition
    assert not re.search(r"(?<![\w-])opacity\s*:", body), f"{tree}/{name}: {selector} sets an opacity on top of --text2"


@pytest.mark.parametrize("tree", TREES)
def test_download_folder_hint_follows_the_theme(tree):
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    m = re.search(r"#dl-dir::placeholder\s*\{([^}]*)\}", css)
    assert m, f"{tree}: #dl-dir has no ::placeholder rule, so it shows the browser grey"
    assert "var(--text2)" in m.group(1)
