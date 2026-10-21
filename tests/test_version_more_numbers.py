"""The app version follows Electron's and can have 3, 4 or 5 numbers
(1.5.0, 1.5.1.3, 1.5.1.3.1). Linux and Mac need a strict X.Y.Z in package.json
(electron-builder), everything else carries the full string."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bump = _load("bump_version", "scripts/bump-version.py")
validate = _load("validate_version_sync", "scripts/validate-version-sync.py")
gen = _load("gen_update_json", "scripts/gen-update-json.py")

CASES = [("1.5.0", "1.5.0"), ("1.5.0.0", "1.5.0"), ("1.5.1.3", "1.5.1"), ("1.5.1.3.1", "1.5.1")]


@pytest.mark.parametrize("full,mapped", CASES)
def test_linux_and_mac_get_the_first_three_numbers(full, mapped):
    assert bump.semver3(full) == mapped
    assert validate.semver3(full) == mapped


@pytest.mark.parametrize("full,mapped", CASES)
def test_validator_accepts_mapped_package_json_and_full_on_windows(tmp_path, monkeypatch, full, mapped):
    monkeypatch.setattr(validate, "ROOT", tmp_path)
    for plat in ("windows", "linux", "mac"):
        (tmp_path / plat / "electron").mkdir(parents=True)

    def put(plat, version, build_version=None):
        data = {"version": version}
        if build_version:
            data["build"] = {"buildVersion": build_version}
        (tmp_path / plat / "electron" / "package.json").write_text(json.dumps(data))

    put("windows", full)
    put("linux", mapped)
    put("mac", mapped, mapped)
    assert validate.check_windows_package_json(full) == []
    assert validate.check_linux_package_json(full) == []
    assert validate.check_mac_package_json(full) == []

    if full != mapped:      # the full string is rejected where electron-builder runs
        put("linux", full)
        put("mac", full, full)
        assert validate.check_linux_package_json(full)
        assert validate.check_mac_package_json(full)
        put("windows", mapped)
        assert validate.check_windows_package_json(full)


def test_bump_writes_the_mapped_value(tmp_path, monkeypatch):
    for plat in ("windows", "linux", "mac"):
        d = tmp_path / plat / "electron"
        d.mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"version": "1.4.3", "build": {"buildVersion": "1.4.3"}}))
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    bump.update_windows_package_json("1.5.1.3.1", False)
    bump.update_linux_package_json("1.5.1.3.1", False)
    bump.update_mac_package_json("1.5.1.3.1", False)
    read = lambda p: json.loads((tmp_path / p / "electron" / "package.json").read_text())
    assert read("windows")["version"] == "1.5.1.3.1"
    assert read("linux")["version"] == "1.5.1"
    assert read("mac")["version"] == "1.5.1" and read("mac")["build"]["buildVersion"] == "1.5.1"


NOTES = """v1.5.1.3.1 - Five (10/22/2026 9:00 AM EST)
-----------------------------------------

  • [ALL] five number note

v1.5.1.3 - Four (10/21/2026 9:00 AM EST)
-----------------------------------------

  • [ALL] four number note
  • [MAC] four number mac note

v1.5.0 - Three (10/20/2026 9:00 AM EST)
-----------------------------------------

  • [ALL] three number note
"""


def test_feed_notes_follow_a_four_or_five_number_header(tmp_path, monkeypatch):
    p = tmp_path / "patchnotes.txt"
    monkeypatch.setattr(gen, "PATCHNOTES", p)
    p.write_text(NOTES, encoding="utf-8")
    assert gen.gen_notes("win") == ["five number note"]
    assert [b["version"] for b in gen.parse_history("windows")] == ["1.5.1.3.1", "1.5.1.3", "1.5.0"]
    p.write_text(NOTES.split("v1.5.1.3.1")[0] + NOTES[NOTES.index("v1.5.1.3 -"):], encoding="utf-8")
    assert gen.gen_notes("win") == ["four number note"]
    assert gen.gen_notes("mac") == ["four number note", "four number mac note"]


def test_update_check_offers_the_update_for_a_four_number_feed(app_module, monkeypatch):
    """The 1.4.x style rule: up to date only when the version string is equal and the
    feed's build is not higher. Any version shape works as long as the build rises."""
    import io
    app = app_module

    def serve(version, build):
        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        monkeypatch.setattr(app, "_safe_urlopen",
                            lambda req, t: R(json.dumps({"version": version, "build": build}).encode()))
        monkeypatch.setattr(app, "_verify_manifest", lambda d: True)
        monkeypatch.setattr(app, "PORTABLE_MODE", False)
        return app.app.test_client().get("/api/check-app-update",
                                         headers={"X-EGM-Token": app._API_TOKEN}).get_json()

    monkeypatch.setattr(app, "APP_VERSION", "1.5.1.2")
    monkeypatch.setattr(app, "APP_BUILD", 170)
    assert serve("1.5.1.3", 171)["up_to_date"] is False       # next Electron patch
    assert serve("1.5.1.2.1", 171)["up_to_date"] is False     # our own patch, five numbers
    assert serve("1.5.1.2", 171)["up_to_date"] is False       # same string, higher build
    assert serve("1.5.1.2", 170)["up_to_date"] is True
