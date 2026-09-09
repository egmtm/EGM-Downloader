"""Regression coverage for the What's New footer button (manual re-trigger of
the existing "shown once per version" modal) and two bugs fixed while wiring
it up. Scoped narrowly to what's genuinely fragile here -- the broader
i18n/element-id/parity guards elsewhere already cover the general cases."""
import json
import re

from conftest import read_source

INDEX_FILES = ("templates/index.html", "linux/templates/index.html")
QUALITY_FILES = ("templates/js/_quality.html", "linux/templates/js/_quality.html")


def test_footer_whatsnew_button_present_and_correctly_ordered():
    """The button must sit between the version pill and the Diagnostics
    button (EGM's specified placement), on both platform copies."""
    for p in INDEX_FILES:
        src = read_source(p)
        pill_at = src.index('id="footer-version-pill"')
        btn_at = src.index('id="footer-whatsnew-btn"')
        diag_at = src.index('id="footer-diagnostics-btn"')
        assert pill_at < btn_at < diag_at, (
            f"{p}: footer-whatsnew-btn must sit between the version pill "
            f"and the Diagnostics button, found at pill={pill_at} "
            f"btn={btn_at} diag={diag_at}"
        )
        assert 'data-i18n="footer.btn.whatsnew"' in src, (
            f"{p}: footer-whatsnew-btn is missing its data-i18n wiring"
        )


def test_whatsnew_title_placeholder_split_is_not_english_word_order():
    """Regression guard: the modal heading was hardcoded English ("What's
    New in <version>") with whatsnew.title translated in all 10 locales but
    never actually applied. Fixing this means splitting the translated
    string on the literal '{0}' placeholder, NOT assuming the version comes
    last -- Japanese's translation puts it first ("{0}の新機能"). A fix that
    just moved the hardcoded prefix into JS but kept it English-word-order
    (e.g. always rendering "<prefix><version>") would silently mistranslate
    every locale where the placeholder isn't at the end."""
    for p in QUALITY_FILES:
        src = read_source(p)
        assert "i18nGet('whatsnew.title')" in src, (
            f"{p}: whats-new heading must read whatsnew.title, not a "
            f"hardcoded string"
        )
        assert "titleTemplate.split('{0}')" in src, (
            f"{p}: must split on the literal '{{0}}' placeholder rather than "
            f"assuming the version substitution comes at a fixed position"
        )
        # The two resulting segments must both be applied -- a fix that only
        # used the "before" half would silently drop the Japanese case where
        # the meaningful text is entirely in the "after" half.
        assert "whats-new-title-before" in src and "whats-new-title-after" in src, (
            f"{p}: both sides of the {{0}} split must be wired to the DOM"
        )


def test_whatsnew_dismiss_listener_is_reusable_not_one_shot():
    """Regression guard: the dismiss button's listener was originally
    attached with {once: true} inside the auto-show IIFE, since only the
    automatic once-per-version path existed. Adding the manual footer button
    means the modal can now open multiple times per session -- a listener
    that consumes itself after the first dismiss would leave the second and
    every subsequent manual open with a dead 'Got it' button."""
    for p in QUALITY_FILES:
        src = read_source(p)
        i = src.index("whats-new-dismiss-btn").__index__()
        # Find the addEventListener call attached to the dismiss button and
        # confirm it does NOT carry {once: true}.
        j = src.index("addEventListener", i)
        k = src.index(";", j)
        # The listener call may span multiple statements before the
        # terminating ';' of the whole addEventListener(...) expression --
        # walk forward to the matching close paren instead for safety.
        open_paren = src.index("(", j)
        depth = 0
        m = open_paren
        for idx in range(open_paren, len(src)):
            if src[idx] == "(":
                depth += 1
            elif src[idx] == ")":
                depth -= 1
                if depth == 0:
                    m = idx
                    break
        call_src = src[j:m + 1]
        assert "once" not in call_src, (
            f"{p}: the whats-new-dismiss-btn listener must not be "
            f"{{once: true}} -- the button can now be shown multiple times "
            f"per session via the manual footer trigger"
        )


def test_footer_whatsnew_button_click_handler_calls_show_function():
    """The manual trigger must call the same showWhatsNewModal() the
    automatic once-per-version path uses, not a separate/divergent
    implementation that could drift (e.g. missing the fallback-notes
    handling or the i18n title wiring)."""
    for p in QUALITY_FILES:
        src = read_source(p)
        assert "async function showWhatsNewModal(" in src, (
            f"{p}: expected a single shared showWhatsNewModal(version) "
            f"function used by both the automatic and manual paths"
        )
        i = src.index("footer-whatsnew-btn").__index__()
        j = src.index("addEventListener", i)
        k = src.index("});", j)
        handler_src = src[j:k]
        assert "showWhatsNewModal(" in handler_src, (
            f"{p}: footer-whatsnew-btn's click handler must call "
            f"showWhatsNewModal(), not a separate implementation"
        )


def test_footer_whatsnew_key_present_in_every_locale():
    """The new footer.btn.whatsnew key must exist in all 10 locales (English
    placeholder is fine pending Linguist translation -- this only guards
    against the key being missing entirely, which would silently fall back
    to the raw key name in the UI)."""
    import os
    root = os.path.dirname(os.path.dirname(__file__))
    lang_dir = os.path.join(root, "languages")
    locales = sorted(f for f in os.listdir(lang_dir) if f.endswith(".json"))
    assert len(locales) == 10, f"expected 10 locale files, found {len(locales)}"
    for fname in locales:
        d = json.load(open(os.path.join(lang_dir, fname), encoding="utf-8"))
        assert "footer.btn.whatsnew" in d["strings"], (
            f"{fname}: missing footer.btn.whatsnew"
        )
        assert d["strings"]["footer.btn.whatsnew"].strip(), (
            f"{fname}: footer.btn.whatsnew is present but empty"
        )
