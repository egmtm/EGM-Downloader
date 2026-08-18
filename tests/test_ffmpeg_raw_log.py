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


# ── Hardening added in the delta review of 404b751 ────────────────────────────

def _load_real_drain(captured):
    """The real _drain_ffmpeg_stderr from source, with a working
    _ffmpeg_log bound in its namespace.

    The namespace matters: exec'ing this function with an EMPTY namespace
    would leave _ffmpeg_log undefined. Any mock that DOES yield a line
    would then raise NameError *inside* the function's own resilience
    wrapper -- swallowed, so a test would pass while capturing nothing.
    Binding it here keeps the capture assertions below honest."""
    import re as _re

    src = read_source("app.py")
    m = _re.search(r"def _drain_ffmpeg_stderr\(p\):.*?(?=\nsys\.stdout = _StdTee)",
                   src, _re.DOTALL)
    assert m, "could not locate _drain_ffmpeg_stderr source"
    namespace = {"_ffmpeg_log": captured.append}
    exec(m.group(0), namespace)
    return namespace["_drain_ffmpeg_stderr"]


class _FakeStderr:
    """Minimal binary pipe stand-in: yields the given chunks, then EOF."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def readline(self):
        return self._chunks.pop(0) if self._chunks else b""


def test_drain_captures_lines_when_the_log_hook_is_actually_bound():
    """Guards the vacuity described in _load_real_drain: with a real
    _ffmpeg_log bound, a line-yielding process must genuinely capture."""
    captured = []
    drain = _load_real_drain(captured)

    class P:
        stderr = _FakeStderr([b"frame= 100 fps=25\n", b"[libx264] encoded 42 frames\n"])

    drain(P())
    assert captured == ["frame= 100 fps=25", "[libx264] encoded 42 frames"]


def test_drain_survives_every_hostile_stream_shape():
    """The 'never raises' contract, exercised against every shape a live
    subprocess or a test mock can actually present -- a bare object with no
    .stderr attribute at all (test_hw_encode_slots.py monkeypatches _popen
    to return exactly this), a .stderr that's explicitly None, a readline()
    that raises, and a readline() that returns something that isn't bytes.
    Without this contract matching _pump_encode_progress's identical 'never
    raises' guarantee, a bare mock leaks an exception into a background
    thread and pytest's thread-exception hook fails unrelated tests running
    at the time. Each case must return cleanly AND leave the process object
    usable by the caller."""
    captured = []
    drain = _load_real_drain(captured)

    class NoStderrAttr:
        pass

    class NoneStderr:
        stderr = None

    class RaisingReadline:
        class S:
            def readline(self):
                raise ValueError("I/O operation on closed file")

        stderr = S()

    class NonBytesReadline:
        class S:
            def readline(self):
                return None      # never equals the b"" sentinel; .decode() fails

        stderr = S()

    for obj in (NoStderrAttr(), NoneStderr(), RaisingReadline(), NonBytesReadline()):
        before = len(captured)
        drain(obj)               # must not raise
        assert len(captured) == before, f"{type(obj).__name__} should capture nothing"


def test_drain_decodes_invalid_utf8_without_losing_the_line():
    """ffmpeg stderr is binary and can carry non-UTF-8 bytes (a filename in
    a legacy encoding). The line must survive with replacement chars rather
    than raising and killing the drain -- which would stop the pipe from
    being read at all (see the deadlock test below)."""
    captured = []
    drain = _load_real_drain(captured)

    class P:
        stderr = _FakeStderr([b"\xff\xfe bad bytes here\n", b"still draining\n"])

    drain(P())
    assert len(captured) == 2, "an undecodable line must not abort the drain"
    assert "bad bytes here" in captured[0]
    assert captured[1] == "still draining"


def test_ffmpeg_stderr_pipe_cannot_deadlock_the_encode():
    """The load-bearing property of piping stderr instead of DEVNULL: a
    process writing far more than the OS pipe buffer (~64KB) must still
    exit, because the drain thread keeps reading. If the drain is ever
    removed, made conditional on the toggle, or started after proc.wait(),
    ffmpeg blocks forever on a full stderr pipe and the encode hangs with
    the card stuck on 'Converting…'. Uses a real child process and the
    real drain function.
    """
    import subprocess
    import sys as _sys
    import threading

    captured = []
    drain = _load_real_drain(captured)

    # ~210KB of stderr: >3x a typical 64KB pipe buffer.
    child = subprocess.Popen(
        [_sys.executable, "-c",
         "import sys\n"
         "for i in range(3000):\n"
         "    sys.stderr.write('noisy ffmpeg stderr line %d ' % i + 'x' * 50 + chr(10))\n"
         "sys.stderr.flush()\n"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    t = threading.Thread(target=drain, args=(child,), daemon=True)
    t.start()
    assert child.wait(timeout=30) == 0, "child blocked on a full stderr pipe"
    t.join(timeout=10)
    assert not t.is_alive(), "drain thread must exit at EOF"
    assert len(captured) == 3000, f"captured {len(captured)}/3000 lines"


def test_drain_thread_is_actually_started_before_proc_wait():
    """The spawn-site guard above asserts `"_drain_ffmpeg_stderr" in block`
    -- which the explanatory NOTE comment above the _popen call satisfies
    on its own. Deleting the real `threading.Thread(target=
    _drain_ffmpeg_stderr, ...).start()` line therefore passes it, and that
    deletion is precisely what reintroduces the pipe deadlock: stderr is
    piped but never read, so ffmpeg blocks once the ~64KB buffer fills and
    proc.wait() never returns.

    This asserts the executable facts instead: the thread is genuinely
    started (comments stripped first), and started BEFORE proc.wait() --
    starting it after would deadlock exactly the same way.
    """
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index("def _run_h264_encode")
        j = src.index("def ", i + 10)
        block = src[i:j]
        code = "\n".join(
            ln for ln in block.split("\n") if not ln.lstrip().startswith("#")
        )

        def _thread_start_index(target):
            """Index of a real `threading.Thread(target=<target>...).start()`
            in the comment-stripped code, or None. Deliberately not one
            regex: `args=(proc,)` contains a ')', so a naive `[^)]*` never
            reaches `.start()` and the assertion would fail (or pass)
            for the wrong reason."""
            for tm in re.finditer(r"threading\.Thread\(", code):
                tail = code[tm.start():tm.start() + 200]
                if f"target={target}" in tail and ".start()" in tail:
                    return tm.start()
            return None

        drain_at = _thread_start_index("_drain_ffmpeg_stderr")
        assert drain_at is not None, (
            f"{p}: no real threading.Thread(target=_drain_ffmpeg_stderr...).start() "
            f"call in _run_h264_encode -- piping stderr without draining it "
            f"deadlocks the encode once the pipe buffer fills"
        )

        wait_idx = code.index("proc.wait()")
        assert drain_at < wait_idx, (
            f"{p}: the stderr drain thread must start BEFORE proc.wait() -- "
            f"starting it afterwards deadlocks on a full stderr pipe"
        )

        # Same property for the stdout pump, which shares the deadlock risk.
        pump_at = _thread_start_index("_pump_encode_progress")
        assert pump_at is not None and pump_at < wait_idx, (
            f"{p}: the stdout pump thread must start before proc.wait()"
        )


# ── hw-encoder probe failure output now routes into the ffmpeg ring ──────────

def test_hw_probe_failure_helper_present_on_all_platforms():
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        assert "def _log_hw_probe_failure(" in src, (
            f"{p}: missing _log_hw_probe_failure"
        )
        i = src.index("def _detect_hw_encoder")
        j = src.index("def ", i + 10)
        block = src[i:j]
        assert "_log_hw_probe_failure(name, r.stderr)" in block, (
            f"{p}: hw-probe non-zero-returncode path must route stderr into "
            f"the ffmpeg ring"
        )
        assert "_log_hw_probe_failure(name, str(e))" in block, (
            f"{p}: hw-probe exception path must route the failure into "
            f"the ffmpeg ring too"
        )


def test_hw_probe_failure_helper_never_writes_to_disk_log():
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index("def _log_hw_probe_failure")
        j = src.index("def _detect_hw_encoder")
        block = src[i:j]
        assert "_atomic_write_text" not in block, (
            f"{p}: _log_hw_probe_failure must not write to disk"
        )
        assert "open(" not in block, (
            f"{p}: _log_hw_probe_failure must not perform any file write"
        )


def test_hw_probe_failure_helper_feeds_the_real_ffmpeg_ring():
    """Executes the REAL _log_hw_probe_failure + _ffmpeg_log pair extracted
    from source, confirms multi-line probe stderr lands in the ring with
    the per-candidate prefix, blank lines are dropped, and an empty/None
    message is a silent no-op (nothing to report)."""
    src = read_source("app.py")
    m = re.search(
        r"_FFMPEG_RING: list = \[\].*?(?=\nsys\.stdout = _StdTee)",
        src, re.DOTALL,
    )
    assert m, "could not locate the ffmpeg ring block"
    ring_and_log_src = m.group(0)

    hw_m = re.search(
        r"\ndef _log_hw_probe_failure\(name, text\):.*?(?=\ndef _detect_hw_encoder)",
        src, re.DOTALL,
    )
    assert hw_m, "could not locate _log_hw_probe_failure"

    namespace = {
        "threading": __import__("threading"),
        "time": __import__("time"),
        "_LOG_RING_LOCK": __import__("threading").Lock(),
        "_LOG_RING_MAX": 1000,
    }
    exec(ring_and_log_src, namespace)
    exec(hw_m.group(0), namespace)
    log_failure = namespace["_log_hw_probe_failure"]
    ring = namespace["_FFMPEG_RING"]

    log_failure("h264_nvenc", "Cannot load nvcuda.dll\n\n[error] init failed\n")
    messages = [e["m"] for e in ring]
    assert "[hw-probe:h264_nvenc] Cannot load nvcuda.dll" in messages
    assert "[hw-probe:h264_nvenc] [error] init failed" in messages
    assert "" not in messages, "blank lines must not be logged"

    before = len(ring)
    log_failure("h264_qsv", "")
    log_failure("h264_amf", None)
    assert len(ring) == before, "empty/None probe output must be a no-op"


def test_ffmpeg_log_defined_before_detect_hw_encoder_on_all_platforms():
    """_detect_hw_encoder calls _log_hw_probe_failure, which calls
    _ffmpeg_log -- source-order sanity so the helper isn't referencing a
    name that (at module load, before any call happens) doesn't exist yet
    further down the file. Python's late binding tolerates this at
    definition time either way, but wrong order would be a readability/
    maintenance trap, so it's asserted directly."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        ffmpeg_log_at = src.index("def _ffmpeg_log(")
        detect_at = src.index("def _detect_hw_encoder(")
        assert ffmpeg_log_at < detect_at, (
            f"{p}: _ffmpeg_log must be defined before _detect_hw_encoder"
        )


