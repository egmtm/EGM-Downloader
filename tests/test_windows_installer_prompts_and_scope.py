"""
windows/setup.nsi: what the installer does when nobody answers, where it installs, and what its first
screen says.

* Silent runs keep everything the user owns: an uninstall with /S (QuietUninstallString, scripts)
  answers every uninstaller question with No, which jumps past what it would remove. The box
  about the running app defaults to closing it, and the "already installed" box maps
  Yes to repair and No to uninstall.
* One user, no admin: the installer asks for user rights, installs under %LOCALAPPDATA% (the folder
  app.py takes as "installed, not portable") and never switches to the all-users folders.
* The uninstaller closes the app before it deletes anything.
* Every data file app.py writes through a temporary file has that temporary file removed with the data.
* The language hand-off file goes to the install folder, where app.py reads it.
* The welcome text names ffmpeg and Deno, asks for no Python and quotes no size, in all ten languages.
"""
import re

from conftest import read_source

NSI = read_source("windows/setup.nsi")


def _section(name):
    start = NSI.index(f'Section "{name}"')
    return NSI[start:NSI.index("SectionEnd", start)]


def _function(name):
    start = NSI.index(f"Function {name}\n")
    return NSI[start:NSI.index("FunctionEnd", start)]


def _statements(text):
    """NSIS statements with continuation lines (a trailing backslash) joined."""
    out, buf = [], ""
    for line in text.splitlines():
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
        else:
            out.append((buf + line).strip())
            buf = ""
    return out


def _message_boxes(text):
    return [s for s in _statements(text) if s.startswith("MessageBox ")]


# ── silent runs ───────────────────────────────────────────────────────────────

def test_every_uninstaller_prompt_defaults_to_no_and_jumps_past_what_it_removes():
    sec = _section("Uninstall")
    boxes = [b for b in _message_boxes(sec) if "MB_YESNO" in b]   # the questions; the running app box closes it
    assert len(boxes) == 2, boxes
    for box in boxes:
        m = re.search(r"/SD (\w+) IDNO (\w+)\s*$", box)
        assert m, box
        assert m.group(1) == "IDNO", f"a silent uninstall would answer {m.group(1)}: {box[:60]}"
        label = m.group(2)
        between = sec[sec.index(f"IDNO {label}"):sec.index(f"{label}:")]
        assert re.search(r'^\s*(?:RMDir /r|Delete) "\$', between, re.M), f"{label}: the prompt skips nothing"


def test_the_already_installed_box_runs_the_uninstaller_with_its_questions():
    """No: the uninstaller runs with its own questions (not /S), and the installer waits for it
    (tests/test_windows_installer_uninstall_details.py runs it in the model)."""
    pre = _function("WelcomePage_Pre")
    box = _message_boxes(pre)
    assert len(box) == 1
    assert re.search(r"/SD IDCANCEL IDYES repair IDNO do_uninstall\s*$", box[0]), box[0]
    repair = pre[pre.index("repair:"):pre.index("do_uninstall:")]
    assert "Return" in repair and "uninstall.exe" not in repair
    uninstall = pre[pre.index("do_uninstall:"):]
    assert re.search(r"""ExecWait '"\$PreviousInstDir\\uninstall\.exe" _\?=\$PreviousInstDir' \$0""", uninstall), uninstall


def test_a_silent_install_closes_a_running_app_instead_of_cancelling():
    first = next(b for b in _message_boxes(_section("Install")) if "$(EGM_APP_RUNNING)" in b)
    assert "$(EGM_APP_RUNNING)" in first
    assert re.search(r"/SD IDOK IDOK kill_running\s*$", first), first


# ── one user, no admin ────────────────────────────────────────────────────────

def test_the_installer_is_per_user_in_local_appdata():
    assert re.search(r"^RequestExecutionLevel user$", NSI, re.M)
    assert re.search(r'^InstallDir\s+"\$LOCALAPPDATA\\EGM Downloader"$', NSI, re.M)
    assert not re.search(r"^\s*SetShellVarContext\s+all", NSI, re.M | re.I), "shortcuts and $SMPROGRAMS stay per user"
    # app.py takes exactly that folder as an installed (not portable) copy
    assert 'Path(local_appdata) / "EGM Downloader"' in read_source("app.py")


def test_the_uninstaller_closes_the_app_before_it_deletes_anything():
    sec = _section("Uninstall")
    kill = sec.find("taskkill")
    assert kill != -1, "the uninstaller no longer closes the app"
    first_change = min(i for i in (sec.find("Delete "), sec.find("RMDir"), sec.find("!insertmacro")) if i != -1)
    assert kill < first_change


# ── data files ────────────────────────────────────────────────────────────────

def test_the_temporary_file_of_every_data_file_is_removed_with_the_data():
    src = read_source("app.py")
    files = dict(re.findall(r'^(\w+_FILE)\s*=\s*get_data_dir\(\) / "([^"]+)"', src, re.M))
    written = set(re.findall(r"_atomic_write_text\((\w+_FILE)\b", src))
    assert written and written <= set(files), (written, files)
    assert "path.suffix + \".tmp\"" in src, "the temporary name is no longer <file>.tmp"
    sec = _section("Uninstall")
    user_data = sec[sec.index("skip_components:"):sec.index("skip_userdata:")]
    for const in sorted(written):
        name = files[const]
        assert f'Delete "$INSTDIR\\{name}"' in user_data, name
        assert f'Delete "$INSTDIR\\{name}.tmp"' in user_data, f"{name}.tmp"


def test_the_language_hand_off_goes_where_app_py_reads_it():
    inst = _section("Install")
    assert re.search(r'FileOpen \$0 "\$INSTDIR\\first-run-language\.txt" w', inst)
    assert 'INSTALL_DIR / "first-run-language.txt"' in read_source("app.py")


# ── first screen ──────────────────────────────────────────────────────────────

def test_the_welcome_text_names_ffmpeg_and_deno_and_asks_for_no_python_in_every_language():
    lines = re.findall(r'^LangString EGM_WELCOME_TEXT \$\{LANG_(\w+)\} "(.*)"$', NSI, re.M)
    assert len(lines) == 10, [lang for lang, _ in lines]
    for lang, text in lines:
        assert "ffmpeg" in text and "Deno" in text, lang
        assert "python" not in text.lower(), lang
        assert not re.search(r"\d", text.replace("${VERSION}", "")), f"{lang}: quotes a number (a size or a version)"
        assert text.count("$\\r$\\n") == 2, lang
