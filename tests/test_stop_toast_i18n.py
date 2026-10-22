"""Regression guard for the toast shown when the user cancels a playlist fetch
("Stopped - keeping N loaded videos").

The old code glued a translated fragment (toast.stopped_keeping) to a
hardcoded English " loaded video(s)" with an English plural rule, so every
locale except English showed a half English toast, and the fragment assumed
English word order. The fix uses two full sentence keys with a {0} count
placeholder, picked by count, like toast.quality.capped_one / capped_many.

test_js_i18n_coverage.py did not catch the original because any inline
i18nGet() counts as wired there; this pins the specific shape instead."""
from conftest import read_source

DOWNLOAD_FILES = ("templates/js/_download.html", "linux/templates/js/_download.html")
KEYS = ("toast.stopped_keeping_one", "toast.stopped_keeping_many")


def test_stop_toast_uses_full_sentence_keys_not_a_glued_fragment():
    for p in DOWNLOAD_FILES:
        src = read_source(p)
        for key in KEYS:
            assert f"i18nFmt('{key}'" in src, f"{p}: the stop toast must use i18nFmt('{key}', ...)"
        assert "i18nGet('toast.stopped_keeping')" not in src, (
            f"{p}: the translated fragment toast.stopped_keeping is glued to "
            "hardcoded English again; use the _one/_many sentence keys"
        )
