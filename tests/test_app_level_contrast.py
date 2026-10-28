"""The LIVE tag on a video card is black or white text on the theme's --red, whichever reads better.

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
