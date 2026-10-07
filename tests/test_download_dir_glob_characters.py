"""Download folders whose path contains glob characters ([ ] * ?).

run_download and _cleanup find the job's own files with glob.glob() on the
user's download folder. glob reads [ ] in that folder path as a pattern, so a
folder such as "Movies [4K]" matched nothing: yt-dlp finished the download,
but the job ended as "No output file found." and the unrenamed {job_id}.ext
stayed in the folder (external review, Oct 7 2026). The folder part of every
glob.glob() pattern must go through glob.escape().

The behaviour tests drive the real run_download() with only the yt-dlp process
replaced by a stub that writes the output file. The parity test covers all
three app.py files.
"""
import re

import pytest

from conftest import PLATFORM_APP_FILES, read_source

JOB_ID = "abcdef1234"


class _FakeProc:
    """Stands in for the yt-dlp process: no output, exit code 0."""
    returncode = 0

    def __init__(self):
        self.stdout = iter(())
        self.stderr = iter(())

    def wait(self):
        return 0


@pytest.fixture
def stubbed_run(app_module, monkeypatch):
    m = app_module
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_append_history", lambda *a, **k: None)
    for name in ("_ffmpeg_args", "_deno_args", "_cookies_args", "_bgutil_args"):
        monkeypatch.setattr(m, name, lambda: [])
    yield m
    m.jobs.pop(JOB_ID, None)


@pytest.mark.parametrize("folder", ["Plain", "Movies [4K]", "Music [2026] [FLAC]"])
def test_run_download_finds_its_output_in_folders_with_glob_characters(
        stubbed_run, tmp_path, monkeypatch, folder):
    m = stubbed_run
    out_dir = tmp_path / folder

    def fake_popen(*cmd, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{JOB_ID}.mkv").write_bytes(b"x")
        return _FakeProc()

    monkeypatch.setattr(m, "_popen_yt", fake_popen)
    m.jobs[JOB_ID] = {"status": "queued", "url": "https://video.example/v",
                      "title": "", "proc": None, "cancelled": False}
    m.run_download(JOB_ID, "https://video.example/v", "video", None,
                   str(out_dir), output_format="mkv")
    job = m.jobs[JOB_ID]
    assert job["status"] == "done", (
        f"download into {folder!r} ended as {job['status']!r} "
        f"({job.get('error')!r}) -- a [ or ] in the folder path was read as a "
        "glob pattern instead of literal text; wrap the folder in glob.escape()"
    )
    assert (out_dir / f"{JOB_ID}.mkv").exists()


@pytest.mark.parametrize("folder", ["Plain", "Movies [4K]"])
def test_cancel_cleanup_removes_job_files_in_folders_with_glob_characters(
        stubbed_run, tmp_path, folder):
    out_dir = tmp_path / folder
    out_dir.mkdir()
    mine = out_dir / f"{JOB_ID}.f137.mp4.part"
    other = out_dir / "someone_elses_download.part"
    mine.write_bytes(b"x")
    other.write_bytes(b"x")
    stubbed_run._cleanup(JOB_ID, out_dir)
    assert not mine.exists(), f"_cleanup left the job's file behind in {folder!r}"
    assert other.exists(), "_cleanup removed a file that is not the job's"


@pytest.mark.parametrize("rel", PLATFORM_APP_FILES)
def test_every_glob_glob_call_escapes_the_folder(rel):
    """glob.glob(<folder>/<pattern>) is only safe when the folder part is
    glob.escape()d. pathlib's Path.glob() takes the folder literally and is
    not affected, so this only looks at glob.glob( calls."""
    source = read_source(rel)
    calls = [m.start() for m in re.finditer(r"\bglob\.glob\(", source)]
    assert calls, f"{rel}: no glob.glob( call found -- update this guard"
    ok = "glob.glob(os.path.join(glob.escape("
    for pos in calls:
        assert source.startswith(ok, pos), (
            f"{rel}: unescaped glob.glob() on a folder path: "
            f"{source[pos:source.index(chr(10), pos)].strip()!r}"
        )
