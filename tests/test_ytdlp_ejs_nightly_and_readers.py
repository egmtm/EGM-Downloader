"""yt-dlp and its solver package stay a pair on the nightly channel too, and the three backends read
the pin alike.

test_ytdlp_ejs_local.py drives Update Plugins on the stable channel only, and checks each backend's
_ytdlp_ejs_pin on its own list of lines. So:

* a nightly yt-dlp names its yt-dlp-ejs version the same way; Update Plugins must install it after a
  nightly update as after a stable one, or the person who chose nightly gets the script from GitHub;
* the Windows launcher and the Mac and Linux builds are each compared with app.py's reading; the Mac
  and Linux backends were not, so one copy of the regex could drift (an anchor dropped, say) unseen.

Nothing is installed or downloaded: pip, the nightly download and the metadata read are fakes.
"""
import importlib.util
import io
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
        spec = importlib.util.spec_from_file_location("egm_ejs_nightly_" + path.split("/")[0], Path(ROOT) / path)
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


class _Download(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def nightly(backend_module, tmp_path, monkeypatch):
    m = backend_module
    calls = []

    def fake_run(*cmd, **kw):
        calls.append([str(c) for c in cmd])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(m, "_run", fake_run)
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_get_ytdlp_version", lambda *a, **k: "2026.11.05.232701")
    monkeypatch.setattr(m, "_load_settings", lambda *a, **k: {"yt_dlp_channel": "nightly"})
    monkeypatch.setattr(m, "_ytdlp_ejs_pin", lambda: "0.8.1")
    monkeypatch.setattr(m, "_safe_urlopen", lambda req, timeout: _Download(b"not a real archive"))
    if hasattr(m, "DATA_DIR"):
        monkeypatch.setattr(m, "DATA_DIR", tmp_path)
    if hasattr(m, "PACKAGES_DIR"):
        pk = tmp_path / "packages"
        pk.mkdir()
        monkeypatch.setattr(m, "PACKAGES_DIR", pk)
    return types.SimpleNamespace(mod=m, calls=calls)


def test_a_nightly_update_is_followed_by_the_solver_version_it_names(nightly):
    nightly.mod._run_update(True, False)
    st = nightly.mod.update_status
    pips = [c for c in nightly.calls if "pip" in c]
    ytdlp = [i for i, c in enumerate(pips) if any(a.endswith((".tar.gz", "yt-dlp.tar.gz")) for a in c)]
    ejs = [i for i, c in enumerate(pips) if "yt-dlp-ejs==0.8.1" in c]
    assert ytdlp, f"the nightly install did not run, so this checks nothing: {pips}"
    assert len(ejs) == 1 and ejs[0] > ytdlp[-1], pips
    assert st["error"] is None and st["done"] is True, st


def test_a_pip_run_given_the_nightly_url_does_not_use_pips_cache(nightly):
    """The Windows backend hands pip the GitHub URL itself (Mac and Linux download the archive and hand
    pip a local file). pip keeps that download in the person's own pip cache, shared with every pip
    they run, and one bad entry there ended every nightly update with "tarfile.ReadError: empty file"
    until the cache was purged (seen on a Windows machine, bundled pip 26.2.2). The URL never changes
    (it always names the newest nightly), so the cache saves nothing: pip must not read or write it."""
    nightly.mod._run_update(True, False)
    pips = [c for c in nightly.calls if "pip" in c]
    ytdlp = [c for c in pips if any(a.endswith(".tar.gz") for a in c)]
    assert ytdlp, f"the nightly install did not run, so this checks nothing: {pips}"
    for cmd in ytdlp:
        by_url = any("://" in a for a in cmd)
        assert not by_url or "--no-cache-dir" in cmd, f"pip is given a URL and may use its cache: {cmd}"


LINES = [
    "yt-dlp-ejs==0.8.0; extra == \"default\"",
    "yt-dlp-ejs==0.8.0; extra == 'default' and python_version < '3.9'",
    "yt-dlp-ejs==0.8.0; extra == 'default' or extra == 'pin'",
    "yt-dlp-ejs==0.8.0;extra=='default'",
    "  yt-dlp-ejs==0.8.0 ; extra == \"default\"  ",
    "yt-dlp-ejs==0.8.0",
    "yt-dlp-ejs==0.8.0; extra == 'defaults'",
    "yt-dlp-ejs===0.8.0; extra == 'default'",
    "yt-dlp-ejs==0.8.0 ; extra == 'default' ; x",
    "yt-dlp-ejs-extra==0.8.0; extra == 'default'",
    "Yt-Dlp-Ejs==0.8.0; extra == 'default'",
    "yt-dlp-ejs==v0.8.0; extra == 'default'",
]


_CACHE = {}   # one load of each backend for all the lines


@pytest.mark.parametrize("line", LINES)
@pytest.mark.parametrize("rel", ("mac/app.py", "linux/app.py"))
def test_mac_and_linux_read_the_pin_exactly_as_app_py(rel, line, app_module, tmp_path_factory, monkeypatch):
    other = _CACHE.get(rel) or _CACHE.setdefault(rel, _load(rel, tmp_path_factory))
    for m in (app_module, other):
        monkeypatch.setattr(m, "_run_yt", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=line + "\n", stderr=""))
    assert other._ytdlp_ejs_pin() == app_module._ytdlp_ejs_pin(), line

