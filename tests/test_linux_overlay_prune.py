"""
Linux: an older yt-dlp or brotli in the plugin overlay must not hide the bundled one.

Update Plugins installs into DATA_DIR/packages (PACKAGES_DIR) and _yt_env() puts that folder
first on PYTHONPATH, so a copy installed there before a floor was raised keeps winning over the
newer one the app ships (brotli 1.2.0 over the bundle's 1.2.1, CVE-2026-111497). At start the
app now removes a floor package from the overlay when its highest version there is below its
floor. The tests build overlays shaped like a real `pip install --target` (RECORD included,
checked once by hand on a real one) in a temporary folder. Nothing is installed.
"""
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LINUX_APP = ROOT / "linux" / "app.py"
LAUNCH = ROOT / "windows" / "launch.py"


@pytest.fixture(scope="module")
def mod(tmp_path_factory):
    # linux/app.py creates its data folders at import: point them at a temporary home.
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_linux_overlay_prune", LINUX_APP)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        mp.undo()
    return m


@pytest.fixture
def overlay(mod, monkeypatch, tmp_path):
    ov = tmp_path / "packages"
    ov.mkdir()
    monkeypatch.setattr(mod, "PACKAGES_DIR", ov)
    return ov


def _install(ov, files, dist_info, extra_record=()):
    """Write `files` (paths relative to the overlay) and a dist-info whose RECORD lists them,
    like pip does (plus its own dist-info files)."""
    rows = list(files) + [f"{dist_info}/METADATA", f"{dist_info}/RECORD"] + list(extra_record)
    for rel in files:
        p = ov / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    (ov / dist_info).mkdir(exist_ok=True)
    (ov / dist_info / "METADATA").write_text("Name: x")
    (ov / dist_info / "RECORD").write_text("\n".join(f"{r},," for r in rows) + "\n")


def _brotli(ov, version):
    # a real brotli RECORD also lists its bytecode in the overlay's shared __pycache__
    _install(ov, ["brotli.py", "_brotli.cpython-311-x86_64-linux-gnu.so",
                  "__pycache__/brotli.cpython-311.pyc"], f"brotli-{version}.dist-info")


def _ytdlp(ov, version):
    _install(ov, ["yt_dlp/__init__.py", "yt_dlp/extractor/kick.py"], f"yt_dlp-{version}.dist-info",
             extra_record=["../../bin/yt-dlp"])


def test_old_brotli_is_removed_and_the_rest_is_left(mod, overlay):
    _brotli(overlay, "1.2.0")
    _install(overlay, ["certifi/__init__.py"], "certifi-2026.10.19.dist-info")
    (overlay / "__pycache__" / "other.cpython-311.pyc").write_text("x")
    mod._prune_overlay_below_floors()
    assert not (overlay / "brotli.py").exists()
    assert not list(overlay.glob("_brotli*.so"))
    assert not (overlay / "brotli-1.2.0.dist-info").exists()
    assert (overlay / "certifi" / "__init__.py").exists()                  # another package
    assert (overlay / "certifi-2026.10.19.dist-info").exists()
    assert (overlay / "__pycache__" / "other.cpython-311.pyc").exists()    # shared folder untouched


def test_a_current_brotli_is_kept(mod, overlay):
    _brotli(overlay, "1.2.1")
    mod._prune_overlay_below_floors()
    assert (overlay / "brotli.py").exists() and (overlay / "brotli-1.2.1.dist-info").exists()


@pytest.mark.parametrize("version, pruned", [
    ("2026.8.19", True),
    ("2026.10.20", True),
    ("2026.10.21", False),            # at the floor
    ("2026.10.22.232843", False),     # a nightly after the floor
    ("2026.10.20.220001", True),      # a nightly before it
])
def test_yt_dlp_is_compared_on_its_version(mod, overlay, version, pruned):
    _ytdlp(overlay, version)
    mod._prune_overlay_below_floors()
    assert (not (overlay / "yt_dlp").exists()) is pruned
    assert (not (overlay / f"yt_dlp-{version}.dist-info").exists()) is pruned


def test_an_old_dist_info_next_to_a_current_one_does_not_trigger_a_prune(mod, overlay):
    """pip --target leaves superseded dist-infos beside the overwritten code: the highest wins."""
    _ytdlp(overlay, "2026.10.21")
    (overlay / "yt_dlp-2026.8.19.dist-info").mkdir()
    mod._prune_overlay_below_floors()
    assert (overlay / "yt_dlp" / "__init__.py").exists()


