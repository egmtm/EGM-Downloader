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

Three classes of match are correctly NOT flagged:
  - the toast()/setBadge() TYPE argument ('err'/'warn'/'ok' and setBadge's
    'dl'/'done'/'error'/'wait'/'cancel'), which looks like a hardcoded
    string but is a status code, not user-facing text
  - short punctuation/connector fragments used as concatenation glue
    (': ', ' — ', '. ') that aren't real standalone messages on their own
  - template literals whose only content is interpolation plumbing --
    DOM-id builders like `st${n}` or numeric readouts like
    `${pct}%` -- recognized by having no space in the residual once
    every ${...} is stripped (every real template-literal message in the
    codebase is a multi-word sentence)

The original version of this guard only extracted single-quoted
strings, so any message built as a backtick template literal (or a
double-quoted string) was invisible -- that blind spot hid 5 live
unwired toasts. It also matched calls with a first-')'-wins regex, so a
nested call like esc(...) truncated the argument text before the
message was reached, and it only looked at a string directly after
'=' in assignments, missing ternaries. All three are fixed here:
strings of all three JS quote kinds are extracted (template literals
have their ${...} interpolations stripped first, and a literal that
opens on the line but closes on a later one is scanned from the
backtick to end-of-line), calls are extracted paren-balanced and
quote-aware, and assignments scan the full right-hand side.

New hardcoded JS messages going forward: wrap with
`i18nGet('key') || 'original English'` (or i18nFmt for messages with
dynamic values), matching every existing call site's own established
pattern.

