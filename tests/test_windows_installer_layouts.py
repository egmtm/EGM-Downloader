"""windows/setup.nsi: what an install does to the folder it goes into, before the new files are written.

The Install section is run in tests/nsis_model.py over models of the folders an install meets:
* the 1.5.x layout (launch.py, electron\\, templates\\ ...) loses its program files by name;
* this layout (resources\\app.asar) loses resources\\ and locales\\ as a whole (upgrade or repair);
* a folder holding both is cleaned of the old files first and then of the old resources;
* a cleanup cut short between two steps is finished by the next run (launch.py goes last);
* user data, ffmpeg and Deno are never touched;
* a folder is ours by EGM Downloader.exe, the recorded install path, egm_settings.json or a named
  ffmpeg or Deno file; resources\\app.asar, launch.py and electron\\main.js are in other software too;
* only a folder with EGM Downloader.exe or the recorded path may lose files (the strong ones): a
  folder the weaker markers let in gets the install and loses nothing."""
import re

import pytest

from nsis_model import NSI, Run, expand, macro, section, statements

DATA = {"egm_settings.json", "egm_history.json", "egm_subscriptions.json", "cookies.txt", "thumbnails/a.jpg",
        "logs/security.log", "egm_debug.log", "ffmpeg_bin/ffmpeg.exe", "runtime/deno.exe", "electron-data/x",
        "first-run-language.txt"}
NEW = {"EGM Downloader.exe", "ffmpeg.dll", "resources.pak", "uninstall.exe", "instructions.txt", "LICENSE",
       "resources/app.asar", "resources/app/app.py", "resources/app/old_module.py",
       "resources/app/__pycache__/app.cpython-311.pyc", "resources/python/python.exe",
       "resources/python/Lib/site-packages/dropped_package/__init__.py", "locales/en-US.pak", "locales/dropped.pak"}
OLD = {"EGM Downloader.exe", "launch.py", "app.py", "patchnotes.txt", "instructions.txt", "LICENSE", "uninstall.exe",
       "templates/index.html", "static/icon.ico", "languages/en.json", "electron/main.js", "electron/package.json",
       "electron/node_modules/electron/dist/EGM Downloader.exe", "node_bin/node.exe", "__pycache__/app.cpython-311.pyc",
       "rcedit-x64.exe", ".electron-update", "launch.vbs"}
OLD_PROGRAM_TOPS = {"launch.py", "app.py", "patchnotes.txt", "templates", "static", "languages", "electron", "node_bin",
                    "__pycache__", "rcedit-x64.exe", ".electron-update", "launch.vbs"}


def folder(*names):
    return {f"$INSTDIR/{n}" for group in names for n in group}


def tops(paths):
    return {p.split("/")[1] for p in paths if p.startswith("$INSTDIR/")}


def install(paths, **kw):
    """Run the Install section up to the first write; the model's folder is changed in place."""
    return Run(paths, **kw).run(expand(section("Install")))


# ── the two layouts ───────────────────────────────────────────────────────────

def test_the_old_layout_loses_its_program_files_and_keeps_data():
    paths = folder(OLD, DATA)
    r = install(paths)
    assert r.outcome == "writes"
    assert tops(paths) == {"EGM Downloader.exe", "instructions.txt", "LICENSE", "uninstall.exe"} | tops(folder(DATA))


def test_an_upgrade_replaces_resources_and_locales_as_a_whole():
    """A module, a package or a locale an earlier version had and this one dropped does not stay."""
    paths = folder(NEW, DATA)
    r = install(paths)
    assert r.outcome == "writes"
    assert not {p for p in paths if p.startswith(("$INSTDIR/resources/", "$INSTDIR/locales/"))}, sorted(paths)
    assert folder(DATA) <= paths, "user data is never in resources or locales"


def test_a_folder_holding_both_layouts_is_cleaned_of_both():
    paths = folder(OLD, NEW, DATA)
    r = install(paths)
    assert r.outcome == "writes"
    assert not tops(paths) & OLD_PROGRAM_TOPS, sorted(tops(paths) & OLD_PROGRAM_TOPS)
    assert not tops(paths) & {"resources", "locales"}
    assert folder(DATA) <= paths


def test_the_old_layout_is_checked_first_and_the_two_checks_are_independent():
    sec = section("Install")
    sec = sec[sec.index("What is installed here already"):]
    old = sec.index('${If} ${FileExists} "$INSTDIR\\launch.py"')
    new = sec.index('${If} ${FileExists} "$INSTDIR\\resources\\app.asar"')
    assert old < sec.index("!insertmacro EGM_REMOVE_OLD_LAYOUT") < sec.index("${EndIf}", old) < new
    between = sec[old:sec.index("${EndIf}", new)]
    assert "${ElseIf}" not in between and "${Else}" not in between


# ── a cleanup cut short ───────────────────────────────────────────────────────

