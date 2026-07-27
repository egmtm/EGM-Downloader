"""Raw ffmpeg stderr capture guards.

Adds a fourth ring alongside the diagnostic (_LOG_RING), yt-dlp (_YT_RING),
and Flask (_FLASK_RING) rings: raw stderr from _run_h264_encode's directly
-spawned ffmpeg process. Deliberately scoped to that process only -- not
yt-dlp's internal postprocessing ffmpeg (its output arrives on yt-dlp's own
stderr, not cleanly separable), and not the short capture_output=True probe
calls (hw encoder detection, duration probing -- synchronous, not worth a
live stream).

Memory-only like _YT_RING/_FLASK_RING: ffmpeg stderr can echo local file
paths, so this must never reach egm_debug.log.

stdout on the ffmpeg Popen must stay binary (_pump_encode_progress does its
own manual bytes.decode() on -progress pipe:1 lines), so stderr is also
left binary and decoded manually in _drain_ffmpeg_stderr -- text=True on
Popen would have applied to stdout too and broken the existing progress
reader.
"""
import re

from conftest import PLATFORM_APP_FILES, read_source


def test_ffmpeg_ring_present_on_all_platforms():
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        assert "_FFMPEG_RING: list = []" in src, f"{p}: missing the ffmpeg output ring"
        assert "def _ffmpeg_log(" in src, f"{p}: missing _ffmpeg_log"
        assert "def _drain_ffmpeg_stderr(" in src, f"{p}: missing _drain_ffmpeg_stderr"


def test_ffmpeg_ring_never_writes_to_disk_log():
    """_ffmpeg_log must never call the disk-log write path -- memory-only
    by design, same reasoning as _YT_RING/_FLASK_RING."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index("def _ffmpeg_log")
        j = src.index("def _drain_ffmpeg_stderr")
        block = src[i:j]
        assert "_atomic_write_text" not in block, (
            f"{p}: _ffmpeg_log must not write to disk"
        )
        assert "open(" not in block and ".write(" not in block, (
            f"{p}: _ffmpeg_log must not perform any file write"
        )


def test_api_logs_supports_ffmpeg_toggle_on_all_platforms():
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index('@app.route("/api/logs")')
        block = src[i:i + 1100]
        assert 'request.args.get("ffmpeg", 0, type=int)' in block, (
            f"{p}: /api/logs missing the ffmpeg query param"
        )
        assert '"ffmpeg_lines"' in block and '"ffmpeg_next"' in block, (
            f"{p}: /api/logs missing ffmpeg_lines/ffmpeg_next in the response"
        )


def test_stdtee_class_is_not_accidentally_split():
    """Permanent guard against the exact mistake this session risked: the
    ffmpeg ring insertion landing *inside* the _StdTee class body (between
    two of its methods), which silently ends the class early since Python
    class bodies end at the first de-indented line. ast.parse() alone does
    NOT catch this -- it's syntactically valid Python, just structurally
    wrong -- so this asserts the real method list via AST."""
    import ast

    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "_StdTee":
                found = True
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                assert methods == ["__init__", "write", "flush", "isatty", "__getattr__"], (
                    f"{p}: _StdTee methods out of shape (class likely split): {methods}"
                )
        assert found, f"{p}: _StdTee class not found"


def test_h264_encode_pipes_stderr_instead_of_discarding_it():
    """ffmpeg's stderr must now be piped (not DEVNULL) so it can be
    drained into _ffmpeg_log. start_new_session=True (the killpg process
    -group isolation fix) must survive on mac/linux -- but Windows app.py
    genuinely never had this argument (PID-tree-scoped taskkill instead
    of Unix process groups), so it's correctly absent there."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index("def _run_h264_encode")
        j = src.index("def ", i + 10)
        block = src[i:j]
        assert "stderr=subprocess.PIPE" in block, (
            f"{p}: ffmpeg spawn must pipe stderr, not discard it"
        )
        assert "stderr=subprocess.DEVNULL" not in block, (
            f"{p}: ffmpeg spawn still discards stderr"
        )
        assert "_drain_ffmpeg_stderr" in block, (
            f"{p}: ffmpeg spawn must start the stderr-draining thread"
        )
        if p != "app.py":
            assert "start_new_session=True" in block, (
                f"{p}: killpg process-group isolation fix must survive"
            )


