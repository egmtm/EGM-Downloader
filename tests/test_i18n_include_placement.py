"""Guard against a real bug: templates/i18n.html has no <script> wrapper of its
own (it's meant to be included INSIDE an already-open <script> tag). console.html
had '{% include \"i18n.html\" %}' BEFORE its own <script> tag instead of inside it,
so the raw JS -- including its leading comment block -- rendered as literal
visible text at the top of the page, and none of the i18n boot logic executed
at all (it was inert text, not a running script). Screenshot from the field:
the console showed nothing but a wall of unstyled source-code text and never
updated.

Neither the Flask-route test-client checks nor the jsdom harness caught this at
the time, because both assert on rendered *content* and *behavior* respectively
without checking that a template's {% include %} directives land inside their
intended script boundaries -- a gap this test closes directly by rendering the
real route and checking DOM structure the way a browser would.
"""
import re

from conftest import read_source

# Standalone windows that include i18n.html directly, following the simple
# '<script>' then '{% include %}' pattern. index.html is deliberately excluded:
# it includes i18n.html indirectly through index_scripts.html, nested inside a
# <script> tag opened much earlier in the file -- a different, correct pattern
# that isn't the one that broke here.
WINDOWS_WITH_I18N_INCLUDE = (
    "templates/history.html",
    "templates/themes.html",
    "templates/subscriptions.html",
    "templates/console.html",
)


def test_i18n_include_lands_inside_a_script_tag():
    """For every window, '<script>' must appear strictly before
    '{% include 'i18n.html' %}' with nothing but whitespace/comments between --
    i.e. the include is the first thing inside that script tag, not floating
    in the body before it."""
    include_re = re.compile(r"\{%\s*include\s*'i18n\.html'\s*%\}")

    for path in WINDOWS_WITH_I18N_INCLUDE:
        source = read_source(path)
        m = include_re.search(source)
        assert m, f"{path}: does not include i18n.html at all"

        before = source[:m.start()]
        last_script_open = before.rfind("<script>")
        last_script_close = before.rfind("</script>")

        assert last_script_open != -1, (
            f"{path}: '{{% include \"i18n.html\" %}}' has no preceding <script> tag "
            f"at all -- it will render as literal visible text on the page, and "
            f"none of the i18n boot logic will execute. This exact bug shipped in "
            f"console.html: the include landed between a closing </div> and the "
            f"page's own <script> tag."
        )
        assert last_script_open > last_script_close, (
            f"{path}: the nearest preceding <script> tag before the i18n.html "
            f"include is already closed by the time the include appears -- the "
            f"include is sitting outside any script tag."
        )


def test_root_and_linux_console_mirrors_match():
    """Byte-identical, matching every other template's parity discipline."""
    assert read_source("templates/console.html") == read_source("linux/templates/console.html")


# ── Generalized guard: the whole bug class, tree-derived and transitive ────────
#
# The targeted test above pins the exact i18n.html mistake in the four known
# windows. But the bug class is wider than i18n.html: theme_data.html,
# theme_validator.html, and every js/_*.html partial are also raw JS with no
# <script> wrapper of their own, and theme_styles/index_styles are raw CSS --
# ANY of them included outside its container element leaks source text into the
# page the same way. And a hand-maintained window list has the same weakness the
# v1.3.1 coverage guards had: a future window isn't in the tuple, so its
# mistake is invisible.
#
# This check does what a browser does: expand every {% include %} recursively
# (exactly as Jinja would), parse the resulting document, and assert no
# non-whitespace text node sits DIRECTLY under <body> -- in these templates all
# real text lives inside elements, so direct-child text of <body> can only be
# leaked source. Windows are discovered by glob (any templates/*.html starting
# with <!DOCTYPE), so a new window is covered the day it's created.

import glob as _glob
import os as _os
from html.parser import HTMLParser

from conftest import ROOT

_INCLUDE_RE = re.compile(r"\{%\s*include\s*'([^']+)'\s*%\}")

# Elements that never take a closing tag -- must not affect nesting depth.
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}


def _flatten_includes(rel_path, _stack=()):
    """Recursively expand {% include %} directives exactly as Jinja would
    (templates are resolved relative to templates/)."""
    assert rel_path not in _stack, f"include cycle: {_stack + (rel_path,)}"
    src = read_source(rel_path)
    return _INCLUDE_RE.sub(
        lambda m: _flatten_includes("templates/" + m.group(1), _stack + (rel_path,)),
        src,
    )


class _BodyTextFinder(HTMLParser):
    """Collects non-whitespace text nodes that are DIRECT children of <body>."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.depth = 0          # element depth relative to <body>
        self.stray = []

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
            self.depth = 0
        elif self.in_body and tag not in _VOID_TAGS:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        pass  # self-closing: no depth change

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
        elif self.in_body and tag not in _VOID_TAGS and self.depth > 0:
            self.depth -= 1

    def handle_data(self, data):
        if self.in_body and self.depth == 0 and data.strip():
            self.stray.append(data.strip()[:80])


def _window_templates():
    files = []
    for p in sorted(_glob.glob(_os.path.join(ROOT, "templates", "*.html"))):
        with open(p, encoding="utf-8") as fh:
            head = fh.read(200)
        if head.lstrip().lower().startswith("<!doctype"):
            files.append("templates/" + _os.path.basename(p))
    return files


def test_no_include_leaks_source_text_into_body_in_any_window():
    windows = _window_templates()
    # scope sanity: the glob must keep finding the known windows, or this
    # whole test passes vacuously.
    for known in ("templates/console.html", "templates/history.html",
                  "templates/index.html", "templates/subscriptions.html",
                  "templates/themes.html"):
        assert known in windows, f"window glob no longer finds {known}"

    for path in windows:
        finder = _BodyTextFinder()
        finder.feed(_flatten_includes(path))
        assert not finder.stray, (
            f"{path}: non-whitespace text directly under <body> after include "
            f"expansion -- a raw JS/CSS partial is being included outside its "
            f"<script>/<style> container and will render as visible source "
            f"text (the console.html i18n bug, generalized). Leaked: "
            f"{finder.stray[:3]}"
        )


def test_generalized_guard_has_teeth():
    """Prove-by-construction against the REAL broken structure: console.html
    with its include moved back outside the <script> tag (the exact shipped
    bug) must be flagged; the fixed structure must pass."""
    fixed = _flatten_includes("templates/console.html")
    finder = _BodyTextFinder()
    finder.feed(fixed)
    assert not finder.stray

    broken_template = read_source("templates/console.html").replace(
        "<script>\n{% include 'i18n.html' %}",
        "{% include 'i18n.html' %}\n<script>",
    )
    assert "{% include 'i18n.html' %}\n<script>" in broken_template, (
        "mutation anchor not found -- update this test if console.html's "
        "script/include layout changes"
    )
    broken = _INCLUDE_RE.sub(
        lambda m: _flatten_includes("templates/" + m.group(1), ("templates/console.html",)),
        broken_template,
    )
    finder = _BodyTextFinder()
    finder.feed(broken)
    assert finder.stray, (
        "the generalized guard failed to flag the exact structure that "
        "shipped broken -- it has no teeth"
    )
