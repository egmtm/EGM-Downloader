"""
windows/setup.nsi for the installer edition (Electron, Python and the app in one folder).

* Layout by files, never by version: the v1.5.0 to v1.5.2.3 layout (launch.py) loses its program
  files by explicit name; this layout (resources\\app.asar) loses resources\\ and locales\\ before
  the copy; anything else is installed over without deleting.
* The old-layout list is the program files of v1.5.2.3's installer (compared with that tag when the
  clone has it), never a user data name.
* The uninstaller removes exactly what the installer wrote (its top level list is generated from
  the built folder) plus what the app and Python create at runtime: with Yes to both prompts the
  install folder ends up empty and is removed. This is checked by running the uninstaller's Delete
  and RMDir lines over a model of an install folder.
* When makensis and 7z are installed, the installer is compiled for a small folder and listed.
"""
import fnmatch
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent
NSI = read_source("windows/setup.nsi")

# Rule B of the migration: the v1.5.x layout's program files, by name.
OLD_LAYOUT_DIRS = {"electron", "node_bin", "__pycache__", "templates", "static", "languages"}
OLD_LAYOUT_FILES = {"launch.py", "launch.vbs", "launch.bat", "rcedit-x64.exe", "rcedit_tmp.exe",
                    ".electron-update", "embedded-python-setup.log", "patchnotes.txt", "app.py"}
# Rule C: never deleted by an upgrade.
KEEP = {"egm_settings.json", "egm_history.json", "egm_subscriptions.json", "cookies.txt", "thumbnails",
        "logs", "data", "electron-data", "egm_debug.log", "egm_debug.log.old", "egm_error.log",
        "ffmpeg_bin", "runtime"}
# Written by the installer itself on every install (and by the old one): overwritten, not migrated.
REWRITTEN = {"EGM Downloader.exe", "instructions.txt", "LICENSE", "first-run-language.txt", "uninstall.exe"}


def _macro(text, name):
    m = re.search(rf"^!macro {name}\n(.*?)^!macroend", text, re.M | re.S)
    assert m, f"macro {name} not found"
    return m.group(1)


def _names(body):
    dirs = set(re.findall(r'^\s*RMDir /r "\$INSTDIR\\([^"\\]+)"', body, re.M))
    files = set(re.findall(r'^\s*Delete "\$INSTDIR\\([^"\\]+)"', body, re.M))
    return dirs, files


def _section(name):
    start = NSI.index(f'Section "{name}"')
    return NSI[start:NSI.index("SectionEnd", start)]


# ── migration ─────────────────────────────────────────────────────────────────

def test_the_old_layout_list_is_exactly_rule_b_and_never_user_data():
    dirs, files = _names(_macro(NSI, "EGM_REMOVE_OLD_LAYOUT"))
    assert dirs == OLD_LAYOUT_DIRS
    assert files == OLD_LAYOUT_FILES
    assert not (dirs | files) & KEEP
    assert not (dirs | files) & REWRITTEN
    body = _macro(NSI, "EGM_REMOVE_OLD_LAYOUT")
    assert "*" not in body and "?" not in body, "no wildcard on the install root"
    assert all(l.strip().startswith(("RMDir /r", "Delete")) for l in body.splitlines() if l.strip())


def _git_show(rev, path):
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def test_the_old_layout_list_matches_what_v1_5_2_3_installed():
    """From v1.5.2.3's own installer: the top level entries its File lines placed, and the program
    files its uninstaller removed. Take away what the new installer writes again and what stays
    (user data, ffmpeg, Deno); what remains is the list. Its launcher's own runtime files are named
    in its launch.py. The old uninstaller's python\\ cleanup is left out on purpose: the 1.5.x
    installer edition never created it (launch.py makes python\\ only for the portable edition)."""
    old_nsi = _git_show("v1.5.2.3", "windows/setup.nsi")
    old_launch = _git_show("v1.5.2.3", "windows/launch.py")
    if old_nsi is None:
        pytest.skip("the v1.5.2.3 tag is not in this clone")
    placed = set()
    for line in old_nsi.splitlines():
        m = re.match(r'\s*SetOutPath "\$INSTDIR\\([^"\\]+)', line)
        if m:
            placed.add(m.group(1))
    install = old_nsi[old_nsi.index('Section "Install"'):old_nsi.index("SectionEnd")]
    root_files = install[:install.index('SetOutPath "$INSTDIR\\templates"')]
    placed |= {m.rsplit("/", 1)[-1] for m in re.findall(r'File "\$\{REPO_ROOT\}/([^"]+)"', root_files)}
    uninstall = old_nsi[old_nsi.index('Section "Uninstall"'):]
    removed = set(re.findall(r'(?:Delete|RMDir /r) "\$INSTDIR\\([^"\\]+)"', uninstall))
    old_program = (placed | removed) - KEEP - REWRITTEN - {"python"}
    launcher_runtime = {"rcedit_tmp.exe", ".electron-update", "embedded-python-setup.log"}
    for name in launcher_runtime:
        assert name in old_launch, name
    dirs, files = _names(_macro(NSI, "EGM_REMOVE_OLD_LAYOUT"))
    assert dirs | files == old_program | launcher_runtime


