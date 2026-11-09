"""The <job id>.headers.json files yt-dlp writes for a download do not stay behind, on all three backends.

run_download asks yt-dlp to write the headers it sent to <data folder>/<job id>.headers.json and removes
the file when the job ends. A backend killed in the middle of a download leaves it, and for a site
extractor it can hold a Referer or Origin that names the site. So:

* Clear History removes those files, except the one of a download that is still running: the worker
  reads it after yt-dlp ends (for the user agent of the fallback picture fetch) and only then leaves
  _active_procs, so a job in _active_procs still needs its file;
* the start up removes every file of that name (no job runs yet).

Only the exact name the app writes is touched: 10 lowercase hex digits (uuid4().hex[:10]) plus
.headers.json, directly in the data folder. Anything else stays.
"""
import importlib.util
import json
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
LEFTOVER = "0123456789.headers.json"
OTHERS = ["012345678.headers.json", "0123456789a.headers.json", "ABCDEF0123.headers.json",
          "0123456789.headers.json.bak", "x0123456789.headers.json", "0123456789.headers.jsonx",
          "egm_settings.json", "abcdef0123.mp4"]


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_headers_" + path.split("/")[0], ROOT / path)
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
def backend(backend_module, tmp_path, monkeypatch):
    mod = backend_module
    data = tmp_path / "data"
    (data / "thumbnails").mkdir(parents=True)
    monkeypatch.setattr(mod, "THUMBNAILS_DIR", data / "thumbnails")
    monkeypatch.setattr(mod, "HISTORY_FILE", data / "egm_history.json")
    if hasattr(mod, "DATA_DIR"):
        monkeypatch.setattr(mod, "DATA_DIR", data)
    else:
        monkeypatch.setattr(mod, "get_data_dir", lambda: data)
    monkeypatch.setattr(mod, "_sec_event", lambda *a: None)
    mod.data_for_test = data
    yield mod
    mod._active_procs.clear()


def _plant(data):
    for name in [LEFTOVER] + OTHERS:
        (data / name).write_text("{}", encoding="utf-8")
    (data / "fedcba9876.headers.json").mkdir()               # a folder with that name
    (data / "sub").mkdir()
    (data / "sub" / "abcdef0123.headers.json").write_text("{}", encoding="utf-8")


def _left(data):
    return sorted(p.name for p in data.iterdir())


def _clear(mod):
    r = mod.app.test_client().post("/api/history/clear", headers={"X-EGM-Token": mod._API_TOKEN})
    assert r.status_code == 200


def test_clear_history_removes_a_leftover_headers_file_and_nothing_else(backend):
    data = backend.data_for_test
    _plant(data)
    _clear(backend)
    assert LEFTOVER not in _left(data)
    assert set(OTHERS) | {"fedcba9876.headers.json", "sub"} <= set(_left(data))
    assert (data / "sub" / "abcdef0123.headers.json").exists()


def test_clear_history_keeps_the_file_of_a_running_download(backend):
    data = backend.data_for_test
    (data / "aaaaaaaaaa.headers.json").write_text("{}", encoding="utf-8")
    (data / "bbbbbbbbbb.headers.json").write_text("{}", encoding="utf-8")
    backend._active_procs["aaaaaaaaaa"] = object()
    _clear(backend)
    assert (data / "aaaaaaaaaa.headers.json").exists(), "the file of a running download was removed"
    assert not (data / "bbbbbbbbbb.headers.json").exists()


class _Proc:
    returncode = 0

    def __init__(self, on_wait):
        self.stdout, self.stderr = iter(()), iter(())
        self.on_wait = on_wait

    def wait(self):
        self.on_wait()
        return 0


def test_a_download_running_while_history_is_cleared_still_gets_its_agent(backend, tmp_path, monkeypatch):
    """The real run_download: yt-dlp (a stand in) writes the headers file, Clear History runs while it
    is still running, and the finished job still has the user agent read from that file."""
    m = backend
    job_id = "c1ea4ed0c1"
    finished = []
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_append_history", lambda job, path: finished.append(dict(job)))
    for name in ("_ffmpeg_args", "_deno_args", "_cookies_args", "_bgutil_args"):
        monkeypatch.setattr(m, name, lambda: [])
    out = tmp_path / "out"

    def fake_popen(*cmd, **kw):
        i = cmd.index("--print-to-file")
        target = Path(cmd[i + 2].replace("%%", "%"))
        target.write_text(json.dumps({"User-Agent": UA}) + "\n", encoding="utf-8")
        out.mkdir(exist_ok=True)
        (out / f"{job_id}.mkv").write_bytes(b"x")
        return _Proc(lambda: _clear(m))
    monkeypatch.setattr(m, "_popen_yt", fake_popen)
    m.jobs[job_id] = {"status": "queued", "url": "https://video.example/v", "title": "", "proc": None, "cancelled": False}
    try:
        m.run_download(job_id, "https://video.example/v", "video", None, str(out), output_format="mkv")
    finally:
        m.jobs.pop(job_id, None)
    (job,) = finished
    assert job["user_agent"] == UA, "Clear History removed the file of the download that was running"
    assert not (m.data_for_test / f"{job_id}.headers.json").exists(), "the job removes its own file when it ends"


def test_the_start_up_removes_every_leftover_and_nothing_else(backend):
    data = backend.data_for_test
    _plant(data)
    (data / "aaaaaaaaaa.headers.json").write_text("{}", encoding="utf-8")
    backend._remove_headers_files(data)
    assert LEFTOVER not in _left(data) and "aaaaaaaaaa.headers.json" not in _left(data)
    assert set(OTHERS) | {"fedcba9876.headers.json", "sub"} <= set(_left(data))
    assert (data / "sub" / "abcdef0123.headers.json").exists()


@pytest.mark.parametrize("rel", APP_FILES)
def test_the_start_up_calls_it_next_to_the_partials_cleanup(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    data = "get_data_dir()" if rel == "app.py" else "DATA_DIR"
    assert f"_remove_headers_files({data})" in main
    assert main.index(f"_remove_headers_files({data})") > main.index("_cleanup_orphan_partials(")
