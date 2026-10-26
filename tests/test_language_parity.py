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
        "themes.cat.memes",
        "themes.cat.modern",
        "themes.cat.puerto_rico",
        "themes.cat.retro",
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
        "themes.cat.experimental",
        "themes.cat.memes",
        "themes.cat.puerto_rico",
        "themes.cat.retro",
        "themes.cat.sneakers",
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
        "themes.cat.architecture",
        "themes.cat.nature",
        "themes.section.style",
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
        "themes.cat.sneakers",
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
        "themes.cat.memes",
        "themes.cat.modern",
        "themes.cat.puerto_rico",
        "themes.cat.retro",
        "themes.cat.sneakers",
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
        "themes.cat.experimental",
        "themes.cat.memes",
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
READ_IN_TEMPLATES = {"card.status.eta": 2, "subscriptions.title_short": 1, "subscriptions.detail.videos_total": 1,
                     "url.btn.download_all_videos": 1, "url.btn.download_all_audio": 1, "bulk.btn.cancel_all": 1,
                     "themes.filter.all": 1, "url.btn.paste_fetch": 2,
                     "subscriptions.detail.fetching": 1, "subscriptions.label.unknown": 2, "toast.plugins.error_prefix": 3,
                     "whatsnew.loading": 1,
                     "bulk.progress.videos": 1, "bulk.progress.audio": 1, "bulk.progress.mixed": 1,
                     "toast.bulk.done_videos": 1, "toast.bulk.done_audio": 1, "toast.bulk.done_mixed": 1,
                     "themes.section.style": 1, "themes.section.vibe": 1, "themes.section.pop_culture": 1,
                     "themes.section.heritage": 1, "themes.section.other": 1,
                     "themes.filter.imported": 1, "themes.filter.seasonal": 1}


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


def test_every_themes_category_is_named_by_the_language_file():
    """The Themes sidebar builds a category's key as themes.cat.<id>, so no template text carries the key
    for the reading test above to count. This reads the category ids from the page instead: each one
    (Seasonal and Imported use the filter chips' keys) has its name in the language file, and each sidebar
    section is read by its own key."""
    with open(os.path.join(ROOT, "templates", "themes.html"), encoding="utf-8") as fh:
        page = fh.read()
    labels = re.search(r"const CAT_LABELS = \{(.*?)\n\};", page, re.S).group(1)
    ids = set(re.findall(r"\b(\w+):\s*'", labels)) - {"seasonal", "custom"}
    sections = re.findall(r"key: '([^']+)'", re.search(r"const SECTIONS = \[(.*?)\n\];", page, re.S).group(1))
    assert len(ids) == 30 and len(sections) == 5, f"expected 30 categories and 5 sections, found {len(ids)} and {len(sections)}"
    missing = sorted({f"themes.cat.{i}" for i in ids} - set(EN)) + sorted(set(sections) - set(EN))
    assert not missing, f"the Themes sidebar names these in a language file, but en.json lacks them: {missing}"
    assert "'themes.cat.' + id" in page, "the sidebar no longer reads themes.cat.<id>, so the 30 translations never show"
    unused = sorted(k for k in EN if k.startswith("themes.cat.") and k[len("themes.cat."):] not in ids)
    assert not unused, f"language keys for categories the page does not have: {unused}"


def test_the_themes_sidebar_breaks_a_long_name_and_keeps_its_count_whole():
    """The sidebar is 135px wide. Measured in Chromium, the Russian Experimental and Imported and the Dutch
    Operating Systems names are one long word each: without these two rules the word pushes the count out of
    the sidebar (or the sidebar scrolls sideways), with them the word breaks and the number stays at the edge."""
    for folder in ("templates", "linux/templates"):
        with open(os.path.join(ROOT, folder, "themes.html"), encoding="utf-8") as fh:
            page = fh.read()
        tab = re.search(r"\.cat-tab \{(.*?)\}", page, re.S).group(1)
        count = re.search(r"\.cat-count \{(.*?)\}", page, re.S).group(1)
        assert "overflow-wrap:anywhere" in tab, f"{folder}/themes.html: .cat-tab no longer breaks a name longer than the sidebar"
        assert "flex-shrink:0" in count and "white-space:nowrap" in count, f"{folder}/themes.html: .cat-count can shrink and wrap again"


def test_no_translation_contains_markup():
    """A translated string is text. Some of them are placed into HTML by the page (the card ETA, the
    queue lines, the videos total), so a '<' or '>' inside one would become markup that runs in the page
    that holds the API token. No value has either character today. A translator who needs a comparison
    sign writes the word instead."""
    markup = {f"{code}.json: {key}": value for code, strings in LOCALES.items()
              for key, value in strings.items() if "<" in value or ">" in value}
    assert not markup, f"these translations contain < or >: {markup}"
