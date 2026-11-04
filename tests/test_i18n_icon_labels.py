"""A control that already shows an SVG icon must not get a second one from its translated label.

Four labels ("Open full history", "Create theme", "View all themes", "Import") carried an icon
character in every language (↗ ＋ › ↓) while the element next to them already had the SVG
icon, so each showed two icons. This scans every element with a data-i18n key that sits next to
an <svg> (or holds one) and checks that the English value neither starts nor ends with a symbol.
"""
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr", "path", "line", "polyline",
        "circle", "rect", "polygon", "ellipse"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = [{"tag": "#root", "kids": []}]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "key": dict(attrs).get("data-i18n"), "kids": [], "line": self.getpos()[0]}
        self.stack[-1]["kids"].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break


def _labels_next_to_an_icon(html):
    html = re.sub(r"<script\b.*?</script>", lambda m: "\n" * m.group(0).count("\n"), html, flags=re.S)
    tree = _Tree()
    tree.feed(html)
    out = []

    def walk(node):
        has_svg = any(k["tag"] == "svg" for k in node["kids"])
        for k in node["kids"]:
            if k.get("key") and (has_svg or any(g["tag"] == "svg" for g in k["kids"])):
                out.append((k["key"], k["line"]))
            walk(k)
    walk(tree.stack[0])
    return out


def _is_icon_char(ch):
    return bool(ch) and unicodedata.category(ch)[0] == "S" or ch in "›‹»«"


def test_labels_beside_an_svg_icon_carry_no_icon_character_of_their_own():
    en = json.loads((ROOT / "languages" / "en.json").read_text(encoding="utf-8"))["strings"]
    found = []
    for page in sorted((ROOT / "templates").glob("*.html")):
        found += [(page.name, line, key) for key, line in _labels_next_to_an_icon(page.read_text(encoding="utf-8"))]
    assert len(found) >= 4, f"the scan found only {found}; it no longer sees the labels"
    doubled = [(p, line, k, en[k]) for p, line, k in found
               if k in en and (_is_icon_char(en[k][:1]) or _is_icon_char(en[k][-1:]))]
    assert doubled == [], f"these labels sit next to an SVG icon and add one of their own: {doubled}"


def test_the_scan_sees_a_doubled_icon():
    html = '<button><svg><path d=""/></svg><span data-i18n="k">x</span></button>'
    assert _labels_next_to_an_icon(html) == [("k", 1)]
