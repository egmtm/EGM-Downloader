"""windows/setup.nsi: the installer and the uninstaller close only the app of their own folder.

* The processes are found by image path, not by image name: the app's exe (also the 1.5.x launcher
  and that layout's Electron) and the bundled Python of THIS folder. A portable copy running from
  another folder is left alone; the backend that outlived the app is found too.
* PowerShell asks WMI (wmic is gone from new Windows); the query is run here under pwsh with a stand
  in for Get-CimInstance, exactly as setup.nsi spells it.
* Every Windows tool is called by its full path and nothing is piped to find, so a GNU find or
  tasklist earlier on PATH cannot change the answer.
* The uninstaller asks and checks again like the installer, and both stop before anything changes
  when the app cannot be closed. /S closes it without asking."""
import json
import os
import re
import shutil
import subprocess

import pytest

from nsis_model import NSI, Run, expand, function, macro, section, statements

# ── the query ─────────────────────────────────────────────────────────────────

def _query():
    body = macro("EGM_FIND_RUNNING_FUNCTION")
    cmd = re.search(r'nsExec::ExecToStack `"\$SYSDIR\\WindowsPowerShell\\v1\.0\\powershell\.exe" '
                    r'-NoProfile -NonInteractive -Command "(.*)"`', body)
    assert cmd, body
    assert "'$INSTDIR'" not in cmd.group(1) and "$INSTDIR" not in cmd.group(1), "the folder is passed in the environment"
    return cmd.group(1).replace("$$", "$")


PWSH = shutil.which("pwsh")
DIR = r"C:\Users\O'Brien\AppData\Local\EGM Downloader"


def _ask(processes):
    """Run the query under pwsh; Get-CimInstance answers with `processes`."""
    stub = "function Get-CimInstance { $env:EGM_FAKE_PROCESSES | ConvertFrom-Json }; "
    env = dict(os.environ, EGM_STOP_DIR=DIR, EGM_FAKE_PROCESSES=json.dumps(processes or [{"ProcessId": 1, "ExecutablePath": None}]))
    r = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", stub + _query()],
                       capture_output=True, text=True, timeout=120, env=env)
    return r.returncode, r.stdout, r.stderr


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_only_the_processes_of_this_folder_are_found():
    procs = [
        (101, DIR + r"\EGM Downloader.exe", True),
        (102, DIR + r"\resources\python\python.exe", True),              # the backend, orphaned or not
        (103, r"C:\Tools\EGM Downloader\EGM Downloader.exe", False),       # a portable copy elsewhere
        (104, DIR + r"2\EGM Downloader.exe", False),                       # a folder whose name starts the same
        (105, DIR.upper() + r"\EGM DOWNLOADER.EXE", True),                 # Windows paths ignore case
        (106, None, False),                                                # another user's process: no path
        (107, DIR + r"\tools\python.exe", False),                          # some other Python under the folder
        (108, DIR + r"\electron\node_modules\electron\dist\EGM Downloader.exe", True),   # the 1.5.x Electron
        (109, DIR + r"\electron\node_modules\electron\dist\electron.exe", True),         # not yet renamed
        (110, DIR + r"\ffmpeg_bin\ffmpeg.exe", False),                     # goes with its parent (taskkill /T)
        (111, r"C:\Python311\python.exe", False),
    ]
    code, out, err = _ask([{"ProcessId": p, "ExecutablePath": path} for p, path, _ in procs])
    want = [p for p, _, found in procs if found]
    assert out == " ".join(f"/PID {p}" for p in want), (out, err)
    assert code == len(want), (code, err)


@pytest.mark.skipif(not PWSH, reason="pwsh is not installed")
def test_nothing_running_prints_nothing_and_exits_0():
    code, out, err = _ask([{"ProcessId": 5, "ExecutablePath": r"C:\Other\EGM Downloader.exe"}])
    assert (code, out) == (0, ""), err


