"""Raw Flask stdout/stderr capture guards.

Adds a third ring alongside the diagnostic (_LOG_RING) and yt-dlp
(_YT_RING) rings: everything that would print to a terminal running the
app directly -- Werkzeug's own request logging, print()s, uncaught
tracebacks -- unfiltered, per EGM's explicit request. Captured by
redirecting sys.stdout/sys.stderr through a line-buffering Tee inside
app.py itself, rather than piping the subprocess at the Electron level --
keeps this entirely inside the existing /api/logs polling architecture,
no main.js/preload.js changes needed.

Memory-only like _YT_RING: a traceback can embed a full local path, so
this must never reach egm_debug.log, the file the support field protocol
asks users to email in.
"""
import re

from conftest import PLATFORM_APP_FILES, read_source


def test_flask_ring_and_tee_present_on_all_platforms():
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        assert "_FLASK_RING: list = []" in src, f"{p}: missing the flask output ring"
        assert "class _StdTee" in src, f"{p}: missing the StdTee class"
        assert "sys.stdout = _StdTee(sys.stdout)" in src, f"{p}: stdout not redirected"
        assert "sys.stderr = _StdTee(sys.stderr)" in src, f"{p}: stderr not redirected"


def test_flask_ring_never_writes_to_disk_log():
    """_flask_raw_log and _StdTee must never call the disk-log write path --
    this ring is memory-only by design, same reasoning as _YT_RING."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index("def _flask_raw_log")
        j = src.index("class _StdTee")
        block = src[i:j]
        assert "_atomic_write_text" not in block, (
            f"{p}: _flask_raw_log must not write to disk"
        )
        assert "open(" not in block and ".write(" not in block, (
            f"{p}: _flask_raw_log must not perform any file write"
        )


def test_api_logs_supports_flask_toggle_on_all_platforms():
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index('@app.route("/api/logs")')
        block = src[i:i + 900]
        assert 'request.args.get("flask", 0, type=int)' in block, (
            f"{p}: /api/logs missing the flask query param"
        )
        assert '"flask_lines"' in block and '"flask_next"' in block, (
            f"{p}: /api/logs missing flask_lines/flask_next in the response"
        )


def test_stdtee_reassembles_partial_writes_and_is_thread_safe():
    """Executes the REAL _StdTee class extracted from the actual source,
    not a reimplementation -- proves partial-write reassembly and
    concurrent-thread safety against the real code, not an assumption
    about how it should behave."""
    import threading

    src = read_source("app.py")
    m = re.search(r"class _StdTee:.*?\n\nsys\.stdout", src, re.DOTALL)
    class_src = m.group(0).rsplit("\n\nsys.stdout", 1)[0]

    captured = []
    lock = threading.Lock()

    def _flask_raw_log(line):
        with lock:
            captured.append(line)

    namespace = {"_flask_raw_log": _flask_raw_log}
    exec(class_src, namespace)
    StdTee = namespace["_StdTee"]

    class FakeReal:
        def write(self, s):
            pass

        def flush(self):
            pass

    tee = StdTee(FakeReal())
    tee.write("partial")
    tee.write(" line completed across two write() calls\n")
    assert "partial line completed across two write() calls" in captured

    def worker():
        for i in range(20):
            tee.write(f"line {i}\n")

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for c in captured if c.startswith("line ")) == 100, (
        "concurrent writes from multiple threads must not lose or corrupt lines"
    )


def test_flask_toggle_i18n_key_translated_across_all_locales():
    import json
    import os

    lang_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "languages")
    en = json.load(open(os.path.join(lang_dir, "en.json")))["strings"]
    assert "console.toggle.flask" in en
    locales = ["ar", "de", "es", "fr", "it", "ja", "nl", "pt", "ru"]
    for loc in locales:
        d = json.load(open(os.path.join(lang_dir, f"{loc}.json")))["strings"]
        assert "console.toggle.flask" in d, f"{loc}: missing console.toggle.flask"
