"""
Windows launcher: minimum versions for yt-dlp and brotli on installs that already work.

The launcher only installed Python packages when an import failed (installer) or a folder was
missing (portable), so an existing install kept an old yt-dlp or brotli for good. The launcher
now also checks PY_DEP_FLOORS and runs pip with the floors when a package is older. A failed
upgrade (offline, say) must never stop the start; a missing package still does.
windows/launch.py is import safe, so these tests drive the real functions with a fake pip.
Nothing is installed.
"""
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCH = ROOT / "windows" / "launch.py"

REQUIRED = ("flask", "yt_dlp", "cryptography", "mutagen", "curl_cffi", "Cryptodome", "websockets", "certifi")


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("egm_launch_floor_test", LAUNCH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def pip(mod, monkeypatch):
    """A fake pip: records every call, can be told to fail."""
    class Pip:
        calls = []
        fail = False
    p = Pip()
    p.calls = []

    def fake_run(cmd, **kw):
        p.calls.append((cmd, kw))
        if p.fail:
            raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    return p


def _spec(floors):
    return {n: ".".join(map(str, v)) for n, v in floors.items()}


def test_floors_match_requirements_and_both_pip_lists(mod):
    """PY_DEP_FLOORS, the two requirements files and the two pip lists in the launcher are
    four copies of the same decision; they must move together."""
    src = LAUNCH.read_text(encoding="utf-8")
    for name, spec in _spec(mod.PY_DEP_FLOORS).items():
        for req in ("requirements.txt", "linux/requirements.txt"):
            lines = (ROOT / req).read_text(encoding="utf-8").splitlines()
            line = next(l for l in lines if l.strip().lower().startswith(name + ">="))
            assert line.strip() == f"{name}>={spec}", f"{req}: {line!r} differs from the launcher floor {spec}"
        assert src.count(f'"{name}>={spec}"') == 2, f"both launcher pip lists must carry {name}>={spec}"


def test_version_tuple():
    mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location("egm_vt", LAUNCH))
    mod.__spec__.loader.exec_module(mod)
    assert mod._version_tuple("1.2.1") == (1, 2, 1)
    assert mod._version_tuple("2026.10.22.232843") == (2026, 10, 22)   # nightly
    assert mod._version_tuple("1.2") == (1, 2)
    assert mod._version_tuple("not a version") is None


@pytest.mark.parametrize("versions, below", [
    ({"yt-dlp": (2026, 10, 26), "brotli": (1, 2, 1)}, False),      # at the floors
    ({"yt-dlp": (2026, 10, 27), "brotli": (1, 3, 0)}, False),      # newer
    ({"yt-dlp": (2026, 8, 19), "brotli": (1, 2, 1)}, True),        # old yt-dlp
    ({"yt-dlp": (2026, 10, 21), "brotli": (1, 2, 1)}, True),       # the previous floor: it stops at curl_cffi 0.16.x
    ({"yt-dlp": (2026, 10, 26), "brotli": (1, 2, 0)}, True),       # old brotli
    ({"yt-dlp": (2026, 10, 26), "brotli": (1, 1, 0)}, True),
    ({"yt-dlp": None, "brotli": None}, False),                     # unknown is not "below": the sentinels cover missing
])
def test_deps_below_floor(mod, versions, below):
    assert mod._deps_below_floor(versions.get) is below


def test_installer_upgrades_an_old_brotli_without_importing_first(mod, pip, monkeypatch):
    monkeypatch.setattr(mod, "_meta_version", lambda n: {"yt-dlp": (2026, 10, 26), "brotli": (1, 2, 0)}[n])
    monkeypatch.setattr(mod, "_modules_present", lambda names: True)      # everything is installed
    # if the sentinel imports ran first they would map brotli's files into this process
    monkeypatch.setitem(sys.modules, "flask", None)
    mod.ensure_python_deps()
    (cmd, kw), = pip.calls
    assert "brotli>=1.2.1" in cmd and "yt-dlp>=2026.10.26" in cmd
    assert kw["check"] is False and "--retries" in cmd and "--timeout" in cmd


def test_installer_failed_upgrade_does_not_stop_the_start(mod, pip, monkeypatch):
    monkeypatch.setattr(mod, "_meta_version", lambda n: (1, 0, 0) if n == "brotli" else (2026, 10, 26))
    monkeypatch.setattr(mod, "_modules_present", lambda names: True)
    pip.fail = True
    mod.ensure_python_deps()            # offline: no exception
    assert len(pip.calls) == 1


