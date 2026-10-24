"""Every language file has exactly English's keys, the same placeholders, and a real translation.

The app falls back to English for a missing key, so a key added to en.json alone would ship as an
English string in nine languages with nothing failing. Together with test_i18n_keys_exist_in_en_locale
(test_parity.py: every key a template uses exists in en.json) these tests make "the app uses a key"
mean "all ten files carry it, translated".

A value identical to English fails unless it is on the allowlist below. Most identical values are
right as they are (brand and tool names, Audio, Video, LIVE, Intro). Adding a key to the allowlist
is a deliberate decision, made with the translator, not a way to silence the test. An entry that
stops being identical, or whose key is gone, fails too, so the list cannot rot.
"""
import glob
import json
import os
import re
from collections import Counter

from conftest import ROOT

PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _locales():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "languages", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            out[os.path.basename(f)[:-5]] = json.load(fh)["strings"]
    assert len(out) == 10 and "en" in out, f"expected ten language files with en.json, found {sorted(out)}"
    return out


LOCALES = _locales()
EN = LOCALES["en"]
OTHERS = {code: strings for code, strings in LOCALES.items() if code != "en"}

# Identical to English in every language, including Arabic, Japanese and Russian.
COMMON = {
    "advanced.channel.nightly",
    "app.subtitle.more_sites",
    "app.title",
    "card.format.video.h264",
    "console.toggle.ffmpeg.label",
    "console.toggle.flask.label",
    "console.toggle.ytdlp.label",
    "cookies.browser.chrome",
    "cookies.browser.firefox",
    "fetch.error.prefix",
    "footer.link.github",
    "footer.link.website",
    "history.filter.flac",
    "plugins.deno.label",
    "plugins.ffmpeg.label",
    "plugins.ytdlp.label",
    "settings.toggle.sponsorblock",
}

# Identical to English in this language only (a cognate or a term the language keeps).
EXTRA = {
    "de": {
        "advanced.section.plugins",
        "advanced.section.system",
        "card.badge.live",
        "card.format.audio",
        "card.format.video",
        "card.label.format",
        "creator.live_badge",
        "creator.picker.text",
        "creator.title",
        "help.shortcut.creator",
        "help.shortcut.themes",
        "history.col.format",
        "history.filter.audio",
        "history.filter.video",
        "panel.tab.themes",
        "quality.section.standard",
        "settings.toggle.sponsorblock_intro",
        "settings.toggle.sponsorblock_outro",
        "settings.toggle.sponsorblock_sponsor",
        "subscriptions.label.format",
        "themes.window.title",
    },
    "es": {
        "advanced.section.general",
        "advanced.section.plugins",
        "card.format.audio",
        "card.format.video",
        "card.status.error",
        "history.filter.audio",
        "history.filter.video",
        "settings.toggle.sponsorblock_intro",
        "settings.toggle.sponsorblock_outro",
        "subscriptions.detail.videos_count",
        "toast.plugins.error_prefix",
    },
    "fr": {
        "advanced.channel.stable",
        "advanced.section.interface",
        "advanced.section.plugins",
        "app.tagline.sites",
        "card.format.audio",
        "card.label.format",
        "console.title",
        "creator.picker.acc",
        "creator.picker.red",
        "creator.picker.surf",
        "creator.picker.surf2",
        "footer.btn.diagnostics",
        "history.col.actions",
        "history.col.date",
        "history.col.format",
        "history.filter.audio",
        "quality.section.standard",
        "settings.toggle.sponsorblock_intro",
        "settings.toggle.sponsorblock_outro",
        "settings.toggle.sponsorblock_sponsor",
        "subscriptions.label.format",
        "url.label.fragments",
    },
    "it": {
        "card.badge.live",
        "card.format.audio",
        "card.format.video",
        "creator.live_badge",
        "history.filter.audio",
        "history.filter.video",
        "quality.section.standard",
        "settings.toggle.sponsorblock_intro",
        "settings.toggle.sponsorblock_outro",
        "settings.toggle.sponsorblock_sponsor",
    },
    "nl": {
        "advanced.section.interface",
        "advanced.section.plugins",
        "app.tagline.sites",
        "card.badge.live",
        "card.format.audio",
        "card.format.video",
        "creator.live_badge",
        "creator.picker.acc",
        "creator.picker.acc_h",
        "footer.btn.help",
        "help.section.tips",
        "help.title",
        "history.filter.audio",
        "history.filter.video",
        "panel.history.downloads",
        "panel.section.recent",
        "plugins.badge.updates_many",
        "plugins.badge.updates_one",
        "settings.toggle.sponsorblock_intro",
        "settings.toggle.sponsorblock_outro",
        "settings.toggle.sponsorblock_sponsor",
        "status.bar.count",
        "update.available.btn.later",
    },
    "pt": {
        "advanced.section.interface",
        "advanced.section.plugins",
        "app.tagline.sites",
        "panel.history.downloads",
        "settings.toggle.sponsorblock_intro",
        "settings.toggle.sponsorblock_outro",
        "status.bar.count",
    },
}


