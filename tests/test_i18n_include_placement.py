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
