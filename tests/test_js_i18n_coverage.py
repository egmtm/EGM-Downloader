"""JS-level translation coverage guard: toast()/confirm()/alert() calls and
direct textContent/innerText assignments.

Companion to test_tooltip_i18n_coverage.py, which only covers HTML
attributes (title/placeholder/aria-label/alt). This one covers the other
surface EGM found broken during manual testing: roughly 60 user-facing
JS-level messages (toast notifications, confirm dialogs, an alert, and a
few direct status-text assignments) were hardcoded English across 12
files, discovered in two rounds of full-codebase sweeps after the
attribute-level fix already shipped. Every one of the ~60 traces back to
the same root cause as the tooltip gap: wired incrementally per-feature,
never audited as a whole surface.

This test flags any toast()/confirm()/alert() call, or any
.textContent=/.innerText= assignment, whose message is a plain hardcoded
string with no i18n wiring of any kind (data-i18n-attr doesn't apply
here -- these are pure JS, not HTML attributes -- so the only recognized
wiring is an inline i18nGet()/i18nFmt()/i18nAttr() call within the same
statement).

Two classes of match are correctly NOT flagged:
  - the toast() TYPE argument ('err'/'warn'/'ok'), which looks like a
    hardcoded string but is a status code, not user-facing text
  - short punctuation/connector fragments used as concatenation glue
    (': ', ' — ', '. ') that aren't real standalone messages on their own

New hardcoded JS messages going forward: wrap with
`i18nGet('key') || 'original English'`, matching every existing call
site's own established pattern.
"""
import re

from conftest import read_source

FILES = (
    "templates/index.html",
    "templates/history.html",
    "templates/themes.html",
    "templates/subscriptions.html",
    "templates/js/_bulk.html",
    "templates/js/_core.html",
    "templates/js/_download.html",
    "templates/js/_nav_history.html",
    "templates/js/_creator.html",
    "templates/js/_settings.html",
    "templates/js/_quality.html",
    "templates/js/_theme.html",
)

CALL_FNS = ("toast", "confirm", "alert")
ASSIGN_PROPS = ("textContent", "innerText")

I18N_CALL_RE = re.compile(r"i18n(?:Get|Fmt|Attr)\(")

# toast()'s own status-code argument, not a message.
TYPE_TOKENS = {"err", "warn", "ok", ""}

# Explicit, reasoned exceptions -- not a dumping ground. Each entry names the
# exact string and file, with the same reasoning bar as
# test_tooltip_i18n_coverage.py's ALLOWED_UNWIRED.
ALLOWED_UNWIRED = {
    # (file, text): reason
}


def _looks_translatable(text: str) -> bool:
    """A real message has at least one run of 2+ letters that isn't just
    connector punctuation ('. ', ': ', ' — '), and isn't CSS syntax being
    dynamically constructed for injection into a <style> element (which
    always contains a literal '{' -- confirmed against a real example,
    themes.html's custom-theme-style builder: `'body.custom{' + ... + '}'`)."""
    if "{" in text or "}" in text:
        return False
    return bool(re.search(r"[A-Za-z]{2,}", text))


def _find_unwired(html: str, path: str):
    unwired = []
    for lineno, line in enumerate(html.split("\n"), start=1):
        # toast()/confirm()/alert() calls
        for fn in CALL_FNS:
            for m in re.finditer(rf"\b{fn}\(([^;]*?)\)", line):
                call = m.group(1)
                if I18N_CALL_RE.search(call):
                    continue
                qm = re.search(r"'([^']{1,150})'", call)
                if not qm:
                    continue
                text = qm.group(1)
                if text in TYPE_TOKENS or not _looks_translatable(text):
                    continue
                if (path, text) in ALLOWED_UNWIRED:
                    continue
                unwired.append((path, lineno, fn, text))
        # direct .textContent = / .innerText = assignments
        for prop in ASSIGN_PROPS:
            for m in re.finditer(rf"\.{prop}\s*=\s*'([^']{{1,150}})'", line):
                text = m.group(1)
                if I18N_CALL_RE.search(line) and I18N_CALL_RE.search(line).start() < m.start():
                    # an i18n call earlier on the same line is almost certainly
                    # feeding this assignment (e.g. `x.textContent = i18nGet(...) || '...'`)
                    continue
                if not _looks_translatable(text):
                    continue
                if (path, text) in ALLOWED_UNWIRED:
                    continue
                unwired.append((path, lineno, f".{prop}", text))
    return unwired


def test_no_unwired_js_messages():
    all_unwired = []
    for f in FILES:
        html = read_source(f)
        all_unwired.extend(_find_unwired(html, f))

    if all_unwired:
        lines = "\n".join(
            f"  {path}:{lineno} {kind}: \"{text[:70]}\"" for path, lineno, kind, text in all_unwired
        )
        raise AssertionError(
            f"{len(all_unwired)} hardcoded JS message(s) with no i18n wiring -- "
            f"wrap with i18nGet('key') || 'original text', matching every "
            f"existing call site, or add a reasoned entry to ALLOWED_UNWIRED "
            f"if this one genuinely shouldn't be translated:\n{lines}"
        )


def test_guard_recognizes_wired_toast():
    html = "toast(i18nGet('toast.done') || 'Done', 'ok');"
    assert _find_unwired(html, "fake.html") == []


def test_guard_recognizes_wired_assignment():
    html = "badge.textContent = i18nGet('plugins.badge.all_current') || 'All current';"
    assert _find_unwired(html, "fake.html") == []


def test_guard_ignores_toast_type_argument():
    # Second arg alone, if somehow matched, must never be flagged as a message.
    html = "toast('Something happened', 'err');"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1 and found[0][3] == "Something happened"  # only the real message


def test_guard_ignores_punctuation_fragments():
    html = "toast('Reset failed' + ': ' + e.message, 'err');"
    found = _find_unwired(html, "fake.html")
    # 'Reset failed' should be flagged, ': ' should not be a separate finding
    texts = [f[3] for f in found]
    assert ": " not in texts


def test_guard_has_teeth_on_calls():
    html = "toast('Cookies removed', 'ok');"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1
    assert found[0][2] == "toast" and found[0][3] == "Cookies removed"


def test_guard_has_teeth_on_assignments():
    html = "dlBtn.textContent = 'Starting...';"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1
    assert found[0][2] == ".textContent" and found[0][3] == "Starting..."


def test_guard_has_teeth_on_confirm_and_alert():
    for fn in ("confirm", "alert"):
        html = f"{fn}('Are you sure?');"
        found = _find_unwired(html, "fake.html")
        assert len(found) == 1 and found[0][2] == fn
