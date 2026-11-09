"""When the backend fetches a history thumbnail itself, it sends the user agent yt-dlp used for that download.

The backend's own fetch is the fallback for when the shell cannot fetch the picture (web mode, a
failed shell fetch, no answer from the shell). It used to go out as Python-urllib/3.x. Now:

* run_download asks yt-dlp to write the headers it sends for the download (--print-to-file
  before_dl:%(http_headers)j into the data folder; since 2023 yt-dlp keeps cookies out of
  http_headers), reads the User-Agent from it after the run and removes the file when the job ends;
* the fetch sends that agent, and fetches nothing when there is none (never Python's own);
* every redirect hop is checked before it is followed: HTTPS only and never an internal address.
  Before, only the final address was checked, after the hops had been requested.

All three backends. The network is replaced below urllib's redirect handling, so the real handlers
run; one test runs the real yt-dlp (skipped where it is not installed) against a local server and
compares the agent that server saw with the one the backend reads back.
"""
import http.server
import importlib.util
import io
import json
import subprocess
import sys
import threading
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
JOB_ID = "fa11bac0de"


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_thumb_ua_" + path.split("/")[0], ROOT / path)
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


INTERNAL = {"10.0.0.5", "127.0.0.1", "intranet.local", "169.254.169.254"}


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
    monkeypatch.setattr(mod, "_is_internal_host", lambda host: host in INTERNAL)
    mod.data_for_test = data
    return mod


def _web(monkeypatch, pages):
    """HTTPS and plain HTTP answers from a table {url: (status, headers, body)}; everything above the
    transport (the redirect handler, the error processor) is urllib's own. Returns the requests, in order."""
    seen = []

    def https_open(self, req):
        seen.append({"url": req.full_url, "headers": dict(req.header_items())})
        status, headers, body = pages[req.full_url]
        msg = Message()
        for k, v in headers.items():
            msg[k] = v
        resp = urllib.response.addinfourl(io.BytesIO(body), msg, req.full_url, status)
        resp.msg = "OK" if status == 200 else "Found"
        return resp
    monkeypatch.setattr(urllib.request.HTTPSHandler, "https_open", https_open)
    monkeypatch.setattr(urllib.request.HTTPHandler, "http_open", https_open)
    return seen


IMAGE = (200, {"Content-Type": "image/jpeg", "Content-Length": str(len(JPEG))}, JPEG)


def _job(tmp_path, **kw):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    return dict({"url": "https://video.example/v", "title": "t", "thumbnail": "https://cdn.example/x.jpg"}, **kw), f


# ── the agent ─────────────────────────────────────────────────────────────────────────────────

def test_the_fallback_sends_the_user_agent_yt_dlp_used_and_nothing_else_of_note(backend, tmp_path, monkeypatch):
    seen = _web(monkeypatch, {"https://cdn.example/x.jpg": IMAGE})
    backend._append_history(*_job(tmp_path, user_agent=UA))
    (req,) = seen
    assert req["headers"].get("User-agent") == UA, req["headers"]
    assert "Python-urllib" not in json.dumps(req["headers"])
    assert not {"Cookie", "Referer"} & set(req["headers"]), req["headers"]
    (entry,) = backend._load_history()
    assert entry["thumbnail"] == entry["id"] + ".jpg", "the picture was not stored"


def test_without_yt_dlps_user_agent_nothing_is_fetched(backend, tmp_path, monkeypatch):
    """Never Python's own agent: no agent read back from yt-dlp, no request."""
    seen = _web(monkeypatch, {"https://cdn.example/x.jpg": IMAGE})
    backend._append_history(*_job(tmp_path))
    backend._append_history(*_job(tmp_path, user_agent=""))
    assert seen == []
    assert [e["thumbnail"] for e in backend._load_history()] == ["", ""]


# ── the redirect hops ─────────────────────────────────────────────────────────────────────────

def _redirect(to):
    return (302, {"Location": to, "Content-Length": "0"}, b"")


@pytest.mark.parametrize("hop", ["https://10.0.0.5/x.jpg", "https://intranet.local/x.jpg",
                                 "http://img.example/x.jpg", "https://169.254.169.254/latest/meta-data"])
