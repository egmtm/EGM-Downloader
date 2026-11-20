"""Linux ships two files from one build: the AppImage (inside EGMdL.zip) and EGMdL.deb. Both are made by
one electron-builder run from the same packed folder, so they hold the same app. These tests keep the
.deb settings from drifting, keep the AppImage settings as they were, and keep the .deb version equal to
the full app version (dpkg and apt compare versions, and linux/electron/package.json carries only the
first three numbers)."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "linux" / "electron" / "package.json"
BUILD_SH = ROOT / "linux" / "BUILD.sh"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bump = _load("bump_version_deb", "scripts/bump-version.py")
validate = _load("validate_version_sync_deb", "scripts/validate-version-sync.py")


def _pkg():
    return json.loads(PKG.read_text(encoding="utf-8"))


def _app_version():
    return json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]


# ── the two targets ──────────────────────────────────────────────────────────

def test_linux_builds_the_appimage_and_the_deb_for_x64_only():
    targets = _pkg()["build"]["linux"]["target"]
    assert targets == [{"target": "AppImage", "arch": ["x64"]}, {"target": "deb", "arch": ["x64"]}]


def test_the_build_script_makes_both_files_in_one_electron_builder_run():
    lines = [l.strip() for l in BUILD_SH.read_text(encoding="utf-8").splitlines()]
    runs = [l for l in lines if "electron-builder" in l and not l.startswith("#")]
    assert runs == ["node ./node_modules/.bin/electron-builder --linux AppImage deb --x64 --publish never"], runs


def test_the_build_script_puts_the_zip_and_the_deb_in_dist():
    text = BUILD_SH.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert any(re.match(r'\s*zip -r "\$REPO_ROOT/dist/EGMdL\.zip"', l) for l in lines)
    copy = next((i for i, l in enumerate(lines) if re.match(r'\s*cp "\$DEB" "\$REPO_ROOT/dist/EGMdL\.deb"', l)), None)
    assert copy is not None, "linux/BUILD.sh does not copy EGMdL.deb into dist/"
    assert 'DEB="$ELECTRON_DIR/dist/EGMdL.deb"' in text
    # a build without the .deb stops instead of shipping the zip alone
    missing = next((i for i, l in enumerate(lines[:copy]) if 'if [ ! -f "$DEB" ]' in l), None)
    assert missing is not None and "exit 1" in "\n".join(lines[missing:copy])
    # an older .deb in dist/ goes before the new one is copied
    assert any(re.match(r'\s*rm -f "\$REPO_ROOT/dist/EGMdL\.deb"', l) for l in lines[:copy])


# ── the package's own data ───────────────────────────────────────────────────

def test_maintainer_and_homepage_are_the_public_ones():
    pkg = _pkg()
    assert pkg["build"]["linux"]["maintainer"] == "EGM Downloader <help@egmdownloader.app>"
    assert pkg["homepage"] == "https://egmdownloader.app"


def test_deb_name_section_and_short_description():
    deb = _pkg()["build"]["deb"]
    # without its own name the .deb would take linux.artifactName and be called "EGM Downloader.AppImage"
    assert deb["artifactName"] == "EGMdL.deb"
    assert deb["packageCategory"] == "net"
    assert deb["synopsis"] == "download videos from 1000+ sites"
    assert _pkg()["license"] == "AGPL-3.0"


def test_the_deb_carries_the_license_text():
    """The AppImage's LICENSE travels beside it in EGMdL.zip. The .deb ships bare, so the file goes inside."""
    fpm = _pkg()["build"]["deb"]["fpm"]
    assert "../../LICENSE=/usr/share/doc/egm-downloader/copyright" in fpm
    assert (PKG.parent / "../../LICENSE").resolve() == ROOT / "LICENSE"
    assert (ROOT / "LICENSE").is_file()


def test_the_deb_keeps_electron_builders_dependency_list():
    """No depends or recommends of our own: the list electron-builder writes is the one that was
    installed and launched on Debian and Ubuntu."""
    deb = _pkg()["build"]["deb"]
    assert "depends" not in deb and "recommends" not in deb


def test_electron_builder_never_assumes_a_publish_target():
    """With GH_TOKEN or GITHUB_TOKEN set, electron-builder assumed a GitHub publish target and stopped
    while preparing update data for the AppImage. An explicit null publish setting switches that off.
    The app has no updater of its own in the shell, and the built files are the same with it."""
    build = _pkg()["build"]
    assert "publish" in build
    assert build["publish"] is None


# ── the AppImage settings are as they were ───────────────────────────────────

