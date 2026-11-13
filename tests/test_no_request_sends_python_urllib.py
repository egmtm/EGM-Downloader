"""Nothing the app's own code requests goes out as Python-urllib/<version>: it says EGM-Downloader.

The update check, the ffmpeg downloads and the GitHub API calls already did. Python's default agent was
still sent by the Deno zip download, the PyPI version checks (mutagen, the optional libraries) and, in
windows/launch.py, every download (the portable Python, Node.js, rcedit) and the signal to a running app.

* Backends: every urllib call (urlopen, _safe_urlopen, and open on an opener from build_opener) must
  be given a Request that carries the User-Agent header. Found by reading the code (an AST scan), so a
  new call without it fails here. The agent is EGM-Downloader everywhere but in the history thumbnail
  fetch, which runs only when the shell cannot fetch the picture and sends the agent yt-dlp used for
  that download (its user_agent argument; test_thumbnail_fallback_user_agent.py checks the value).
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
# The one function that sends another agent than EGM-Downloader, and the argument it sends.
YT_DLP_AGENT = ("_fetch_thumbnail", "user_agent")


def _name(func):
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)


def _is_request_with_agent(node, fn_name=""):
    if not (isinstance(node, ast.Call) and _name(node.func) == "Request"):
        return False
    for kw in node.keywords:
        if kw.arg == "headers" and isinstance(kw.value, ast.Dict):
            return any(isinstance(k, ast.Constant) and k.value == "User-Agent"
                       and ((isinstance(v, ast.Constant) and v.value == AGENT)
                            or (isinstance(v, ast.Name) and (fn_name, v.id) == YT_DLP_AGENT))
                       for k, v in zip(kw.value.keys, kw.value.values))
    return False


def _is_url_call(node):
    """urlopen, urlretrieve, _safe_urlopen, or open on an opener built with build_opener."""
    if not isinstance(node, ast.Call):
        return False
    if _name(node.func) in URL_CALLS:
        return True
    return (isinstance(node.func, ast.Attribute) and node.func.attr == "open"
            and isinstance(node.func.value, ast.Call) and _name(node.func.value.func) == "build_opener")


def _nearest(assigned, name, line):
    """Whether the last assignment to name before line (the one that reaches the call) is a Request
    with the agent. A second request in the same function is judged by its own assignment."""
    before = [a for a in assigned if a[1] == name and a[0] < line]
    return bool(before) and max(before)[2]


def _requests_without_agent(src):
    """(function, line) of every urllib call in src whose request carries no EGM-Downloader agent."""
    tree = ast.parse(src)
    found, seen = [], 0
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if fn.name == "_safe_urlopen":
            continue                                   # the wrapper passes on what its callers give it
        # Every assignment to a name in this function: (line, name, whether it is a Request with the agent).
        assigned = [(n.lineno, t.id, _is_request_with_agent(n.value, fn.name)) for n in ast.walk(fn)
                    if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        for call in [n for n in ast.walk(fn) if _is_url_call(n)]:
            seen += 1
            arg = call.args[0] if call.args else None
            ok = _is_request_with_agent(arg, fn.name) or (isinstance(arg, ast.Name) and _nearest(assigned, arg.id, call.lineno))
            if not ok:
                found.append((fn.name, call.lineno))
    return found, seen


@pytest.mark.parametrize("rel", APP_FILES)
def test_every_backend_request_carries_the_agent(rel):
    found, seen = _requests_without_agent(read_source(rel))
    assert seen >= 8, f"{rel}: only {seen} urllib calls found, the scan is looking at the wrong thing"
    assert found == [], f"{rel}: requests without the agent: {found}"


def test_a_second_request_in_the_same_function_is_judged_by_its_own_assignment():
    src = (
        "def update():\n"
        "    req = urllib.request.Request(a, headers={'User-Agent': 'EGM-Downloader'})\n"
        "    with _safe_urlopen(req, 5) as r: pass\n"
        "    req = urllib.request.Request(b)\n"
        "    with _safe_urlopen(req, 5) as r: pass\n"
        "    req = urllib.request.Request(c, headers={'User-Agent': 'EGM-Downloader'})\n"
        "    urllib.request.urlopen(req)\n"
    )
    assert _requests_without_agent(src) == ([("update", 5)], 3)


@pytest.mark.parametrize("rel", APP_FILES)
def test_the_scan_sees_the_thumbnail_fetch(rel):
    """The thumbnail fetch goes through an opener (its redirect handler checks each hop): the scan
    must count it, or a later change to it would pass unseen."""
    tree = ast.parse(read_source(rel))
    (fn,) = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == YT_DLP_AGENT[0]]
    assert [n for n in ast.walk(fn) if _is_url_call(n)], f"{rel}: the scan does not see the thumbnail request"


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
