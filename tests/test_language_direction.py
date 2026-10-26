"""The page direction comes from I18N_RTL in templates/i18n.html; each language file's _direction must agree.

i18nLoad sets dir="rtl" for a code in I18N_RTL and dir="ltr" for every other code. It never reads the
direction from a language file: the files are data, and the allowlisted code alone decides the layout.
The files still carry the field for translators and tools, so this test keeps the two from drifting:
a new right to left language needs its code in I18N_RTL and "rtl" in its file, or this fails.
"""
import glob
import json
import os
import re

from conftest import ROOT, read_source

I18N = read_source("templates/i18n.html")


def _js_list(name):
    m = re.search(rf"const {name} = \[([^\]]*)\];", I18N)
    assert m, f"{name} not found in templates/i18n.html"
    return re.findall(r"'([a-z]{2})'", m.group(1))


RTL = _js_list("I18N_RTL")
SUPPORTED = _js_list("I18N_SUPPORTED")


def test_every_language_file_declares_the_direction_the_code_applies():
    files = sorted(glob.glob(os.path.join(ROOT, "languages", "*.json")))
    assert len(files) == len(SUPPORTED) == 10
    wrong = {}
    for f in files:
        code = os.path.basename(f)[:-5]
        with open(f, encoding="utf-8") as fh:
            declared = json.load(fh).get("_direction")
        expected = "rtl" if code in RTL else "ltr"
        if declared != expected:
            wrong[code] = (declared, expected)
    assert not wrong, f"_direction in the file vs what I18N_RTL applies (file, code): {wrong}"


def test_right_to_left_codes_are_allowlisted_codes():
    assert RTL, "I18N_RTL is empty: Arabic would be laid out left to right"
    assert set(RTL) <= set(SUPPORTED), f"I18N_RTL has codes outside I18N_SUPPORTED: {sorted(set(RTL) - set(SUPPORTED))}"


def test_i18n_load_takes_the_direction_from_the_code_only():
    load = I18N[I18N.index("async function i18nLoad"):I18N.index("function i18nBoot")]
    assert "setAttribute('dir', I18N_RTL.includes(code) ? 'rtl' : 'ltr')" in load
    for path in glob.glob(os.path.join(ROOT, "templates", "**", "*.html"), recursive=True):
        assert not re.search(r"\b_direction\b", open(path, encoding="utf-8").read()), f"{path} reads the direction from a language file"


def test_direction_change_runs_with_transitions_off():
    """A direction change is not an animation.

    The closed Theme Creator panel sits at translateX(100%) in left to right and translateX(-100%) in
    right to left, and its anchor moves to the other side at the same moment, so with its .22s transition
    on it sweeps across the whole window on every switch and at start up with Arabic saved. i18nLoad
    adds html.dir-switching, sets the direction, forces a style flush and removes the class again;
    index_styles.html turns transitions off while the class is on. Verified in Chromium: 340 px of the
    panel visible mid switch before, 0 after (tests have no real browser, so this guards the wiring).
    """
    load = I18N[I18N.index("async function i18nLoad"):I18N.index("function i18nBoot")]
    cls = re.search(r"classList\.add\('([\w-]+)'\)", load)
    assert cls, "i18nLoad does not add a class around the direction change"
    cls = cls.group(1)
    steps = [f"classList.add('{cls}')", "setAttribute('dir'", "offsetWidth", f"classList.remove('{cls}')"]
    at = [load.index(s) for s in steps]
    assert at == sorted(at), f"i18nLoad must add the class, set dir, flush style, then remove the class: {steps}"
    css = read_source("templates/index_styles.html")
    assert re.search(rf"html\.{cls} \*\s*,[^{{]*\{{\s*transition:\s*none\s*!important", css), \
        f"index_styles.html has no rule that turns transitions off under html.{cls}"
