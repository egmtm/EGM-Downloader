"""windows/setup.nsi: uninstall details.

* "Already installed", No: the installer runs the uninstaller in place (_?=) and waits, so the user
  answers its questions; after an uninstall that ran to its end it removes uninstall.exe and the
  folder if nothing else is left in it. A cancelled uninstall leaves the install as it was.
* An uninstall that keeps the data keeps the InstallPath value, so a later install finds the folder
  (a custom one too) and the data in it; the other values and the key go."""
import pytest

from nsis_model import Run, expand, function, section, statements

INSTALLED = {"$INSTDIR/uninstall.exe", "$INSTDIR/egm_settings.json"}


def _no_uninstall(exit_code):
    paths = set(INSTALLED)
    r = Run(paths, silent=False, answers=["IDNO"], exec_exit=exit_code,
            regs={"$PreviousVersion": "9.9.9.9", "$PreviousInstDir": "$INSTDIR"}).run(statements(function("WelcomePage_Pre")))
    return r, paths


def test_no_runs_the_uninstaller_in_place_with_its_questions_and_waits():
    r, _ = _no_uninstall(0)
    assert r.execs == ['"$INSTDIR\\uninstall.exe" _?=$INSTDIR'], r.execs
    assert r.outcome == "quit"


def test_after_an_uninstall_that_ran_to_its_end_its_uninstaller_is_removed():
    r, paths = _no_uninstall(0)
    assert paths == {"$INSTDIR/egm_settings.json"}, "uninstall.exe goes; the data the user kept stays"


@pytest.mark.parametrize("exit_code", [1, 2])
def test_a_cancelled_or_failed_uninstall_leaves_the_install_with_its_uninstaller(exit_code):
    r, paths = _no_uninstall(exit_code)
    assert paths == INSTALLED and r.outcome == "quit"


def test_yes_repairs_and_cancel_quits():
    for answer, outcome in (("IDYES", "end"), ("IDCANCEL", "quit")):
        r = Run(set(INSTALLED), silent=False, answers=[answer],
                regs={"$PreviousVersion": "9.9.9.9", "$PreviousInstDir": "$INSTDIR"}).run(statements(function("WelcomePage_Pre")))
        assert r.outcome == outcome and not r.execs, answer


# ── the recorded folder ───────────────────────────────────────────────────────

APP_KEY = "Software\\EGM Downloader"
REGISTRY = {f"{APP_KEY}/{v}" for v in ("Version", "Language", "Build", "InstallPath")}


def _uninstall(silent, answers):
    registry = set(REGISTRY)
    paths = {"$INSTDIR/EGM Downloader.exe", "$INSTDIR/egm_settings.json", "$INSTDIR/ffmpeg_bin/ffmpeg.exe"}
    body = expand(section("Uninstall"), extra={"EGM_REMOVE_APP_FOLDER": 'Delete "$INSTDIR\\EGM Downloader.exe"'})
    Run(paths, silent=silent, answers=answers, registry=registry).run(body)
    return registry


@pytest.mark.parametrize("silent, answers, kept", [
    (True, [], {f"{APP_KEY}/InstallPath"}),                       # /S keeps the data
    (False, ["IDNO", "IDNO"], {f"{APP_KEY}/InstallPath"}),
    (False, ["IDYES", "IDNO"], {f"{APP_KEY}/InstallPath"}),       # components go, data stays
    (False, ["IDNO", "IDYES"], set()),                            # the data goes
    (False, ["IDYES", "IDYES"], set()),
])
def test_install_path_stays_exactly_when_the_data_stays(silent, answers, kept):
    assert _uninstall(silent, answers) == kept


# ── Add/Remove Programs ───────────────────────────────────────────────────────

def test_add_remove_programs_gets_the_size_and_a_quiet_uninstall():
    sec = section("Install")
    assert sec.startswith('Section "Install" SecInstall\n')
    s = statements(sec)
    size = s.index("SectionGetSize ${SecInstall} $0")
    assert s[size + 1] == 'WriteRegDWORD HKCU "${UNINSTREG}" "EstimatedSize" $0'
    assert """WriteRegStr HKCU "${UNINSTREG}" "QuietUninstallString" '"$INSTDIR\\uninstall.exe" /S'""" in s
    assert s.index("""WriteRegStr HKCU "${UNINSTREG}" "UninstallString" '"$INSTDIR\\uninstall.exe"'""") < size


def test_the_quiet_uninstall_keeps_what_the_user_owns():
    """QuietUninstallString runs /S: both questions take their default, No (keep)."""
    registry = _uninstall(True, [])
    assert registry == {f"{APP_KEY}/InstallPath"}
