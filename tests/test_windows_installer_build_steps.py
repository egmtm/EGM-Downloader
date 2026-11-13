"""
The steps of the Windows installer folder build that run only on a release machine, checked here
without downloading anything:

* stage_package.py: the Electron zip checksum is taken from the electron package npm installed and
  handed to electron-builder under electronDownload.checksums; a version that is not the pinned one,
  or a staging lock that differs from the Mac or Linux lock, stops the build.
* exe_strings.js (run against a stand-in for the PE library): it sets OriginalFilename, accepts the
  version strings electron-builder writes from the staging package, and fails the build on any other.
* build-folder.sh stops on the first failed step, checks the Python archive against the pin and the
  release's own SHA256SUMS, and sets the exe's version strings after electron-builder.
* builder-config.json puts the app and the Python where the packaged shell looks for them.
* windows/BUILD.sh writes the uninstaller's list from the signed folder right before makensis.
"""
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


def _stage_module():
    spec = importlib.util.spec_from_file_location("egm_stage_package_steps", ROOT / "windows/installer/stage_package.py")
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


# ── Electron zip checksum ─────────────────────────────────────────────────────

def _stage_dir(tmp_path, electron_version=None, checksum="a" * 64):
    mod, _, pkg, _ = _staged()
    stage = tmp_path / "electron"
    (stage / "node_modules" / "electron").mkdir(parents=True)
    (stage / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    version = electron_version or pkg["devDependencies"]["electron"]
    (stage / "node_modules/electron/package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    name = mod.ARTIFACT.format(version=version)
    sums = {name: checksum, f"electron-v{version}-linux-x64.zip": "b" * 64}
    (stage / "node_modules/electron/checksums.json").write_text(json.dumps(sums), encoding="utf-8")
    return mod, stage, name


def test_the_electron_zip_checksum_is_handed_to_electron_builder(tmp_path):
    mod, stage, name = _stage_dir(tmp_path)
    mod.pin_electron_checksum(stage)
    pkg = json.loads((stage / "package.json").read_text(encoding="utf-8"))
    assert pkg["build"]["electronDownload"] == {"checksums": {name: "a" * 64}}
    assert name.endswith("-win32-x64.zip")


@pytest.mark.parametrize("electron_version, checksum", [("1.0.0", "a" * 64), (None, ""), (None, "not-a-sha256")])
def test_an_electron_package_that_is_not_the_pinned_one_stops_the_build(tmp_path, electron_version, checksum):
    mod, stage, _ = _stage_dir(tmp_path, electron_version, checksum)
    with pytest.raises(SystemExit):
        mod.pin_electron_checksum(stage)


def test_a_staging_lock_that_differs_from_the_mac_lock_stops_the_build(tmp_path):
    mod = _stage_module()
    for rel in ("version.json", "windows/electron/package.json", "windows/electron/package-lock.json",
                "windows/installer/builder-config.json", "mac/electron/package-lock.json",
                "linux/electron/package-lock.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    mod.write_stage(tmp_path, tmp_path / "stage-ok")          # the repo as it is passes
    mac = tmp_path / "mac/electron/package-lock.json"
    lock = json.loads(mac.read_text(encoding="utf-8"))
    lock["packages"]["node_modules/electron"]["integrity"] = "sha512-other"
    mac.write_text(json.dumps(lock), encoding="utf-8")
    with pytest.raises(SystemExit, match="mac"):
        mod.write_stage(tmp_path, tmp_path / "stage-bad")
    assert not (tmp_path / "stage-bad").exists()


# ── exe version strings ───────────────────────────────────────────────────────

# A stand-in for the PE library: the "exe" is JSON holding its version strings and fixed versions.
FAKE_RESEDIT = r"""
'use strict';
const lang = { lang: 1033, codepage: 1200 };
class VersionInfo {
  constructor(entries) { this.entries = entries; this.fixedInfo = entries.fixed; this.strings = { ...entries.strings }; }
  static fromEntries(entries) { return [new VersionInfo(entries)]; }
  getAllLanguagesForStringValues() { return [lang]; }
  setStringValues(l, values) { Object.assign(this.strings, values); }
  getStringValues() { return { ...this.entries.strings }; }
  outputToResourceEntries(entries) { entries.strings = { ...this.strings }; }
}
module.exports = {
  NtExecutable: { from: (buf) => ({ data: JSON.parse(Buffer.from(buf).toString('utf8')),
                                    generate() { return Buffer.from(JSON.stringify(this.data)); } }) },
  NtExecutableResource: { from: (pe) => ({ entries: pe.data, outputResource() {} }) },
  Resource: { VersionInfo },
};
"""


def _fixed(version):
    a, b, c, d = (int(x) for x in version.split("."))
    return (a << 16) | b, (c << 16) | d


def _exe_as_electron_builder_writes_it(pkg, config, version):
    ms, ls = _fixed(version)
    return {
        "strings": {"CompanyName": pkg["author"], "FileDescription": config["productName"],
                    "ProductName": config["productName"], "InternalName": config["productName"],
                    "OriginalFilename": "", "FileVersion": pkg["shortVersion"],
                    "ProductVersion": pkg["shortVersionWindows"]},
        "fixed": {"fileVersionMS": ms, "fileVersionLS": ls, "productVersionMS": ms, "productVersionLS": ls},
    }


def _exe_strings(tmp_path, exe_data, version, build):
    stage = tmp_path / "stage"
    (stage / "node_modules" / "resedit").mkdir(parents=True)
    (stage / "node_modules/resedit/index.js").write_text(FAKE_RESEDIT, encoding="utf-8")
    exe = tmp_path / "EGM Downloader.exe"
    exe.write_text(json.dumps(exe_data), encoding="utf-8")
    r = subprocess.run([NODE, str(ROOT / "windows/installer/exe_strings.js"), str(stage), str(exe), version, str(build)],
                       capture_output=True, text=True, timeout=60)
    return r, json.loads(exe.read_text(encoding="utf-8"))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_exe_strings_sets_the_original_filename_and_accepts_what_electron_builder_wrote(tmp_path):
    _, ver, pkg, _ = _staged()
    config = _json("windows/installer/builder-config.json")
    r, after = _exe_strings(tmp_path, _exe_as_electron_builder_writes_it(pkg, config, ver["version"]),
                            ver["version"], ver["build"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert after["strings"]["OriginalFilename"] == f"{config['executableName']}.exe"
    assert after["strings"]["FileVersion"] == f"{ver['version']}.{ver['build']}"


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("field, value", [("CompanyName", "someone else"), ("ProductVersion", "0.0.0.1"),
                                          ("FileVersion", "0.0.0.1.1")])
def test_exe_strings_fails_the_build_on_a_wrong_version_string(tmp_path, field, value):
    _, ver, pkg, _ = _staged()
    data = _exe_as_electron_builder_writes_it(pkg, _json("windows/installer/builder-config.json"), ver["version"])
    data["strings"][field] = value
    r, _ = _exe_strings(tmp_path, data, ver["version"], ver["build"])
    assert r.returncode == 1, r.stdout + r.stderr


# ── build-folder.sh ───────────────────────────────────────────────────────────

def _commands(sh):
    return [l for l in sh.splitlines() if l.strip() and not l.lstrip().startswith("#")]


def test_the_folder_build_stops_on_the_first_failed_step():
    sh = read_source("windows/installer/build-folder.sh")
    first = _commands(sh)[0:3]
    assert "set -e" in [l.strip() for l in _commands(sh)][:3], first
    assert not re.search(r"\|\|\s*true\b", sh), "a step whose failure is ignored"


def test_the_python_archive_is_checked_against_the_pin_and_the_release_sums():
    sh = read_source("windows/installer/build-folder.sh")
    check = next(l for l in sh.splitlines() if '"$PYTHON_SHA256  python.tar.gz"' in l)
    assert "-c -" in check and check.rstrip().endswith("exit 1; }"), check
    sums = next(l for l in sh.splitlines() if "SHA256SUMS" in l and "grep" in l)
    assert '"$PYTHON_SHA256  ${PYTHON_URL##*/}"' in sums and sums.rstrip().endswith("exit 1; }"), sums
    assert sh.index(check) < sh.index(sums) < sh.index("tar -xzf python.tar.gz")


def test_the_exe_version_strings_are_set_after_electron_builder():
    sh = read_source("windows/installer/build-folder.sh")
    cmds = "\n".join(_commands(sh))
    i = cmds.index('node "$SCRIPT_DIR/exe_strings.js" "$STAGE/electron" "$OUT/EGM Downloader.exe" "$VERSION" "$BUILD_NUM"')
    assert cmds.index("npx --no-install electron-builder") < cmds.index('mv "$STAGE/electron/out/win-unpacked" "$OUT"') < i


# ── builder-config.json and the packaged shell ────────────────────────────────

def test_the_folder_layout_is_the_one_the_packaged_shell_looks_for():
    config = _json("windows/installer/builder-config.json")
    main = read_source("windows/electron/main.js")
    assert config["asar"] is True
    assert "path.basename(__dirname).toLowerCase() === 'app.asar'" in main, "the shell finds its layout by app.asar"
    to = {r["from"]: r["to"] for r in config["extraResources"]}
    assert to == {"../app": "app", "../python": "python"}, to
    assert "path.join(process.resourcesPath, 'app')" in main
    assert "path.join(process.resourcesPath, 'python', 'python.exe')" in main
    assert set(config["files"]) >= {"main.js", "preload.js", "splash.html"}


# ── BUILD.sh ──────────────────────────────────────────────────────────────────

def test_the_uninstall_list_is_written_from_the_signed_folder_right_before_makensis():
    sh = read_source("windows/BUILD.sh")
    resume = sh[sh.index("# ── Resuming after signing"):]
    cmds = "\n".join(_commands(resume))
    gen = cmds.index('python3 "$WIN_DIR/installer/uninstall_list.py" "$REPO_ROOT/dist/win-unpacked" "$REPO_ROOT/dist/win-unpacked-files.nsh"')
    assert cmds.index("osslsigncode verify") < gen < cmds.index("makensis")
    assert '-DAPP_FOLDER_LIST="$REPO_ROOT/dist/win-unpacked-files.nsh"' in resume
