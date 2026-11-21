"""Linux also ships EGMdL.rpm (Fedora, openSUSE and relatives), made by the same electron-builder run
and from the same packed folder as the AppImage and EGMdL.deb, so the three hold the same app. These
tests keep the .rpm settings from drifting, keep the AppImage and .deb settings as they were, and keep
the .rpm version equal to the full app version (rpm, dnf and zypper compare versions, and
linux/electron/package.json carries only the first three numbers)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "linux" / "electron" / "package.json"
BUILD_SH = ROOT / "linux" / "BUILD.sh"

LICENSE_IN_DEB = "../../LICENSE=/usr/share/doc/egm-downloader/copyright"
LICENSE_IN_RPM = "../../LICENSE=/usr/share/licenses/egm-downloader/LICENSE"
DESCRIPTION = ("Free, open source video and audio downloader for 1000+ sites.\n"
               "Multi-platform native desktop apps, built on yt-dlp.\n"
               "No terminal, no account, zero telemetry.")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bump = _load("bump_version_rpm", "scripts/bump-version.py")
validate = _load("validate_version_sync_rpm", "scripts/validate-version-sync.py")


def _pkg():
    return json.loads(PKG.read_text(encoding="utf-8"))


def _app_version():
    return json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]


# ── the target and the build ─────────────────────────────────────────────────

def test_the_rpm_target_is_there_once_and_for_x64_only():
    targets = _pkg()["build"]["linux"]["target"]
    assert [t for t in targets if t["target"] == "rpm"] == [{"target": "rpm", "arch": ["x64"]}]
    assert [t["target"] for t in targets] == ["AppImage", "deb", "rpm"]


def test_the_build_script_makes_the_three_files_in_one_run():
    lines = [l.strip() for l in BUILD_SH.read_text(encoding="utf-8").splitlines()]
    runs = [l for l in lines if "electron-builder" in l and not l.startswith("#")]
    assert len(runs) == 1, runs
    assert re.search(r"--linux AppImage deb rpm --x64 --publish never$", runs[0]), runs


def test_the_build_script_puts_the_rpm_in_dist_beside_the_zip_and_the_deb():
    text = BUILD_SH.read_text(encoding="utf-8")
    lines = text.splitlines()
    copy = next((i for i, l in enumerate(lines) if re.match(r'\s*cp "\$RPM" "\$REPO_ROOT/dist/EGMdL\.rpm"', l)), None)
    assert copy is not None, "linux/BUILD.sh does not copy EGMdL.rpm into dist/"
    assert 'RPM="$ELECTRON_DIR/dist/EGMdL.rpm"' in text
    # a build without the .rpm stops instead of shipping the other two alone
    missing = next((i for i, l in enumerate(lines[:copy]) if 'if [ ! -f "$RPM" ]' in l), None)
    assert missing is not None and "exit 1" in "\n".join(lines[missing:copy])
    # an older .rpm in dist/ goes before the new one is copied
    assert any(re.match(r'\s*rm -f "\$REPO_ROOT/dist/EGMdL\.rpm"', l) for l in lines[:copy])
    # the zip and the .deb are still made
    assert any(re.match(r'\s*zip -r "\$REPO_ROOT/dist/EGMdL\.zip"', l) for l in lines)
    assert any(re.match(r'\s*cp "\$DEB" "\$REPO_ROOT/dist/EGMdL\.deb"', l) for l in lines)


def test_the_build_script_asks_for_rpmbuild_before_it_starts():
    """Without rpmbuild electron-builder fails at the very end, after the AppImage and the .deb are made."""
    lines = BUILD_SH.read_text(encoding="utf-8").splitlines()
    check = next(i for i, l in enumerate(lines) if re.match(r"\s*for cmd in .*; do", l))
    assert "rpmbuild" in lines[check].replace(";", " ").split()
    build = next(i for i, l in enumerate(lines) if "electron-builder" in l and not l.strip().startswith("#"))
    assert check < build
    assert any("rpmbuild)" in l and "sudo apt install rpm" in l for l in lines[check:check + 12])


# ── the package's own data ───────────────────────────────────────────────────

def test_rpm_name_group_summary_and_description():
    pkg = _pkg()
    rpm = pkg["build"]["rpm"]
    # without its own name the .rpm would take linux.artifactName and be called "EGM Downloader.AppImage"
    assert rpm["artifactName"] == "EGMdL.rpm"
    assert rpm["packageCategory"] == "Applications/Internet"
    assert rpm["synopsis"] == "Download videos from 1000+ sites"
    assert rpm["description"] == DESCRIPTION
    # the same words as the .deb
    assert rpm["synopsis"] == pkg["build"]["deb"]["synopsis"]
    assert rpm["description"] == pkg["build"]["deb"]["description"]


def test_rpm_packager_and_url_are_the_public_ones():
    """Packager and Vendor come from linux.maintainer, the URL from homepage; the .rpm sets none of its own."""
    pkg = _pkg()
    assert pkg["build"]["linux"]["maintainer"] == "EGM Downloader <help@egmdownloader.app>"
    assert pkg["homepage"] == "https://egmdownloader.app"
    assert "maintainer" not in pkg["build"]["rpm"] and "vendor" not in pkg["build"]["rpm"]


def test_the_rpm_text_is_plain_ascii():
    """The top description has a dash outside ASCII, and electron-builder turns ' and " into curly quotes."""
    rpm = _pkg()["build"]["rpm"]
    for text in (rpm["description"], rpm["synopsis"], rpm["packageCategory"], rpm["artifactName"], *rpm["fpm"]):
        assert text.isascii(), text
    for text in (rpm["description"], rpm["synopsis"]):
        assert "'" not in text and '"' not in text
    assert all(len(line) < 80 for line in rpm["description"].split("\n"))


