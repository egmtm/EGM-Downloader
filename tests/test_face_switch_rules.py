"""The rules in index_styles.html that a Face switch relies on (applyFace in templates/js/_face.html).

The switch is drawn as a view transition. While it runs, html carries the class face-switching, and
two rules hang on that class (the frontend tests cover that the class goes on and comes off). Those
tests have no layout and no view transitions, so nothing else notices when one of the rules is lost
or widened:

- the page's own CSS transitions are off, as for a direction change (several elements have
  transition: all, which would animate sizes by themselves, in the instant path too);
- the parts that change place are named for the transition only while the class is on (a lasting
  name makes an element a stacking context and could change what overlaps what in Classic), and of
  the queue only the first few cards are named: every name costs a capture, and a queue can hold
  hundreds. Measured in Chromium with every card named: 300 cards froze the window for 1 s, 1000
  cards for 6 to 13 s.
"""
import re

from conftest import read_source

CSS = re.sub(r"/\*.*?\*/", "", read_source("templates/index_styles.html"), flags=re.S)
NAMED_CARDS_AT_MOST = 8


def test_the_pages_own_transitions_are_off_during_a_switch():
    assert re.search(r"html\.face-switching \*\s*,[^{]*\{\s*transition:\s*none\s*!important", CSS), \
        "index_styles.html has no rule that turns transitions off under html.face-switching"


def test_parts_are_named_only_during_a_switch_and_only_the_first_queue_cards():
    naming = [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS)
              if re.search(r"view-transition-name\s*:\s*(?!none\b)", body)]
    assert naming, "no rule names the parts of the page for the Face switch"
    for selector, _ in naming:
        assert selector.startswith("html.face-switching "), f"named outside a Face switch: {selector}"
        cards = re.findall(r"\.vcard\b(?!-)(:nth-child\(-n\+(\d+)\))?", selector)
        assert cards, f"the queue cards are not named at all: {selector}"
        for bound, n in cards:
            assert bound and int(n) <= NAMED_CARDS_AT_MOST, f"every queue card is named, or too many: {selector}"
