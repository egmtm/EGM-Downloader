"""Three colours that did not follow the theme now do, so they stay readable on every theme.

- The LIVE tag on a video card is black or white text on the theme's --red, whichever reads better.
- The History format badges (MP3, MP4, FLAC and the like) are light on dark themes and dark on light
  ones. The lightness comes from --surf because --bg is a gradient in a few themes, and a gradient
  would make the whole colour invalid.
- The Save button of the Theme Creator panel (a fixed dark panel) is a blue that carries white text.

Windows and Mac read templates/, Linux reads linux/templates/ (kept byte identical elsewhere).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TREES = ("templates", "linux/templates")


def _rgb(c):
    c = c.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(x * 2 for x in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _lum(rgb):
    f = lambda v: v / 255 / 12.92 if v / 255 <= .03928 else ((v / 255 + .055) / 1.055) ** 2.4
    return .2126 * f(rgb[0]) + .7152 * f(rgb[1]) + .0722 * f(rgb[2])


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + .05) / (min(la, lb) + .05)


def _theme_vars(tree):
    """{theme key: {variable: value}} for every body.<key> block, plus the default colours as 'void'."""
    css = (ROOT / tree / "theme_styles.html").read_text(encoding="utf-8")
    out = {m.group(1): dict((a, b.strip()) for a, b in re.findall(r"(--[\w-]+):\s*([^;\n]*);", m.group(2)))
           for m in re.finditer(r"^\s*body\.([\w-]+)\s*\{(.*?)\n\s*\}", css, re.S | re.M)}
    idx = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    root = re.search(r":root\s*\{(.*?)\}", idx, re.S).group(1)
    out["void"] = dict((a, b.strip()) for a, b in re.findall(r"(--[\w-]+):\s*([^;\n]*);", root))
    return out


@pytest.mark.parametrize("tree", TREES)
def test_live_tag_text_reads_on_every_theme_red(tree):
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    rule = re.search(r"\.live-tag\s*\{([^}]*)\}", css, re.S).group(1)
    assert not re.search(r"(?<!-)color:\s*#", rule), "the LIVE tag text is a fixed colour again"
    t = float(re.search(r"\(\s*(\.\d+)\s*-\s*y\s*\)", rule).group(1))   # white up to this luminance, black above it
    worst = 99
    for key, v in _theme_vars(tree).items():
        red = _rgb(v["--red"])
        text = (255, 255, 255) if _lum(red) <= t else (0, 0, 0)
        worst = min(worst, _ratio(text, red))
    assert worst >= 4.5, f"{tree}: the LIVE tag text is {worst:.2f}:1 on the worst theme red"


@pytest.mark.parametrize("tree", TREES)
def test_history_badges_take_their_lightness_from_a_solid_colour(tree):
    css = (ROOT / tree / "history.html").read_text(encoding="utf-8")
    rules = re.findall(r"^\s*(\.fmt-(?:mp3|mp4|flac)[^{]*)\{([^}]*)\}", css, re.M)
    assert len(rules) == 3
    for sel, body in rules:
        assert "oklch(from var(--surf)" in body, f"{sel.strip()}: the badge colour is fixed or reads a gradient"
    for key, v in _theme_vars(tree).items():
        assert re.fullmatch(r"#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)", v["--surf"]), (
            f"{key}: --surf is not a solid colour, so the History badge colours would be dropped")


@pytest.mark.parametrize("tree", TREES)
def test_creator_save_button_carries_white_text(tree):
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    m = re.search(r"\.cvp-save\s*\{\s*background:\s*(#\w+);\s*border-color:\s*(#\w+);\s*color:\s*(#\w+);", css)
    assert m, "the Creator panel Save rule changed shape"
    bg, border, text = m.groups()
    assert bg == border
    assert _ratio(_rgb(text), _rgb(bg)) >= 4.5
