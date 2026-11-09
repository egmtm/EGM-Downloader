"""windows/setup.nsi: the installer's texts.

* Every LangString key has exactly one text in each of the ten installer languages, every key the
  script shows is defined, and every defined key is shown.
* Escapes: inside a LangString a quote is $\\", a line break is $\\r$\\n, and $ starts nothing but
  those, ${VERSION}, $INSTDIR or $$ (a stray $ would swallow the next word at run time).
* The texts added for the folder check, the processor check, the running app in the uninstaller and
  the two uninstaller questions are in all ten languages (English placeholders until the translator
  pass); the two questions keep the English text they had when they were English only.
* Every message box shows a LangString, except the one English only box the installer already had
  ("still running and could not be closed")."""
import re

from nsis_model import NSI, statements

LANGS = re.findall(r'^!insertmacro MUI_LANGUAGE "(\w+)"$', NSI, re.M)
LINES = re.findall(r'^LangString (\w+) \$\{LANG_(\w+)\} "(.*)"$', NSI, re.M)
NEW_KEYS = ["EGM_UN_APP_RUNNING", "EGM_UN_APP_STILL_RUNNING", "EGM_FOLDER_NOT_OURS", "EGM_ARCH_UNSUPPORTED",
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
        rest = re.sub(r'\$\\r\$\\n|\$\\"|\$\{VERSION\}|\$INSTDIR\b|\$\$', "", text)
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


def test_every_message_box_shows_a_language_string_but_the_one_english_box_it_had():
    english_only = []
    for s in statements(NSI):
        if s.startswith("MessageBox "):
            text = re.search(r'"([^"]*)"', s).group(1)
            if not re.fullmatch(r"\$\(EGM_\w+\)", text):
                english_only.append(text)
    assert english_only == ["${APPNAME} is still running and could not be closed.$\\r$\\nNothing was changed. "
                            "Quit it from the tray icon (or end it in Task Manager), then run the installer again."], english_only


def test_the_english_finish_text_names_ffmpeg_and_deno_like_the_welcome_page():
    texts = _texts("EGM_FINISH_TEXT")
    english = texts.pop("ENGLISH")
    assert "ffmpeg and Deno" in english and "required components" not in english
    assert "ffmpeg" in _texts("EGM_WELCOME_TEXT")["ENGLISH"] and "Deno" in _texts("EGM_WELCOME_TEXT")["ENGLISH"]
    assert not re.search(r"\d", english.replace("${VERSION}", "")), "no size and no other version"
    # the nine others wait for the translator pass, as they were
    assert len(texts) == 9 and all(t != english for t in texts.values())


def test_the_english_finish_text_promises_no_single_download():
    """The downloads are tried again at every launch until ffmpeg and Deno are there, so the text
    no longer says it happens once (EGM's wording)."""
    assert _texts("EGM_FINISH_TEXT")["ENGLISH"] == (
        "EGM Downloader v${VERSION} has been installed.$\\r$\\n"
        "On first launch, ffmpeg and Deno are downloaded in the background.")
