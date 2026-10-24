"""No new left/right CSS in the templates: the layout mirrors for right to left languages.

Arabic sets dir="rtl" on the page, and the templates use logical properties (margin-inline-start,
padding-inline-end, border-inline-start, inset-inline-end, text-align: start/end) so the layout
mirrors on its own. A physical one (margin-left, padding-right, border-left, left:/right: offsets,
text-align: left/right) stays put in Arabic, so this test fails when one appears in a stylesheet
rule, a <style> block, a style="" attribute (in markup or built in a JS string), a cssText string,
or an el.style.marginLeft style assignment.

Only places CSS lives are read: comments are blanked first and text content is never scanned, so
prose and JS geometry such as getBoundingClientRect().left do not count. The few physical
properties that are right on purpose are listed in ALLOWED by file and exact line text, each with
its reason. An entry that no longer matches fails too, so the list cannot rot.
"""
import glob
import os
import re

import pytest

from conftest import ROOT

ALLOWED = {
    ("templates/index_styles.html", "border-right: 1.5px solid #fff; border-bottom: 1.5px solid #fff;"):
        "the theme check mark is two borders turned 45 degrees; a check mark is not mirrored",
    ("templates/index_styles.html", ".vtitle { font-size: .9rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding-right: 4px; }"):
        "the title is dir=\"auto\", so padding-inline-end would follow the title; the gap follows the page instead",
    ("templates/index_styles.html", "[dir=rtl] .vtitle { padding-right: 0; padding-left: 4px; }   /* the gap follows the page; the title itself is dir=\"auto\" */"):
        "the right to left side of the line above",
    ("templates/index_styles.html", ".quit-card { position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%); z-index: 20001; display: flex; flex-direction: column; align-items: center; gap: 14px; min-width: min(300px, 86vw); padding: 22px 28px; background: var(--surf); border: 1px solid var(--border2); border-radius: 12px; box-shadow: var(--modal-shadow); color: var(--text); font-size: .95rem; font-weight: 600; text-align: center; animation: quit-card-in .18s ease; }"):
        "centred with left: 50% and translate(-50%), the same in both directions",
    ("templates/subscriptions.html", ".quit-card { position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%); z-index: 20001; display: flex; flex-direction: column; align-items: center; gap: 14px; min-width: min(300px, 86vw); padding: 22px 28px; background: var(--surf); border: 1px solid var(--border2); border-radius: 12px; box-shadow: var(--modal-shadow); color: var(--text); font-size: .95rem; font-weight: 600; text-align: center; animation: quit-card-in .18s ease; }"):
        "centred with left: 50% and translate(-50%), the same in both directions",
}

# Files that are plain CSS, included inside a <style> element.
CSS_FILES = {"index_styles.html", "theme_styles.html"}

PHYSICAL = re.compile(
    r"(?<![\w.$-])(?:(?:margin|padding)-(?:left|right)|border-(?:left|right)(?:-[a-z]+)?)\s*:"
    r"|(?<![\w.$-])(?:left|right)\s*:\s*(?=[-+.\d]|auto\b|calc\(|var\()"
    r"|(?<![\w-])text-align\s*:\s*(?:left|right)\b")
CSSOM = re.compile(r"\.style\.(?:(?:margin|padding|border)(?:Left|Right)\w*\s*=|textAlign\s*=\s*['\"](?:left|right)\b)")
STYLE_BLOCK = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)
STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""")
CSS_TEXT = re.compile(r"""cssText\s*\+?=\s*(['"`])(.*?)\1""")
COMMENTS = re.compile(r"/\*.*?\*/|<!--.*?-->|(?:^|(?<=[\s;{}(),]))//[^\n]*", re.S | re.M)


def _blank(m):
    return re.sub(r"[^\n]", " ", m.group(0))   # keep offsets and line numbers


def findings(name, text):
    """(offset, matched text) for every physical property in the places CSS lives."""
    text = COMMENTS.sub(_blank, text)
    spans = [(0, text)] if name in CSS_FILES else []
    for rx, group in ((STYLE_BLOCK, 1), (STYLE_ATTR, None), (CSS_TEXT, 2)):
        for m in rx.finditer(text):
            g = group or (1 if m.group(1) is not None else 2)
            spans.append((m.start(g), m.group(g)))
    hits = {(start + m.start(), m.group(0)) for start, body in spans for m in PHYSICAL.finditer(body)}
    hits |= {(m.start(), m.group(0)) for m in CSSOM.finditer(text)}
    return sorted(hits)


def _scan():
    out = []
    files = glob.glob(os.path.join(ROOT, "templates", "*.html")) + glob.glob(os.path.join(ROOT, "templates", "js", "*.html"))
    for path in sorted(files):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        text = open(path, encoding="utf-8").read()
        lines = text.split("\n")
        for offset, what in findings(os.path.basename(path), text):
            n = text.count("\n", 0, offset)
            out.append((rel, n + 1, lines[n].strip(), what))
    return out


def test_no_physical_left_right_properties_outside_the_allowlist():
    found = _scan()
    new = [f"{rel}:{n}: {what!r} in: {line[:160]}" for rel, n, line, what in found if (rel, line) not in ALLOWED]
    assert not new, ("physical left/right CSS mirrors wrong in Arabic; use the logical property "
                     "(margin-inline-start, padding-inline-end, border-inline-start, inset-inline-end, "
                     "text-align: start/end) or, if it is right on purpose, add it to ALLOWED with a reason:\n"
                     + "\n".join(new))
    used = {(rel, line) for rel, _n, line, _w in found}
    stale = [key for key in ALLOWED if key not in used]
    assert not stale, f"ALLOWED entries that no longer match a line: {stale}"


@pytest.mark.parametrize("name, text, expected", [
    ("a.html", "<style>.x { margin-left: 4px; }</style>", 1),
    ("a.html", '<div style="padding-right:8px;color:red">', 1),
    ("a.html", "el.innerHTML = `<span style=\"border-left:2px solid\">${t}</span>`;", 1),
    ("a.html", "t.style.cssText = 'display:flex;right:0';", 1),
    ("a.html", "el.style.marginLeft = '4px';", 1),
    ("index_styles.html", ".x { text-align: right; left: 2px; }", 2),
    ("index_styles.html", ".x { margin-inline-start: 4px; inset-inline-end: 0; text-align: end; }", 0),
    ("index_styles.html", "/* nav → margin-right -21px lands its right edge */ .x { color: red; }", 0),
    ("a.html", "<p>Move it left: 4 places</p>", 0),
    ("a.html", "const r = el.getBoundingClientRect(); let left = r.right - w; menu.style.left = left + 'px';", 0),
    ("a.html", "// was style=\"margin-left:auto\"\nconst a = 1;", 0),
])
def test_guard_finds_physical_css_and_ignores_the_rest(name, text, expected):
    assert len(findings(name, text)) == expected