# ── Diagnostics toggle labels shortened, full text moved to a tooltip ────────

def test_toggle_labels_shortened_with_full_text_as_tooltip():
    root = read_source("templates/console.html")
    linux = read_source("linux/templates/console.html")
    assert root == linux, "templates/console.html and its Linux mirror have diverged"

    for tool, label_key, sentence_key in (
        ("yt-dlp", "console.toggle.ytdlp.label", "console.toggle.ytdlp"),
        ("Flask", "console.toggle.flask.label", "console.toggle.flask"),
        ("ffmpeg", "console.toggle.ffmpeg.label", "console.toggle.ffmpeg"),
    ):
        assert f'data-i18n="{label_key}"' in root, (
            f"missing short-label i18n wiring for {tool}"
        )
        assert f'data-i18n-attr="title:{sentence_key}"' in root, (
            f"missing tooltip i18n wiring for {tool} (full sentence should "
            f"move to a title= tooltip, not stay as the visible label)"
        )
    # The old long-form visible labels must be gone from the visible span --
    # they now live only in the title= attribute.
    assert "Show yt-dlp output</span>" not in root
    assert "Show Flask output</span>" not in root
    assert "Show ffmpeg output</span>" not in root


def test_toggle_label_i18n_keys_are_untranslated_tool_names_everywhere():
    """yt-dlp/Flask/ffmpeg are tool/brand names -- per standing convention
    (same as theme names) these must NOT be translated, so the .label
    value must be identical across every locale, unlike the full-sentence
    tooltip text which genuinely varies per language."""
    import json
    import os

    lang_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "languages")
    expected = {
        "console.toggle.ytdlp.label": "yt-dlp",
        "console.toggle.flask.label": "Flask",
        "console.toggle.ffmpeg.label": "ffmpeg",
    }
    locales = ["ar", "de", "en", "es", "fr", "it", "ja", "nl", "pt", "ru"]
    for loc in locales:
        d = json.load(open(os.path.join(lang_dir, f"{loc}.json"), encoding="utf-8"))["strings"]
        for key, value in expected.items():
            assert key in d, f"{loc}: missing {key}"
            assert d[key] == value, (
                f"{loc}: {key} must stay '{value}' (tool/brand name, "
                f"not translated) but is {d[key]!r}"
            )