def test_layout_is_decided_by_files_and_the_app_is_stopped_before_anything_changes():
    """The order of the two layout checks is in tests/test_windows_installer_layouts.py."""
    sec = _section("Install")
    layout = sec.index("What is installed here already")
    new = sec.index('${If} ${FileExists} "$INSTDIR\\resources\\app.asar"', layout)
    old = sec.index('${If} ${FileExists} "$INSTDIR\\launch.py"', layout)
    assert old < sec.index("!insertmacro EGM_REMOVE_OLD_LAYOUT") < sec.index("${EndIf}", old) < new
    assert "PreviousVersion" not in sec and "${VERSION}" not in sec[:sec.index("File /r")]
    # The app is stopped first: the second check after the kill aborts before any change
    second_check = sec.index("Call EGM_FindRunning", sec.index("taskkill"))
    abort = sec.index("Abort", second_check)
    first_change = min(sec.find(k) for k in ("RMDir", "!insertmacro", "File ", "WriteReg") if k in sec)
    assert second_check < abort < first_change
    assert sec.index('RMDir /r "$INSTDIR\\resources"') < sec.index('File /r "${APP_FOLDER}/*"')


def test_icons_point_into_the_folder_and_shortcuts_at_the_exe():
    assert "$INSTDIR\\static\\" not in NSI
    icon = "$INSTDIR\\resources\\app\\static\\icon.ico"
    for key in ('"DisplayIcon"', '"IconUri"'):
        line = next(l for l in NSI.splitlines() if key in l)
        assert icon in line, key
    for lnk in ('"$DESKTOP\\EGM Downloader.lnk"', '"$SMPROGRAMS\\${APPNAME}\\${APPNAME}.lnk"'):
        block = NSI[NSI.index(lnk):NSI.index(lnk) + 200]
        assert '"$INSTDIR\\EGM Downloader.exe"' in block and icon in block, lnk


# ── uninstaller: a model of the install folder ────────────────────────────────

