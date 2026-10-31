"""Colours that did not follow the theme now do, so they stay readable on every theme.

- The LIVE tag on a video card is black or white text on the theme's --red, whichever reads better.
- The History format badges (MP3, MP4, FLAC and the like) are light on dark themes and dark on light
  ones. The lightness comes from --surf because --bg is a gradient in a few themes, and a gradient
  would make the whole colour invalid.
- The green buttons (Stop and save, Update, Install Deno) get black or white text from contrast-color().
- The Save button of the Theme Creator panel (a fixed dark panel) is a blue that carries white text.

The first three need a recent engine (relative colour syntax, contrast-color()). Their values hold var(),
and an engine that does not know the function keeps such a declaration at parse time and then inherits a
colour, so a plain earlier declaration is never a fallback: each sits in an @supports block, with a fixed
colour outside it.

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


def _supports_spans(css):
    """(start, end, condition, body) of every @supports block, braces balanced."""
    out = []
    for m in re.finditer(r"@supports\s*([^{]*)\{", css):
        i, depth = m.end(), 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append((m.start(), i, m.group(1).strip(), css[m.end():i - 1]))
    return out


def _supports_blocks(css):
    return [(cond, body) for _, _, cond, body in _supports_spans(css)]


def _outside_supports(css):
    """The text with every @supports block, its condition included, cut out."""
    for start, end, _, _ in reversed(_supports_spans(css)):
        css = css[:start] + css[end:]
    return css


@pytest.mark.parametrize("tree", TREES)
def test_live_tag_text_reads_on_every_theme_red(tree):
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    base = re.search(r"\.live-tag\s*\{([^}]*)\}", _outside_supports(css), re.S).group(1)
    assert re.search(r"(?<!-)color:\s*#fff\b", base), "the LIVE tag lost its fixed fallback colour"
    rule = next(b for c, b in _supports_blocks(css) if "color(from" in c and ".live-tag" in b)
    t = float(re.search(r"\(\s*(\.\d+)\s*-\s*y\s*\)\s*\*\s*\d+", rule).group(1))   # white up to this luminance, black above it
    k = float(re.search(r"\(\s*\.\d+\s*-\s*y\s*\)\s*\*\s*(\d+)", rule).group(1))   # how sharp the switch is
    worst = (99, "")
    for key, v in _theme_vars(tree).items():
        y = _lum(_rgb(v["--red"]))
        text = min(max((t - y) * k, 0), 1)   # the text is D65 white scaled by this, so its luminance is this number
        worst = min(worst, ((max(text, y) + .05) / (min(text, y) + .05), key))
    assert worst[0] >= 4.5, f"{tree}: the LIVE tag text is {worst[0]:.2f}:1 on {worst[1]}'s red (near the switch it turns grey)"


@pytest.mark.parametrize("tree", TREES)
def test_history_badges_take_their_lightness_from_a_solid_colour(tree):
    css = (ROOT / tree / "history.html").read_text(encoding="utf-8")
    pattern = r"^\s*(\.fmt-(?:mp3|mp4|flac)[^{]*)\{([^}]*)\}"
    base = re.findall(pattern, _outside_supports(css), re.M)
    assert len(base) == 3 and all(re.search(r"(?<!-)color:\s*#", body) for _, body in base), "a badge lost its fixed fallback colour"
    block = next(b for c, b in _supports_blocks(css) if "oklch(from" in c)
    rules = re.findall(pattern, block, re.M)
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


@pytest.mark.parametrize("tree", TREES)
def test_green_button_label_is_chosen_from_the_green(tree):
    """contrast-color() picks black or white for the label; outside @supports the label is --btn-on-accent.
    contrast-color() judges a colour as if it were opaque, so every --green must be a solid colour."""
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    base = re.search(r"\.btn-green\s*\{([^}]*)\}", _outside_supports(css)).group(1)
    assert "color: var(--btn-on-accent)" in base and "contrast-color" not in base
    assert any("contrast-color(" in c and re.search(r"\.btn-green\s*\{\s*color:\s*contrast-color\(var\(--green\)\)", b)
               for c, b in _supports_blocks(css)), "the green button label is no longer chosen from the green"
    for key, v in _theme_vars(tree).items():
        assert re.fullmatch(r"#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}", v["--green"]), f"{key}: --green {v['--green']} is not a solid colour"


@pytest.mark.parametrize("tree", TREES)
def test_new_colour_functions_sit_behind_supports(tree):
    """A value that needs contrast-color() or relative colour syntax and holds var() cannot fall back to an
    earlier declaration, so it has to be inside an @supports block (with a fixed colour outside it)."""
    found = []
    for path in sorted((ROOT / tree).glob("*.html")) + sorted((ROOT / tree / "js").glob("*.html")):
        css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
        rest = _outside_supports(css)
        for m in re.finditer(r"contrast-color\(|\b(?:color|oklch|oklab|lch|lab|rgb|rgba|hsl|hsla|hwb)\(\s*from\b", rest):
            found.append(f"{path.name}: ...{rest[max(0, m.start() - 40):m.start() + 30]}...")
    assert not found, f"{tree}: outside @supports: {found}"


_HISTORY_BADGE_CLASSES = {"fmt-mp3", "fmt-aac", "fmt-m4a", "fmt-mp4", "fmt-webm", "fmt-flac", "fmt-wav"}
_BADGE_TINTS = ((22, 163, 74), (59, 130, 246), (168, 85, 247))   # the three .fmt backgrounds, at .1


@pytest.mark.parametrize("tree", TREES)
def test_windows_95_and_98_history_badges_are_white_on_the_teal_desktop_and_dark_on_a_hovered_row(tree):
    """These two themes draw the History rows straight on --bg (teal) while the badge colour is taken from the
    light --surf, so the dark badges sat on teal at about 2:1. At rest they get white text; a hovered row turns
    light (--surf2), where white would be about 1.5:1, so the rule must not apply there."""
    css = (ROOT / tree / "history.html").read_text(encoding="utf-8")
    m = re.search(r"body\.windows95\s+\.row:not\(:hover\)\s*:is\(([^)]*)\)\s*,\s*"
                  r"body\.windows98\s+\.row:not\(:hover\)\s*:is\(([^)]*)\)\s*\{\s*color:\s*#fff\s*\}", css)
    assert m, "the Windows 95 and 98 History badge rule is gone or lost its :not(:hover)"
    for group in m.groups():
        assert {c.strip(" .") for c in group.split(",")} == _HISTORY_BADGE_CLASSES
    themes = _theme_vars(tree)
    for key in ("windows95", "windows98"):
        bg, surf2 = _rgb(themes[key]["--bg"]), _rgb(themes[key]["--surf2"])
        assert _ratio((255, 255, 255), surf2) < 4.5, f"{key}: white would read on a hovered row, so :not(:hover) is no longer needed"
        for tint in _BADGE_TINTS:
            behind = tuple(round(t * .1 + b * .9) for t, b in zip(tint, bg))
            assert _ratio((255, 255, 255), behind) >= 4.5, f"{key}: white badge text on the teal desktop is under 4.5:1"


@pytest.mark.parametrize("tree", TREES)
def test_windows_98_hover_blue_keeps_the_downloading_badge_readable(tree):
    """--acc-h is the Downloading badge text as well as the hover colour: on Windows 98's light cards a bright
    hover blue (#0e78c4) read at 2.6:1. It stays lighter than the navy accent, and reads at 4.5:1."""
    css = (ROOT / tree / "index_styles.html").read_text(encoding="utf-8")
    r, g, b, a = re.search(r"\.b-dl\s*\{\s*background:\s*rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)\s*;\s*color:\s*var\(--acc-h\)", css).groups()
    v = _theme_vars(tree)["windows98"]
    surf = _rgb(v["--surf"])
    behind = tuple(round(int(t) * float(a) + s * (1 - float(a))) for t, s in zip((r, g, b), surf))
    assert _ratio(_rgb(v["--acc-h"]), behind) >= 4.5, "the Windows 98 Downloading badge is under 4.5:1"
    assert _lum(_rgb(v["--acc-h"])) > _lum(_rgb(v["--acc"])), "the Windows 98 hover blue is no longer lighter than its accent"
