"""Tooltip/attribute translation coverage guard.

Found by EGM during manual testing: roughly half of the app's tooltips
(title=/aria-label=/placeholder=/alt=) were hardcoded English with zero
i18n wiring of any kind, regardless of selected language. History window
had ZERO wired tooltips. The translation *mechanism* itself was never
broken (verified independently with a real browser render before writing
this test) -- these attributes just never got wired in the first place.

Root cause: tooltip translation happened incrementally, tied to whatever
feature was being built that day, never as one deliberate sweep of every
existing tooltip already in the app. The only prior i18n test
(test_i18n_keys_exist_in_en_locale) checks the opposite direction --
that keys someone already referenced actually exist -- it has no
awareness of an attribute that was never referenced at all.

This test flags any title/placeholder/aria-label/alt attribute that
looks like real, static, translatable UI copy but has no i18n wiring of
either recognized kind:
  - the static convention: data-i18n-attr="attr:key" on the same element
  - the dynamic convention (JS-template-literal windows): an inline
    i18nAttr()/i18nGet()/i18nFmt() call inside the attribute's own value

Two classes of match are correctly NOT flagged, both confirmed by
tracing real examples before writing the exclusion, not guessed:
  - CSS attribute selectors inside <style> blocks (e.g. history.html's
    .rb[title="Re-add"] -- matches an element by its title value, isn't
    an element's title attribute itself)
  - attributes that are purely user data after removing ${...}
    interpolation (channel names, file paths via attrEsc()) -- these
    display the user's own data, not app copy, and must never be
    translated (same principle as never translating a person's name)

New static tooltips going forward: use data-i18n-attr like everything
else. New dynamic ones (template-literal windows): call i18nAttr()
inline, same as the existing wired examples in those files.
"""
import re

from conftest import ROOT, read_source

FILES = (
    "templates/index.html",
    "templates/history.html",
    "templates/themes.html",
    "templates/subscriptions.html",
)

ATTRS = ("title", "placeholder", "aria-label", "alt")

I18N_CALL_RE = re.compile(r"i18n(?:Attr|Get|Fmt)\(")
INTERPOLATION_RE = re.compile(r"\$\{[^}]*\}")

# Explicit, reasoned exceptions -- not a dumping ground. Each entry names the
# exact static text and why it's allowed to stay unwired. Add here only with
# the same reasoning bar as the ones already documented, not to silence a
# real gap.
ALLOWED_UNWIRED = {
    # (file, attr, text): reason
}


def _strip_style_blocks(html: str) -> str:
    return re.sub(r"<style\b.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)


def _find_unwired(html: str, path: str):
    unwired = []
    body = _strip_style_blocks(html)
    for lineno, line in enumerate(body.split("\n"), start=1):
        for attr in ATTRS:
            for m in re.finditer(rf'{attr}="([^"]*)"', line):
                value = m.group(1).strip()
                if not value:
                    continue
                # Wired via the dynamic (inline i18n call) convention.
                if I18N_CALL_RE.search(value):
                    continue
                # Wired via the static (data-i18n-attr) convention on this element.
                if re.search(rf'data-i18n-attr="[^"]*{attr}:', line):
                    continue
                # Purely user data (e.g. attrEsc(channel_name)) once interpolation
                # is stripped -- nothing left that looks like translatable copy.
                residual = INTERPOLATION_RE.sub("", value)
                if not re.search(r"[A-Za-z]{2,}", residual):
                    continue
                key = (path, attr, value)
                if key in ALLOWED_UNWIRED:
                    continue
                unwired.append((path, lineno, attr, value))
    return unwired


def test_no_unwired_translatable_attributes():
    all_unwired = []
    for f in FILES:
        html = read_source(f)
        all_unwired.extend(_find_unwired(html, f))

    if all_unwired:
        lines = "\n".join(
            f"  {path}:{lineno} {attr}=\"{value[:60]}\"" for path, lineno, attr, value in all_unwired
        )
        raise AssertionError(
            f"{len(all_unwired)} translatable attribute(s) with no i18n wiring "
            f"of any kind -- wire with data-i18n-attr (static HTML) or an "
            f"inline i18nAttr() call (JS template-literal windows), or add a "
            f"reasoned entry to ALLOWED_UNWIRED if this one genuinely "
            f"shouldn't be translated:\n{lines}"
        )


def test_guard_recognizes_the_dynamic_wiring_convention():
    """Prove-by-construction: an inline i18nAttr() call must NOT be flagged,
    since history.html/themes.html/subscriptions.html rely on exactly this
    pattern for their real, already-wired tooltips."""
    html = '<button title="${i18nAttr(\'tooltip.card.pin\',\'Pin to top\')}">x</button>'
    assert _find_unwired(html, "fake.html") == []


def test_guard_recognizes_the_static_wiring_convention():
    html = '<button data-i18n-attr="title:panel.tab.themes" title="Browse and switch themes">x</button>'
    assert _find_unwired(html, "fake.html") == []


def test_guard_ignores_css_attribute_selectors():
    html = '<style>.rb[title="Re-add"] { display: none; }</style>'
    assert _find_unwired(html, "fake.html") == []


def test_guard_ignores_pure_user_data():
    html = '<div title="${attrEsc(s.name || s.url)}">x</div>'
    assert _find_unwired(html, "fake.html") == []


def test_guard_has_teeth():
    """Prove-by-mutation: a genuinely unwired, genuinely translatable
    attribute must be flagged."""
    html = '<button title="Drag to reorder">x</button>'
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1
    assert found[0][2] == "title" and found[0][3] == "Drag to reorder"
