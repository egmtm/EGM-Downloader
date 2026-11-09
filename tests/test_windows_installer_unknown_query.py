"""windows/setup.nsi: when the PowerShell query cannot tell, the app is looked for by image name, and the
installer and the uninstaller ask before they close anything.

* The query writes EGM_QUERY_RAN after its list, and only once WMI has answered (Get-CimInstance with
  -ErrorAction Stop in a try). EGM_FindRunning turns a missing marker (PowerShell blocked or missing,
  WMI failing, nsExec's "error" or "timeout") into $0 = -1, whatever the exit code: a blocked script
  can exit with a number that looks like a count.
* Then tasklist (full path, /FO CSV /NH, no cmd, no pipe) looks for "EGM Downloader.exe" by name. It
  cannot tell this folder's copy from another, so its own box says closing ends every copy; OK runs
  taskkill /F /T /IM "EGM Downloader.exe", checks again after a second, and stops with nothing changed
  if one is still there; Cancel stops with nothing changed. Silent: Cancel, exit code 2 (nobody agreed
  to close every copy). The normal path, when the query ran, is unchanged.
* Known limit: an orphaned backend (the folder's python.exe without the app) is not found by name.

The real script runs in tests/nsis_model.py, with stand ins for PowerShell, tasklist and taskkill; the
query itself runs under pwsh with a Get-CimInstance that throws."""
import json
import os
import re
import subprocess

import pytest

from nsis_model import NSI, Run, expand, macro_functions, section, statements
from test_windows_installer_running_app import DIR, PWSH, _query

UNKNOWN = ["error", "timeout", "blocked", "wmi"]
FOLDER = {"$INSTDIR/EGM Downloader.exe", "$INSTDIR/resources/app.asar", "$INSTDIR/egm_settings.json"}


# ── the query says it ran ─────────────────────────────────────────────────────

def _pwsh(stub):
    env = dict(os.environ, EGM_STOP_DIR=DIR,
               EGM_FAKE_PROCESSES=json.dumps([{"ProcessId": 7, "ExecutablePath": DIR + r"\EGM Downloader.exe"}]))
    return subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", stub + _query()],
                          capture_output=True, text=True, timeout=120, env=env)


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_the_query_says_it_ran_only_when_wmi_answered():
    ok = _pwsh("function Get-CimInstance { $env:EGM_FAKE_PROCESSES | ConvertFrom-Json }; ")
    assert (ok.returncode, ok.stdout) == (1, "/PID 7 EGM_QUERY_RAN"), ok.stderr
    failed = _pwsh("function Get-CimInstance { throw 'RPC server is unavailable' }; ")
    assert "EGM_QUERY_RAN" not in failed.stdout + failed.stderr, (failed.stdout, failed.stderr)
    assert failed.returncode == 255


def test_a_wmi_error_is_no_longer_hidden():
    """-ErrorAction SilentlyContinue would turn a WMI error into an empty list: "nothing running". The text
    of the query, read everywhere (the test above runs it, where pwsh is installed): the WMI call stops on
    an error inside a try whose catch exits 255, and the marker is written last, after the list."""
    q = _query()
    assert "SilentlyContinue | Where-Object" not in q
    assert re.search(r"try \{ \$a = @\(Get-CimInstance Win32_Process -ErrorAction Stop\) \} catch \{ exit 255 \};", q), q
    tail = q[q.index("[Console]::Out.Write("):]
    assert re.fullmatch(r"\[Console\]::Out\.Write\(.*\+ ' EGM_QUERY_RAN'\); exit \$p\.Count", tail), tail


def _find(un="", **kw):
    r = Run(set(), **kw)
    r.run(macro_functions()[f"{un}EGM_FindRunning"])
    return r.regs["$0"], r.regs["$1"]


@pytest.mark.parametrize("un", ["", "un."])
def test_the_function_tells_found_none_and_unknown_apart(un):
    assert _find(un, running={4, 5}, backend={6}) == (3, "/PID 4 /PID 5 /PID 6")
    assert _find(un) == (0, "")
    for ps in UNKNOWN:
        assert _find(un, ps=ps, running={4}) == ("-1", ""), ps


def _by_name(un="", **kw):
    r = Run(set(), **kw)
    r.run(macro_functions()[f"{un}EGM_FindRunningByName"])
    return r.regs["$0"]


@pytest.mark.parametrize("un", ["", "un."])
def test_the_name_check_finds_any_copy_but_nothing_else(un):
    assert _by_name(un, running={4}) == "1"
    assert _by_name(un, elsewhere={9}) == "1"
    assert _by_name(un) == "0"
    assert _by_name(un, backend={6}) == "0", "python.exe is not looked for by name"
    assert _by_name(un, tasklist_fails=True, running={4}) == "0"


def test_the_name_check_calls_tasklist_by_its_full_path_and_reads_its_output_itself():
    fns = macro_functions()
    for un in ("", "un."):
        body = "\n".join(fns[f"{un}EGM_FindRunningByName"])
        assert """nsExec::ExecToStack '"$SYSDIR\\tasklist.exe" /FI "IMAGENAME eq EGM Downloader.exe" /FO CSV /NH'""" in body
        assert "cmd" not in body.lower().replace("execto", "") and "find" not in body.lower().replace("findrunning", "")
        assert "python" not in body.lower()


# ── the flow ──────────────────────────────────────────────────────────────────

def _install(**kw):
    paths = set(FOLDER)
    return Run(paths, **kw).run(expand(section("Install"))), paths