def _uninstall_list(folder):
    spec = importlib.util.spec_from_file_location("egm_uninstall_list", ROOT / "windows/installer/uninstall_list.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render(folder)


def _fake_folder(tmp_path):
    """A small installer folder shaped like the real one (top level runtime files, locales,
    resources with app, app.asar and python)."""
    d = tmp_path / "win-unpacked"
    for rel in ("EGM Downloader.exe", "LICENSE.electron.txt", "ffmpeg.dll", "icudtl.dat", "resources.pak",
                "locales/en-US.pak", "resources/app.asar", "resources/app/app.py",
                "resources/app/templates/index.html", "resources/python/python.exe",
                "resources/python/Lib/os.py", "resources/python/Lib/site-packages/yt_dlp/__init__.py"):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(b"x")
    return d


def _folder_for_model(tmp_path):
    real = ROOT / "dist" / "win-unpacked"
    return real if real.is_dir() else _fake_folder(tmp_path)


def _app_runtime_names():
    """Top level names app.py writes into the install folder (BASE_DIR and the data folder)."""
    src = read_source("app.py")
    names = set(re.findall(r'(?:get_data_dir\(\)|BASE_DIR) / ["\']([^"\'/]+)["\']', src))
    assert {"egm_settings.json", "egm_history.json", "ffmpeg_bin", "runtime", "logs", "thumbnails",
            "egm_debug.log", "egm_error.log", "cookies.txt", ".electron-update"} <= names, names
    return names


def _installed(folder):
    """Every path (relative to $INSTDIR, plus the other roots) after an install and some use."""
    files = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    files |= {"instructions.txt", "LICENSE", "uninstall.exe", "first-run-language.txt"}
    # written at runtime: Python's bytecode under resources, the app's own files at the top level
    files |= {"resources/python/Lib/__pycache__/os.cpython-311.pyc",
              "resources/python/Lib/site-packages/yt_dlp/__pycache__/__init__.cpython-311.pyc"}
    for name in _app_runtime_names():
        files.add(f"{name}/x" if "." not in name or name in ("logs", "runtime") else name)
    files |= {"ffmpeg_bin/ffmpeg.exe", "runtime/deno.exe", "thumbnails/a.jpg", "logs/security.log",
              "egm_debug.log.old", "egm_settings.json.tmp", "egm_history.json.tmp",
              "egm_settings.json.4242.tmp", "data/x", "electron-data/x",
              # the copies app.py keeps of a file it could not read (_keep_unreadable_copy)
              "egm_settings.json.unreadable", "egm_history.json.unreadable", "egm_subscriptions.json.unreadable"}
    other = {"$APPDATA/egm-downloader/Local Storage/x", "$SMPROGRAMS/EGM Downloader/EGM Downloader.lnk",
             "$SMPROGRAMS/EGM Downloader/Uninstall EGM Downloader.lnk", "$DESKTOP/EGM Downloader.lnk"}
    return {f"$INSTDIR/{f}" for f in files} | other


def _logical(lines):
    """Join NSIS continuation lines (a trailing backslash)."""
    out, buf = [], ""
    for line in lines:
        if line.rstrip().endswith("\\"):
            buf += line.rstrip()[:-1] + " "
        else:
            out.append(buf + line)
            buf = ""
    return out


def _run(lines, paths, answers):
    """Run Delete, RMDir and 'MessageBox ... IDNO label' lines over a set of paths (labels skip)."""
    norm = lambda s: s.replace("\\", "/").replace("${APPNAME}", "EGM Downloader")
    answers = list(answers)
    paths, removed_dirs, skip_to = set(paths), set(), None
    for line in (l.strip() for l in _logical(lines)):
        if skip_to:
            if line == f"{skip_to}:":
                skip_to = None
            continue
        m = re.match(r'(Delete|RMDir /r|RMDir)\s+"([^"]+)"', line)
        if m:
            op, target = m.group(1), norm(m.group(2))
            if op == "Delete":
                folder, pattern = target.rsplit("/", 1)
                paths -= {p for p in paths if p.rsplit("/", 1)[0] == folder
                          and fnmatch.fnmatchcase(p.rsplit("/", 1)[1], pattern)}
            elif op == "RMDir /r":
                paths -= {p for p in paths if p.startswith(target + "/")}
                removed_dirs.add(target)
            elif not any(p.startswith(target + "/") for p in paths):
                removed_dirs.add(target)
        elif line.startswith("MessageBox MB_YESNO"):   # the questions (the running app box is not one)
            jump = re.search(r"\bIDNO\s+(?!ID)(\w+)\s*$", line)   # "/SD IDNO IDNO label": the label
            if not answers.pop(0) and jump:
                skip_to = jump.group(1)
    assert not answers, "a prompt was not reached"
    return paths, removed_dirs


def _uninstall_lines(folder):
    sec = _section("Uninstall")
    gen = _uninstall_list(folder)
    expanded = sec.replace("!insertmacro EGM_REMOVE_APP_FOLDER", _macro(gen, "EGM_REMOVE_APP_FOLDER"))
    expanded = expanded.replace("!insertmacro EGM_REMOVE_OLD_LAYOUT", _macro(NSI, "EGM_REMOVE_OLD_LAYOUT"))
    assert "!insertmacro" not in expanded
    return expanded.splitlines()


def test_yes_to_both_prompts_leaves_nothing(tmp_path):
    folder = _folder_for_model(tmp_path)
    left, removed_dirs = _run(_uninstall_lines(folder), _installed(folder), [True, True])
    assert left == set(), sorted(left)[:10]
    for d in ("$INSTDIR", "$SMPROGRAMS/EGM Downloader"):
        assert d in removed_dirs, d
    unsec = _section("Uninstall")
    for key in ('"Software\\Classes\\AppUserModelId\\com.egerena.egm-downloader"', '"${UNINSTREG}"'):
        assert f"DeleteRegKey HKCU {key}" in unsec, key
    # the app's own key goes value by value: InstallPath stays with kept data (test_windows_installer_uninstall_details.py)
    assert 'DeleteRegKey /ifempty HKCU "${REGKEY}"' in unsec


@pytest.mark.parametrize("components, data, stays", [
    (False, False, {"ffmpeg_bin", "runtime", "egm_settings.json", "thumbnails", "logs", "egm_debug.log"}),
    (True, False, {"egm_settings.json", "thumbnails", "logs", "egm_debug.log"}),
    (False, True, {"ffmpeg_bin", "runtime"}),
])
def test_no_to_a_prompt_keeps_only_what_it_names(tmp_path, components, data, stays):
    folder = _folder_for_model(tmp_path)
    left, removed_dirs = _run(_uninstall_lines(folder), _installed(folder), [components, data])
    tops = {p.split("/")[1] for p in left if p.startswith("$INSTDIR/")}
    assert stays <= tops, tops
    assert not tops & {"EGM Downloader.exe", "resources", "locales", "LICENSE", "instructions.txt", "uninstall.exe"}
    data_files = KEEP - {"ffmpeg_bin", "runtime"} | {"egm_settings.json.tmp", "egm_history.json.tmp", "egm_settings.json.4242.tmp",
                                                    "egm_settings.json.unreadable", "egm_history.json.unreadable",
                                                    "egm_subscriptions.json.unreadable"}
    keep_all = (set() if components else {"ffmpeg_bin", "runtime"}) | (set() if data else data_files)
    assert tops <= keep_all, tops - keep_all
    assert "$INSTDIR" not in removed_dirs


def test_every_top_level_entry_the_installer_places_is_removed(tmp_path):
    folder = _folder_for_model(tmp_path)
    placed = {p.name for p in folder.iterdir()} | {"instructions.txt", "LICENSE", "uninstall.exe", "first-run-language.txt"}
    lines = "\n".join(_uninstall_lines(folder))
    program_part = lines[:lines.index("MessageBox MB_YESNO")]
    for name in placed:
        assert (f'Delete "$INSTDIR\\{name}"' in program_part or f'RMDir /r "$INSTDIR\\{name}"' in program_part), name


def test_an_old_layout_upgrade_keeps_data_and_unknown_files_and_then_uninstalls_clean(tmp_path):
    """Run the old-layout branch over a v1.5.x folder, copy the new folder over, then uninstall
    with Yes to both: only what is unknown to the app stays."""
    old = {f"$INSTDIR/{p}" for p in (
        "EGM Downloader.exe", "launch.py", "instructions.txt", "app.py", "patchnotes.txt", "LICENSE",
        "uninstall.exe", "templates/index.html", "templates/js/_core.html", "static/icon.ico",
        "languages/en.json", "electron/main.js", "electron/package.json", "electron/.launcher.lock",
        "electron/node_modules/electron/dist/EGM Downloader.exe", "electron/node_modules.old/x",
        "electron/.electron-stage/x", "node_bin/node.exe", "rcedit-x64.exe", "__pycache__/app.cpython-311.pyc",
        ".electron-update", "egm_settings.json", "egm_history.json", "thumbnails/a.jpg",
        "ffmpeg_bin/ffmpeg.exe", "runtime/deno.exe", "logs/security.log", "egm_debug.log",
        "my notes.txt", "my folder/keep.txt")}
    migrate = _macro(NSI, "EGM_REMOVE_OLD_LAYOUT").splitlines()
    after, _ = _run(migrate, set(old), [])
    tops = {p.split("/")[1] for p in after}
    assert tops == {"EGM Downloader.exe", "instructions.txt", "LICENSE", "uninstall.exe", "egm_settings.json",
                    "egm_history.json", "thumbnails", "ffmpeg_bin", "runtime", "logs", "egm_debug.log",
                    "my notes.txt", "my folder"}, tops
    folder = _folder_for_model(tmp_path)
    installed = after | {f"$INSTDIR/{p.relative_to(folder).as_posix()}" for p in folder.rglob("*") if p.is_file()}
    left, _ = _run(_uninstall_lines(folder), installed, [True, True])
    assert left == {"$INSTDIR/my notes.txt", "$INSTDIR/my folder/keep.txt"}


def test_prompt_one_names_only_ffmpeg_and_deno():
    unsec = _section("Uninstall")
    prompt = unsec[unsec.index("Prompt 1"):unsec.index("skip_components:")]
    assert '"$(EGM_UN_REMOVE_COMPONENTS)"' in prompt
    text = re.search(r'^LangString EGM_UN_REMOVE_COMPONENTS \$\{LANG_ENGLISH\} "(.*)"$', NSI, re.M).group(1)
    assert "ffmpeg and Deno" in text
    assert "Node.js" not in text and "Electron" not in text
    assert not re.search(r"\d\s*MB", text), "no size is quoted (ffmpeg and Deno were not measured)"
    assert _names(prompt) == ({"runtime", "ffmpeg_bin"}, set())


# ── compiled installer ────────────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("makensis") or not (shutil.which("7z") or shutil.which("7za")),
                    reason="makensis or 7z is not installed")
