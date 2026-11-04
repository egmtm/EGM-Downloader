"""The Windows backend notices when another program answers on its port.

Windows lets a second program listen on a port that is already in use (the server asks for address
reuse), so the bind can succeed behind the other program. On EGM's Windows run, with a stand in server
on the port, the backend stayed alive, the shell's polling got 404 for its three minutes and no box
appeared. Mac and Linux refuse the second listener and exit with code 3 (test_backend_port_in_use.py).
The Windows backend now asks its own port, several times, with this run's token, and exits with code 3
when anything else answers. Which program gets a given connection when two share a port is not
something to rely on, so one good answer is not enough, and not answering yet never counts as taken
(a slow start must not turn into a false port message).

CI cannot show the Windows bind behaviour itself; the checks here are on what the check does with each
answer. A real Windows run is the proof for the rest.
"""
import http.server
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCAL = "127.0.0.1"


class _Scripted(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        srv = self.server
        srv.seen.append(self.headers.get("X-EGM-Token"))
        status = srv.statuses[min(len(srv.seen) - 1, len(srv.statuses) - 1)]
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


@contextmanager
def _stand_in(*statuses):
    """A program on a port that answers every GET with the next status of the list (the last one repeats)."""
    srv = http.server.ThreadingHTTPServer((LOCAL, 0), _Scripted)
    srv.statuses, srv.seen = statuses, []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _verdict(app_module, port, **kw):
    kw.setdefault("pause", 0)
    kw.setdefault("patience", 3)
    return app_module._port_verdict(LOCAL, port, **kw)


def test_a_program_that_answers_404_has_the_port(app_module):
    with _stand_in(404) as srv:
        assert _verdict(app_module, srv.server_port) == "taken"
        assert srv.seen and all(t == app_module._API_TOKEN for t in srv.seen), "the run's token is what is sent"


def test_a_backend_with_another_token_has_the_port(app_module):
    with _stand_in(403) as srv:                      # a leftover backend answers 403 to this run's token
        assert _verdict(app_module, srv.server_port) == "taken"


def test_one_good_answer_is_not_enough(app_module):
    with _stand_in(200, 404) as srv:                 # answers well once, then the other program answers
        assert _verdict(app_module, srv.server_port) == "taken"
        assert len(srv.seen) == 2


def test_three_good_answers_in_a_row_mean_the_port_is_ours(app_module):
    with _stand_in(200) as srv:
        assert _verdict(app_module, srv.server_port) == "ours"
        assert len(srv.seen) == 3


def test_a_late_bad_answer_still_counts(app_module):
    with _stand_in(200, 200, 404) as srv:
        assert _verdict(app_module, srv.server_port) == "taken"


def test_a_program_that_is_not_speaking_http_has_the_port(app_module):
    srv = socket.socket()
    srv.bind((LOCAL, 0))
    srv.listen(5)

    def garbage():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            conn.sendall(b"not http at all\r\n\r\n")
            conn.close()
    threading.Thread(target=garbage, daemon=True).start()
    try:
        assert _verdict(app_module, srv.getsockname()[1]) == "taken"
    finally:
        srv.close()


def test_the_real_backend_answers_ours(app_module):
    from werkzeug.serving import make_server
    server = make_server(LOCAL, 0, app_module.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _verdict(app_module, server.server_port) == "ours"
    finally:
        server.shutdown()
        server.server_close()


def test_nothing_answering_is_never_taken(app_module):
    probe = socket.socket()
    probe.bind((LOCAL, 0))
    port = probe.getsockname()[1]
    probe.close()                                    # nothing listens here
    started = time.monotonic()
    assert _verdict(app_module, port, patience=0.3) == "unknown"
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("answers, expected", [
    ([200, None, None, None, None, None, None, None, None, None, None, None, None, None], "unknown"),
    ([None, None, 200, 200, 200], "ours"),           # slow start: a few refusals first
    ([200, None, 200, None, 200], "ours"),
    ([None, None, 404], "taken"),
    ([200, 200, None, 403], "taken"),
])
def test_the_answers_are_taken_one_by_one(app_module, monkeypatch, answers, expected):
    it = iter(answers)
    monkeypatch.setattr(app_module, "_probe_own_port", lambda host, port: next(it, None))
    assert _verdict(app_module, 1, patience=0.3) == expected


def test_only_a_taken_port_ends_the_backend_with_code_3(app_module, monkeypatch):
    exits = []
    monkeypatch.setattr(app_module.os, "_exit", lambda code: exits.append(code))
    for verdict, expected in (("ours", []), ("unknown", []), ("taken", [3])):
        exits.clear()
        monkeypatch.setattr(app_module, "_port_verdict", lambda host, port, v=verdict: v)
        app_module._watch_own_port(LOCAL, 8899)
        assert exits == expected, verdict


def test_the_check_starts_under_electron_only_after_the_server_thread():
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    main = src[src.index('if __name__ == "__main__":'):]
    start = 'threading.Thread(target=_watch_own_port, args=(host, port), daemon=True, name="port-check").start()'
    assert main.count(start) == 1
    guard = main.index('if os.environ.get("EGM_ELECTRON") == "1":', main.index('name="flask").start()'))
    assert guard < main.index(start) < main.index('name="template-warmup"'), (
        "the check starts under Electron only, right after the server thread")
    assert main[guard:main.index(start)].count("\n") == 1, "nothing else sits between the guard and the start"
