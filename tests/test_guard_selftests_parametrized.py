"""Self tests of the two i18n guards (test_js_i18n_coverage.py, test_tooltip_i18n_coverage.py):
each case feeds the guard a snippet and states what it must flag or ignore, so a guard that
stops flagging (or starts flagging wired code) fails here.

Shape shared by every case: (snippet, expected findings) where expected is a list of
(fn_or_attr, text_predicate). An empty list means "ignored". The predicate is either an
exact string or a substring wrapped in Contains(); this keeps the three existing styles
(== exact, `in` substring, len-only) in one place. test_scope_covers_the_whole_template_tree is not
a snippet test and stays in each guard's file.
"""
import pytest

from test_js_i18n_coverage import _find_unwired as find_js
from test_tooltip_i18n_coverage import _find_unwired as find_attr


class Contains(str):
    """Match when the finding's text contains this fragment."""


def _check(find, html, expected):
    found = find(html, "fake.html")
    assert len(found) == len(expected), found
    for (path, lineno, where, text), (exp_where, exp_text) in zip(found, expected):
        assert where == exp_where, found
        if isinstance(exp_text, Contains):
            assert exp_text in text, found
        elif exp_text is not None:
            assert text == exp_text, found


JS_CASES = {
    "wired_toast": ("toast(i18nGet('toast.nothing_to_download') || 'Nothing to download', 'ok');", []),
    "wired_assignment": ("badge.textContent = i18nGet('plugins.badge.all_current') || 'All current';", []),
    "toast_type_argument_not_a_message": ("toast('Something happened', 'err');", [("toast", "Something happened")]),
    "punctuation_fragment_not_separate": ("toast('Reset failed' + ': ' + e.message, 'err');", [("toast", "Reset failed")]),
    "teeth_on_calls": ("toast('Cookies removed', 'ok');", [("toast", "Cookies removed")]),
    "teeth_on_assignments": ("dlBtn.textContent = 'Starting...';", [(".textContent", "Starting...")]),
    "teeth_on_confirm": ("confirm('Are you sure?');", [("confirm", None)]),
    "teeth_on_alert": ("alert('Are you sure?');", [("alert", None)]),
    # backtick messages: the blind spot the first version of the guard shipped with (interpolations,
    # quotes inside them, a nested call whose ")" truncated the old first-")"-wins extraction)
    "teeth_on_template_literal_nested_call": (
        "toast(`✗ Missing required vars: ${missing.slice(0,3).join(', ')}${missing.length>3?' …':''}`, 'err');",
        [("toast", Contains("Missing required vars"))]),
    "teeth_on_template_literal_nested_quotes": ('toast(`Theme "${esc(theme.name)}" applied ✓`, \'ok\');', [("toast", Contains("applied"))]),
    "teeth_on_double_quoted": ('toast("Cookies removed", \'ok\');', [("toast", "Cookies removed")]),
    "teeth_on_template_literal_assignment": ("more.textContent = `· · · ${hidden} more in this batch · · ·`;", [(".textContent", Contains("more in this batch"))]),
    # a literal that is not directly after "=" (the old regex's other blind spot): first branch wins
    "teeth_on_ternary_assignment": ("empty.textContent = total > 0 ? `${total} downloads (refresh to load)` : 'No downloads yet';", [(".textContent", Contains("refresh to load"))]),
    # `st${n}` builds an element id, not copy: letters but no space, so it is not flagged
    "ignores_dom_id_template_literal": ("setBadge(document.getElementById(`st${n}`), 'error', e.message);", []),
    "ignores_numeric_readout": ("setBadge(stEl, 'dl', `${Math.round(d.progress)}%${spd}`);", []),
    "teeth_on_setbadge": ("setBadge(stEl, 'error', 'Download interrupted');", [("setBadge", "Download interrupted")]),
    "wired_setbadge_fallback": ("setBadge(stEl, 'error', d.error || i18nGet('card.status.error') || '✗ Error');", []),
    "wired_template_fallback": ("toast(i18nFmt('toast.theme.applied', theme.name) || `Theme \"${theme.name}\" applied ✓`, 'ok');", []),
}

ATTR_CASES = {
    "dynamic_wiring": ('<button title="${i18nAttr(\'tooltip.card.pin\',\'Pin to top\')}">x</button>', []),
    "static_wiring": ('<button data-i18n-attr="title:panel.tab.themes" title="Browse and switch themes">x</button>', []),
    "css_attribute_selector": ('<style>.rb[title="Re-add"] { display: none; }</style>', []),
    "pure_user_data": ('<div title="${attrEsc(s.name || s.url)}">x</div>', []),
    "teeth": ('<button title="Drag to reorder">x</button>', [("title", "Drag to reorder")]),
}


@pytest.mark.parametrize("html, expected", JS_CASES.values(), ids=list(JS_CASES))
def test_js_guard(html, expected):
    _check(find_js, html, expected)


@pytest.mark.parametrize("html, expected", ATTR_CASES.values(), ids=list(ATTR_CASES))
def test_attr_guard(html, expected):
    _check(find_attr, html, expected)