Scope is derived from the template tree (templates/*.html +
templates/js/*.html), not a hand-maintained list, for the same reason
as test_tooltip_i18n_coverage.py -- a new window or partial is covered
automatically, and the scope-sanity test keeps the glob honest.
"""
import glob
import os
import re

from conftest import ROOT, read_source


def _template_files():
    files = []
    for pattern in ("templates/*.html", "templates/js/*.html"):
        files.extend(sorted(glob.glob(os.path.join(ROOT, pattern))))
    return tuple(os.path.relpath(f, ROOT).replace(os.sep, "/") for f in files)


FILES = _template_files()

KNOWN_FILES = (
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

CALL_FNS = ("toast", "confirm", "alert", "setBadge")
ASSIGN_PROPS = ("textContent", "innerText")

I18N_CALL_RE = re.compile(r"i18n(?:Get|Fmt|Attr)\(")
INTERPOLATION_RE = re.compile(r"\$\{[^}]*\}")

# toast()'s and setBadge()'s own status-code arguments, not messages.
TYPE_TOKENS = {"err", "warn", "ok", "", "dl", "done", "error", "wait", "cancel"}

# Explicit, reasoned exceptions -- not a dumping ground. Each entry names the
# exact string and file, with the same reasoning bar as
# test_tooltip_i18n_coverage.py's ALLOWED_UNWIRED.
ALLOWED_UNWIRED = {
    # (file, text): reason
    ("templates/js/_theme.html", "Custom"):
        "default label for the custom-theme row when the user's theme has no "
        "name -- a theme-catalog label, same class as its 500 untranslated "
        "siblings (Lavender, Espresso, ...), and replaced by the user's own "
        "theme name whenever one exists. Kept consistent with the static "
        "'Custom' in index.html's theme list and THEME_DATA's custom entry; "
        "translating this one catalog label but not the others would be "
        "inconsistent.",
}


def _looks_translatable(text: str, template: bool = False) -> bool:
    """A real message has at least one run of 2+ letters that isn't just
    connector punctuation ('. ', ': ', ' — '), and isn't CSS syntax being
    dynamically constructed for injection into a <style> element (which
    always contains a literal '{' -- confirmed against a real example,
    themes.html's custom-theme-style builder: `'body.custom{' + ... + '}'`).
    For template-literal residuals (${...} already stripped) additionally
    require a space: filters DOM-id builders like `st${n}` whose residual
    ('st') is letters but not copy -- every real template-literal message in
    the codebase is a multi-word sentence. A single-word template literal
    with no static neighbors would slip through; plain-quoted strings (the
    normal way to write a static one-word message) are still caught."""
    if "{" in text or "}" in text:
        return False
    if template and " " not in text:
        return False
    return bool(re.search(r"[A-Za-z]{2,}", text))


def _extract_call(line: str, open_paren: int) -> str:
    """Return the argument text of the call whose '(' is at open_paren,
    walking to the balanced ')' while treating quotes of all three JS kinds
    as opaque (a ')' inside a string doesn't close the call). If the call
    doesn't close on this line, return what's there -- the guard is
    line-scoped by design."""
    depth = 0
    quote = None
    i = open_paren
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"', "`"):
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return line[open_paren + 1:i]
        i += 1
    return line[open_paren + 1:]


STRING_RE = re.compile(
    r"`([^`]*)`"            # template literal (interpolations stripped below)
    r"|'([^']{1,150})'"     # single-quoted
    r'|"([^"]{1,150})"'     # double-quoted
)


def _candidate_strings(text: str):
    """Yield (is_template, content) for every string literal in text, in
    order. Template literals have their ${...} interpolations stripped, so
    quoted fragments inside an interpolation (e.g. join(', ')) are consumed
    with the literal instead of surfacing as separate false candidates. A
    template literal that opens here but closes on a later line is scanned
    from its backtick to end-of-line."""
    out = []
    end = 0
    for m in STRING_RE.finditer(text):
        end = m.end()
        if m.group(1) is not None:
            out.append((True, INTERPOLATION_RE.sub("", m.group(1))))
        elif m.group(2) is not None:
            out.append((False, m.group(2)))
        else:
            out.append((False, m.group(3)))
    tick = text.find("`", end)
    if tick != -1:
        out.append((True, INTERPOLATION_RE.sub("", text[tick + 1:])))
    return out


def _first_unwired_message(arg_text: str):
    """The first string literal in arg_text that reads as a real message
    (skipping type tokens and non-copy), or None."""
    for is_template, text in _candidate_strings(arg_text):
        if text in TYPE_TOKENS:
            continue
        if not _looks_translatable(text, template=is_template):
            continue
        return text
    return None


def _find_unwired(html: str, path: str):
    unwired = []
    for lineno, line in enumerate(html.split("\n"), start=1):
        # toast()/confirm()/alert()/setBadge() calls
        for fn in CALL_FNS:
            for m in re.finditer(rf"\b{fn}\(", line):
                call = _extract_call(line, m.end() - 1)
                if I18N_CALL_RE.search(call):
                    continue
                text = _first_unwired_message(call)
                if text is None:
                    continue
                if (path, text) in ALLOWED_UNWIRED:
                    continue
                unwired.append((path, lineno, fn, text))
        # .textContent = / .innerText = assignments: scan the whole
        # right-hand side (up to ';'), so ternaries and concatenations are
        # seen, not just a literal sitting directly after the '='.
        for prop in ASSIGN_PROPS:
            for m in re.finditer(rf"\.{prop}\s*=\s*([^;]+)", line):
                rhs = m.group(1)
                if I18N_CALL_RE.search(rhs):
                    continue
                text = _first_unwired_message(rhs)
                if text is None:
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


def test_guard_has_teeth_on_template_literals():
    """The blind spot the original guard shipped with: a backtick message
    (with interpolations, nested quotes inside them, and a nested call whose
    ')' would have truncated the old first-')'-wins extraction)."""
    html = "toast(`✗ Missing required vars: ${missing.slice(0,3).join(', ')}${missing.length>3?' …':''}`, 'err');"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1
    assert found[0][2] == "toast" and "Missing required vars" in found[0][3]

    html = 'toast(`Theme "${esc(theme.name)}" applied ✓`, \'ok\');'
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1 and "applied" in found[0][3]


def test_guard_has_teeth_on_double_quoted_strings():
    html = 'toast("Cookies removed", \'ok\');'
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1 and found[0][3] == "Cookies removed"


def test_guard_has_teeth_on_template_literal_assignments():
    html = "more.textContent = `· · · ${hidden} more in this batch · · ·`;"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1 and "more in this batch" in found[0][3]


def test_guard_has_teeth_on_ternary_assignments():
    """A literal that isn't directly after '=' (the old regex's other blind
    spot) -- both branches of the ternary are candidates, first one wins."""
    html = "empty.textContent = total > 0 ? `${total} downloads (refresh to load)` : 'No downloads yet';"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1 and "refresh to load" in found[0][3]


def test_guard_ignores_dom_id_template_literals():
    """`st${n}` builds an element id, not copy -- its residual has letters
    but no space, so it must not be flagged (and the real 'error' second arg
    is a type token)."""
    html = "setBadge(document.getElementById(`st${n}`), 'error', e.message);"
    assert _find_unwired(html, "fake.html") == []


def test_guard_ignores_numeric_template_readouts():
    html = "setBadge(stEl, 'dl', `${Math.round(d.progress)}%${spd}`);"
    assert _find_unwired(html, "fake.html") == []


def test_guard_has_teeth_on_setbadge():
    html = "setBadge(stEl, 'error', 'Download interrupted');"
    found = _find_unwired(html, "fake.html")
    assert len(found) == 1
    assert found[0][2] == "setBadge" and found[0][3] == "Download interrupted"


def test_guard_recognizes_wired_setbadge_and_template_fallbacks():
    html = "setBadge(stEl, 'error', d.error || i18nGet('card.status.error') || '✗ Error');"
    assert _find_unwired(html, "fake.html") == []
    html = "toast(i18nFmt('toast.theme.applied', theme.name) || `Theme \"${theme.name}\" applied ✓`, 'ok');"
    assert _find_unwired(html, "fake.html") == []


def test_scope_covers_the_whole_template_tree():
    """The glob-derived scope must include every known window and JS partial.
    If this fails after moving/renaming templates, update KNOWN_FILES -- but
    make sure the new locations are still matched by _template_files()."""
    missing = [f for f in KNOWN_FILES if f not in FILES]
    assert not missing, f"template-tree glob no longer finds: {missing}"
    assert len(FILES) >= len(KNOWN_FILES)