# ── Hardening added in the delta review of 98b9271..c2cc477 ───────────────────

def _load_real_hw_probe_logger():
    """The real _FFMPEG_RING/_ffmpeg_log/_log_hw_probe_failure trio from
    source, wired together in one namespace. Returns (log_failure, ring)."""
    import threading as _threading
    import time as _time

    src = read_source("app.py")
    ring_m = re.search(r"_FFMPEG_RING: list = \[\].*?(?=\nsys\.stdout = _StdTee)",
                       src, re.DOTALL)
    hw_m = re.search(r"\ndef _log_hw_probe_failure\(name, text\):.*?(?=\ndef _detect_hw_encoder)",
                     src, re.DOTALL)
    assert ring_m and hw_m, "could not locate the ring / hw-probe helper"
    ns = {"threading": _threading, "time": _time,
          "_LOG_RING_LOCK": _threading.Lock(), "_LOG_RING_MAX": 1000}
    exec(ring_m.group(0), ns)
    exec(hw_m.group(0), ns)
    return ns["_log_hw_probe_failure"], ns["_FFMPEG_RING"]


def test_hw_probe_blank_lines_are_genuinely_dropped():
    """Tightens the blank-line assertion in
    test_hw_probe_failure_helper_feeds_the_real_ffmpeg_ring, which checks
    `"" not in messages`. That can never fail: a blank line would be logged
    as the PREFIX plus a space ('[hw-probe:x] '), never as a bare ''. So
    removing the `if line:` guard leaves that test green while the ring
    fills with prefix-only filler.

    Asserts the property that actually distinguishes the two: no ring entry
    is just the prefix, and the exact line count is what was fed."""
    log_failure, ring = _load_real_hw_probe_logger()

    log_failure("h264_nvenc", "first\n\n   \nsecond\n\n")
    messages = [e["m"] for e in ring]

    assert messages == ["[hw-probe:h264_nvenc] first",
                        "[hw-probe:h264_nvenc] second"], messages
    assert not any(msg.strip() == "[hw-probe:h264_nvenc]" for msg in messages), (
        "blank/whitespace-only probe lines must be dropped, not logged as a "
        "bare prefix"
    )