def test_installer_current_versions_run_no_pip(mod, pip, monkeypatch):
    monkeypatch.setattr(mod, "_meta_version", lambda n: {"yt-dlp": (2026, 10, 26), "brotli": (1, 2, 1)}[n])
    for name in REQUIRED + ("brotli",):
        monkeypatch.setitem(sys.modules, name, type(sys)(name))
    mod.ensure_python_deps()
    assert pip.calls == []


def test_installer_missing_package_is_still_fatal(mod, pip, monkeypatch):
    monkeypatch.setattr(mod, "_meta_version", lambda n: None)
    monkeypatch.setitem(sys.modules, "brotli", None)        # import fails
    pip.fail = True
    with pytest.raises(subprocess.CalledProcessError):
        mod.ensure_python_deps()
    (cmd, kw), = pip.calls
    assert kw["check"] is True and "--retries" not in cmd


def test_installer_old_brotli_and_a_missing_package_stays_fatal(mod, pip, monkeypatch):
    """The floor upgrade must not hide a missing package: with brotli old AND flask missing,
    pip runs as a real install (fatal on failure), like the portable path."""
    monkeypatch.setattr(mod, "_meta_version", lambda n: {"yt-dlp": (2026, 10, 26), "brotli": (1, 2, 0)}[n])
    monkeypatch.setitem(sys.modules, "flask", None)          # find_spec says missing, import fails
    pip.fail = True
    with pytest.raises(subprocess.CalledProcessError):
        mod.ensure_python_deps()
    (cmd, kw), = pip.calls
    assert kw["check"] is True and "--retries" not in cmd


def test_modules_present(mod, monkeypatch):
    assert mod._modules_present(("os", "sys")) is True
    assert mod._modules_present(("os", "no_such_module_for_egm_test")) is False
    monkeypatch.setitem(sys.modules, "egm_half_loaded", type(sys)("egm_half_loaded"))   # __spec__ is None
    assert mod._modules_present(("egm_half_loaded",)) is False         # no exception


def test_dep_modules_match_the_sentinel_import_line(mod):
    """_DEP_MODULES (the presence check) and the installer's sentinel import are two copies of one list."""
    m = re.search(r"import (flask, [\w, ]+?); return", LAUNCH.read_text(encoding="utf-8"))
    assert m, "sentinel import line not found"
    assert tuple(x.strip() for x in m.group(1).split(",")) == mod._DEP_MODULES


def _site_packages(tmp_path, brotli, ytdlp):
    sp = tmp_path / "python" / "Lib" / "site-packages"
    sp.mkdir(parents=True)
    for pkg in REQUIRED:
        (sp / pkg).mkdir()
    (sp / "brotli.py").write_text("")                       # brotli is a single module file
    if brotli:
        (sp / f"Brotli-{brotli}.dist-info").mkdir()         # older wheels used a capital B
    if ytdlp:
        (sp / f"yt_dlp-{ytdlp}.dist-info").mkdir()
    (sp / "yt_dlp_ejs-0.3.2.dist-info").mkdir()             # a neighbour with a similar name
    return sp


def test_portable_old_brotli_is_upgraded(mod, pip, monkeypatch, tmp_path):
    _site_packages(tmp_path, "1.2.0", "2026.10.26")
    monkeypatch.setattr(mod, "PY_DIR", tmp_path / "python")
    mod.ensure_python_deps_embedded("python.exe")
    (cmd, kw), = pip.calls
    assert "brotli>=1.2.1" in cmd and kw["check"] is False


def test_portable_old_dist_infos_do_not_hide_the_new_one(mod, pip, monkeypatch, tmp_path):
    sp = _site_packages(tmp_path, "1.2.1", "2026.10.26")
    (sp / "brotli-1.2.0.dist-info").mkdir()                  # a leftover next to the current one
    monkeypatch.setattr(mod, "PY_DIR", tmp_path / "python")
    mod.ensure_python_deps_embedded("python.exe")
    assert pip.calls == []


def test_portable_failed_upgrade_does_not_stop_the_start(mod, pip, monkeypatch, tmp_path):
    _site_packages(tmp_path, "1.2.1", "2026.8.19")
    monkeypatch.setattr(mod, "PY_DIR", tmp_path / "python")
    pip.fail = True
    mod.ensure_python_deps_embedded("python.exe")            # offline: no exception
    assert len(pip.calls) == 1


def test_portable_missing_package_is_still_fatal(mod, pip, monkeypatch, tmp_path):
    sp = _site_packages(tmp_path, "1.2.1", "2026.10.26")
    (sp / "flask").rmdir()
    monkeypatch.setattr(mod, "PY_DIR", tmp_path / "python")
    pip.fail = True
    with pytest.raises(subprocess.CalledProcessError):
        mod.ensure_python_deps_embedded("python.exe")
    assert pip.calls[0][1]["check"] is True