def test_lingering_old_dist_infos_go_with_an_old_copy(mod, overlay):
    _ytdlp(overlay, "2026.8.19")
    _ytdlp(overlay, "2026.9.1")
    mod._prune_overlay_below_floors()
    assert not (overlay / "yt_dlp").exists()
    assert not list(overlay.glob("yt_dlp-*.dist-info"))


def test_packages_with_a_similar_name_are_untouched(mod, overlay):
    _brotli(overlay, "1.2.0")
    _ytdlp(overlay, "2026.8.19")
    _install(overlay, ["brotlicffi/__init__.py"], "brotlicffi-1.0.0.dist-info")
    _install(overlay, ["yt_dlp_ejs/__init__.py"], "yt_dlp_ejs-0.3.2.dist-info")
    mod._prune_overlay_below_floors()
    assert (overlay / "brotlicffi" / "__init__.py").exists()
    assert (overlay / "brotlicffi-1.0.0.dist-info").exists()
    assert (overlay / "yt_dlp_ejs" / "__init__.py").exists()
    assert (overlay / "yt_dlp_ejs-0.3.2.dist-info").exists()


def test_the_script_entry_in_bin_is_not_touched(mod, overlay):
    (overlay / "bin").mkdir()
    (overlay / "bin" / "yt-dlp").write_text("x")
    _ytdlp(overlay, "2026.8.19")
    mod._prune_overlay_below_floors()
    assert (overlay / "bin" / "yt-dlp").exists()


def test_a_record_cannot_reach_outside_the_overlay(mod, overlay, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    _install(overlay, ["brotli.py"], "brotli-1.2.0.dist-info",
             extra_record=["../outside.txt", "/etc/hostname", "./brotli.py"])
    mod._prune_overlay_below_floors()
    assert outside.exists()
    assert not (overlay / "brotli.py").exists()


def test_an_unreadable_version_or_a_missing_record_is_left_alone(mod, overlay):
    _brotli(overlay, "1.2.0")
    (overlay / "brotli-1.2.0.dist-info" / "RECORD").unlink()
    _install(overlay, ["yt_dlp/__init__.py"], "yt_dlp-weird.dist-info")
    mod._prune_overlay_below_floors()                       # no exception
    assert (overlay / "brotli.py").exists()                 # old, but no record: not touched
    assert (overlay / "yt_dlp" / "__init__.py").exists()    # version not a number: not touched


def test_a_missing_overlay_is_fine(mod, monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "PACKAGES_DIR", tmp_path / "does-not-exist")
    mod._prune_overlay_below_floors()


def test_a_failing_delete_never_raises(mod, overlay, monkeypatch):
    _brotli(overlay, "1.2.0")
    _ytdlp(overlay, "2026.8.19")

    def boom(*a, **k):
        raise PermissionError("no")
    monkeypatch.setattr(mod.shutil, "rmtree", boom)
    monkeypatch.setattr(Path, "unlink", boom)
    mod._prune_overlay_below_floors()                       # swallowed: the app must still start


def test_the_floors_equal_the_launcher_and_requirements(mod):
    """windows/launch.py PY_DEP_FLOORS, this table and both requirements files are copies
    of one decision; they move together."""
    spec = importlib.util.spec_from_file_location("egm_launch_for_overlay_test", LAUNCH)
    launch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launch)
    assert mod.PY_DEP_FLOORS == launch.PY_DEP_FLOORS
    for name, floor in mod.PY_DEP_FLOORS.items():
        spec_str = ".".join(map(str, floor))
        for req in ("requirements.txt", "linux/requirements.txt"):
            lines = (ROOT / req).read_text(encoding="utf-8").splitlines()
            assert f"{name}>={spec_str}" in [l.strip() for l in lines], f"{req}: {name} floor differs"


def test_the_prune_runs_at_start_before_anything_uses_the_overlay():
    src = LINUX_APP.read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    call = main.index("_prune_overlay_below_floors()")
    assert call < main.index("_cleanup_orphan_partials(")
    assert call < main.index("ensure_ffmpeg")
    assert call < main.index("app.run(")
    # and never at import time (tests and tools load this module without starting the app)
    assert not re.search(r"^_prune_overlay_below_floors\(\)", src, flags=re.M)