def test_the_appimage_settings_are_untouched():
    pkg = _pkg()
    linux = pkg["build"]["linux"]
    assert linux["artifactName"] == "EGM Downloader.AppImage"
    assert linux["executableName"] == "egm-downloader"
    assert linux["category"] == "Network"
    assert linux["icon"] == "../../static/icon-512.png"
    assert pkg["build"]["afterPack"] == "build/after-pack.js"
    assert pkg["build"]["extraFiles"] == [
        {"from": "../../static/icon-512.png", "to": "usr/share/icons/hicolor/512x512/apps/egm-downloader.png"},
        {"from": "../../THIRD_PARTY_NOTICES.txt", "to": "THIRD_PARTY_NOTICES.txt"},
    ]
    assert pkg["name"] == "egm-downloader" and pkg["build"]["productName"] == "EGM Downloader"
    assert set(linux) == {"target", "icon", "category", "executableName", "artifactName", "maintainer"}


# ── the .deb version ─────────────────────────────────────────────────────────

def test_the_deb_version_is_the_full_app_version():
    fpm = _pkg()["build"]["deb"]["fpm"]
    assert [a for a in fpm if a.startswith("--version")] == [f"--version={_app_version()}"]


def _write_linux_pkg(tmp_path, version, fpm):
    d = tmp_path / "linux" / "electron"
    d.mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(json.dumps({"version": version, "build": {"deb": {"fpm": fpm}}}))


@pytest.mark.parametrize("full", ["1.5.4.1", "1.5.4.2", "1.6", "1.5.1.3.1"])
def test_validator_wants_the_full_version_in_the_deb(tmp_path, monkeypatch, full):
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    three = validate.semver3(full)
    _write_linux_pkg(tmp_path, three, [f"--version={full}", "../../LICENSE=/usr/share/doc/egm-downloader/copyright"])
    assert validate.check_linux_package_json(full) == []
    for wrong in ([], ["--version=1.5.3.2"], ["--version=" + full + ".9"], [f"--version={full}", "--version=1.0"]):
        _write_linux_pkg(tmp_path, three, wrong)
        assert validate.check_linux_package_json(full), wrong
    if three != full:      # the first three numbers alone are not enough: two releases would share them
        _write_linux_pkg(tmp_path, three, [f"--version={three}"])
        assert validate.check_linux_package_json(full)


def test_validator_reports_a_package_json_with_no_deb_block(tmp_path, monkeypatch):
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    d = tmp_path / "linux" / "electron"
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"version": "1.5.4", "build": {"linux": {}}}))
    assert validate.check_linux_package_json("1.5.4.1")


def test_bump_writes_the_full_version_into_the_deb_and_keeps_the_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    before = ["--version=1.5.4.1", "../../LICENSE=/usr/share/doc/egm-downloader/copyright"]
    _write_linux_pkg(tmp_path, "1.5.4", before)
    bump.update_linux_package_json("1.5.4.2", False)
    data = json.loads((tmp_path / "linux" / "electron" / "package.json").read_text())
    assert data["version"] == "1.5.4"
    assert data["build"]["deb"]["fpm"] == ["--version=1.5.4.2", "../../LICENSE=/usr/share/doc/egm-downloader/copyright"]
    assert validate.check_linux_package_json("1.5.4.2") == []
    bump.update_linux_package_json("1.6", False)
    data = json.loads((tmp_path / "linux" / "electron" / "package.json").read_text())
    assert data["version"] == "1.6" and data["build"]["deb"]["fpm"][0] == "--version=1.6"
    assert len(data["build"]["deb"]["fpm"]) == 2


def test_bump_adds_the_version_when_the_deb_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    _write_linux_pkg(tmp_path, "1.5.4", ["../../LICENSE=/usr/share/doc/egm-downloader/copyright"])
    bump.update_linux_package_json("1.5.4.2", False)
    data = json.loads((tmp_path / "linux" / "electron" / "package.json").read_text())
    assert data["build"]["deb"]["fpm"] == ["--version=1.5.4.2", "../../LICENSE=/usr/share/doc/egm-downloader/copyright"]


def test_bump_dry_run_leaves_the_file_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    _write_linux_pkg(tmp_path, "1.5.4", ["--version=1.5.4.1"])
    text = (tmp_path / "linux" / "electron" / "package.json").read_text()
    bump.update_linux_package_json("1.5.4.2", True)
    assert (tmp_path / "linux" / "electron" / "package.json").read_text() == text


def test_the_deb_text_is_plain_ascii_and_the_appimage_keeps_its_description():
    # apt hands PackageKit the long description converted to the daemon's character set, and with no
    # UTF-8 locale every character outside ASCII comes out as "?", so App Center showed the dash as "??".
    # electron-builder also turns ' and " into curly quotes. The AppImage reads the top description.
    pkg = _pkg()
    deb = pkg["build"]["deb"]
    for text in (deb["description"], deb["synopsis"]):
        assert text.isascii() and "'" not in text and '"' not in text
    assert "description" not in pkg["build"]["linux"]
    assert "description" not in pkg["build"].get("appImage", {})
    assert pkg["description"] == "EGM Downloader — download videos from 1000+ sites"
