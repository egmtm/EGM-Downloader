"""In v2 the message of a link that could not be fetched wraps, as it does in Classic.

The v2 queue rows keep the line under the title (channel and duration) on one line and cut it short.
A link that could not be fetched has no such line: renderErr (templates/js/_download.html) puts the
whole error message there, and a message the app has no short text for is shown as the backend sent
it. Measured in Chromium at 700 px wide with a message of 237 characters: one line 1356 px long in
a row of 485 px, so 871 px were hidden, with no ellipsis (the badge is a flex box) and no tooltip.
Classic shows the same message on four lines.
"""
import re

from conftest import read_source


def _declarations(css, wanted):
    """The declarations of every rule that has `wanted` among its selectors, as one dict."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if wanted in [s.strip() for s in selectors.split(",")]:
            out.update(dict((p.strip(), v.strip()) for p, _, v in (d.partition(":") for d in body.split(";")) if p.strip()))
    return out


def test_the_error_message_of_a_fetch_error_card_wraps_in_v2():
    css = read_source("templates/face_v2_styles.html")
    line = _declarations(css, "body.face-v2 .vmeta")
    assert line.get("white-space") == "nowrap" and line.get("overflow") == "hidden", "the v2 rows no longer cut the line under the title: this test is out of date"
    error = _declarations(css, "body.face-v2 .fetch-err .vmeta")
    assert error.get("white-space") == "normal" and error.get("overflow") == "visible", \
        "in v2 a fetch error is cut to one line again, and most of a long message cannot be read"


def test_a_fetch_error_card_still_shows_its_message_in_that_line():
    page = read_source("templates/js/_download.html")
    render = page[page.index("function renderErr("):page.index("// Shown when a video has no thumbnail")]
    assert "el.classList.add('fetch-err')" in render and '<div class="vmeta"><span class="badge b-error">' in render, \
        "renderErr builds the error card another way: check that its message still wraps in v2"
