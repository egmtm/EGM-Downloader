"""
Windows portable: the private Python is a python-build-standalone build (the family Mac and Linux
bundle), pinned by version, release and SHA-256, checked before anything is unpacked, and unpacked
by a reader that refuses paths outside its folder. It brings its own pip, so there is no pip
download any more.

windows/launch.py is import safe (constants and functions only; the real work is
behind __main__), so these tests exercise the real functions with the network and
the subprocess faked. Nothing here downloads or runs anything.

The SHA-256 in launch.py was compared by hand with the SHA256SUMS file of the release it names
(cpython-3.11.18+20261026-x86_64-pc-windows-msvc-install_only_stripped.tar.gz); the tests can only
check its shape.
"""
import hashlib
import importlib.util
import inspect
import io
import re
import tarfile
from pathlib import Path

import pytest

from conftest import read_source

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


@pytest.fixture
def launch(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("egm_launch_under_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "PY_SETUP_LOG", tmp_path / "setup.log")
    monkeypatch.setattr(mod, "_gui_msg", lambda *a, **k: None)
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)
    py_dir = tmp_path / "python"
    monkeypatch.setattr(mod, "PY_DIR", py_dir)
    monkeypatch.setattr(mod, "PY_EXE", py_dir / "python.exe")
    return mod


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive(tmp_path, members, name="py.tar.gz"):
    """A tar.gz holding (name, bytes) files; a bytes value of None makes a symlink."""
    path = tmp_path / name
    with tarfile.open(path, "w:gz") as t:
        for member, data in members:
            info = tarfile.TarInfo(member)
            if data is None:
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                t.addfile(info)
            else:
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return path


def _pin(name, text):
    m = re.search(rf'^{name}="([^"]+)"', text, re.M)
    assert m, f"{name} is not pinned"
    return m.group(1)


# ── the pin ───────────────────────────────────────────────────────────────────

def test_python_pin_is_well_formed(launch):
    assert re.fullmatch(r"3\.11\.\d+", launch.PY_VERSION)
    assert re.fullmatch(r"\d{8}", launch.PY_RELEASE)
    assert re.fullmatch(r"[0-9a-f]{64}", launch.PY_SHA256)
    assert launch.PY_ARCHIVE_NAME == (f"cpython-{launch.PY_VERSION}+{launch.PY_RELEASE}"
                                      "-x86_64-pc-windows-msvc-install_only_stripped.tar.gz")
    assert launch.PY_ARCHIVE_URL == ("https://github.com/astral-sh/python-build-standalone/releases/download/"
                                     f"{launch.PY_RELEASE}/{launch.PY_ARCHIVE_NAME}")


def test_windows_pins_the_same_python_as_mac_and_linux(launch):
    for script in ("linux/BUILD.sh", "mac/BUILD.sh"):
        text = read_source(script)
        assert _pin("PYTHON_VERSION", text) == launch.PY_VERSION, script
        assert _pin("PYTHON_RELEASE", text) == launch.PY_RELEASE, script


def test_verify_sha256_accepts_only_the_exact_digest(launch, tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert launch._verify_sha256(f, _sha(b"abc"), "t") is True
    assert launch._verify_sha256(f, _sha(b"abc").upper(), "t") is True
    assert launch._verify_sha256(f, _sha(b"abd"), "t") is False


@pytest.mark.parametrize("pin", [None, "", "abc", "z" * 64, "0" * 63, "0" * 65])
def test_verify_sha256_fails_closed_on_a_bad_pin(launch, tmp_path, pin):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert launch._verify_sha256(f, pin, "t") is False


def test_verify_sha256_fails_closed_on_a_missing_file(launch, tmp_path):
    assert launch._verify_sha256(tmp_path / "nope.bin", _sha(b"abc"), "t") is False


def test_python_archive_check_uses_its_own_pin(launch, tmp_path, monkeypatch):
    f = tmp_path / "py.tar.gz"
    f.write_bytes(b"archive")
    monkeypatch.setattr(launch, "PY_SHA256", _sha(b"archive"))
    assert launch._verify_py_archive(f) is True
    monkeypatch.setattr(launch, "PY_SHA256", _sha(b"other"))
    assert launch._verify_py_archive(f) is False
    monkeypatch.setattr(launch, "PY_SHA256", "")
    assert launch._verify_py_archive(f) is False


# ── unpacking ─────────────────────────────────────────────────────────────────

def test_extract_drops_the_top_folder_and_keeps_the_tree(launch, tmp_path):
    archive = _archive(tmp_path, [("python/python.exe", b"exe"), ("python/Lib/site-packages/pip/a.py", b"x"),
                                  ("python/DLLs/_ssl.pyd", b"dll")])
    dest = tmp_path / "out"
    dest.mkdir()
    launch._extract_python_archive(archive, dest)
    assert (dest / "python.exe").read_bytes() == b"exe"
    assert (dest / "Lib" / "site-packages" / "pip" / "a.py").read_bytes() == b"x"
    assert (dest / "DLLs" / "_ssl.pyd").read_bytes() == b"dll"
    assert not (dest / "python").exists()


def test_extract_refuses_paths_outside_the_folder_and_non_files(launch, tmp_path):
    archive = _archive(tmp_path, [("python/ok.txt", b"ok"), ("python/../evil.txt", b"x"),
                                  ("python/a/../../evil2.txt", b"x"), ("/abs.txt", b"x"),
                                  ("other/stray.txt", b"x"), ("python/link", None), ("python", b"top")])
    dest = tmp_path / "inner" / "out"
    dest.mkdir(parents=True)
    launch._extract_python_archive(archive, dest)
    assert sorted(p.name for p in dest.rglob("*")) == ["ok.txt"]
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "inner" / "evil.txt").exists()
    assert not (tmp_path / "evil2.txt").exists() and not (tmp_path / "abs.txt").exists()


# The extractor has two guards on a path: the name check (no "..", not absolute, no drive) and
# the resolve check (the written file must resolve to a place inside the folder). The test above
# is stopped by either one, so removing one of them alone went unnoticed. These two each need
# their own guard.

def test_extract_refuses_dotdot_even_when_it_would_land_inside(launch, tmp_path):
    # Resolves to dest/inside.txt, so only the name check stops it.
    archive = _archive(tmp_path, [("python/ok.txt", b"ok"), ("python/a/../inside.txt", b"x")])
    dest = tmp_path / "out"
    dest.mkdir()
    launch._extract_python_archive(archive, dest)
    assert sorted(p.name for p in dest.rglob("*") if p.is_file()) == ["ok.txt"]


def test_extract_refuses_a_path_that_resolves_outside_through_a_link(launch, tmp_path):
    # No ".." and not absolute, so the name check lets it through; only the resolve check stops it.
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "out"
    dest.mkdir()
    try:
        (dest / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system cannot make symbolic links")
    archive = _archive(tmp_path, [("python/ok.txt", b"ok"), ("python/link/evil.txt", b"x")])
    launch._extract_python_archive(archive, dest)
    assert not (outside / "evil.txt").exists()
    assert (dest / "ok.txt").read_bytes() == b"ok"


# ── ensure_python ─────────────────────────────────────────────────────────────

class _Done:
    def __init__(self, stdout="", rc=0):
        self.returncode, self.stdout, self.stderr = rc, stdout, ""


def _fake_run(calls, version="3.11.18", pip_rc=0):
    def run(cmd, *a, **k):
        calls.append([str(c) for c in cmd])
        if "-m" in cmd and "pip" in cmd:
            return _Done("pip 26.2.2", pip_rc)
        return _Done(version)
    return run


def test_an_archive_that_fails_the_check_is_never_unpacked_or_run_and_is_removed(launch, monkeypatch):
    def fake_download(url, dest, *a, **k):
        Path(dest).write_bytes(b"tampered")

    def must_not_run(*a, **k):
        raise AssertionError("an unverified download was used")

    monkeypatch.setattr(launch.urllib.request, "urlretrieve", fake_download)
    monkeypatch.setattr(launch, "_extract_python_archive", must_not_run)
    monkeypatch.setattr(launch.subprocess, "run", must_not_run)
    # PY_SHA256 stays the real pin, so b"tampered" can never match it.
    assert launch.ensure_python() is None
    assert not (launch.PY_DIR / "py_tmp.tar.gz").exists()
    assert "Python archive: checksum mismatch" in launch.PY_SETUP_LOG.read_text(encoding="utf-8")


def test_a_failed_download_runs_nothing(launch, monkeypatch):
    def broken_download(*a, **k):
        raise OSError("offline")

    def must_not_run(*a, **k):
        raise AssertionError("something ran after a failed download")

    monkeypatch.setattr(launch.urllib.request, "urlretrieve", broken_download)
    monkeypatch.setattr(launch.subprocess, "run", must_not_run)
    assert launch.ensure_python() is None
    assert "offline" in launch.PY_SETUP_LOG.read_text(encoding="utf-8")


def test_a_verified_archive_is_unpacked_pip_is_checked_and_the_download_is_cleaned_up(launch, tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("python/python.exe", b"exe"), ("python/Lib/site-packages/pip/__init__.py", b"")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    calls = []
    monkeypatch.setattr(launch.subprocess, "run", _fake_run(calls))
    assert launch.ensure_python() == str(launch.PY_EXE)
    assert launch.PY_EXE.read_bytes() == b"exe"
    assert not (launch.PY_DIR / "py_tmp.tar.gz").exists()
    # pip is checked in the stage folder, before the new Python becomes python\, and the
    # stage folder is gone once it has been moved into place
    stage = launch._py_stage_dir()
    assert [str(stage / "python.exe"), "-m", "pip", "--isolated", "--version"] in calls
    assert not stage.exists()


def test_a_python_that_cannot_run_pip_is_reported_not_used(launch, tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("python/python.exe", b"exe")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([], pip_rc=1))
    assert launch.ensure_python() is None
    assert "pip --version failed" in launch.PY_SETUP_LOG.read_text(encoding="utf-8")


def test_a_working_private_python_is_kept_not_replaced(launch, monkeypatch):
    # On a warm start the launcher runs ON this python.exe, and Windows will not replace a folder whose
    # python.exe is running: an older working Python (the 3.12.10 embeddable of earlier versions) stays.
    launch.PY_DIR.mkdir()
    launch.PY_EXE.write_bytes(b"exe")
    marker = launch.PY_DIR / "site-marker"
    marker.write_bytes(b"keep")

    def must_not_download(*a, **k):
        raise AssertionError("a working Python was replaced")

    monkeypatch.setattr(launch.urllib.request, "urlretrieve", must_not_download)
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([], version="3.12.10"))
    assert launch.ensure_python() == str(launch.PY_EXE)
    assert marker.exists()


def test_a_broken_private_python_is_rebuilt(launch, tmp_path, monkeypatch):
    launch.PY_DIR.mkdir()
    launch.PY_EXE.write_bytes(b"broken")
    (launch.PY_DIR / "stale.txt").write_bytes(b"old")
    archive = _archive(tmp_path, [("python/python.exe", b"fresh")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    versions = iter(["", "3.11.18", "3.11.18"])   # the broken one prints nothing, the new one is 3.11.18

    def run(cmd, *a, **k):
        if "pip" in cmd:
            return _Done("pip 26.2.2")
        return _Done(next(versions))

    monkeypatch.setattr(launch.subprocess, "run", run)
    assert launch.ensure_python() == str(launch.PY_EXE)
    assert launch.PY_EXE.read_bytes() == b"fresh"
    assert not (launch.PY_DIR / "stale.txt").exists()


# ── an unpack that is cut off ────────────────────────────────────────────────
# The native launcher prefers python\python.exe whenever that file exists, and ensure_python keeps
# any python.exe that starts. An unpack cut off after python.exe (the launcher killed, power loss,
# antivirus) must therefore never leave python\ behind: the new Python is unpacked and checked in
# python.part\ and only then renamed to python\.

def test_an_unpack_that_is_cut_off_leaves_no_python_folder(launch, tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("python/python.exe", b"exe")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))

    def cut_off(src, dest):
        (Path(dest) / "python.exe").write_bytes(b"half")
        raise OSError("the disk went away")

    monkeypatch.setattr(launch, "_extract_python_archive", cut_off)
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([]))
    assert launch.ensure_python() is None
    assert not launch.PY_DIR.exists()
    assert not launch._py_stage_dir().exists()


def test_a_stage_folder_left_by_a_killed_launcher_is_cleared_and_setup_completes(launch, tmp_path, monkeypatch):
    stage = launch._py_stage_dir()
    stage.mkdir(parents=True)
    (stage / "python.exe").write_bytes(b"half")
    (stage / "stale.txt").write_bytes(b"old")
    archive = _archive(tmp_path, [("python/python.exe", b"fresh")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([]))
    assert launch.ensure_python() == str(launch.PY_EXE)
    assert launch.PY_EXE.read_bytes() == b"fresh"
    assert not (launch.PY_DIR / "stale.txt").exists()
    assert not stage.exists()


def test_a_rename_that_keeps_failing_falls_back_to_a_copy(launch, tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("python/python.exe", b"exe"), ("python/Lib/os.py", b"os")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([]))
    tries = []

    def locked(src, dst):
        tries.append(src)
        raise PermissionError("a scanner still has a file open")

    monkeypatch.setattr(launch.os, "rename", locked)
    assert launch.ensure_python() == str(launch.PY_EXE)
    assert len(tries) == 20
    assert (launch.PY_DIR / "Lib" / "os.py").read_bytes() == b"os"
    assert not launch._py_stage_dir().exists()


def test_a_copy_that_is_cut_off_halfway_leaves_no_python_folder(launch, tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("python/python.exe", b"exe")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([]))

    def locked(src, dst):
        raise PermissionError("a scanner still has a file open")

    def half_copy(src, dst, **k):
        Path(dst).mkdir(parents=True)
        (Path(dst) / "python.exe").write_bytes(b"half")
        raise OSError("the disk went away")

    monkeypatch.setattr(launch.os, "rename", locked)
    monkeypatch.setattr(launch.shutil, "copytree", half_copy)
    assert launch.ensure_python() is None
    assert not launch.PY_DIR.exists()
    assert not launch._py_stage_dir().exists()


def test_the_python_this_launcher_runs_on_is_kept_without_a_probe(launch, monkeypatch):
    """On a warm start the launcher runs on the private Python. A probe that misses its time limit
    (a slow USB stick or network folder) must not get it deleted while it runs."""
    launch.PY_DIR.mkdir()
    launch.PY_EXE.write_bytes(b"exe")
    (launch.PY_DIR / "Lib").mkdir()
    monkeypatch.setattr(launch.sys, "executable", str(launch.PY_DIR / "pythonw.exe"))

    def must_not_run(*a, **k):
        raise AssertionError("nothing may be probed, downloaded or removed")

    monkeypatch.setattr(launch.subprocess, "run", must_not_run)
    monkeypatch.setattr(launch.urllib.request, "urlretrieve", must_not_run)
    monkeypatch.setattr(launch.shutil, "rmtree", must_not_run)
    assert launch.ensure_python() == str(launch.PY_EXE)
    assert (launch.PY_DIR / "Lib").is_dir()


# ── nothing unchecked is fetched or run ──────────────────────────────────────

def test_the_download_is_checked_before_it_is_unpacked_or_run(launch):
    src = LAUNCH.read_text(encoding="utf-8")
    assert "get-pip" not in src and "GETPIP" not in src and "bootstrap.pypa.io" not in src
    body = inspect.getsource(launch.ensure_python)
    download = body.index("urlretrieve(")
    verify = body.index("_verify_py_archive(")
    unpack = body.index("_extract_python_archive(")
    first_run = body.index("_python_has_pip(")
    move = body.index("_move_python_into_place(")
    assert download < verify < unpack < first_run < move


def test_the_embeddable_zip_and_the_pip_wheel_steps_are_gone():
    src = LAUNCH.read_text(encoding="utf-8")
    for old in ("embed-amd64", "PIP_BOOTSTRAP_CODE", "PIP_WHEEL", "PIP_SHA256", "_setup_embedded_pip", "_pth"):
        assert old not in src, old


def test_a_python_older_than_required_is_not_put_in_place(launch, tmp_path, monkeypatch):
    archive = _archive(tmp_path, [("python/python.exe", b"exe")])
    monkeypatch.setattr(launch, "PY_SHA256", _sha(archive.read_bytes()))
    monkeypatch.setattr(launch.urllib.request, "urlretrieve",
                        lambda url, dest, *a, **k: Path(dest).write_bytes(archive.read_bytes()))
    monkeypatch.setattr(launch.subprocess, "run", _fake_run([], version="3.9.18"))
    assert launch.ensure_python() is None
    assert not launch.PY_DIR.exists() and not launch._py_stage_dir().exists()
    assert "older than required" in launch.PY_SETUP_LOG.read_text(encoding="utf-8")
