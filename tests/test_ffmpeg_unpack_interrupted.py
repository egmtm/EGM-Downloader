"""ffmpeg and ffprobe must never sit under their final names half written.

The first start counts ffmpeg as installed when both files exist, so a failure while ffprobe was
being written (a full disk, a kill, a power cut) used to leave a broken ffprobe that every later
start took as ready, and an interrupted update did the same to a working pair. Here the failure is
a full disk, injected while the ffprobe bytes are written; the download and its checksum are
stubbed, so nothing is fetched.
"""
import errno
import importlib.util
import io
import shutil
import tarfile
import urllib.error
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")
OLD = b"old working binary"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_ffmpeg_unpack_" + path.split("/")[0], ROOT / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


def _rel(mod):
    return Path(mod.__file__).resolve().relative_to(ROOT).as_posix()


def _names(mod):
    return ("ffmpeg.exe", "ffprobe.exe") if _rel(mod) == "app.py" else ("ffmpeg", "ffprobe")


class _Resp(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _archives(mod):
    """{url part: archive bytes} the way each platform's ffmpeg source ships them."""
    payload = {"ffmpeg": b"new ffmpeg " * 40000, "ffprobe": b"new ffprobe " * 40000}
    rel = _rel(mod)
    if rel.startswith("mac"):
        out = {}
        for name in ("ffmpeg", "ffprobe"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr(name, payload[name])
            out[name + ".zip"] = buf.getvalue()
        return out
    if rel.startswith("linux"):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:xz") as t:
            for name in ("ffmpeg", "ffprobe"):
                info = tarfile.TarInfo(f"ffmpeg-x/bin/{name}")
                info.size = len(payload[name])
                t.addfile(info, io.BytesIO(payload[name]))
        return {"": buf.getvalue()}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("ffmpeg", "ffprobe"):
            z.writestr(f"ffmpeg-x/bin/{name}.exe", payload[name])
    return {"": buf.getvalue()}


@pytest.fixture
def rig(backend, tmp_path, monkeypatch):
    ff = tmp_path / "ffmpeg_bin"
    ff.mkdir()
    monkeypatch.setattr(backend, "FFMPEG_DIR", ff)
    monkeypatch.setattr(backend, "FFMPEG_TAG_FILE", ff / "build_tag.txt")
    monkeypatch.setattr(backend, "_verify_upstream_checksum", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(backend, "_get_latest_ffmpeg_tag", lambda: "t")
    monkeypatch.setattr(backend, "_get_ffmpeg_version", lambda: "x")
    archives = _archives(backend)

    def fake_urlopen(req, timeout):
        url = req if isinstance(req, str) else req.full_url
        key = next(k for k in sorted(archives, key=len, reverse=True) if k in url)
        return _Resp(archives[key], url)
    monkeypatch.setattr(backend, "_safe_urlopen", fake_urlopen)

    # A full disk while the ffprobe bytes are written (not while the archive is downloaded).
    real_shutil, real_tar = shutil.copyfileobj, tarfile.copyfileobj

    def is_probe(f):
        name = Path(getattr(f, "name", "") or "").name
        return name.startswith("ffprobe") and not name.endswith((".zip", ".xz"))

    def full_disk_shutil(src, dst, *a, **k):
        if is_probe(dst):
            dst.write(src.read(1000))
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_shutil(src, dst, *a, **k)

    def full_disk_tar(src, dst, length=None, *a, **k):
        if is_probe(dst):
            dst.write(src.read(1000))
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_tar(src, dst, length, *a, **k)
    monkeypatch.setattr(shutil, "copyfileobj", full_disk_shutil)
    monkeypatch.setattr(tarfile, "copyfileobj", full_disk_tar)

    def offline(*a, **k):
        raise urllib.error.URLError("offline")

    def disk_ok():
        monkeypatch.setattr(shutil, "copyfileobj", real_shutil)
        monkeypatch.setattr(tarfile, "copyfileobj", real_tar)

    def next_start():
        disk_ok()
        monkeypatch.setattr(backend, "_safe_urlopen", offline)
    return ff, next_start, disk_ok


def test_a_first_run_unpack_that_fails_part_way_is_not_taken_as_installed(backend, rig):
    ff, next_start, _ = rig
    assert not backend.ensure_ffmpeg()
    next_start()
    assert not backend.ensure_ffmpeg(), (
        "the next start took a half written ffprobe as an installed ffmpeg: "
        f"{sorted(p.name for p in ff.iterdir())}")


def test_an_update_that_fails_part_way_keeps_the_working_pair(backend, rig):
    ff, _, _ = rig
    names = _names(backend)
    for n in names:
        (ff / n).write_bytes(OLD)
    backend._run_update(False, True)
    assert backend.update_status.get("error"), backend.update_status
    for n in names:
        assert (ff / n).read_bytes() == OLD, f"{n} was left half written: {(ff / n).stat().st_size} bytes"
    leftovers = sorted(p.name for p in ff.iterdir() if p.name not in names and p.name != "build_tag.txt")
    assert leftovers == [], leftovers


def test_a_complete_unpack_and_a_complete_update_put_both_binaries_in_place(backend, rig):
    ff, _, disk_ok = rig
    disk_ok()
    names = _names(backend)
    assert backend.ensure_ffmpeg()
    assert [(ff / n).read_bytes()[:10] for n in names] == [b"new ffmpeg", b"new ffprob"]
    for n in names:
        (ff / n).write_bytes(OLD)
    backend._run_update(False, True)
    assert not backend.update_status.get("error"), backend.update_status
    assert [(ff / n).read_bytes()[:10] for n in names] == [b"new ffmpeg", b"new ffprob"]
    assert not (ff / "_staging").exists()
