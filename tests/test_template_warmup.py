"""Template warm-up: each backend renders index.html once in a background thread as soon as the
server is listening, so the templates are compiled before the shell's first successful poll. The
request for / and the warm-up share one lock around their render: a request arriving mid-warm-up
waits for the compile instead of repeating it in parallel, and a request arriving before the warm-up
has started compiles the templates itself exactly as today. Outside the __main__ block the lock is
never contended and nothing changes: the page bytes are identical."""
import hashlib
import os
import re
import socket
import subprocess
import sys
import threading
import time

from conftest import PLATFORM_APP_FILES, ROOT, read_source

HELPER_START = "_TEMPLATES_LOCK = threading.Lock()\n\ndef _warm_templates(host=None, port=None):"
RENDER = ('        with _TEMPLATES_LOCK:\n'
          '            app.jinja_env.get_template("index.html").render(egm_token="", platform_url="")\n')
MAIN_START = ('    threading.Thread(target=_warm_templates, args=(host, port), daemon=True, '
              'name="template-warmup").start()\n')
INDEX = ('def index():\n    with _TEMPLATES_LOCK:\n'
         '        return render_template("index.html", egm_token=_API_TOKEN')


def _helper(src):
    a = src.index("# ── Template warm-up")
    return src[a:src.index('@app.route("/")', a)]


def _include_closure(name, seen=None):
    """index.html and every template it includes, transitively, read from the template files."""
    seen = seen if seen is not None else set()
    if name in seen:
        return seen
    seen.add(name)
    src = read_source(os.path.join("templates", name))
    for inc in re.findall(r"""{%-?\s*include\s+["']([^"']+)["']""", src):
        _include_closure(inc, seen)
    return seen


def _lock_is_free(app_module):
    got = app_module._TEMPLATES_LOCK.acquire(blocking=False)
    if got:
        app_module._TEMPLATES_LOCK.release()
    return got


def _cached_names(app_module):
    return {key[1] for key in app_module.app.jinja_env.cache.keys()}


def test_every_backend_has_the_identical_warm_up():
    base = _helper(read_source(PLATFORM_APP_FILES[0]))
    assert HELPER_START in base and RENDER in base
    for p in PLATFORM_APP_FILES:
        s = read_source(p)
        assert _helper(s) == base, p
        assert s.count(INDEX) == 1, p
        assert s.count(MAIN_START) == 1, p
        main = s.index('if __name__ == "__main__":')
        # the warm-up thread is started inside __main__, right after the Flask thread, with the
        # server's host and port
        assert main < s.index('name="flask").start()') < s.index(MAIN_START), p


def test_the_lock_is_free_outside_main(app_module):
    assert _lock_is_free(app_module)


def test_warm_up_compiles_index_and_everything_it_includes(app_module):
    wanted = _include_closure("index.html")
    assert len(wanted) >= 15, wanted
    app_module.app.jinja_env.cache.clear()
    app_module._warm_templates()
    assert wanted <= _cached_names(app_module), wanted - _cached_names(app_module)
    assert _lock_is_free(app_module)


def test_warm_up_never_raises_and_leaves_the_lock_free(app_module, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("template broken")
    monkeypatch.setattr(app_module.app.jinja_env, "get_template", boom)
    app_module._warm_templates()
    assert _lock_is_free(app_module)


def test_warm_up_starts_compiling_only_once_the_port_accepts(app_module):
    """Bound but not yet listening: the thread keeps waiting without holding the lock; after
    listen() it compiles."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    app_module.app.jinja_env.cache.clear()
    try:
        th = threading.Thread(target=app_module._warm_templates, args=("127.0.0.1", port), daemon=True)
        th.start()
        time.sleep(0.3)
        assert th.is_alive()
        assert "index.html" not in _cached_names(app_module)
        assert _lock_is_free(app_module)
        srv.listen(1)
        th.join(20)
        assert not th.is_alive()
        assert _include_closure("index.html") <= _cached_names(app_module)
        assert _lock_is_free(app_module)
    finally:
        srv.close()


def test_warm_up_gives_up_waiting_for_the_port_after_five_seconds(app_module):
    """Nothing ever listens: the thread still compiles and returns."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))      # bound, never listening: every connect is refused
    port = srv.getsockname()[1]
    app_module.app.jinja_env.cache.clear()
    try:
        t0 = time.perf_counter()
        app_module._warm_templates("127.0.0.1", port)
        elapsed = time.perf_counter() - t0
        assert 4.5 <= elapsed <= 8.0, elapsed
        assert _include_closure("index.html") <= _cached_names(app_module)
        assert _lock_is_free(app_module)
    finally:
        srv.close()


def test_index_waits_while_the_warm_up_holds_the_lock(app_module):
    app_module._TEMPLATES_LOCK.acquire()
    try:
        threading.Timer(0.3, app_module._TEMPLATES_LOCK.release).start()
        t0 = time.perf_counter()
        with app_module.app.test_client() as c:
            r = c.get("/")
        assert r.status_code == 200
        assert time.perf_counter() - t0 >= 0.25
    finally:
        if not _lock_is_free(app_module):
            app_module._TEMPLATES_LOCK.release()


def test_index_compiles_the_templates_itself_when_the_warm_up_has_not_started(app_module):
    app_module.app.jinja_env.cache.clear()
    assert _lock_is_free(app_module)
    with app_module.app.test_client() as c:
        r = c.get("/")
    assert r.status_code == 200
    assert _include_closure("index.html") <= _cached_names(app_module)
    assert _lock_is_free(app_module)


def test_the_page_bytes_are_identical_with_and_without_the_warm_up():
    """Two fresh processes: one serves / cold, the other after _warm_templates(). Same bytes."""
    code = ("import sys, hashlib, importlib.util; sys.argv = ['app.py']\n"
            "spec = importlib.util.spec_from_file_location('app', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "if %r: m._warm_templates()\n"
            "with m.app.test_client() as c: print(hashlib.sha256(c.get('/').data).hexdigest())\n")
    app_py = os.path.join(ROOT, "app.py")
    out = []
    for warm in (False, True):
        r = subprocess.run([sys.executable, "-c", code % (app_py, warm)], capture_output=True, text=True,
                           cwd=ROOT, env=dict(os.environ, EGM_API_TOKEN="ci-test-token-not-secret"), timeout=120)
        assert r.returncode == 0, r.stderr
        out.append(r.stdout.strip().splitlines()[-1])
    assert out[0] == out[1] and len(out[0]) == 64, out