def test_the_compiled_installer_holds_the_folder_and_the_uninstaller(tmp_path):
    """The installer's file list is the installer folder plus uninstall.exe, and the two files the
    installer writes at the root besides the folder (instructions.txt and LICENSE). A small folder
    keeps this quick; the real folder is listed the same way in the release notes of the build."""
    folder = _fake_folder(tmp_path)
    lst = tmp_path / "files.nsh"
    lst.write_text(_uninstall_list(folder), encoding="utf-8")
    out = tmp_path / "egm-setup.exe"
    r = subprocess.run(["makensis", "-V1", "-DVERSION=0.0.0.1", "-DBUILD=1", f"-DREPO_ROOT={ROOT}",
                        f"-DAPP_FOLDER={folder}", f"-DAPP_FOLDER_LIST={lst}", f"-DOUTFILE={out}",
                        str(ROOT / "windows/setup.nsi")], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    seven = shutil.which("7z") or shutil.which("7za")
    r = subprocess.run([seven, "l", "-slt", str(out)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    listed = set()
    for block in r.stdout.split("\n\n"):
        path = re.search(r"^Path = (.+)$", block, re.M)
        if path and "Folder = +" not in block and not path.group(1).startswith("$PLUGINSDIR") and "Size = " in block:
            listed.add(path.group(1).replace("\\", "/"))
    listed.discard(str(out))
    want = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert listed == want | {"uninstall.exe", "instructions.txt", "LICENSE"}, sorted(listed ^ (want | {"uninstall.exe", "instructions.txt", "LICENSE"}))


def test_the_uninstaller_removes_the_common_folder_names_only_where_this_app_is_installed():
    """resources, locales, electron, templates, static and languages are common names, and the install
    folder is the user's choice: the generated list runs only where this edition is installed, the old
    layout's list only where a 1.5.x install is."""
    sec = _section("Uninstall")
    app = sec.index("!insertmacro EGM_REMOVE_APP_FOLDER")
    guard = sec.rfind("${If}", 0, app)
    assert sec[guard:app].strip().startswith('${If} ${FileExists} "$INSTDIR\\resources\\app.asar"'), sec[guard:app]
    assert sec.index("${EndIf}", app) < sec.index("!insertmacro EGM_REMOVE_OLD_LAYOUT")
    old = sec.index("!insertmacro EGM_REMOVE_OLD_LAYOUT")
    guard = sec.rfind("${If}", 0, old)
    assert sec[guard:old].strip().startswith('${If} ${FileExists} "$INSTDIR\\launch.py"'), sec[guard:old]
    assert sec.index("${EndIf}", old) < sec.index("MessageBox MB_YESNO")


def test_the_unreadable_copies_go_with_the_data():
    src = read_source("app.py")
    assert "def _keep_unreadable_copy" in src and '.unreadable' in src
    sec = _section("Uninstall")
    data = sec[sec.index("skip_components:"):sec.index("skip_userdata:")]
    for name in ("egm_settings.json", "egm_history.json", "egm_subscriptions.json"):
        assert f'Delete "$INSTDIR\\{name}.unreadable"' in data, name