def _uninstall(**kw):
    paths = set(FOLDER)
    body = expand(section("Uninstall"), extra={"EGM_REMOVE_APP_FOLDER": 'Delete "$INSTDIR\\EGM Downloader.exe"\n'
                                                                       'RMDir /r "$INSTDIR\\resources"'})
    return Run(paths, **kw).run(body), paths


RUNS = [(_install, "$(EGM_APP_RUNNING_ANY_COPY)", "$(EGM_APP_STILL_RUNNING)", "writes"),
        (_uninstall, "$(EGM_UN_APP_RUNNING_ANY_COPY)", "$(EGM_UN_APP_STILL_RUNNING)", "end")]
KILL_BY_NAME = '"$SYSDIR\\taskkill.exe" /F /T /IM "EGM Downloader.exe"'


def _kills(r):
    return [c for c in r.execs if "taskkill" in c]


@pytest.mark.parametrize("run, box, still, done", RUNS)
@pytest.mark.parametrize("ps", UNKNOWN)
def test_unknown_and_nothing_by_name_goes_on_without_a_box(run, box, still, done, ps):
    r, _ = run(silent=False, answers=["IDNO", "IDNO"], ps=ps)
    assert r.outcome == done and not any("RUNNING" in b[0] for b in r.boxes), r.boxes
    assert r.name_finds == 1 and not _kills(r)


@pytest.mark.parametrize("run, box, still, done", RUNS)
@pytest.mark.parametrize("ps", UNKNOWN)
def test_unknown_and_running_asks_and_ok_closes_every_copy(run, box, still, done, ps):
    r, paths = run(silent=False, answers=["IDOK", "IDNO", "IDNO"], ps=ps, running={4}, elsewhere={9})
    assert r.boxes[0] == (box, "IDOK")
    assert _kills(r) == [KILL_BY_NAME], r.execs
    assert r.name_finds == 2, "checked again after closing"
    assert not r.running and not r.elsewhere, "every copy was closed, the portable one too"
    assert r.outcome == done


@pytest.mark.parametrize("run, box, still, done", RUNS)
def test_unknown_and_running_cancel_changes_nothing(run, box, still, done):
    r, paths = run(silent=False, answers=["IDCANCEL"], ps="blocked", running={4}, elsewhere={9})
    assert r.boxes == [(box, "IDCANCEL")]
    assert r.outcome == "aborted" and paths == FOLDER and not r.deleted and not _kills(r)
    assert r.running == {4} and r.elsewhere == {9}


@pytest.mark.parametrize("run, box, still, done", RUNS)
def test_unknown_and_running_when_silent_stops_without_closing_anything(run, box, still, done):
    """Exit code 2: Abort, as the installer's other refusals (checked under Wine)."""
    r, paths = run(silent=True, ps="error", running={4})
    assert r.boxes == [(box, "IDCANCEL")]
    assert r.outcome == "aborted" and paths == FOLDER and not _kills(r) and r.running == {4}


@pytest.mark.parametrize("run, box, still, done", RUNS)
def test_unknown_and_it_cannot_be_closed_stops_with_nothing_changed(run, box, still, done):
    r, paths = run(silent=False, answers=["IDOK", "IDOK"], ps="wmi", running={4}, unkillable={4})
    assert [b[0] for b in r.boxes] == [box, still]
    assert r.outcome == "aborted" and paths == FOLDER and not r.deleted


@pytest.mark.parametrize("run, box, still, done", RUNS)
def test_only_a_copy_elsewhere_also_asks_because_it_cannot_be_told_apart(run, box, still, done):
    r, _ = run(silent=False, answers=["IDCANCEL"], ps="timeout", elsewhere={9})
    assert r.boxes == [(box, "IDCANCEL")] and r.outcome == "aborted"


@pytest.mark.parametrize("run, box, still, done", RUNS)
def test_an_orphaned_backend_is_not_seen_by_name_the_known_limit(run, box, still, done):
    r, _ = run(silent=False, answers=["IDNO", "IDNO"], ps="blocked", backend={6})
    assert r.outcome == done and not any("RUNNING" in b[0] for b in r.boxes) and not _kills(r)


@pytest.mark.parametrize("run, box, still, done", RUNS)
def test_when_the_query_ran_nothing_changes(run, box, still, done):
    """The normal path: this folder's processes by PID, silent closes them, a copy elsewhere is left."""
    r, _ = run(silent=True, running={4}, backend={6}, elsewhere={9})
    assert _kills(r) == ['"$SYSDIR\\taskkill.exe" /F /T /PID 4 /PID 6'] and r.elsewhere == {9}
    assert r.name_finds == 0 and r.outcome == done
    r, _ = run(silent=False, answers=["IDNO", "IDNO"], elsewhere={9})
    assert r.name_finds == 0 and not any("RUNNING" in b[0] for b in r.boxes) and r.outcome == done


def test_the_fallback_box_defaults_to_cancel_and_the_normal_box_to_ok():
    for sec in (section("Install"), section("Uninstall")):
        s = statements(sec)
        any_copy = [x for x in s if "ANY_COPY)" in x]
        assert len(any_copy) == 1 and "/SD IDCANCEL IDOK " in any_copy[0], any_copy
        normal = [x for x in s if x.startswith("MessageBox MB_OKCANCEL") and "APP_RUNNING)" in x]
        assert len(normal) == 1 and "/SD IDOK IDOK " in normal[0], normal
    assert NSI.count('"$SYSDIR\\taskkill.exe" /F /T $1') == 2, "the normal kill lines are kept as they were"
