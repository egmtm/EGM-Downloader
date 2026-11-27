"""The v2 stylesheet leaves the page's side padding to index_styles.html.

Opening the Theme Creator puts body.creator-panel-open on the page, and index_styles.html then
gives body a wide padding on the panel's side, so the page moves out from under the docked panel.
That rule and a rule of the selector body.face-v2 weigh the same, and the v2 stylesheet comes
later, so a padding shorthand (or any side padding) on body there wins and the panel covers the
page. Measured in Chromium at 800 px wide: 320 px of the links card were under the panel in v2,
none in Classic. v2 only needs a different bottom padding.
"""
import re

from conftest import read_source

SIDE = {"padding", "padding-inline", "padding-inline-start", "padding-inline-end", "padding-left", "padding-right"}


def _body_rules(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [body for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if selector.strip() == "body.face-v2"]


def test_the_v2_rule_for_body_sets_no_side_padding():
    rules = _body_rules(read_source("templates/face_v2_styles.html"))
    assert rules, "found no rule whose selector is exactly body.face-v2"
    props = {d.split(":")[0].strip().lower() for body in rules for d in body.split(";") if d.strip()}
    assert not props & SIDE, f"body.face-v2 sets {sorted(props & SIDE)}: that beats the room the Theme Creator panel needs"
    assert "padding-bottom" in props, "v2 keeps its own bottom padding"


def test_the_theme_creator_still_asks_for_that_room():
    assert re.search(r"body\.creator-panel-open\s*\{\s*padding-inline-end:\s*356px;\s*\}", read_source("templates/index_styles.html")), (
        "index_styles.html no longer moves the page aside for the Theme Creator panel")