def test_a_redirect_through_an_internal_or_plain_http_hop_is_never_followed(backend, tmp_path, monkeypatch, hop):
    """public -> (refused hop) -> public: the refused hop is not requested, and nothing is stored, even
    though the chain would have ended on a public image server (the final address check alone passed it)."""
    seen = _web(monkeypatch, {"https://cdn.example/x.jpg": _redirect(hop),
                              hop: _redirect("https://img.example/x.jpg"),
                              "https://img.example/x.jpg": IMAGE})
    backend._append_history(*_job(tmp_path, user_agent=UA))
    assert [r["url"] for r in seen] == ["https://cdn.example/x.jpg"], "a refused hop was requested"
    assert [e["thumbnail"] for e in backend._load_history()] == [""]


def test_a_redirect_between_public_image_servers_is_followed_with_the_same_agent(backend, tmp_path, monkeypatch):
    seen = _web(monkeypatch, {"https://cdn.example/x.jpg": _redirect("https://img.example/x.jpg"),
                              "https://img.example/x.jpg": IMAGE})
    backend._append_history(*_job(tmp_path, user_agent=UA))
    assert [r["url"] for r in seen] == ["https://cdn.example/x.jpg", "https://img.example/x.jpg"]
    assert all(r["headers"].get("User-agent") == UA for r in seen)
    assert backend._load_history()[0]["thumbnail"].endswith(".jpg")


# ── where the agent comes from ────────────────────────────────────────────────────────────────

class _FakeProc:
    returncode = 0

    def __init__(self):
        self.stdout, self.stderr = iter(()), iter(())

    def wait(self):
        return 0


def _print_to_file(cmd):
    i = cmd.index("--print-to-file")
    return cmd[i + 1], cmd[i + 2]


@pytest.fixture
def downloads(backend, tmp_path, monkeypatch):
    """run_download with the yt-dlp process replaced: the stand in writes the headers file as yt-dlp
    does and the output file. Returns (commands run, jobs handed to _append_history)."""
    m = backend
    runs, finished = [], []
    monkeypatch.setattr(m, "_egm_log", lambda *a, **k: None)
    monkeypatch.setattr(m, "_append_history", lambda job, path: finished.append(dict(job)))
    for name in ("_ffmpeg_args", "_deno_args", "_cookies_args", "_bgutil_args"):
        monkeypatch.setattr(m, name, lambda: [])
    out = tmp_path / "out"

    def fake_popen(*cmd, **kw):
        runs.append(list(cmd))
        tmpl, target = _print_to_file(cmd)
        assert tmpl == "before_dl:%(http_headers)j"
        Path(target.replace("%%", "%")).write_text(json.dumps({"User-Agent": UA, "Accept": "*/*"}) + "\n", encoding="utf-8")
        out.mkdir(exist_ok=True)
        (out / f"{JOB_ID}.mkv").write_bytes(b"x")
        return _FakeProc()
    monkeypatch.setattr(m, "_popen_yt", fake_popen)
    m.jobs[JOB_ID] = {"status": "queued", "url": "https://video.example/v", "title": "", "proc": None, "cancelled": False}
    yield runs, finished, out
    m.jobs.pop(JOB_ID, None)


def test_run_download_reads_the_agent_yt_dlp_wrote_and_removes_the_file(backend, downloads):
    runs, finished, out = downloads
    backend.run_download(JOB_ID, "https://video.example/v", "video", None, str(out), output_format="mkv")
    (cmd,) = runs
    _, target = _print_to_file(cmd)
    assert Path(target).parent == backend.data_for_test, "the headers file is not in the data folder"
    assert cmd[-1] == "https://video.example/v", "the URL must stay the last argument"
    (job,) = finished
    assert job["user_agent"] == UA
    assert not Path(target).exists(), "the headers file was left behind"
    assert backend.jobs[JOB_ID]["status"] == "done"


