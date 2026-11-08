"""windows/setup.nsi: uninstall details.

* "Already installed", No: the installer runs the uninstaller in place (_?=) and waits, so the user
  answers its questions; after an uninstall that ran to its end it removes uninstall.exe and the
  folder if nothing else is left in it. A cancelled uninstall leaves the install as it was."""
import pytest

from nsis_model import Run, function, statements

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
