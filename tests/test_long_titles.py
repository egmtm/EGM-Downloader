"""A finished download keeps its title as its name, whatever script the title is in.

The name was cut to 120 characters, but Linux and Mac allow 255 bytes per file name, and a
character of Japanese or Chinese takes three bytes (an emoji four). A long title in those scripts
made the check for an existing file raise "File name too long" outside the code that falls back to
a plain name, so a download that had finished ended as an error, left under its job number and
missing from History. yt-dlp is a fake here; nothing is fetched.
"""
import importlib.util
import io
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_long_titles_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


class _FakeYtDlp:
    pid = 4242

    def __init__(self, out_file):
        out_file.write_bytes(b"x" * 5000)
        self.stdout = io.StringIO("[download]  50.0% of 10.00MiB at 1.00MiB/s ETA 00:05\n[download] 100% of 10.00MiB\n")
        self.stderr = io.StringIO("")
        self.returncode = None

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode


TITLES = {
    "japanese": "日本語のとても長い動画タイトル" * 8,
    "emoji": "\U0001F600" * 70,
    "latin": "A very long title " * 10,
}


@pytest.mark.parametrize("script", sorted(TITLES))
def test_a_long_title_in_any_script_finishes_with_its_title_as_the_name(backend, script, tmp_path, monkeypatch):
    out = tmp_path / "downloads"
    out.mkdir()
    for name in ("HISTORY_FILE", "SETTINGS_FILE"):
        monkeypatch.setattr(backend, name, tmp_path / Path(getattr(backend, name)).name)
    monkeypatch.setattr(backend, "_download_thumbnail", lambda *a: "")
    job_id = "0123456789"
    monkeypatch.setattr(backend, "_popen_yt", lambda *a, **k: _FakeYtDlp(out / f"{job_id}.mp4"))
    backend.jobs[job_id] = {"status": "queued", "url": "https://example.invalid/v", "title": TITLES[script],
                            "proc": None, "cancelled": False, "live": False}
    try:
        backend.run_download(job_id, "https://example.invalid/v", "video", None, str(out), output_format="mp4")
        job = backend.jobs[job_id]
        assert job["status"] == "done", (job.get("status"), job.get("error"))
        name = job["filename"]
        assert name.endswith(".mp4") and len(name.encode("utf-8")) <= 255
        assert name.startswith(TITLES[script].strip()[:10])
        assert [p.name for p in out.iterdir()] == [name]
        assert backend._load_history()[0]["filename"] == name
    finally:
        backend.jobs.pop(job_id, None)


def test_the_name_is_cut_on_a_character_boundary(backend):
    for title in TITLES.values():
        name = backend._safe_filename(title, ".mp4")
        assert len(name.encode("utf-8")) <= 210
        name.encode("utf-8").decode("utf-8")      # no half character at the cut
    assert backend._safe_filename("Short: a/b", ".mp4") == "Short ab.mp4"


# ── H.264 compatibility pass: a failed final step must keep the download ─────────────────────

def test_a_conversion_whose_last_step_fails_keeps_the_original_file(backend, tmp_path, monkeypatch):
    """The original used to be deleted before the converted copy was moved over it; when that move
    failed (on Windows a scanner briefly holding the new file), both were gone and the job still
    ended "done" with History pointing at a missing file."""
    ff = tmp_path / "ffmpeg_bin"
    ff.mkdir()
    exe = ".exe" if Path(backend.__file__).resolve() == ROOT / "app.py" else ""
    for n in ("ffmpeg", "ffprobe"):
        (ff / f"{n}{exe}").write_text("")
    monkeypatch.setattr(backend, "FFMPEG_DIR", ff)
    original = tmp_path / "clip.mp4"
    original.write_bytes(b"original video")
    monkeypatch.setattr(backend, "_run", lambda *a, **k: __import__("subprocess").CompletedProcess([], 0, "vp9\n", ""))

    def fake_encode(job_id, job, ffmpeg, src, dst, level, ffprobe=None):
        Path(dst).write_bytes(b"converted video")
        return True
    monkeypatch.setattr(backend, "_run_h264_encode", fake_encode)
    real_rename, real_replace = backend.os.rename, backend.os.replace

    def locked(src, dst, *a, **k):
        if str(src).endswith(".h264.mp4"):
            raise PermissionError("the file is in use")
        return (real_replace if locked.kind == "replace" else real_rename)(src, dst, *a, **k)
    locked.kind = "rename"
    monkeypatch.setattr(backend.os, "rename", locked)

    def locked_replace(src, dst, *a, **k):
        locked.kind = "replace"
        return locked(src, dst, *a, **k)
    monkeypatch.setattr(backend.os, "replace", locked_replace)
    job = {"status": "downloading"}
    result = backend._ensure_h264("j1", original, job)
    assert Path(result).read_bytes() == b"original video"
    assert not (tmp_path / "clip.mp4.h264.mp4").exists()


# ── Live recording pieces that cannot be joined are kept under their own names ───────────────

@pytest.mark.parametrize("script", sorted(TITLES))
def test_pieces_that_cannot_be_joined_get_different_names_for_a_long_title(backend, script, tmp_path, monkeypatch):
    """The ' (part n)' suffix used to be cut off together with the end of a long title, so the second
    and later pieces were given the same name and the search for a free one never ended."""
    real, calls = backend._safe_filename, []

    def counted(*a, **k):
        calls.append(1)
        assert len(calls) < 100, "the search for a free name does not end"
        return real(*a, **k)
    monkeypatch.setattr(backend, "_safe_filename", counted)
    segs = []
    for i in range(3):
        p = tmp_path / f"piece{i}.mp4"
        p.write_bytes(b"x")
        segs.append(str(p))
    job = {"title": TITLES[script]}
    backend._live_keep_parts(job, "0123456789", tmp_path, segs)
    kept = [Path(p).name for p in job["_live_parts"]]
    assert len(kept) == 2 and len(set(kept)) == 2, kept
    assert kept[0].endswith("(part 2).mp4") and kept[1].endswith("(part 3).mp4"), kept
    assert all(len(n.encode("utf-8")) <= 255 for n in kept)
