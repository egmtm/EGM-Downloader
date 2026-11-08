"""Check for Updates offers yt-dlp again when its solver package does not match it.

Update Plugins installs the yt-dlp-ejs version the installed yt-dlp names, right after a yt-dlp
update. When that pairing failed once (offline, say), nothing showed it: yt-dlp was up to date, so the
Plugins page offered nothing, and yt-dlp kept fetching its solver script from GitHub.

Now /api/check-updates (three backends) also compares the installed yt-dlp-ejs with the version the
installed yt-dlp names, both read locally (no network), and reports yt-dlp as needing an update when they
differ. The page's existing yt-dlp row then shows "Update available" with its switch on, and Update
Plugins reinstalls yt-dlp and pairs the solver. A yt-dlp that names none, or a read that fails, flags
nothing. The network lookups are stand ins here; the reads run a stand in child Python."""
import importlib.util
import types
from pathlib import Path

import pytest

from conftest import ROOT

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_unpaired_" + path.split("/")[0], Path(ROOT) / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend_module(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


@pytest.fixture
def check(backend_module, monkeypatch):
    m = backend_module
    for name, value in (("_get_latest_ytdlp_version", "2026.10.26"), ("_get_ytdlp_version", "2026.10.26"),
                        ("_get_latest_ffmpeg_tag", "n8.1"), ("_get_ffmpeg_version", "n8.1"),
                        ("_get_latest_mutagen_version", "1.47.0"), ("_get_mutagen_version", "1.47.0"),
                        ("_get_latest_optlibs_versions", {}), ("_get_optlibs_versions", {}),
                        ("_get_latest_deno_version", "2.5.0"), ("_get_deno_version", "2.5.0")):
        if hasattr(m, name):
            monkeypatch.setattr(m, name, lambda *a, _v=value, **k: _v)
    state = {"requires": "yt-dlp-ejs==0.8.0; extra == \"default\"\n", "installed": "0.8.0", "fail": set(), "reads": []}

    def child(*cmd, **kw):
        code = cmd[cmd.index("-c") + 1]
        kind = "requires" if "requires(" in code else "installed"
        state["reads"].append(kind)
        if kind in state["fail"]:
            raise OSError("no python")
        if kind == "installed":
            out = state["installed"]
            return types.SimpleNamespace(returncode=0, stdout=(out or "") + "\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout=state["requires"], stderr="")

    monkeypatch.setattr(m, "_run_yt", child)

    def go(**kw):
        state.update(kw)
        state["reads"].clear()
        r = m.app.test_client().get("/api/check-updates", headers={"X-EGM-Token": m._API_TOKEN})
        assert r.status_code == 200
        return r.get_json()["ytdlp"], list(state["reads"])
    return go


def test_a_paired_solver_flags_nothing(check):
    yt, _ = check()
    assert yt["up_to_date"] is True


@pytest.mark.parametrize("installed", ["0.7.1", "0.9.0", ""])
def test_a_solver_that_is_not_the_one_yt_dlp_names_offers_yt_dlp_again(check, installed):
    yt, reads = check(installed=installed)
    assert yt["up_to_date"] is False, f"installed {installed!r}, yt-dlp names 0.8.0"
    assert reads == ["requires", "installed"]


def test_a_yt_dlp_that_names_none_flags_nothing(check):
    yt, reads = check(requires="certifi>=1\n", installed="")
    assert yt["up_to_date"] is True and reads == ["requires"]


@pytest.mark.parametrize("fail", [{"requires"}, {"installed"}])
def test_a_read_that_fails_flags_nothing(check, fail):
    yt, _ = check(fail=fail, installed="0.7.1")
    assert yt["up_to_date"] is True


def test_a_yt_dlp_that_is_behind_is_still_flagged(check, backend_module, monkeypatch):
    monkeypatch.setattr(backend_module, "_get_ytdlp_version", lambda *a, **k: "2026.10.01")
    yt, _ = check()
    assert yt["up_to_date"] is False
