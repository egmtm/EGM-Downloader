"""
The startup update check must never offer an older release.

Every past signed feed is public and verifies forever, so a feed served again by whoever
controls the host is genuinely signed. /api/check-app-update used to say "up to date" only
when the version string was equal, so any other version, older included, read as an update
(and on Windows the startup check then downloaded it). It now decides by build number alone:
builds rise with every release (the release gate enforces it), so a feed with a lower build is
never an update, and a rebuild of the same version (higher build) still is.

All three backends are driven through their real route with a fake feed. Nothing is fetched.
"""
import io
import json
from pathlib import Path

import importlib.util
import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


@pytest.fixture(scope="module", params=APP_FILES)
def app(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    # Linux and Mac create their data folders at import: point them at a temporary home.
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_update_check_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _check(app, monkeypatch, current, feed):
    monkeypatch.setattr(app, "APP_VERSION", current[0])
    monkeypatch.setattr(app, "APP_BUILD", current[1])
    monkeypatch.setattr(app, "PORTABLE_MODE", False, raising=False)
    monkeypatch.setattr(app, "_verify_manifest", lambda d: True)
    monkeypatch.setattr(app, "_safe_urlopen", lambda req, t: _Resp(json.dumps(feed).encode()))
    return app.app.test_client().get("/api/check-app-update",
                                     headers={"X-EGM-Token": app._API_TOKEN}).get_json()


OFFERED = [
    (("1.5.0", 169), {"version": "1.5.0.0.1", "build": 170}),        # our own patch, five numbers
    (("1.5.0.0.1", 170), {"version": "1.5.0.1", "build": 171}),      # next Electron point release
    (("1.5.0.0.1", 170), {"version": "1.5.0.0.1", "build": 171}),    # a rebuild of the same version
    (("1.4.14", 168), {"version": "1.5.0", "build": 169}),
]

NOT_OFFERED = [
    (("1.5.0.0.1", 170), {"version": "1.5.0.0.1", "build": 170}),    # equal
    (("1.5.0.0.1", 170), {"version": "1.5.0", "build": 169}),        # an older signed feed again
    (("1.5.0.0.1", 170), {"version": "1.4.14", "build": 168}),       # and a much older one
    (("1.5.0.0.1", 170), {"version": "9.9.9", "build": 170}),        # other version string, build not higher
    (("1.5.0.0.1", 170), {"version": "1.5.0.1"}),                    # no build: reads as 0
]


@pytest.mark.parametrize("current, feed", OFFERED)
def test_a_higher_build_is_offered(app, monkeypatch, current, feed):
    assert _check(app, monkeypatch, current, feed)["up_to_date"] is False


@pytest.mark.parametrize("current, feed", NOT_OFFERED)
def test_an_equal_or_lower_build_is_never_offered(app, monkeypatch, current, feed):
    assert _check(app, monkeypatch, current, feed)["up_to_date"] is True


def test_a_junk_build_is_an_error_and_not_an_update(app, monkeypatch):
    d = _check(app, monkeypatch, ("1.5.0.0.1", 170), {"version": "1.5.0.1", "build": "abc"})
    assert "error" in d and d.get("up_to_date") is not False   # the startup check returns on an error


def test_all_three_backends_use_the_same_rule():
    for rel in APP_FILES:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "up_to_date   = latest_build <= APP_BUILD" in src, f"{rel} lost the build number rule"
        assert "latest_ver == APP_VERSION and latest_build" not in src, f"{rel} has the old rule again"


@pytest.mark.parametrize("build, offered", [("171", True), (170.9, False), (True, False), (-5, False)])
def test_other_build_shapes_are_read_as_whole_numbers(app, monkeypatch, build, offered):
    """A build written as a string still counts (int() reads it); a float is truncated, a bool
    is 0/1 and a negative number is below ours: none of them is an update by accident."""
    r = _check(app, monkeypatch, ("1.5.0.0.1", 170), {"version": "1.5.0.1", "build": build})
    assert r.get("error") is None and r["up_to_date"] is (not offered)