def test_pump_encode_progress_stdout_reading_is_unaffected():
    """The ffmpeg Popen must stay binary overall (no text=True) -- that
    kwarg applies to stdout as well as stderr, and _pump_encode_progress
    does its own manual bytes.decode() on stdout. Piping stderr must not
    have flipped the process into text mode."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index("def _run_h264_encode")
        j = src.index("def ", i + 10)
        block = src[i:j]
        popen_m = re.search(r"proc = _popen\(\*cmd,.*?\)\n", block, re.DOTALL)
        assert popen_m, f"{p}: could not locate the ffmpeg _popen(...) call"
        popen_call = popen_m.group(0)
        assert "text=True" not in popen_call, (
            f"{p}: ffmpeg Popen call must not be text=True -- would break "
            f"_pump_encode_progress's manual bytes.decode() on stdout"
        )


def test_drain_ffmpeg_stderr_never_raises_against_a_bare_mock_process():
    """The regression this session actually hit: tests elsewhere
    (test_hw_encode_slots.py) monkeypatch _popen to return bare fake
    objects with no .stderr attribute. _pump_encode_progress tolerates
    this by design (broad try/except, documented as 'never raises').
    _drain_ffmpeg_stderr must have the identical contract, or a bare
    mock leaks an AttributeError into a background thread and pytest's
    thread-exception hook fails unrelated tests running at the time."""
    src = read_source("app.py")
    m = re.search(
        r"def _drain_ffmpeg_stderr\(p\):.*?(?=\nsys\.stdout = _StdTee)",
        src, re.DOTALL,
    )
    assert m, "could not locate _drain_ffmpeg_stderr source"
    func_src = m.group(0)

    class FailThenSucceed:
        """Bare fake process object, same shape as the existing
        test_hw_encode_slots.py mocks -- .pid/.returncode/.wait() only,
        no .stdout/.stderr."""
        pid = 1234
        returncode = 0

        def wait(self):
            return 0

    namespace = {}
    exec(func_src, namespace)
    drain = namespace["_drain_ffmpeg_stderr"]

    # No .stderr attribute at all -- must not raise.
    drain(FailThenSucceed())

    class HasNoneStderr:
        stderr = None

    drain(HasNoneStderr())  # must also not raise


def test_ffmpeg_drain_thread_actually_captures_real_subprocess_output():
    """Spawns a real child process and drains its real stderr through the
    actual _drain_ffmpeg_stderr / _ffmpeg_log functions extracted from
    source -- not a reimplementation. Confirms genuine output capture,
    not just that the resilience wrapper swallows errors silently."""
    import subprocess
    import sys as _sys
    import threading
    import time

    src = read_source("app.py")
    ring_m = re.search(
        r"_FFMPEG_RING: list = \[\].*?(?=\nsys\.stdout = _StdTee)",
        src, re.DOTALL,
    )
    assert ring_m, "could not locate ffmpeg ring block"

    namespace = {
        "threading": threading,
        "time": time,
        "_LOG_RING_LOCK": threading.Lock(),
        "_LOG_RING_MAX": 1000,
    }
    exec(ring_m.group(0), namespace)
    drain = namespace["_drain_ffmpeg_stderr"]
    ring = namespace["_FFMPEG_RING"]

    proc = subprocess.Popen(
        [_sys.executable, "-c",
         "import sys; sys.stderr.write('hello from child\\n'); "
         "sys.stderr.write('second line\\n'); sys.stderr.flush()"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    t = threading.Thread(target=drain, args=(proc,), daemon=True)
    t.start()
    proc.wait(timeout=10)
    t.join(timeout=5)

    messages = [e["m"] for e in ring]
    assert "hello from child" in messages
    assert "second line" in messages


def test_ffmpeg_toggle_i18n_key_translated_across_all_locales():
    import json
    import os

    lang_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "languages")
    en = json.load(open(os.path.join(lang_dir, "en.json")))["strings"]
    assert "console.toggle.ffmpeg" in en
    locales = ["ar", "de", "es", "fr", "it", "ja", "nl", "pt", "ru"]
    for loc in locales:
        d = json.load(open(os.path.join(lang_dir, f"{loc}.json")))["strings"]
        assert "console.toggle.ffmpeg" in d, f"{loc}: missing console.toggle.ffmpeg"
        # Genuine translation, not an English copy left behind.
        assert d["console.toggle.ffmpeg"] != en["console.toggle.ffmpeg"], (
            f"{loc}: console.toggle.ffmpeg still reads as the English placeholder"
        )


def test_ffmpeg_toggle_present_in_console_html_and_mirrored_on_linux():
    root = read_source("templates/console.html")
    linux = read_source("linux/templates/console.html")
    assert root == linux, "templates/console.html and its Linux mirror have diverged"
    for marker in ("ffmpeg-toggle", "console.toggle.ffmpeg", "ffmpeg_lines",
                   "egm-console-ffmpeg", "log-line.ffmpeg"):
        assert marker in root, f"console.html missing expected ffmpeg marker: {marker}"