def test_the_rpm_license_tag_says_or_later_and_the_package_json_license_stays():
    """README: version 3 or any later version. The .rpm says so in SPDX form; the license field of
    package.json is left alone, because the .deb and the AppImage read it."""
    pkg = _pkg()
    assert [a for a in pkg["build"]["rpm"]["fpm"] if a.startswith("--license")] == ["--license=AGPL-3.0-or-later"]
    assert pkg["license"] == "AGPL-3.0"


def test_the_rpm_carries_the_license_text_where_rpm_distributions_keep_it():
    fpm = _pkg()["build"]["rpm"]["fpm"]
    assert LICENSE_IN_RPM in fpm
    assert [a for a in fpm if "LICENSE=" in a] == [LICENSE_IN_RPM]
    assert (PKG.parent / "../../LICENSE").resolve() == ROOT / "LICENSE"
    assert (ROOT / "LICENSE").is_file()


def test_the_rpm_has_no_build_id_links():
    """rpmbuild adds a link under /usr/lib/.build-id for every binary. Two packages that carry the same
    Electron file then own the same link, and dnf refuses to install the second one."""
    assert "--rpm-rpmbuild-define=_build_id_links none" in _pkg()["build"]["rpm"]["fpm"]


def test_the_rpm_header_names_no_build_machine():
    """rpmbuild writes the build machine's host name into the header, where rpm -qi shows it."""
    assert "--rpm-rpmbuild-define=_buildhost egmdownloader.app" in _pkg()["build"]["rpm"]["fpm"]


def test_the_rpm_owns_its_own_folders_and_no_shared_one():
    """Without its folders in the file list, removing the package left the empty folder tree under
    /opt/EGM Downloader. The folders other packages share are left to their owners."""
    fpm = _pkg()["build"]["rpm"]["fpm"]
    assert "--rpm-auto-add-directories" in fpm
    excluded = [a.split("=", 1)[1] for a in fpm if a.startswith("--rpm-auto-add-exclude-directories=")]
    assert excluded == ["/usr/share/icons/hicolor", "/usr/share/icons/hicolor/512x512",
                        "/usr/share/icons/hicolor/512x512/apps", "/usr/share/licenses"]
    # every folder above the icon and the LICENSE that is not the package's own is in that list
    for path in ("/usr/share/icons/hicolor/512x512/apps/egm-downloader.png", "/usr/share/licenses/egm-downloader/LICENSE"):
        parent = Path(path).parent
        while str(parent) not in ("/usr/share/icons", "/usr/share"):
            assert str(parent) in excluded or parent.name == "egm-downloader", parent
            parent = parent.parent


def test_the_rpm_fpm_list_is_exactly_the_decided_lines():
    assert _pkg()["build"]["rpm"]["fpm"] == [
        f"--version={_app_version()}",
        "--license=AGPL-3.0-or-later",
        "--rpm-rpmbuild-define=_build_id_links none",
        "--rpm-rpmbuild-define=_buildhost egmdownloader.app",
        "--rpm-auto-add-directories",
        "--rpm-auto-add-exclude-directories=/usr/share/icons/hicolor",
        "--rpm-auto-add-exclude-directories=/usr/share/icons/hicolor/512x512",
        "--rpm-auto-add-exclude-directories=/usr/share/icons/hicolor/512x512/apps",
        "--rpm-auto-add-exclude-directories=/usr/share/licenses",
        LICENSE_IN_RPM,
    ]


