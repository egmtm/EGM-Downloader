"""windows/setup.nsi: the installer's texts.

* Every LangString key has exactly one text in each of the ten installer languages, every key the
  script shows is defined, and every defined key is shown.
* Escapes: inside a LangString a quote is $\\", a line break is $\\r$\\n, and $ starts nothing but
  those, ${VERSION}, ${APPNAME}, $INSTDIR or $$ (a stray $ would swallow the next word at run time).
* The texts added for the folder check, the processor check, the running app in the uninstaller and
  the two uninstaller questions are in all ten languages, translated (no text is an English copy),
  with the same tokens, line breaks and arrows as the English; the two questions keep the English
  text they had when they were English only.
* Every message box and every Abort status text shows a LangString, with no exception."""
import re

from nsis_model import NSI, statements

LANGS = re.findall(r'^!insertmacro MUI_LANGUAGE "(\w+)"$', NSI, re.M)
LINES = re.findall(r'^LangString (\w+) \$\{LANG_(\w+)\} "(.*)"$', NSI, re.M)
NEW_KEYS = ["EGM_APP_STILL_RUNNING", "EGM_INSTALL_CANCELLED", "EGM_APP_RUNNING_ANY_COPY", "EGM_UN_APP_RUNNING_ANY_COPY", "EGM_UN_APP_RUNNING", "EGM_UN_APP_STILL_RUNNING", "EGM_FOLDER_NOT_OURS", "EGM_ARCH_UNSUPPORTED",
            "EGM_UN_REMOVE_COMPONENTS", "EGM_UN_REMOVE_DATA"]


def _texts(key):
    return {lang: text for k, lang, text in LINES if k == key}


def test_every_key_has_one_text_in_every_language():
    assert len(LANGS) == 10
    langs = {l.upper() for l in LANGS}
    assert sum(1 for l in NSI.splitlines() if l.startswith("LangString ")) == len(LINES), "a LangString line the test cannot read"
    keys = sorted({k for k, _, _ in LINES})
    assert set(NEW_KEYS) <= set(keys) and len(keys) >= 9 + len(NEW_KEYS), keys
    for key in keys:
        per_lang = [lang for k, lang, _ in LINES if k == key]
        assert sorted(per_lang) == sorted(langs), (key, sorted(set(langs) ^ set(per_lang)))


def test_every_shown_key_is_defined_and_every_defined_key_is_shown():
    defined = {k for k, _, _ in LINES}
    code = "\n".join(l for l in NSI.splitlines() if not l.startswith("LangString "))
    used = set(re.findall(r"\$\((EGM_\w+)\)", code))
    assert used == defined, (sorted(used - defined), sorted(defined - used))


def test_every_text_is_escaped():
    for key, lang, text in LINES:
        rest = re.sub(r'\$\\r\$\\n|\$\\"|\$\{(VERSION|APPNAME)\}|\$INSTDIR\b|\$\$', "", text)
        assert "$" not in rest, (key, lang, text[:60])
        assert '"' not in rest, (key, lang, "an unescaped quote")
        assert "\\" not in re.sub(r'\$\\[rn"]', "", text), (key, lang, "a backslash that is not part of $\\r, $\\n or $\\\"")
        assert "$\\n" not in text.replace("$\\r$\\n", ""), (key, lang, "a line break without $\\r")


def test_the_uninstaller_questions_are_language_strings_with_their_text():
    assert _texts("EGM_UN_REMOVE_COMPONENTS")["ENGLISH"] == (
        "Also remove the downloaded components (ffmpeg and Deno)?$\\r$\\n$\\r$\\n"
        "The app downloads them again on its first launch after a new install.$\\r$\\n"
        "Choose No to keep them for a faster reinstall.")
    assert _texts("EGM_UN_REMOVE_DATA")["ENGLISH"] == (
        "Also remove your data (settings, download history, cookies, logs)?$\\r$\\n$\\r$\\n"
        "Choose No to keep them for a faster setup on next install.")


