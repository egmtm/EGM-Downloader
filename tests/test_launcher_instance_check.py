"""Windows launcher: the check for an app that is already running first tries a quick TCP connect.

A closed local port takes about 2 s to be refused on Windows (the TCP stack retries the SYN), so the
check's own 1 s limit was spent in full on every cold start. A listening port completes the connect at
once. The connect now gets 250 ms: when nothing listens the launcher moves on at once, and when
something does the request is sent exactly as before, with the same 1 s limit.

windows/launch.py is import safe, so these tests drive the real _signal_running_instance() with the
network calls replaced.
"""
import importlib.util
from pathlib import Path

LAUNCH = Path(__file__).resolve().parent.parent / "windows" / "launch.py"


def _load():
    spec = importlib.util.spec_from_file_location("egm_launch_instance_check_test", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Conn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _drive(monkeypatch, connect, post):
    """Run the real function with socket.create_connection and urllib.request.urlopen replaced;
    returns (result, connect calls, post calls)."""
    mod = _load()
    connects, posts = [], []

    def fake_connect(addr, timeout=None, **kw):
        connects.append((addr, timeout))
        return connect()

    def fake_urlopen(req, timeout=None, **kw):
        posts.append((req.full_url, req.get_method(), req.data, timeout))
        return post()

    monkeypatch.setattr(mod.socket, "create_connection", fake_connect)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    return mod._signal_running_instance(), connects, posts


def test_nothing_listening_returns_false_without_sending_a_request(monkeypatch):
    for exc in (ConnectionRefusedError(10061, "refused"), TimeoutError("timed out"), OSError(10051, "unreachable")):
        def connect(exc=exc):
            raise exc
        result, connects, posts = _drive(monkeypatch, connect, lambda: _Resp(200))
        assert result is False and posts == [], exc
        assert connects == [(("127.0.0.1", 8899), 0.25)], exc


def test_a_listening_app_gets_the_same_request_as_before_and_the_probe_connection_is_closed(monkeypatch):
    conn = _Conn()
    result, connects, posts = _drive(monkeypatch, lambda: conn, lambda: _Resp(200))
    assert result is True and conn.closed
    assert connects == [(("127.0.0.1", 8899), 0.25)]
    assert posts == [("http://127.0.0.1:8899/api/show-window", "POST", b"{}", 1)]


def test_a_listening_port_that_does_not_answer_ok_is_not_a_running_app(monkeypatch):
    result, _, posts = _drive(monkeypatch, _Conn, lambda: _Resp(500))
    assert result is False and len(posts) == 1

    def boom():
        raise TimeoutError("no answer")
    result, _, posts = _drive(monkeypatch, _Conn, boom)
    assert result is False and len(posts) == 1


def test_the_quick_check_comes_before_the_request_in_the_source():
    src = LAUNCH.read_text(encoding="utf-8")
    fn = src[src.index("def _signal_running_instance():"):src.index('if __name__ == "__main__":')]
    assert fn.count('socket.create_connection(("127.0.0.1", 8899), timeout=0.25).close()') == 1
    assert fn.index("timeout=0.25") < fn.index("urllib.request.urlopen(req, timeout=1)")
    assert fn.count("timeout=1)") == 1          # the request keeps its 1 s limit
