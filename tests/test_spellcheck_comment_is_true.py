"""The comment above setSpellCheckerLanguages([]) says what is true.

It said "every input already turns spellcheck off", which is not so: two inputs in index.html set
spellcheck="false" and no other input does. What keeps spelling unchecked is every BrowserWindow, which
turns spellcheck off in its webPreferences (tests/test_no_background_contacts.py), and the session has
no spellchecker language. The comment now says that; these facts are held here so it stays true."""
import re
from pathlib import Path

import pytest

from conftest import ROOT, read_source

MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")


@pytest.mark.parametrize("rel", MAIN_JS + ("tests/test_no_background_contacts.py",))
def test_the_false_sentence_is_gone(rel):
    assert "every input already turns spellcheck off" not in read_source(rel)
    assert "the app's inputs already set" not in read_source(rel)


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_comment_names_what_really_turns_it_off(rel):
    src = read_source(rel)
    comment = src[src.index("// No spellchecker language"):src.index("session.defaultSession.setSpellCheckerLanguages([])")]
    assert "every BrowserWindow turns spellcheck off in" in comment and "webPreferences" in comment
    assert "the two inputs in index.html" in comment


def test_exactly_two_inputs_set_the_attribute_both_in_index_html():
    found = []
    for p in sorted(Path(ROOT, "templates").rglob("*.html")):
        for m in re.finditer(r"<(input|textarea)\b[^>]*\bspellcheck\s*=", p.read_text(encoding="utf-8"), re.I):
            found.append((p.name, m.group(0)[:40]))
    assert [name for name, _ in found] == ["index.html", "index.html"], found