def test_both_the_installer_and_the_uninstaller_have_the_query():
    assert re.search(r'^!insertmacro EGM_FIND_RUNNING_FUNCTION ""$', NSI, re.M)
    assert re.search(r'^!insertmacro EGM_FIND_RUNNING_FUNCTION "un\."$', NSI, re.M)
    body = macro("EGM_FIND_RUNNING_FUNCTION")
    assert re.search(r"""SetEnvironmentVariable\(t "EGM_STOP_DIR", t "\$INSTDIR"\)""", body)


# ── full paths, no find ───────────────────────────────────────────────────────

def test_every_program_is_called_by_its_full_path_and_nothing_is_piped():
    calls = [s for s in statements(NSI) if re.match(r"(nsExec::\w+|ExecWait|Exec|ExecShell)\b", s)]
    assert calls
    for s in calls:
        if s.startswith("ExecShell"):
            continue
        cmd = re.match(r"\S+\s+(.)(.*)\1", s).group(2)
        assert re.match(r'"\$(SYSDIR|PreviousInstDir)\\[^"]+\.exe"', cmd), s
        assert not re.search(r"\|\s*find\b", cmd, re.I) and "cmd /c" not in cmd.lower(), s
    assert "/IM " not in NSI and "IMAGENAME" not in NSI, "nothing is matched by image name any more"


# ── the flow, in the model ────────────────────────────────────────────────────

FOLDER = {"$INSTDIR/EGM Downloader.exe", "$INSTDIR/resources/app.asar", "$INSTDIR/egm_settings.json"}


def _install(**kw):
    paths = set(FOLDER)
    return Run(paths, **kw).run(expand(section("Install"))), paths


def _uninstall(**kw):
    paths = set(FOLDER)
    body = expand(section("Uninstall"), extra={"EGM_REMOVE_APP_FOLDER": 'Delete "$INSTDIR\\EGM Downloader.exe"\n'
                                                                       'RMDir /r "$INSTDIR\\resources"'})
    return Run(paths, **kw).run(body), paths


@pytest.mark.parametrize("run", [_install, _uninstall])
def test_silent_closes_the_app_of_this_folder_without_asking_and_goes_on(run):
    r, paths = run(silent=True, running={4242, 4343})
    assert any("taskkill.exe" in c and "/PID 4242 /PID 4343" in c for c in r.execs), r.execs
    assert r.finds == 2, "checked again after closing"
    assert r.outcome in ("writes", "end"), r.outcome


@pytest.mark.parametrize("run, prompt", [(_install, "$(EGM_APP_RUNNING)"), (_uninstall, "$(EGM_UN_APP_RUNNING)")])
def test_cancel_at_the_prompt_changes_nothing(run, prompt):
    r, paths = run(silent=False, answers=["IDCANCEL"], running={7})
    assert r.boxes[0] == (prompt, "IDCANCEL")
    assert r.outcome == "aborted" and paths == FOLDER and not r.execs


@pytest.mark.parametrize("run, still", [(_install, None), (_uninstall, "$(EGM_UN_APP_STILL_RUNNING)")])
def test_an_app_that_cannot_be_closed_stops_everything_before_any_change(run, still):
    r, paths = run(silent=True, running={7}, unkillable={7})
    assert r.outcome == "aborted" and paths == FOLDER and not r.deleted
    assert len(r.boxes) == 2 and r.boxes[1][1] == "IDOK"
    if still:
        assert r.boxes[1][0] == still


def test_nothing_running_asks_nothing():
    for run in (_install, _uninstall):
        r, _ = run(silent=False, answers=["IDNO", "IDNO"], running=set())
        assert not any("APP_RUNNING" in b[0] for b in r.boxes)


def test_the_uninstaller_checks_before_it_removes_anything():
    sec = section("Uninstall")
    first_change = min(sec.find(k) for k in ("Delete ", "RMDir", "!insertmacro") if k in sec)
    assert sec.index("Call un.EGM_FindRunning") < first_change
    assert sec.rindex("Call un.EGM_FindRunning") < first_change