def test_every_language_file_has_exactly_the_english_keys():
    problems = []
    for code, strings in OTHERS.items():
        missing, extra = sorted(set(EN) - set(strings)), sorted(set(strings) - set(EN))
        if missing:
            problems.append(f"{code}: missing {missing}")
        if extra:
            problems.append(f"{code}: not in en.json {extra}")
    assert not problems, "language files differ from en.json: " + "; ".join(problems)


def test_every_value_is_a_non_empty_string_with_the_english_placeholders():
    problems = []
    for code, strings in LOCALES.items():
        for key in EN:
            value = strings.get(key)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"{code}: {key} is empty or not a string")
            elif Counter(PLACEHOLDER.findall(value)) != Counter(PLACEHOLDER.findall(EN[key])):
                problems.append(f"{code}: {key} has placeholders {PLACEHOLDER.findall(value)}, "
                                f"English has {PLACEHOLDER.findall(EN[key])}")
    assert not problems, "\n".join(problems)


def _identical(code):
    return {key for key in EN if OTHERS[code].get(key) == EN[key]}


def test_no_value_is_an_english_copy_unless_it_is_on_the_allowlist():
    problems = []
    for code in OTHERS:
        copies = sorted(_identical(code) - COMMON - EXTRA.get(code, set()))
        if copies:
            problems.append(f"{code}: {copies}")
    assert not problems, (
        "identical to English and not on the allowlist (translate it; if English is right in that "
        "language, add it to EXTRA with the translator's okay): " + "; ".join(problems))


def test_the_allowlist_has_no_stale_entries():
    assert set(EXTRA) <= set(OTHERS), f"EXTRA names a language that has no file: {sorted(set(EXTRA) - set(OTHERS))}"
    problems = []
    for code, keys in EXTRA.items():
        stale = sorted(keys - _identical(code))
        if stale:
            problems.append(f"{code}: {stale}")
    gone = sorted(COMMON - set(EN))
    translated_everywhere = sorted(key for key in COMMON if not any(key in _identical(code) for code in OTHERS))
    assert not problems and not gone and not translated_everywhere, (
        f"remove from the allowlist: EXTRA {problems}; COMMON keys not in en.json {gone}; "
        f"COMMON keys translated in every language {translated_everywhere}")



# Keys that replaced English text written straight into a template, with how many places read each.
# Without the template reading the key, ten files carry a translation that never shows (the other
# direction is covered by test_i18n_keys_exist_in_en_locale).
READ_IN_TEMPLATES = {"card.status.eta": 2, "subscriptions.title_short": 1, "subscriptions.detail.videos_total": 1}


def test_the_keys_that_replaced_hardcoded_english_are_read_by_the_templates():
    templates = ""
    for dirpath, _, files in os.walk(os.path.join(ROOT, "templates")):
        for name in files:
            if name.endswith(".html"):
                with open(os.path.join(dirpath, name), encoding="utf-8") as fh:
                    templates += fh.read()
    short = {key: templates.count(f"'{key}'") + templates.count(f'"{key}"') for key in READ_IN_TEMPLATES}
    short = {key: n for key, n in short.items() if n < READ_IN_TEMPLATES[key]}
    assert not short, f"read in fewer templates places than expected, so some text shows in English: {short}"
