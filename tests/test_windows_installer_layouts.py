"""windows/setup.nsi: what an install does to the folder it goes into, before the new files are written.

The Install section is run in tests/nsis_model.py over models of the folders an install meets:
* the 1.5.x layout (launch.py, electron\\, templates\\ ...) loses its program files by name;
* this layout (resources\\app.asar) loses resources\\ and locales\\ as a whole (upgrade or repair);
* a folder holding both is cleaned of the old files first and then of the old resources;
* a cleanup cut short between two steps is finished by the next run (launch.py goes last);
* user data, ffmpeg and Deno are never touched."""
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
MARKERS = ["EGM Downloader.exe", "resources/app.asar", "launch.py", "electron/main.js"]


@pytest.mark.parametrize("name, contents", [
    ("a portable copy", PORTABLE),
    ("a 1.5.x portable copy", OLD | {".portable", "python/python.exe", "data/egm_settings.json"}),
    ("a folder of something else", FOREIGN),
    ("a folder with only a README.md", {"README.md"}),
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


def test_an_empty_or_new_folder_is_installed_into():
    paths = set()
    r = install(paths)
    assert r.outcome == "writes" and not r.boxes and not r.deleted


def test_the_refusal_comes_first_in_the_install_section():
    sec = section("Install")
    refusal = sec.index("$(EGM_FOLDER_NOT_OURS)")
    for later in ("Call EGM_FindRunning", "taskkill", "RMDir", "!insertmacro", "File ", "WriteReg"):
        assert refusal < sec.index(later), later
