"""
Staging package.json and package-lock.json for the Windows installer build (electron-builder).

windows/electron/package.json and its package-lock.json stay the source of the Windows Electron pin.
The portable edition installs Electron from them with `npm ci --omit=dev`, which needs electron under
"dependencies". electron-builder refuses that, and refuses a four part version, so the installer
build writes a staging copy instead of changing those files:
  * electron moves to devDependencies and every locked package is marked dev. Nothing is resolved
    again: versions, resolved URLs and integrity hashes are copied as they are;
  * version is the first three numbers; the exe's version strings carry the full version
    (shortVersionWindows: ProductVersion) and the version with the build number (shortVersion:
    FileVersion);
  * author is the exe's CompanyName.
The result must equal the Mac and Linux locks package for package (they pin the same Electron chain);
anything else stops the build.

usage:
  stage_package.py <repo> <stage_electron_dir>               write package.json and package-lock.json
  stage_package.py --electron-checksum <stage_electron_dir>  after npm ci: pin the Electron zip's
                                                              SHA-256 from the locked electron package
"""
import copy
import json
import re
import sys
from pathlib import Path

COMPANY = "egerena.com"          # exe CompanyName (the publisher in windows/setup.nsi)
ARTIFACT = "electron-v{version}-win32-x64.zip"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stage_package(win_pkg, win_lock, build_config, version, build):
    """Return (package, lock) for the staging folder. version is the four part app version,
    build the build number; win_pkg/win_lock are windows/electron's files, unchanged."""
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
        raise ValueError(f"expected a four part version, got {version!r}")
    if win_pkg.get("version") != version:
        raise ValueError(f"windows/electron/package.json is {win_pkg.get('version')}, version.json {version}")
    ver3 = ".".join(version.split(".")[:3])
    dev = {**win_pkg.get("dependencies", {}), **win_pkg.get("devDependencies", {})}
    if set(dev) != {"electron", "electron-builder"}:
        raise ValueError(f"unexpected Windows dependencies: {sorted(dev)}")
    dev = dict(sorted(dev.items()))

    pkg = {k: win_pkg[k] for k in ("name", "description", "main", "license")}
    pkg.update(version=ver3, author=COMPANY, shortVersion=f"{version}.{build}",
               shortVersionWindows=version, devDependencies=dev, build=copy.deepcopy(build_config))

    lock = copy.deepcopy(win_lock)
    lock["version"] = ver3
    root = lock["packages"][""]
    root["version"] = ver3
    root.pop("dependencies", None)
    root["devDependencies"] = dev
    for key, entry in lock["packages"].items():
        if key:
            entry["dev"] = True
    return pkg, lock


def lock_differences(lock, other):
    """Package keys whose entries differ between two locks, the root entry left out."""
    a = {k: v for k, v in lock["packages"].items() if k}
    b = {k: v for k, v in other["packages"].items() if k}
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def write_stage(repo, stage):
    repo, stage = Path(repo), Path(stage)
    ver = _read(repo / "version.json")
    pkg, lock = stage_package(_read(repo / "windows/electron/package.json"),
                              _read(repo / "windows/electron/package-lock.json"),
                              _read(repo / "windows/installer/builder-config.json"),
                              ver["version"], ver["build"])
    for plat in ("mac", "linux"):
        diff = lock_differences(lock, _read(repo / plat / "electron/package-lock.json"))
        if diff:
            raise SystemExit(f"the staging lock differs from {plat}'s in {len(diff)} package(s): {diff[:5]}")
    stage.mkdir(parents=True, exist_ok=True)
    for name, data in (("package.json", pkg), ("package-lock.json", lock)):
        (stage / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    e = lock["packages"]["node_modules/electron"]
    print(f"   ✓ staging package {pkg['version']} (exe {pkg['shortVersion']}), "
          f"{len(lock['packages']) - 1} locked packages equal to Mac and Linux; electron {e['version']}")


def pin_electron_checksum(stage):
    """Hand electron-builder the SHA-256 of the Electron Windows zip from checksums.json of the
    electron package npm ci installed (checked by npm against the lock's integrity hash), so the
    download is verified against the lockfile chain."""
    stage = Path(stage)
    pkg = _read(stage / "package.json")
    electron = _read(stage / "node_modules/electron/package.json")
    sums = _read(stage / "node_modules/electron/checksums.json")
    name = ARTIFACT.format(version=electron["version"])
    if electron["version"] != pkg["devDependencies"]["electron"] or not re.fullmatch(r"[0-9a-f]{64}", sums.get(name, "")):
        raise SystemExit(f"no checksum for {name} in the installed electron package")
    pkg["build"]["electronDownload"] = {"checksums": {name: sums[name]}}
    (stage / "package.json").write_text(json.dumps(pkg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"   ✓ {name} must have SHA-256 {sums[name]}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--electron-checksum":
        pin_electron_checksum(sys.argv[2])
    elif len(sys.argv) == 3:
        write_stage(sys.argv[1], sys.argv[2])
    else:
        raise SystemExit(__doc__)
