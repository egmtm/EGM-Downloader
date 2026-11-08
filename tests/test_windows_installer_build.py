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


def test_pips_launcher_stubs_stay_in_the_bundled_python():
    """Update Plugins replaces packages that declare console scripts; pip needs distlib's stubs."""
    sh = read_source("windows/installer/build-folder.sh")
    removed = " ".join(l for l in sh.splitlines() if l.lstrip().startswith(("rm ", "find ")))
    assert "distlib" not in removed and '"$SITE/pip"' not in removed and "ensurepip" not in removed


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
    signed = resume[resume.index("SIGNED_FILES=("):resume.index(")", resume.index("SIGNED_FILES=("))]
    assert '"$WIN_DIR/EGM Downloader.exe"' in signed
    assert '"$REPO_ROOT/dist/win-unpacked/EGM Downloader.exe"' in signed
    loop = resume[resume.index('for SIGNED in "${SIGNED_FILES[@]}"; do\n        SIGNED_SIZE'):]
    assert loop.index("osslsigncode verify") < loop.index("exit 1") < loop.index("done")
    # after the stop nothing rebuilds or edits the exe: the signed bytes go into the installer
    commands = "\n".join(l for l in resume.splitlines() if not l.lstrip().startswith("#"))
    for tool in ("electron-builder", "build-folder.sh", "exe_strings.js", "rcedit", "resedit"):
        assert tool not in commands, tool
    assert resume.index("osslsigncode verify") < resume.index("makensis")
    assert '-DAPP_FOLDER="$REPO_ROOT/dist/win-unpacked"' in resume


def test_the_signed_folder_survives_the_clean_step_on_continue():
    sh = read_source("windows/BUILD.sh")
    clean = sh[sh.index("Cleaning old Windows build artifacts"):sh.index("Compile launcher EXE")]
    guarded = re.search(r'if \[ "\$RESUME" -eq 0 \]; then\n(.*?)\nfi', clean, re.S).group(1)
    assert 'rm -rf "$REPO_ROOT/dist/win-unpacked"' in guarded
    assert clean.count("dist/win-unpacked") == 1


def test_the_electron_zip_is_checked_against_the_locked_electron_package():
    sh = read_source("windows/installer/build-folder.sh")
    i = sh.index('python3 "$SCRIPT_DIR/stage_package.py" --electron-checksum')
    assert sh.index("npm ci") < i < sh.index("npx --no-install electron-builder")
    assert "ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci" in sh and "--ignore-scripts" in sh


def test_the_installer_folder_is_built_from_the_app_files_list():
    sh = read_source("windows/installer/build-folder.sh")
    assert 'done < "$WIN_DIR/app-files.txt"' in sh
    assert 'diff -r "$STAGE/app" "$OUT/resources/app"' in sh