def test_electron_goes_first_and_launch_py_last():
    steps = statements(macro("EGM_REMOVE_OLD_LAYOUT"))
    assert steps[0] == 'RMDir /r "$INSTDIR\\electron"'
    assert steps[-1] == 'Delete "$INSTDIR\\launch.py"'


@pytest.mark.parametrize("cut", range(1, len(statements(macro("EGM_REMOVE_OLD_LAYOUT")))))
def test_a_migration_cut_short_after_any_step_is_finished_by_the_next_run(cut):
    """Power off after `cut` steps of the old layout's cleanup; the next installer run must end in the
    same folder as an uninterrupted one."""
    whole = folder(OLD, DATA)
    install(whole)
    paths = folder(OLD, DATA)
    Run(paths).run(statements(macro("EGM_REMOVE_OLD_LAYOUT"))[:cut])
    r = install(paths)
    assert r.outcome == "writes"
    assert paths == whole, sorted(paths ^ whole)


# ── a folder that is not ours ─────────────────────────────────────────────────

PORTABLE = {"EGM Downloader.exe", "launch.py", ".portable", "app.py", "instructions.txt", "templates/index.html",
            "electron/package.json", "data/egm_settings.json", "python/python.exe"}
FOREIGN = {"notes.txt", "photos/a.jpg"}
ELECTRON_APP = {"SomeApp.exe", "ffmpeg.dll", "resources/app.asar", "resources/app/main.js", "locales/en-US.pak"}
FLASK_PROJECT = {"app.py", "launch.py", "requirements.txt", "README.md", "templates/index.html",
                 "static/style.css", "languages/en.json"}
ELECTRON_PROJECT = {"package.json", "electron/main.js", "src/index.js"}
# What makes a folder ours: the launcher, and what an uninstall keeps (the settings file, a named ffmpeg
# or Deno file). The recorded install path is the other way in (below).
MARKERS = ["EGM Downloader.exe", "egm_settings.json", "ffmpeg_bin/ffmpeg.exe", "runtime/deno.exe"]
WEAK = MARKERS[1:]


@pytest.mark.parametrize("name, contents", [
    ("a portable copy", PORTABLE),
    ("a 1.5.x portable copy", OLD | {".portable", "python/python.exe", "data/egm_settings.json"}),
    ("a folder of something else", FOREIGN),
    ("a folder with only a README.md", {"README.md"}),
    ("another Electron app", ELECTRON_APP),
    ("a Flask project", FLASK_PROJECT),
    ("an Electron project", ELECTRON_PROJECT),
    ("a runtime folder that holds no Deno", {"runtime/notes.txt"}),
    ("an ffmpeg_bin folder that holds no ffmpeg", {"ffmpeg_bin/readme.txt"}),
])
def test_a_folder_that_is_not_ours_is_refused_before_anything_changes(name, contents):
    for silent, answers in ((True, []), (False, ["IDOK"])):
        paths = folder(contents)
        r = install(paths, silent=silent, answers=answers, running={7})
        assert r.outcome == "aborted", name
        assert paths == folder(contents) and not r.deleted, name
        assert r.boxes == [("$(EGM_FOLDER_NOT_OURS)", "IDOK")], (name, r.boxes)
        assert r.finds == 0 and not r.execs, f"{name}: nothing is looked for or closed before the refusal"


@pytest.mark.parametrize("marker", MARKERS)
def test_each_marker_makes_a_folder_ours(marker):
    paths = folder({marker} | FOREIGN)
    r = install(paths)
    assert r.outcome == "writes", marker
    assert folder(FOREIGN) <= paths


FOREIGN_PROGRAM = {"launch.py", "app.py", "requirements.txt", "README.md", "templates/index.html",
                   "static/style.css", "languages/en.json", "electron/main.js", "resources/app.asar",
                   "resources/app/main.js", "locales/en-US.pak"}


@pytest.mark.parametrize("weak", WEAK)
def test_a_folder_that_only_a_weak_marker_lets_in_gets_the_install_and_loses_nothing(weak):
    """Leftover components and a settings file can open the door but never delete: the folder also
    holds another program's launch.py and resources\\app.asar, and every one of its files stays."""
    paths = folder({weak}, FOREIGN_PROGRAM)
    before = set(paths)
    r = install(paths)
    assert r.outcome == "writes", weak
    assert paths == before and not r.deleted, sorted(r.deleted)


def test_a_repair_after_antivirus_removed_the_launcher_still_replaces_resources():
    """instructions.txt tells people to run the installer again (Repair) when antivirus took a file of
    the app. The launcher is gone and, on a first install, there is no settings file yet: the install
    path the registry records is what makes the folder ours, and strong."""
    for extra in (DATA, set()):
        paths = folder(NEW - {"EGM Downloader.exe"}, extra)
        r = install(paths, regs={"$PreviousInstDir": "$INSTDIR"})
        assert r.outcome == "writes"
        assert not {p for p in paths if p.startswith(("$INSTDIR/resources/", "$INSTDIR/locales/"))}, sorted(paths)
        assert folder(extra) <= paths


