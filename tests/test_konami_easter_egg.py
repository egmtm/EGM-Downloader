"""Konami-code easter egg (templates/js/_core.html): the fake-crash overlay's
UI-facing text must go through i18n, matching every other user-facing string
in the app.

Deliberately NOT translated, by design:
  - "Konami" -- a proper noun.
  - The 3 fake "backend:"/"at ..." log lines -- styled to read as genuine
    raw process/log output, same convention already established for
    Diagnostics' raw yt-dlp/Flask/ffmpeg output, which is never translated
    either.
  - The "↑ ↑ ↓ ↓ ← → ← → B A" glyph sequence -- universal symbols.

Everything else (the crash headline, "collecting crash report…", "Gotcha!",
the found-it message, and the close hint) is real UI copy and must be wired.
"""
import re

from conftest import read_source

CORE_JS_FILES = ["templates/js/_core.html", "linux/templates/js/_core.html"]

KONAMI_KEYS = {
    "konami.title": "EGM Downloader has stopped responding",
    "konami.collecting": "collecting crash report…",
    "konami.gotcha": "Gotcha!",
    "konami.found": "You found the Konami code — nothing crashed, everything is fine.",
    "konami.close_hint": "click anywhere to close",
}


def _konami_block(src):
    i = src.index("Easter egg: Konami code fake-crash")
    j = src.index("\n})();", i) + len("\n})();")
    return src[i:j]


def test_every_konami_ui_string_is_wired_through_i18n_on_both_platforms():
    for p in CORE_JS_FILES:
        block = _konami_block(read_source(p))
        for key, fallback in KONAMI_KEYS.items():
            pattern = re.escape(f"i18nGet('{key}')") + r"\s*\|\|\s*'" + re.escape(fallback) + r"'"
            assert re.search(pattern, block), (
                f"{p}: konami.* string for {key!r} must be wired as "
                f"i18nGet('{key}') || '{fallback}', matching the "
                f"established fallback pattern used everywhere else in "
                f"the codebase for dynamically-generated JS content"
            )


def test_konami_translated_strings_are_escaped_before_reaching_innerhtml():
    """The overlay is built via innerHTML (not textContent) for layout
    convenience, so every translated value must be passed through esc()
    first -- the same discipline i18n.html's own header comment requires
    ("values land via textContent ... or setAttribute ... never innerHTML"
    unescaped). A translator (or a tampered locale file) shouldn't be able
    to inject markup into this overlay."""
    for p in CORE_JS_FILES:
        block = _konami_block(read_source(p))
        for key in KONAMI_KEYS:
            assert re.search(re.escape(f"esc(i18nGet('{key}')"), block), (
                f"{p}: the value for {key!r} must be wrapped in esc(...) "
                f"before being interpolated into the overlay's innerHTML"
            )


def test_fake_log_lines_and_konami_itself_stay_untranslated():
    """Regression guard against someone 'helpfully' wiring the fake
    backend/stack-trace lines through i18n too -- they're deliberately
    raw/untranslated, matching the Diagnostics raw-output convention.
    'Konami' must never appear as part of a translated key's fallback
    text getting swapped for something localized either."""
    for p in CORE_JS_FILES:
        block = _konami_block(read_source(p))
        assert "'<div>backend: exit code -11 (SIGSEGV)</div>'" in block
        assert "'<div>at yt_dlp.core.extract (frame 0x7f3a19c4)</div>'" in block
        assert "'<div>at egm.download_worker (job_id: KONAMI-1986)</div>'" in block
        assert "↑ ↑ ↓ ↓ ← → ← → B A" in block
        # None of the 3 raw lines should be routed through i18nGet.
        for raw_fragment in ("SIGSEGV", "yt_dlp.core.extract", "KONAMI-1986"):
            line_start = block.index(raw_fragment)
            line = block[max(0, line_start - 80):line_start + 20]
            assert "i18nGet" not in line, (
                f"{p}: the raw log line containing {raw_fragment!r} must "
                f"stay hardcoded, not routed through i18n"
            )


def test_core_js_mirrors_are_byte_identical():
    root = read_source("templates/js/_core.html")
    linux = read_source("linux/templates/js/_core.html")
    assert root == linux, "templates/js/_core.html and its Linux mirror have diverged"