def test_the_headers_file_goes_when_the_download_fails_too(backend, downloads, monkeypatch):
    runs, finished, out = downloads
    monkeypatch.setattr(backend, "_kill_proc", lambda p: None)
    monkeypatch.setattr(backend.glob, "glob", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk gone")))
    backend.run_download(JOB_ID, "https://video.example/v", "video", None, str(out), output_format="mkv")
    _, target = _print_to_file(runs[0])
    assert backend.jobs[JOB_ID]["status"] == "error" and not Path(target).exists()


@pytest.mark.parametrize("text, expected", [
    (json.dumps({"User-Agent": UA}) + "\n", UA),
    (json.dumps({"User-Agent": "first"}) + "\n" + json.dumps({"User-Agent": UA}) + "\n", UA),   # a live reconnect ran it again
    ("NA\n", ""), ("", ""), (json.dumps({"User-Agent": 5}), ""), (json.dumps({"User-Agent": "a\r\nCookie: x"}), ""),
    (json.dumps({"User-Agent": "x" * 513}), ""),
])
def test_the_agent_is_read_only_when_it_is_a_plain_line(backend, tmp_path, text, expected):
    f = tmp_path / "h.json"
    f.write_text(text, encoding="utf-8")
    assert backend._ytdlp_user_agent(f) == expected
    assert backend._ytdlp_user_agent(tmp_path / "missing.json") == ""


# ── the real yt-dlp ───────────────────────────────────────────────────────────────────────────

def _have_yt_dlp():
    return subprocess.run([sys.executable, "-c", "import yt_dlp"], capture_output=True).returncode == 0


@pytest.mark.skipif(not _have_yt_dlp(), reason="yt-dlp is not installed")
def test_the_agent_read_back_is_the_one_yt_dlp_sent_for_the_download(backend, downloads, tmp_path):
    """The template and file the backend gives yt-dlp, run by the real yt-dlp against a local server."""
    runs, _, out = downloads
    backend.run_download(JOB_ID, "https://video.example/v", "video", None, str(out), output_format="mkv")
    tmpl, _ = _print_to_file(runs[0])
    sent = []

    class Clip(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            sent.append(self.headers.get("User-Agent"))
            body = b"\x00" * 4096
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Clip)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        headers_file = tmp_path / "with %percent" / f"{JOB_ID}.headers.json"
        headers_file.parent.mkdir()
        r = subprocess.run([sys.executable, "-m", "yt_dlp", "--ignore-config", "--print-to-file", tmpl,
                            str(headers_file).replace("%", "%%"), "-o", str(tmp_path / "dl" / "%(id)s.%(ext)s"),
                            f"http://127.0.0.1:{srv.server_address[1]}/clip.mp4"],
                           capture_output=True, text=True, timeout=120)
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stderr[-1500:]
    assert "[download]" in r.stdout, "the progress lines the backend reads are gone"
    assert sent and set(sent) == {sent[-1]}
    assert backend._ytdlp_user_agent(headers_file) == sent[-1]
    assert "Cookie" not in headers_file.read_text(encoding="utf-8")


# ── gaps found by mutation (session 4's thumbnail code) ────────────────────────────────────────

def test_the_backend_keeps_a_picture_of_exactly_the_cap_and_refuses_one_byte_more(backend, monkeypatch):
    cap = backend._THUMB_CAP
    exact = JPEG + b"\x00" * (cap - len(JPEG))
    over = exact + b"\x00"
    _web(monkeypatch, {"https://cdn.example/exact.jpg": (200, {"Content-Type": "image/jpeg"}, exact),
                       "https://cdn.example/over.jpg": (200, {"Content-Type": "image/jpeg"}, over)})
    assert backend._fetch_thumbnail("https://cdn.example/exact.jpg", UA) == exact
    assert backend._fetch_thumbnail("https://cdn.example/over.jpg", UA) == b""


def test_a_percent_sign_in_the_data_folder_is_doubled_for_yt_dlp(backend, downloads, tmp_path, monkeypatch):
    """--print-to-file takes an output template, where % starts a field: a data folder named with a %
    (a user name, a portable copy's folder) is written with %% so yt-dlp writes to that very file."""
    runs, finished, out = downloads
    data = tmp_path / "50%off"
    (data / "thumbnails").mkdir(parents=True)
    if hasattr(backend, "DATA_DIR"):
        monkeypatch.setattr(backend, "DATA_DIR", data)
    else:
        monkeypatch.setattr(backend, "get_data_dir", lambda: data)
    backend.run_download(JOB_ID, "https://video.example/v", "video", None, str(out), output_format="mkv")
    _, target = _print_to_file(runs[0])
    assert target == str(data / f"{JOB_ID}.headers.json").replace("%", "%%"), target
    (job,) = finished
    assert job["user_agent"] == UA
