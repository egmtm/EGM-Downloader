"""
The Windows installer edition ships Electron, Python and its packages inside the app folder,
built by windows/installer/build-folder.sh (phase 1 of windows/BUILD.sh).

* Electron comes from windows/electron's lock through a staging package: the transform must
  give exactly the Mac and Linux locks (same packages, same integrity), so a broken chain fails
  here at commit time instead of at release time.
* The bundled Python's packages come from the hashed lock windows/requirements-win-lock.txt: it
  must satisfy requirements.txt and the launcher's PY_DEP_FLOORS, because the installer edition
  never runs launch.py's top-ups (a floor reaches its users only with a new release).
* The exes are signed between the two phases; electron-builder never runs after phase 1.
"""
import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent


def _stage_module():
    spec = importlib.util.spec_from_file_location("egm_stage_package", ROOT / "windows/installer/stage_package.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _json(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _staged():
    mod = _stage_module()
    ver = _json("version.json")
    pkg, lock = mod.stage_package(_json("windows/electron/package.json"), _json("windows/electron/package-lock.json"),
                                  _json("windows/installer/builder-config.json"), ver["version"], ver["build"])
    return mod, ver, pkg, lock


# ── staging package and lock ──────────────────────────────────────────────────

def test_the_staging_lock_equals_the_mac_and_linux_locks():
    mod, _, _, lock = _staged()
    assert len(lock["packages"]) == 284
    for plat in ("mac", "linux"):
        other = _json(f"{plat}/electron/package-lock.json")
        assert mod.lock_differences(lock, other) == [], plat
        assert len(other["packages"]) == len(lock["packages"]), plat


def test_the_staging_package_is_what_electron_builder_accepts_and_keeps_the_windows_pin():
    _, ver, pkg, lock = _staged()
    win = _json("windows/electron/package.json")
    win_lock = _json("windows/electron/package-lock.json")
    assert "electron" not in pkg.get("dependencies", {})
    assert pkg["devDependencies"]["electron"] == win["dependencies"]["electron"]
    assert pkg["devDependencies"]["electron-builder"] == win["devDependencies"]["electron-builder"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pkg["version"]) and ver["version"].startswith(pkg["version"] + ".")
    # the exe's version strings: ProductVersion is the app version, FileVersion adds the build
    assert pkg["shortVersionWindows"] == ver["version"]
    assert pkg["shortVersion"] == f"{ver['version']}.{ver['build']}"
    # nothing re-resolved: the Electron entry is the Windows lock's own (plus the dev flag)
    staged_e = dict(lock["packages"]["node_modules/electron"])
    assert staged_e.pop("dev") is True
    assert staged_e == win_lock["packages"]["node_modules/electron"]
    # the packaged package.json keeps the name Electron derives userData from (%APPDATA%\egm-downloader)
    assert pkg["name"] == "egm-downloader" and "productName" not in pkg


def test_the_windows_electron_package_itself_still_serves_the_portable_edition():
    """launch.py runs npm ci --omit=dev on it: electron has to stay under dependencies there."""
    win = _json("windows/electron/package.json")
    assert "electron" in win["dependencies"] and "electron" not in win.get("devDependencies", {})
    assert win["version"] == _json("version.json")["version"]


def test_a_broken_chain_is_seen(tmp_path):
    mod, _, _, lock = _staged()
    other = json.loads(json.dumps(lock))
    other["packages"]["node_modules/electron"]["integrity"] = "sha512-changed"
    assert mod.lock_differences(lock, other) == ["node_modules/electron"]


def test_the_exe_company_is_the_installer_publisher():
    mod = _stage_module()
    nsi = read_source("windows/setup.nsi")
    assert f'!define PUBLISHER  "{mod.COMPANY}"' in nsi
    assert f"CompanyName: '{mod.COMPANY}'" in read_source("windows/installer/exe_strings.js")


# ── hashed Python lock ────────────────────────────────────────────────────────

def _lock_pins():
    pins, hashes, name = {}, {}, None
    for line in read_source("windows/requirements-win-lock.txt").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", line)
        if m:
            name = canonicalize_name(m.group(1))
            pins[name], hashes[name] = m.group(2), []
        hashes.setdefault(name, []).extend(re.findall(r"--hash=sha256:([0-9a-f]{64})", line))
    return pins, hashes


def test_the_lock_is_for_windows_and_every_pin_is_hashed():
    text = read_source("windows/requirements-win-lock.txt")
    assert "--python-platform x86_64-pc-windows-msvc --python-version 3.11 --generate-hashes --only-binary :all:" in text
    assert " ; " not in text, "a lock resolved for Windows carries no environment markers"
    pins, hashes = _lock_pins()
    assert pins
    for name in pins:
        assert hashes[name], f"{name} has no hash"


def test_the_lock_satisfies_requirements_txt():
    pins, _ = _lock_pins()
    for line in read_source("requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        req = Requirement(line)
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} is not in the lock"
        assert Version(pins[name]) in req.specifier, f"{name} {pins[name]} does not satisfy {req.specifier}"


def test_the_lock_satisfies_the_launcher_floors():
    src = read_source("windows/launch.py")
    floors = ast.literal_eval(re.search(r"^PY_DEP_FLOORS = (\{.*\})$", src, re.M).group(1))
    assert floors, "PY_DEP_FLOORS not found"
    pins, _ = _lock_pins()
    for name, floor in floors.items():
        have = tuple(int(p) for p in pins[canonicalize_name(name)].split(".")[:3])
        assert have >= tuple(floor), f"{name} {have} is below the launcher floor {floor}"


def test_the_installer_build_installs_only_hashed_binary_wheels():
    sh = read_source("windows/installer/build-folder.sh")
    for cmd in ("pip download", "pip install"):
        line = sh[sh.index(f"python3 -m {cmd}"):]
        line = line[:line.index("\n", line.index("requirements-win-lock.txt"))]
        assert "--require-hashes" in line and '"${PLAT[@]}"' in line, cmd
    assert re.search(r'PLAT=\(--only-binary=:all: --platform win_amd64 --python-version 3\.11 --implementation cp ', sh)


# ── build flow ────────────────────────────────────────────────────────────────

def test_precompiled_bytecode_is_off_unless_asked_for():
    sh = read_source("windows/installer/build-folder.sh")
    assert 'PRECOMPILE="${PRECOMPILE:-0}"' in sh
    assert re.search(r'if \[ "\$PRECOMPILE" = 1 \]; then\n\s+"\$\{HOST_PYTHON311:-python3\.11\}" -I -m compileall', sh)


def _removed_names(sh):
    """Every path a rm or find line of the script names, with {a,b} brace lists expanded."""
    names = []
    for line in sh.splitlines():
        if line.lstrip().startswith(("rm ", "find ")):
            for tok in line.split():
                m = re.search(r"\{([^}]*)\}", tok)
                names += [tok.replace(m.group(0), x) for x in m.group(1).split(",")] if m else [tok]
    return names


def test_pips_launcher_stubs_for_this_python_stay_in_the_bundled_python():
    """Update Plugins replaces packages that declare console scripts; pip needs distlib's stubs for
    this Python (x64, so t64.exe and w64.exe: distlib's _get_launcher picks them by pointer size and
    platform). pip itself and ensurepip stay too."""
    names = _removed_names(read_source("windows/installer/build-folder.sh"))
    assert not any(n.endswith(("t64.exe", "w64.exe")) for n in names), names
    for kept in ('"$SITE/pip"', "ensurepip", 'distlib"', "distlib/*", "distlib/t*", "distlib/w*"):
        assert not any(kept in n for n in names), kept


def test_the_folder_build_drops_the_pe_files_the_app_never_runs():
    """The stubs for other architectures, the venv launchers (nothing here creates a venv, and pip's
    venv build isolation is opt in) and certifi's test module: unsigned PE files and dead code that
    only add antivirus surface. The certifi folder comes from the lock, so it goes after the install."""
    sh = read_source("windows/installer/build-folder.sh")
    removed = " ".join(l for l in sh.splitlines() if l.lstrip().startswith("rm "))
    for name in ("t32", "w32", "t64-arm", "w64-arm"):
        assert name in removed, name
    assert "Lib/venv/scripts/nt/python.exe" in removed and "Lib/venv/scripts/nt/pythonw.exe" in removed
    assert '"$SITE/certifi/tests"' in removed
    assert sh.index('"$SITE/certifi/tests"') > sh.index("python3 -m pip install")


def test_phase_one_builds_the_folder_and_stops_for_both_signatures():
    sh = read_source("windows/BUILD.sh")
    phase1 = sh[sh.index('if [ "$RESUME" -eq 0 ]; then\n    echo "🔨 Compiling launcher EXE'):]
    phase1 = phase1[:phase1.index("\n    exit 0\nfi\n")]
    assert phase1.index("x86_64-w64-mingw32-gcc") < phase1.index('bash "$WIN_DIR/installer/build-folder.sh"')
    assert phase1.index('bash "$WIN_DIR/installer/build-folder.sh"') < phase1.index("STOP — launcher compiled")
    assert "windows/EGM Downloader.exe" in phase1 and "dist/win-unpacked/EGM Downloader.exe" in phase1


def test_continue_verifies_both_exes_and_never_rebuilds_the_signed_folder():
    sh = read_source("windows/BUILD.sh")
    resume = sh[sh.index("# ── Resuming after signing"):]
    phase2 = resume[resume.index("# ── Phase 2"):resume.index("# ── Phase 3")]
    signed = phase2[phase2.index("SIGNED_FILES=("):phase2.index(")", phase2.index("SIGNED_FILES=("))]
    assert '"$WIN_DIR/EGM Downloader.exe"' in signed
    assert '"$REPO_ROOT/dist/win-unpacked/EGM Downloader.exe"' in signed
    assert phase2.index('verify_signed "${SIGNED_FILES[@]}"') < phase2.index("makensis")
    # the check itself: a failed verification exits the build
    fn = resume[resume.index("verify_signed() {"):resume.index("\n}\n", resume.index("verify_signed() {"))]
    assert fn.index("osslsigncode verify") < fn.index("exit 1")
    # after the stop nothing rebuilds or edits the exe: the signed bytes go into the installer
    commands = "\n".join(l for l in resume.splitlines() if not l.lstrip().startswith("#"))
    for tool in ("electron-builder", "build-folder.sh", "exe_strings.js", "rcedit", "resedit"):
        assert tool not in commands, tool
    assert resume.index("osslsigncode verify") < resume.index("makensis")
    assert '-DAPP_FOLDER="$REPO_ROOT/dist/win-unpacked"' in resume


def test_continue_stops_after_makensis_and_finish_packages_the_signed_installer():
    """The third stop: egm-setup.exe is signed between --continue and --finish, so the zip, its
    hash and the feed describe the signed installer. Before this, the zip and the feed were made
    from the unsigned installer and nothing ever checked the signature put on it afterwards."""
    sh = read_source("windows/BUILD.sh")
    assert "--finish" in sh[:sh.index("set -e")], "the third phase is documented in the header"
    resume = sh[sh.index("# ── Resuming after signing"):]
    phase2 = resume[resume.index("# ── Phase 2"):resume.index("# ── Phase 3")]
    phase3 = resume[resume.index("# ── Phase 3"):]
    assert phase2.index("makensis") < phase2.index("STOP — egm-setup.exe built, not yet signed") < phase2.index("exit 0")
    assert "--finish" in phase2[phase2.index("STOP — egm-setup.exe built"):], "the banner names the next command"
    assert "Packaging EGMd.zip" not in phase2 and "gen-update-json.py" not in phase2
    signed = phase3[phase3.index("SIGNED_FILES=("):phase3.index(")", phase3.index("SIGNED_FILES=("))]
    assert '"$REPO_ROOT/dist/egm-setup.exe"' in signed
    assert '"$WIN_DIR/EGM Downloader.exe"' in signed, "the portable zip packs the launcher in this phase"
    assert phase3.index('verify_signed "${SIGNED_FILES[@]}"') < phase3.index("Packaging EGMd.zip")
    assert "makensis" not in phase3
    done = phase3[phase3.index("WINDOWS BUILD DONE!"):]
    assert "sign-manifest.py" in done and "NOT signed" in done, "the final banner says the feeds are unsigned"


def test_the_phase_one_banner_names_continue_and_the_mode_line_knows_all_three_phases():
    sh = read_source("windows/BUILD.sh")
    phase1 = sh[sh.index("STOP — launcher compiled, not yet signed"):sh.index("\n    exit 0\nfi\n")]
    assert "bash windows/BUILD.sh --continue" in phase1
    mode = sh[sh.index('if [ "$FINISH" -eq 1 ]; then\n    echo "   Mode:'):]
    mode = mode[:mode.index("\nfi\n")]
    assert "--finish" in mode and "--continue" in mode and "phase 1" in mode


@pytest.mark.parametrize("args, resume, finish", [("", 0, 0), ("--continue", 1, 0), ("--finish", 1, 1)])
def test_each_flag_selects_its_phase(args, resume, finish):
    """--finish is a resumed mode too: phase 1, which removes the signed files, must not run on it."""
    import subprocess
    sh = read_source("windows/BUILD.sh")
    start = sh.index("RESUME=0\n")
    block = sh[start:sh.index("\ndone\n", start) + 6]
    r = subprocess.run(["bash", "-c", f'set -e\nset -- {args}\n{block}\necho "$RESUME $FINISH"'],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == f"{resume} {finish}", r.stdout + r.stderr


def test_an_unknown_argument_is_refused_before_anything_runs(tmp_path):
    """A mistyped --finish would otherwise start phase 1 and throw the signed files away."""
    import subprocess
    r = subprocess.run(["bash", str(ROOT / "windows" / "BUILD.sh"), "--finsh"], capture_output=True, text=True,
                       cwd=tmp_path, timeout=60)
    assert r.returncode == 1
    assert "Unknown argument" in r.stdout + r.stderr and "--finsh" in r.stdout + r.stderr
    assert "Cleaning" not in r.stdout and "Compiling" not in r.stdout


def test_the_signed_folder_survives_the_clean_step_on_continue():
    sh = read_source("windows/BUILD.sh")
    clean = sh[sh.index("Cleaning old Windows build artifacts"):sh.index("Compile launcher EXE")]
    guarded = re.search(r'if \[ "\$RESUME" -eq 0 \]; then\n(.*?)\nfi', clean, re.S).group(1)
    assert 'rm -rf "$REPO_ROOT/dist/win-unpacked" "$REPO_ROOT/dist/win-unpacked.sha256"' in guarded
    assert len([l for l in clean.splitlines() if 'dist/win-unpacked"' in l]) == 1, "the folder is removed in phase 1 only"


def test_the_electron_zip_is_checked_against_the_locked_electron_package():
    sh = read_source("windows/installer/build-folder.sh")
    i = sh.index('python3 "$SCRIPT_DIR/stage_package.py" --electron-checksum')
    assert sh.index("npm ci") < i < sh.index("npx --no-install electron-builder")
    assert "ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci" in sh and "--ignore-scripts" in sh


def test_the_installer_folder_is_built_from_the_app_files_list():
    sh = read_source("windows/installer/build-folder.sh")
    assert 'done < "$WIN_DIR/app-files.txt"' in sh
    assert 'diff -r "$STAGE/app" "$OUT/resources/app"' in sh


# ── yt-dlp and yt-dlp-ejs stay a pair ─────────────────────────────────────────

def _pair_check_script():
    sh = read_source("windows/installer/build-folder.sh")
    m = re.search(r"^python3 - \"\$SITE\" <<'PYEOF' \|\| exit 1\n(.*?)^PYEOF$", sh, re.S | re.M)
    assert m, "the yt-dlp-ejs pair check is missing from build-folder.sh"
    assert sh.index("pip install") < m.start() < sh.index('if [ "$PRECOMPILE" = 1 ]'), \
        "the pair check must run on the installed packages"
    return m.group(1)


def _site(tmp_path, ytdlp_requires, ejs_version):
    site = tmp_path / "site"
    (site / "yt_dlp-2026.10.26.dist-info").mkdir(parents=True)
    (site / "yt_dlp-2026.10.26.dist-info" / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: yt-dlp\nVersion: 2026.10.26\n" + ytdlp_requires, encoding="utf-8")
    if ejs_version:
        d = site / f"yt_dlp_ejs-{ejs_version}.dist-info"
        d.mkdir()
        (d / "METADATA").write_text(f"Metadata-Version: 2.4\nName: yt-dlp-ejs\nVersion: {ejs_version}\n", encoding="utf-8")
    return site


def _run_pair_check(tmp_path, site):
    import subprocess
    import sys
    script = tmp_path / "pair.py"
    script.write_text(_pair_check_script(), encoding="utf-8")
    return subprocess.run([sys.executable, "-I", str(script), str(site)], capture_output=True, text=True)


NAMES_080 = 'Requires-Dist: yt-dlp-ejs==0.8.0; extra == "default"\nRequires-Dist: yt-dlp-ejs==0.8.0; extra == "pin"\n'


def test_the_folder_build_accepts_the_pair_yt_dlp_names(tmp_path):
    assert _run_pair_check(tmp_path, _site(tmp_path, NAMES_080, "0.8.0")).returncode == 0


def test_the_folder_build_stops_when_the_lock_installs_another_yt_dlp_ejs(tmp_path):
    r = _run_pair_check(tmp_path, _site(tmp_path, NAMES_080, "0.9.0"))
    assert r.returncode != 0 and "0.8.0" in r.stderr and "0.9.0" in r.stderr


def test_the_folder_build_stops_when_the_lock_has_no_yt_dlp_ejs(tmp_path):
    assert _run_pair_check(tmp_path, _site(tmp_path, NAMES_080, None)).returncode != 0


def test_a_yt_dlp_that_names_no_yt_dlp_ejs_does_not_stop_the_build(tmp_path):
    assert _run_pair_check(tmp_path, _site(tmp_path, "Requires-Dist: requests\n", None)).returncode == 0


# ── The folder --continue packages is the one phase 1 built ───────────────────

def _manifest_module():
    spec = importlib.util.spec_from_file_location("egm_folder_manifest", ROOT / "windows/installer/folder_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _built_folder(tmp_path):
    folder = tmp_path / "win-unpacked"
    (folder / "resources" / "app").mkdir(parents=True)
    (folder / "EGM Downloader.exe").write_bytes(b"MZ unsigned")
    (folder / "resources" / "app.asar").write_bytes(b"asar")
    (folder / "resources" / "app" / "app.py").write_text("print()", encoding="utf-8")
    (folder / "ffmpeg.dll").write_bytes(b"dll")
    mod = _manifest_module()
    assert mod.main(["x", "write", str(folder), str(tmp_path / "m.sha256")]) == 0
    return mod, folder, tmp_path / "m.sha256"


def _check(mod, folder, manifest):
    return mod.main(["x", "check", str(folder), str(manifest)])


def test_the_folder_as_built_and_signed_passes(tmp_path):
    mod, folder, manifest = _built_folder(tmp_path)
    assert _check(mod, folder, manifest) == 0
    (folder / "EGM Downloader.exe").write_bytes(b"MZ signed, longer")      # signing changes only the exe
    assert _check(mod, folder, manifest) == 0


@pytest.mark.parametrize("change", ["settings", "pycache", "changed", "missing", "nested_exe"])
def test_any_other_change_after_phase_one_stops_the_build(tmp_path, capsys, change):
    """The likely one: the exe is started from dist/win-unpacked to try it, and the app writes its data
    into the folder it runs from (settings, history, cookies, logs, Python's __pycache__)."""
    mod, folder, manifest = _built_folder(tmp_path)
    if change == "settings":
        (folder / "egm_settings.json").write_text("{}", encoding="utf-8")
    elif change == "pycache":
        (folder / "resources" / "app" / "__pycache__").mkdir()
        (folder / "resources" / "app" / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"pyc")
    elif change == "changed":
        (folder / "resources" / "app.asar").write_bytes(b"other")
    elif change == "missing":
        (folder / "ffmpeg.dll").unlink()
    else:
        (folder / "resources" / "EGM Downloader.exe").write_bytes(b"MZ")   # only the top level exe is exempt
    assert _check(mod, folder, manifest) == 1
    assert "changed after phase 1" in capsys.readouterr().out


def test_no_manifest_stops_the_build(tmp_path):
    mod, folder, manifest = _built_folder(tmp_path)
    manifest.unlink()
    assert _check(mod, folder, manifest) == 1


def test_phase_one_writes_the_manifest_and_continue_checks_it_before_packaging():
    sh = read_source("windows/installer/build-folder.sh")
    write = sh.index('folder_manifest.py" write "$OUT" "$OUT.sha256"')
    assert write > sh.index("exe_strings.js") and write > sh.index('diff -r "$STAGE/app" "$OUT/resources/app"')
    build = read_source("windows/BUILD.sh")
    resume = build[build.index("# ── Resuming after signing"):]
    check = resume.index('folder_manifest.py" check "$REPO_ROOT/dist/win-unpacked" "$REPO_ROOT/dist/win-unpacked.sha256"')
    assert resume.index("osslsigncode verify") < check < resume.index("uninstall_list.py") < resume.index("makensis")


def test_a_link_in_the_folder_stops_the_build(tmp_path):
    """File /r would follow it and package whatever it points at."""
    mod, folder, manifest = _built_folder(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    (folder / "resources" / "link").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(SystemExit):
        _check(mod, folder, manifest)


# ── Electron fuses of the signed exe ──────────────────────────────────────────

def test_the_signed_electron_exe_cannot_be_used_as_a_plain_node():
    """The exe is signed in the publisher's name. With Electron's default fuses, ELECTRON_RUN_AS_NODE=1,
    NODE_OPTIONS or --inspect turn it into a signed host for any script; the app uses none of them.
    OnlyLoadAppFromAsar: resources\\app (the app files) is also the folder Electron falls back to when
    app.asar is missing. electron-builder flips the fuses before signing."""
    fuses = _json("windows/installer/builder-config.json")["electronFuses"]
    assert fuses["runAsNode"] is False
    assert fuses["enableNodeOptionsEnvironmentVariable"] is False
    assert fuses["enableNodeCliInspectArguments"] is False
    assert fuses["onlyLoadAppFromAsar"] is True
    _, _, pkg, _ = _staged()
    assert pkg["build"]["electronFuses"] == fuses, "the staging package must carry them to electron-builder"
    for rel in ("windows/electron/main.js", "windows/electron/preload.js"):
        assert "ELECTRON_RUN_AS_NODE" not in read_source(rel), rel
