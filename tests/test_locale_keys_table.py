"""Proposal B: one table-driven check replaces the seven per-feature locale-key tests.

Each row: key, how many times "{0}" must appear (None = don't care), extra placeholder
tokens that must be present, and whether the value must differ from English. All of
the seven tests' assertions are expressible in this table EXCEPT the Konami test
(brand-name rule, ja transliteration), which stays where it is.
"""
import glob
import json
import os

import pytest

from conftest import ROOT

# (key, count_of_{0} or None, other required tokens, must differ from en)
TABLE = [
    # test_live_recording.py::test_new_strings_exist_in_every_locale
    ("card.badge.live",                   None, (), False),
    ("card.status.recording",             None, (), False),
    ("card.btn.stop_save",                None, (), False),
    ("download.warning.live_partial",     None, (), False),
    # test_live_reconnect.py::test_the_reconnect_and_gap_strings_exist_in_every_locale
    ("card.status.reconnecting",          None, ("{0}", "{1}"), False),
    ("download.warning.live_gap",         None, (), False),
    ("download.warning.live_parts",       None, (), False),
    # test_stop_toast_i18n.py::test_stop_toast_keys_exist_with_one_count_placeholder_in_every_locale
    ("toast.stopped_keeping_one",         1, (), False),
    ("toast.stopped_keeping_many",        1, (), False),
    # test_subs_quit_when_done.py::test_countdown_string_exists_with_one_count_placeholder_in_every_locale
    ("subscriptions.queue.quitting_in",   1, (), False),
    # test_whats_new_button.py::test_footer_whatsnew_key_present_in_every_locale
    ("footer.btn.whatsnew",               None, (), False),
    # test_ffmpeg_raw_log.py::test_ffmpeg_toggle_i18n_key_translated_across_all_locales
    ("console.toggle.ffmpeg",             None, (), True),
    # test_flask_raw_log.py::test_flask_toggle_i18n_key_translated_across_all_locales
    # (despite its name it never compared against English; True here is a strengthening)
    ("console.toggle.flask",              None, (), True),
]


def _locales():
    files = sorted(glob.glob(os.path.join(ROOT, "languages", "*.json")))
    assert len(files) >= 10, f"expected at least 10 locale files, found {len(files)}"
    out = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            out[os.path.basename(f)[:-5]] = json.load(fh)["strings"]
    return out


LOCALES = _locales()


@pytest.mark.parametrize("key, zero_count, tokens, must_differ", TABLE, ids=[r[0] for r in TABLE])
def test_locale_key(key, zero_count, tokens, must_differ):
    en = LOCALES["en"]
    assert isinstance(en.get(key), str) and en[key].strip(), f"en: missing {key}"
    for loc, strings in LOCALES.items():
        value = strings.get(key)
        assert isinstance(value, str) and value.strip(), f"{loc}: missing {key}"
        if zero_count is not None:
            assert value.count("{0}") == zero_count, f"{loc}: {key} needs {{0}} x{zero_count}, got {value!r}"
        for tok in tokens:
            assert tok in value, f"{loc}: {key} lacks {tok}: {value!r}"
        if must_differ and loc != "en":
            assert value != en[key], f"{loc}: {key} still reads as the English placeholder"