def test_the_same_folder_without_the_recorded_path_is_not_recognised():
    """resources\\app.asar is in every Electron app, so it is not a marker: without the launcher, the
    settings file, a named ffmpeg or Deno file or the recorded path, the folder is refused."""
    paths = folder(NEW - {"EGM Downloader.exe"})
    before = set(paths)
    r = install(paths)
    assert r.outcome == "aborted" and paths == before and not r.deleted


def test_a_recorded_path_that_is_another_folder_counts_for_nothing():
    paths = folder(FLASK_PROJECT)
    r = install(paths, regs={"$PreviousInstDir": "D:/Elsewhere"})
    assert r.outcome == "aborted" and not r.deleted


def test_every_delete_of_the_install_section_sits_inside_the_strong_check():
    """No Delete, RMDir or cleanup macro before the files are written may run for a folder that is
    not strong; a delete added later without the check fails here."""
    body = section("Install")
    body = body[:body.index("File /r")]
    stack, unguarded = [], []
    for s in statements(body):
        m = re.match(r"\$\{(If|IfNot|ElseIf|Else|EndIf)\}\s*(.*)$", s)
        if m:
            kind, rest = m.groups()
            if kind in ("If", "IfNot"):
                stack.append(rest if kind == "If" else "not " + rest)
            elif kind in ("ElseIf", "Else"):
                stack[-1] = ""
            else:
                stack.pop()
            continue
        if re.match(r"(Delete|RMDir)\b", s) or s == "!insertmacro EGM_REMOVE_OLD_LAYOUT":
            if not any(c == '$FolderStrong == "1"' for c in stack):
                unguarded.append(s)
    assert not unguarded, unguarded
    assert 'RMDir /r "$INSTDIR\\resources"' in body, "no delete found, so this checks nothing"


def test_an_empty_or_new_folder_is_installed_into():
    paths = set()
    r = install(paths)
    assert r.outcome == "writes" and not r.boxes and not r.deleted


def test_the_refusal_comes_first_in_the_install_section():
    sec = section("Install")
    refusal = sec.index("$(EGM_FOLDER_NOT_OURS)")
    for later in ("Call EGM_FindRunning", "taskkill", "RMDir", "!insertmacro", "File ", "WriteReg"):
        assert refusal < sec.index(later), later


# ── v0.99 leftovers ───────────────────────────────────────────────────────────

V099 = {"EGM Downloader.exe", "launch.py", "launch.vbs", "app.py", "README.md", "requirements.txt", "EGM Downloader.vbs", "patchnotes.txt",
        "instructions.txt", "uninstall.exe", "templates/index.html", "static/icon.ico"}


def test_the_v0_99_files_go_from_a_folder_that_is_ours():
    paths = folder(V099, DATA)
    r = install(paths)
    assert r.outcome == "writes"
    assert not tops(paths) & {"README.md", "requirements.txt", "EGM Downloader.vbs"}
    assert folder(DATA) <= paths


def test_the_v0_99_files_are_removed_only_after_the_check():
    sec = section("Install")
    for name in ("README.md", "requirements.txt", "EGM Downloader.vbs"):
        assert sec.index("$(EGM_FOLDER_NOT_OURS)") < sec.index(f'Delete "$INSTDIR\\{name}"') < sec.index("File /r"), name


# ── what an uninstall leaves is ours ──────────────────────────────────────────

def _uninstalled(answers):
    """The folder an install, some use and an uninstall with `answers` leave behind."""
    paths = folder(NEW, DATA)
    body = expand(section("Uninstall"), extra={"EGM_REMOVE_APP_FOLDER": "\n".join(
        f'RMDir /r "$INSTDIR\\{d}"' if d in ("resources", "locales") else f'Delete "$INSTDIR\\{d}"'
        for d in tops(folder(NEW)) - {"uninstall.exe", "instructions.txt", "LICENSE"})})
    Run(paths, silent=False, answers=answers).run(body)
    return paths


@pytest.mark.parametrize("answers", [["IDNO", "IDNO"], ["IDYES", "IDNO"], ["IDNO", "IDYES"]])
def test_a_later_install_goes_into_the_folder_an_uninstall_left(answers):
    """Keeping the data (the default, and what /S does) or the components must not turn the folder
    into one that is not ours: the next install goes into it and finds what was kept."""
    paths = _uninstalled(answers)
    assert paths and not tops(paths) & {"EGM Downloader.exe", "resources", "launch.py", "electron"}, sorted(paths)
    kept = set(paths)
    r = install(paths)
    assert r.outcome == "writes", (answers, sorted(paths))
    assert paths == kept