def test_the_rpm_keeps_electron_builders_dependency_list_and_install_script():
    rpm = _pkg()["build"]["rpm"]
    assert set(rpm) == {"artifactName", "packageCategory", "synopsis", "description", "fpm", "afterRemove"}


# ── the remove script ────────────────────────────────────────────────────────

GUARD = [
    "# rpm runs this script when the package is removed and also when a newer version replaces it.",
    "# In the second case the new version is already installed and its launcher link is in place,",
    "# so only a real removal (rpm passes 0) goes on.",
    'if [ "$1" != "0" ]; then',
    "    exit 0",
    "fi",
    "",
]
# sha256 of templates/linux/after-remove.tpl in app-builder-lib 26.18.0, the script the .deb uses
ELECTRON_BUILDER_AFTER_REMOVE = "c454c4d77e217575bb5eb6c1dc13147c0be9ec193c41242bee8c8747e5d62801"


def _after_remove():
    rpm = _pkg()["build"]["rpm"]
    assert rpm["afterRemove"] == "build/rpm-after-remove.tpl"
    return (PKG.parent / rpm["afterRemove"]).read_text(encoding="utf-8")


def test_the_rpm_remove_script_does_nothing_when_a_newer_version_replaces_the_package():
    """On an upgrade rpm installs the new version first and then runs the old version's remove script.
    electron-builder's script took the launcher link away there, so /usr/bin/egm-downloader was gone
    after every upgrade. rpm passes the number of versions that stay installed: 0 only on a removal."""
    lines = _after_remove().split("\n")
    assert lines[0] == "#!/bin/bash" and lines[1] == ""
    assert lines[2:2 + len(GUARD)] == GUARD
    # the guard comes before the first command that changes anything
    first = next(i for i, l in enumerate(lines) if "update-alternatives" in l and not l.startswith("#"))
    assert first > 2 + len(GUARD) - 1


def test_the_rest_of_the_rpm_remove_script_is_electron_builders_own():
    """Apart from the guard the file is electron-builder's script, byte for byte, so an electron-builder
    update that changes its script shows here (compare, then update the copy and this hash)."""
    import hashlib
    lines = _after_remove().split("\n")
    original = "\n".join(lines[:2] + lines[2 + len(GUARD):])
    assert hashlib.sha256(original.encode("utf-8")).hexdigest() == ELECTRON_BUILDER_AFTER_REMOVE
    installed = PKG.parent / "node_modules" / "app-builder-lib" / "templates" / "linux" / "after-remove.tpl"
    if installed.is_file():      # only on a machine that has run npm install
        assert installed.read_text(encoding="utf-8") == original