def test_every_hw_probe_line_carries_its_own_prefix():
    """The anti-impersonation property, which only holds because the helper
    splits and prefixes PER LINE.

    Probe stderr is third-party text. If it were logged as one blob
    (`_ffmpeg_log(text)`), every line after the first would appear in the
    ring with no prefix -- and since the console renders with
    `white-space: pre-wrap`, a crafted line could then pose as output from a
    different candidate, or as a non-probe ffmpeg line. Per-line prefixing
    makes that impossible: an embedded fake prefix is always preceded by the
    real one.
    """
    log_failure, ring = _load_real_hw_probe_logger()

    hostile = ("real failure line\n"
               "[hw-probe:h264_nvenc] pretending to be another candidate\n"
               "plain line that would be unprefixed in a blob")
    log_failure("h264_qsv", hostile)

    messages = [e["m"] for e in ring]
    assert len(messages) == 3
    for msg in messages:
        assert msg.startswith("[hw-probe:h264_qsv] "), (
            f"every probe line must carry its own prefix, got: {msg!r}"
        )
    # The impersonation attempt survives only as *content*, behind the real prefix.
    assert messages[1] == (
        "[hw-probe:h264_qsv] [hw-probe:h264_nvenc] pretending to be another candidate"
    )


def test_hw_probe_splits_on_all_line_terminators():
    """splitlines() (not split('\\n')) is what keeps the per-line prefix
    guarantee honest against \\r\\n and the Unicode line separators a
    driver-generated message could carry -- each fragment gets its own
    prefix rather than riding along inside one entry."""
    log_failure, ring = _load_real_hw_probe_logger()

    log_failure("h264_amf", "crlf line\r\nu2028 line u2029 line last")
    messages = [e["m"] for e in ring]
    assert len(messages) == 4, messages
    assert all(m.startswith("[hw-probe:h264_amf] ") for m in messages)
    assert not any(" " in m or " " in m or "\r" in m for m in messages), (
        "line terminators must not survive inside a ring entry"
    )