def test_every_message_box_and_every_abort_text_is_a_language_string():
    """No exception: what a person reads in a box or in the status line of an aborted install comes
    in the language they chose. A plain Abort (no text) shows none."""
    shown = []
    for s in statements(NSI):
        if s.startswith("MessageBox "):
            shown.append(re.search(r'"([^"]*)"', s).group(1))
        elif s.startswith("Abort ") or s.startswith("DetailPrint ") or s.startswith("SetDetailsPrint "):
            m = re.search(r'"([^"]*)"', s)
            if m:
                shown.append(m.group(1))
    assert len(shown) >= 10
    plain = [text for text in shown if not re.fullmatch(r"\$\((EGM_\w+)\)", text)]
    assert plain == [], plain


def test_the_two_texts_moved_into_language_strings_keep_their_english():
    assert _texts("EGM_APP_STILL_RUNNING")["ENGLISH"] == (
        "${APPNAME} is still running and could not be closed.$\\r$\\nNothing was changed. "
        "Quit it from the tray icon (or end it in Task Manager), then run the installer again.")
    assert _texts("EGM_INSTALL_CANCELLED")["ENGLISH"] == (
        "Installation cancelled — please close ${APPNAME} and run the installer again.")
    sec = NSI[NSI.index('Section "Install"'):]
    assert sec.count('Abort "$(EGM_INSTALL_CANCELLED)"') >= 2


def test_the_english_finish_text_names_ffmpeg_and_deno_like_the_welcome_page():
    texts = _texts("EGM_FINISH_TEXT")
    english = texts.pop("ENGLISH")
    assert "ffmpeg and Deno" in english and "required components" not in english
    assert "ffmpeg" in _texts("EGM_WELCOME_TEXT")["ENGLISH"] and "Deno" in _texts("EGM_WELCOME_TEXT")["ENGLISH"]
    assert not re.search(r"\d", english.replace("${VERSION}", "")), "no size and no other version"
    assert len(texts) == 9
    for lang, text in texts.items():
        assert "ffmpeg" in text and "Deno" in text, (lang, "the old texts said 'required components'")
        assert not re.search(r"\d", text.replace("${VERSION}", "")), lang


def test_the_english_finish_text_promises_no_single_download():
    """The downloads are tried again at every launch until ffmpeg and Deno are there, so the text
    no longer says it happens once (EGM's wording)."""
    assert _texts("EGM_FINISH_TEXT")["ENGLISH"] == (
        "EGM Downloader v${VERSION} has been installed.$\\r$\\n"
        "On first launch, ffmpeg and Deno are downloaded in the background.")


def test_no_installer_text_is_an_english_copy():
    for key in sorted({k for k, _, _ in LINES}):
        texts = _texts(key)
        english = texts.pop("ENGLISH")
        copies = sorted(lang for lang, text in texts.items() if text == english)
        assert copies == [], (key, copies)


def test_every_language_keeps_the_tokens_line_breaks_and_arrows_of_the_english():
    for key in sorted({k for k, _, _ in LINES}):
        texts = _texts(key)
        english = texts.pop("ENGLISH")
        want = (sorted(re.findall(r"\$\{VERSION\}|\$\{APPNAME\}|\$INSTDIR\b", english)),
                english.count("$\\r$\\n"), english.count("\u2192"))
        for lang, text in texts.items():
            arrows = text.count("\u2190" if lang == "ARABIC" else "\u2192")
            got = (sorted(re.findall(r"\$\{VERSION\}|\$\{APPNAME\}|\$INSTDIR\b", text)), text.count("$\\r$\\n"), arrows)
            assert got == want, (key, lang, got, want)


def test_arabic_cancel_installation_is_not_worded_like_uninstall():
    """In Arabic the words for 'cancel the installation' read as 'uninstall'. The only line that
    may use them is the one whose No button does uninstall."""
    uninstall = "\u0625\u0644\u063a\u0627\u0621 \u0627\u0644\u062a\u062b\u0628\u064a\u062a"
    users = sorted(k for k, lang, text in LINES if lang == "ARABIC" and uninstall in text)
    assert users == ["EGM_ALREADY_INSTALLED"], users


def test_the_portuguese_welcome_text_names_the_button_the_installer_shows():
    """The toolkit's own Brazilian Portuguese file labels the button Pr\u00f3ximo; the text must say the same word."""
    last = _texts("EGM_WELCOME_TEXT")["PORTUGUESEBR"].split("$\\r$\\n")[-1]
    assert "Pr\u00f3ximo" in last and "Avan\u00e7ar" not in last, last