def test_the_copy_is_from_the_electron_builder_version_the_build_installs():
    """The comparison above runs only where npm install has run. Here the lock names the version the
    build installs: when it moves, compare its templates/linux/after-remove.tpl with the copy, then
    update the copy, the hash and this version."""
    lock = json.loads((PKG.parent / "package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"]["node_modules/app-builder-lib"]["version"] == "26.18.0"


def test_the_remove_script_is_not_packed_into_the_app():
    files = _pkg()["build"]["files"]
    assert not any("build" in f or "tpl" in f for f in files if not f.startswith("!"))
    assert _pkg()["build"]["directories"]["buildResources"] == "build"


def test_the_deb_keeps_electron_builders_own_scripts():
    deb = _pkg()["build"]["deb"]
    assert "afterRemove" not in deb and "afterInstall" not in deb
    assert "afterInstall" not in _pkg()["build"]["rpm"]


# ── the AppImage and the .deb settings are as they were ──────────────────────

def test_the_deb_settings_are_untouched():
    deb = _pkg()["build"]["deb"]
    assert deb == {
        "artifactName": "EGMdL.deb",
        "packageCategory": "net",
        "synopsis": "Download videos from 1000+ sites",
        "description": DESCRIPTION,
        "fpm": [f"--version={_app_version()}", LICENSE_IN_DEB],
    }


def test_the_appimage_and_shared_settings_are_untouched():
    pkg = _pkg()
    linux = dict(pkg["build"]["linux"])
    linux.pop("target")
    assert linux == {
        "icon": "../../static/icon-512.png",
        "category": "Network",
        "executableName": "egm-downloader",
        "artifactName": "EGM Downloader.AppImage",
        "maintainer": "EGM Downloader <help@egmdownloader.app>",
    }
    assert pkg["version"] == ".".join(_app_version().split(".")[:3])
    assert pkg["description"] == "EGM Downloader — download videos from 1000+ sites"
    assert pkg["license"] == "AGPL-3.0"
    assert pkg["build"]["publish"] is None
    assert pkg["build"]["afterPack"] == "build/after-pack.js"
    assert "appImage" not in pkg["build"]


# ── the .rpm version ─────────────────────────────────────────────────────────

def test_the_rpm_version_is_the_full_app_version():
    fpm = _pkg()["build"]["rpm"]["fpm"]
    assert [a for a in fpm if a.startswith("--version")] == [f"--version={_app_version()}"]
    # the release number is left to electron-builder (1): nothing sets --iteration
    assert not [a for a in fpm if a.startswith("--iteration")]


def _write_linux_pkg(tmp_path, version, deb_fpm, rpm_fpm):
    d = tmp_path / "linux" / "electron"
    d.mkdir(parents=True, exist_ok=True)
    build = {"deb": {"fpm": deb_fpm}}
    if rpm_fpm is not None:
        build["rpm"] = {"fpm": rpm_fpm}
    (d / "package.json").write_text(json.dumps({"version": version, "build": build}))


def _read_linux_pkg(tmp_path):
    return json.loads((tmp_path / "linux" / "electron" / "package.json").read_text())


@pytest.mark.parametrize("full", ["1.5.4.1", "1.5.4.2", "1.6", "1.5.1.3.1"])
def test_validator_wants_the_full_version_in_the_rpm(tmp_path, monkeypatch, full):
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    three = validate.semver3(full)
    deb = [f"--version={full}", LICENSE_IN_DEB]
    _write_linux_pkg(tmp_path, three, deb, [f"--version={full}", "--license=AGPL-3.0-or-later", LICENSE_IN_RPM])
    assert validate.check_linux_package_json(full) == []
    for wrong in ([], ["--version=1.5.3.2"], ["--version=" + full + ".9"], [f"--version={full}", "--version=1.0"]):
        _write_linux_pkg(tmp_path, three, deb, wrong)
        errors = validate.check_linux_package_json(full)
        assert len(errors) == 1 and "build.rpm.fpm" in errors[0], (wrong, errors)
    if three != full:      # the first three numbers alone are not enough: two releases would share them
        _write_linux_pkg(tmp_path, three, deb, [f"--version={three}"])
        assert validate.check_linux_package_json(full)


def test_validator_reports_a_package_json_with_no_rpm_block(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    _write_linux_pkg(tmp_path, "1.5.4", ["--version=1.5.4.1"], None)
    errors = validate.check_linux_package_json("1.5.4.1")
    assert len(errors) == 1 and "build.rpm.fpm" in errors[0], errors


def test_bump_writes_the_full_version_into_the_rpm_and_keeps_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    rest = ["--license=AGPL-3.0-or-later", "--rpm-rpmbuild-define=_build_id_links none", "--rpm-auto-add-directories", LICENSE_IN_RPM]
    _write_linux_pkg(tmp_path, "1.5.4", ["--version=1.5.4.1", LICENSE_IN_DEB], ["--version=1.5.4.1"] + rest)
    bump.update_linux_package_json("1.5.4.2", False)
    data = _read_linux_pkg(tmp_path)
    assert data["version"] == "1.5.4"
    assert data["build"]["rpm"]["fpm"] == ["--version=1.5.4.2"] + rest
    assert data["build"]["deb"]["fpm"] == ["--version=1.5.4.2", LICENSE_IN_DEB]
    assert validate.check_linux_package_json("1.5.4.2") == []
    bump.update_linux_package_json("1.6", False)
    data = _read_linux_pkg(tmp_path)
    assert data["version"] == "1.6" and data["build"]["rpm"]["fpm"] == ["--version=1.6"] + rest


def test_bump_adds_the_version_when_the_rpm_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    _write_linux_pkg(tmp_path, "1.5.4", ["--version=1.5.4.1"], [LICENSE_IN_RPM])
    bump.update_linux_package_json("1.5.4.2", False)
    assert _read_linux_pkg(tmp_path)["build"]["rpm"]["fpm"] == ["--version=1.5.4.2", LICENSE_IN_RPM]


def test_bump_dry_run_leaves_the_rpm_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    _write_linux_pkg(tmp_path, "1.5.4", ["--version=1.5.4.1"], ["--version=1.5.4.1"])
    text = (tmp_path / "linux" / "electron" / "package.json").read_text()
    bump.update_linux_package_json("1.5.4.2", True)
    assert (tmp_path / "linux" / "electron" / "package.json").read_text() == text


def test_the_real_bump_keeps_the_file_as_json_dumps_writes_it():
    """bump-version.py rewrites package.json with json.dumps(indent=2): the committed file must already
    be in that form, or the first bump would reformat lines that have nothing to do with the version."""
    text = PKG.read_text(encoding="utf-8")
    assert json.dumps(json.loads(text), indent=2) + "\n" == text
