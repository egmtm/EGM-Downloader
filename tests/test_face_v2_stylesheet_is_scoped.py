"""The v2 stylesheet changes nothing while its class is absent, and brings no colour or request of its own.

templates/face_v2_styles.html is loaded on every start of the main window, in both Faces. Three
things keep that safe, and nothing else in the repo checks them:

- every selector starts with body.face-v2, so with Classic chosen no rule applies. One rule without
  it restyles Classic for everyone;
- no colour is written out: every colour comes from a theme variable, so every theme, a custom one
  too, keeps its own look in v2;
- no url() and no @import: a stylesheet can fetch what it names, and the page's policy lets images
  come from any https address.
"""
import re

from conftest import read_source

FACE = "body.face-v2"


def _rules(css):
    """(selector list, declarations) for every rule, comments removed. A rule inside a media block is found too."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _problems(css):
    rules = _rules(css)
    out = [f"selector without {FACE}: {s.strip()}" for selectors, _ in rules for s in selectors.split(",")
           if not re.match(re.escape(FACE) + r"(?![\w-])", s.strip())]
    for selectors, body in rules:
        values = re.sub(r"content\s*:\s*'[^']*'", "", body)   # the prompt glyph is text, not a colour
        out += [f"colour written out in {selectors.strip()}: {m}" for m in re.findall(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", values)]
    out += [f"fetches: {m}" for m in re.findall(r"url\s*\(|@import", re.sub(r"/\*.*?\*/", "", css, flags=re.S), re.I)]
    return out


def test_the_v2_stylesheet_is_scoped_takes_its_colours_from_the_theme_and_fetches_nothing():
    css = read_source("templates/face_v2_styles.html")
    assert len(_rules(css)) > 50, "the v2 stylesheet was not read"
    assert not _problems(css), "\n".join(_problems(css))


def test_the_check_sees_each_kind_of_problem():
    """The check itself: a clean rule passes, and each thing it guards against is reported."""
    clean = "body.face-v2 .a, body.face-v2 #face-x:hover{color:var(--text);border:1px solid color-mix(in srgb,var(--acc) 45%,var(--border))}"
    assert _problems(clean) == []
    for bad in (".vcard{padding:1px}",                                   # no scope
                "body.face-v2 .a, .b{padding:1px}",                      # the second selector of a list
                "body.face-v2x .a{padding:1px}",                         # another class that only starts the same
                "@media (max-width:700px){.a{padding:1px}}",             # inside a media block
                "body.face-v2 .a{color:#888}", "body.face-v2 .a{background:rgba(0,0,0,.2)}", "body.face-v2 .a{color:hsl(0 0% 50%)}",
                "body.face-v2 .a{background:url(https://example.org/x.png)}", "@import 'x.css'; body.face-v2 .a{padding:1px}"):
        assert _problems(bad), bad
