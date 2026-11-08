"""Nothing the app's own code requests goes out as Python-urllib/<version>: it says EGM-Downloader.

The update check, the ffmpeg downloads and the GitHub API calls already did. Python's default agent was
still sent by the Deno zip download, the PyPI version checks (mutagen, the optional libraries) and, in
windows/launch.py, every download (the portable Python, Node.js, rcedit) and the signal to a running app.

* Backends: every urllib call must be given a Request that carries the User-Agent header. Found by
  reading the code (an AST scan), so a new call without it fails here. The one exception, marked
  below, is _download_thumbnail: the history thumbnails are being reworked separately and keep
  Python's agent until then.
* windows/launch.py: urlretrieve takes no headers, so the launcher sets the agent once on the opener
  every urllib call uses, before its first request. Checked against a local server.
* yt-dlp, pip and npm send their own agents; they are not the app's code.
"""
import ast
import importlib.util
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from conftest import ROOT, read_source

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
LAUNCH = Path(ROOT) / "windows" / "launch.py"
AGENT = "EGM-Downloader"
URL_CALLS = {"urlopen", "urlretrieve", "_safe_urlopen"}
# Allowed to send Python's default agent for now, and only these: the history thumbnail fetch is being
# moved out of the backends separately. Remove the entry when that lands.
STILL_PYTHON_URLLIB = {"_download_thumbnail"}


def _name(func):
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)


def _is_request_with_agent(node):
    if not (isinstance(node, ast.Call) and _name(node.func) == "Request"):
        return False
    for kw in node.keywords:
        if kw.arg == "headers" and isinstance(kw.value, ast.Dict):
            return any(isinstance(k, ast.Constant) and k.value == "User-Agent" and isinstance(v, ast.Constant)
                       and v.value == AGENT for k, v in zip(kw.value.keys, kw.value.values))
    return False


def _requests_without_agent(src):
    """(function, line) of every urllib call in src whose request carries no EGM-Downloader agent."""
    tree = ast.parse(src)
    found, seen = [], 0
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if fn.name == "_safe_urlopen":
            continue                                   # the wrapper passes on what its callers give it
        bound = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign) and _is_request_with_agent(n.value)
                 for t in n.targets if isinstance(t, ast.Name)}
        for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call) and _name(n.func) in URL_CALLS]:
            seen += 1
            arg = call.args[0] if call.args else None
            ok = _is_request_with_agent(arg) or (isinstance(arg, ast.Name) and arg.id in bound)
            if not ok:
                found.append((fn.name, call.lineno))
    return found, seen


@pytest.mark.parametrize("rel", APP_FILES)
def test_every_backend_request_carries_the_agent(rel):
    found, seen = _requests_without_agent(read_source(rel))
    assert seen >= 8, f"{rel}: only {seen} urllib calls found, the scan is looking at the wrong thing"
    assert {fn for fn, _ in found} <= STILL_PYTHON_URLLIB, f"{rel}: requests without the agent: {found}"


@pytest.mark.parametrize("rel", APP_FILES)
def test_the_thumbnail_exception_is_still_needed(rel):
    """When the thumbnail fetch stops using urllib, this fails: then drop STILL_PYTHON_URLLIB."""
    found, _ = _requests_without_agent(read_source(rel))
    assert {fn for fn, _ in found} == STILL_PYTHON_URLLIB


def _load(path, tmp_path_factory, prefix):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(prefix + path.split("/")[0], Path(ROOT) / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend_module(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory, "egm_agent_")


def test_the_pypi_version_checks_send_the_agent(backend_module, monkeypatch):
    seen = []

    class Reply:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"info": {"version": "1.0"}, "releases": {"1.0": []}}'

    def fake(req, timeout):
        seen.append(req)
        return Reply()

    monkeypatch.setattr(backend_module, "_safe_urlopen", fake)
    backend_module._get_latest_optlibs_versions()
    if hasattr(backend_module, "_get_latest_mutagen_version"):
        backend_module._get_latest_mutagen_version()
    assert len(seen) >= 5
    for req in seen:
        assert not isinstance(req, str), f"{req} was requested with Python's default agent"
        assert req.get_header("User-agent") == AGENT, req.full_url


# ── windows/launch.py ─────────────────────────────────────────────────────────

class _Agent(BaseHTTPRequestHandler):
    agents = []

    def _answer(self):
        _Agent.agents.append(self.headers.get("User-Agent"))
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    do_GET = do_POST = _answer

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _Agent.agents = []
    srv = HTTPServer(("127.0.0.1", 0), _Agent)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture
def launch():
    spec = importlib.util.spec_from_file_location("egm_launch_agent", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    urllib.request.install_opener(None)      # the test process gets Python's default opener back


def test_the_launchers_downloads_and_signal_send_the_agent(launch, server, tmp_path):
    launch._send_our_user_agent()
    urllib.request.urlretrieve(server + "/python.tar.gz", tmp_path / "a")
    req = urllib.request.Request(server + "/api/show-window", data=b"{}", headers={"Content-Type": "application/json"},
                                 method="POST")
    urllib.request.urlopen(req, timeout=5).read()
    assert _Agent.agents == [AGENT, AGENT]


def test_the_launcher_sets_it_before_its_first_request():
    src = LAUNCH.read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    first_request = main.index("_signal_running_instance()")
    assert "_send_our_user_agent()" in main and main.index("_send_our_user_agent()") < first_request
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and _name(n.func) in URL_CALLS]
    assert len(calls) >= 4, "the launcher's urllib calls were not found"
