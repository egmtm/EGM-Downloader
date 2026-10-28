"""Every row of the hidden static theme list in index.html must be a whole row.

#theme-list-static is hidden, but the seasonal code and tests read it. A row that stops after its
swatches (no name, no check mark, no closing tag) swallows the next row inside it, and something
further down has to carry stray closing tags to keep the page balanced. Windows and Mac read
templates/, Linux reads linux/templates/ (kept byte identical elsewhere).
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TREES = ("templates", "linux/templates")


class _Rows(HTMLParser):
    """Collect one record per .theme-row of the static list, and note rows that open inside another row."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self.nested = []
        self._divs = []   # stack of div kinds: "row", "swatches", "other"
        self._row = None

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div":
            if "theme-row" in classes:
                key = dict(attrs).get("data-theme", "?")
                if self._row is not None:
                    self.nested.append(key)
                self._row = {"key": key, "swatches": 0, "name": 0, "check": 0}
                self.rows.append(self._row)
                self._divs.append("row")
                return
            self._divs.append("other")
            if self._row is not None:
                if "theme-swatches" in classes:
                    self._divs[-1] = "swatches"
                elif "theme-sw" in classes:
                    self._row["swatches"] += 1
                elif "theme-check" in classes:
                    self._row["check"] += 1
        elif tag == "span" and self._row is not None and "theme-name" in classes:
            self._row["name"] += 1

    def handle_endtag(self, tag):
        if tag == "div" and self._divs:
            if self._divs.pop() == "row":
                self._row = None


def static_rows(html):
    start = html.index('id="theme-list-static"')
    end = html.index("end theme-list-static")
    p = _Rows()
    p.feed(html[start:end])
    return p


def _problems(html):
    p = static_rows(html)
    bad = [f"{r['key']} (swatches {r['swatches']}, names {r['name']}, checks {r['check']})"
           for r in p.rows if (r["swatches"], r["name"], r["check"]) != (3, 1, 1)]
    return p, bad


@pytest.mark.parametrize("tree", TREES)
def test_every_static_theme_row_is_whole(tree):
    p, bad = _problems((ROOT / tree / "index.html").read_text(encoding="utf-8"))
    assert len(p.rows) > 400, f"{tree}: only {len(p.rows)} rows found in #theme-list-static"
    assert not bad, f"{tree}: rows without three swatches, one name and one check mark: {bad}"
    assert not p.nested, f"{tree}: rows opened inside another row (a cut-off row before them): {p.nested}"


def test_a_cut_off_row_fails_the_check():
    """The check itself: a row that stops after its swatches is reported, and so is the row it swallows."""
    sw = '<div class="theme-swatches">' + '<div class="theme-sw"></div>' * 3 + "</div>"
    whole = f'<div class="theme-row" data-theme="a">{sw}<span class="theme-name">A</span><div class="theme-check"></div></div>'
    cut = f'<div class="theme-row" data-theme="b">{sw}'
    page = lambda body: f'<div id="theme-list-static">{body}</div><!-- end theme-list-static -->'
    assert _problems(page(whole + whole))[1] == []
    p, bad = _problems(page(whole + cut + whole))
    assert any(b.startswith("b ") for b in bad) and p.nested == ["a"], (bad, p.nested)