def test_konami_i18n_keys_present_and_genuinely_translated_across_locales():
    import json
    import os

    lang_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "languages")
    en = json.load(open(os.path.join(lang_dir, "en.json"), encoding="utf-8"))["strings"]
    for key, expected_en in KONAMI_KEYS.items():
        assert en.get(key) == expected_en, f"en.json: {key} missing or drifted"

    locales = ["ar", "de", "es", "fr", "it", "ja", "nl", "pt", "ru"]
    for loc in locales:
        d = json.load(open(os.path.join(lang_dir, f"{loc}.json"), encoding="utf-8"))["strings"]
        for key in KONAMI_KEYS:
            assert key in d, f"{loc}: missing {key}"
            # "Konami" is a proper noun and should generally survive
            # untranslated, matching the theme-name/tool-name convention --
            # except Japanese, where transliterating a Latin-script brand
            # name into katakana (コナミ, the same rendering the real
            # company uses) is the standard, correct localization practice,
            # not a translation error. Every other locale here uses a
            # Latin-adjacent or Cyrillic/Arabic script where the brand name
            # is conventionally left in Latin script instead.
            if key == "konami.found":
                if loc == "ja":
                    assert "コナミ" in d[key], (
                        f"ja: expected 'Konami' transliterated to コナミ "
                        f"inside konami.found, got {d[key]!r}"
                    )
                else:
                    assert "Konami" in d[key], (
                        f"{loc}: 'Konami' must appear verbatim (proper "
                        f"noun) inside konami.found, got {d[key]!r}"
                    )


# ── Hardening added in the delta review of ffca4f8..80027a8 ──────────────────

def test_no_unescaped_interpolation_reaches_the_overlay_innerhtml():
    """Generalizes test_konami_translated_strings_are_escaped_before_reaching_
    innerhtml from a whitelist into an invariant.

    That test asserts the five *known* keys are wrapped in esc(). It cannot
    see a SIXTH interpolation added later without esc() -- verified by
    mutation: adding `${i18nGet('konami.subtitle') || 'extra'}` to the
    overlay markup leaves it green. Since the overlay is assembled with
    innerHTML, the property worth pinning is "nothing unescaped is
    interpolated here", not "these five are escaped".

    An interpolation passes if it either calls esc() inline, or is a bare
    identifier that was assigned from an esc(...) expression inside the same
    block.
    """
    for p in CORE_JS_FILES:
        block = _konami_block(read_source(p))

        # Identifiers assigned from esc(...) in this block are pre-escaped.
        pre_escaped = set(
            re.findall(r"const\s+(\w+)\s*=\s*esc\(", block)
        )

        for expr in re.findall(r"\$\{([^{}]*)\}", block):
            expr = expr.strip()
            if "esc(" in expr:
                continue
            if re.fullmatch(r"\w+", expr) and expr in pre_escaped:
                continue
            raise AssertionError(
                f"{p}: unescaped interpolation `${{{expr}}}` reaches the "
                f"Konami overlay's innerHTML. Wrap it in esc(), or assign it "
                f"from esc(...) first -- every other value in this block does."
            )

        # Sanity: the scan must actually be finding interpolations, or the
        # invariant above passes vacuously.
        assert len(re.findall(r"\$\{[^{}]*\}", block)) >= 5, (
            f"{p}: expected at least 5 interpolations in the Konami block; "
            f"the block extraction or the markup shape changed"
        )


def test_locale_files_have_no_duplicate_json_keys():
    """json.load() silently keeps the LAST of any duplicated key, so a
    locale file can carry two entries for the same key and every existing
    check -- including the key-count parity tests -- still passes while one
    value is silently discarded.

    This is not hypothetical: commit 5005b06 ("dedupe konami.* placeholder
    keys") exists because it happened during this very release. Nothing
    prevented a recurrence, so this guard does.
    """
    import collections
    import glob
    import json
    import os

    lang_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "languages")
    offenders = {}
    for path in sorted(glob.glob(os.path.join(lang_dir, "*.json"))):
        seen = []

        def _hook(pairs, _seen=seen):
            counts = collections.Counter(k for k, _ in pairs)
            _seen.extend(k for k, n in counts.items() if n > 1)
            return dict(pairs)

        with open(path, encoding="utf-8") as fh:
            json.load(fh, object_pairs_hook=_hook)
        if seen:
            offenders[os.path.basename(path)] = sorted(set(seen))

    assert not offenders, (
        f"duplicate JSON keys found (json.load keeps only the last value, so "
        f"one translation is silently dropped and key-count parity still "
        f"passes): {offenders}"
    )
