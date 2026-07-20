"""yt-dlp progress-line parsing guard (speed / ETA extraction).

The ETA field sat parsed-but-unused in the status payload for several
releases; the moment v1.3.2 gave it a UI consumer, a latent regex bug became
user-visible: `ETA\\s+(\\d+:\\d+)` captures only ONE colon group, so yt-dlp's
over-an-hour form `ETA 1:23:45` displayed as "ETA 1:23" -- reading as 1m23s
when the truth is 1h23m. Fixed to `(\\d+(?::\\d+){1,2})`.

Also pins two clearing behaviors the UI depends on:
  - a progress line with no ETA match (yt-dlp emits `ETA Unknown` near
    completion) must CLEAR the field, not leave a stale value on screen
    (the assign-or-clear pattern both speed and eta now share), and
  - the merge/convert phase detector must clear BOTH speed and eta --
    the subscriptions queue rows render the meta line regardless of job
    status, so a value left behind here sits on screen through the whole
    conversion.

The regexes are function-local in run_download, so this test extracts the
literal patterns from source (asserting all 3 platforms carry identical
ones) and exercises them against real yt-dlp line shapes.
"""
import re

from conftest import PLATFORM_APP_FILES, read_source

SPEED_RE_LITERAL = r'speed_re = _re.compile(r"at\s+([\d.]+\s*[KMG]iB/s)")'
ETA_RE_SRC = re.compile(r'eta_re\s*=\s*_re\.compile\(r"([^"]+)"\)')


def _extract_eta_pattern(path):
    src = read_source(path)
    m = ETA_RE_SRC.search(src)
    assert m, f"{path}: eta_re not found"
    return m.group(1)


def test_progress_regexes_identical_across_platforms():
    patterns = {p: _extract_eta_pattern(p) for p in PLATFORM_APP_FILES}
    assert len(set(patterns.values())) == 1, f"eta_re drifted: {patterns}"
    for p in PLATFORM_APP_FILES:
        assert SPEED_RE_LITERAL in read_source(p), f"{p}: speed_re changed -- update this guard deliberately"


def test_eta_captures_hours_form_completely():
    """yt-dlp emits `ETA 1:23:45` for >1h downloads; capturing only `1:23`
    misreads hours as minutes on screen."""
    eta_re = re.compile(_extract_eta_pattern("app.py"))
    m = eta_re.search("[download]  47.2% of 1.40GiB at 2.34MiB/s ETA 1:23:45")
    assert m and m.group(1) == "1:23:45", f"captured {m and m.group(1)!r}"
    m = eta_re.search("[download]  47.2% of 140.55MiB at 2.34MiB/s ETA 05:30")
    assert m and m.group(1) == "05:30"


def test_eta_unknown_yields_no_match_so_field_clears():
    eta_re = re.compile(_extract_eta_pattern("app.py"))
    assert eta_re.search("[download]  99.8% of 140.55MiB at 1.02MiB/s ETA Unknown") is None
    # the UI contract: no match -> assign-or-clear writes "" (both fields)
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        assert 'job["eta"] = em.group(1) if em else ""' in src, (
            f"{p}: eta must use the assign-or-clear pattern, not leave stale values"
        )
        assert 'job["speed"] = sm.group(1).strip() if sm else ""' in src, (
            f"{p}: speed must use the assign-or-clear pattern"
        )


def test_merge_phase_clears_both_speed_and_eta():
    """The [Merger]/[VideoRemuxer]/[ExtractAudio] branch flips status to
    converting and must clear BOTH transient fields -- the subscriptions
    queue renders them regardless of status."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index('"[Merger]" in line')
        block = src[i:i + 400]
        assert 'job["speed"]  = ""' in block, f"{p}: merge branch must clear speed"
        assert 'job["eta"]' in block and '= ""' in block.split('job["eta"]')[1][:40], (
            f"{p}: merge branch must clear eta too -- a stale ETA sits on the "
            f"subscriptions queue rows through the whole conversion otherwise"
        )


def test_merge_phase_clears_download_progress():
    """The merger branch must also pop \"progress\" (not just speed/eta) --
    otherwise the download phase's final ~100% lingers on the converting
    badge/bar until the encode pump (a separate code path) repopulates a
    real percentage, misleadingly reading as an already-finished conversion
    the instant it starts. The other two conversion-trigger sites in this
    file (the ffprobe-based H.264 checks) already do this; the yt-dlp
    merger-text detector was the one site missing it."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index('"[Merger]" in line')
        block = src[i:i + 400]
        assert 'job.pop("progress", None)' in block, (
            f"{p}: merge branch must pop progress -- otherwise the download "
            f"phase's final percentage lingers through the whole conversion"
        )


def test_eta_charset_is_injection_safe_for_raw_interpolation():
    """subscriptions.html interpolates the eta/speed meta into an innerHTML
    template literal. That is safe ONLY while these regexes can't capture
    HTML metacharacters -- this test pins that invariant so a future regex
    widening can't silently turn the interpolation into an injection path.
    (The template now also esc()'s the meta as belt-and-braces, but the
    charset constraint is the load-bearing layer for the badge path too.)"""
    eta_re = re.compile(_extract_eta_pattern("app.py"))
    hostile = 'ETA <img src=x onerror=alert(1)> at 1.00MiB/s ETA 0:30"><b>'
    m = eta_re.search(hostile)
    assert m and not set(m.group(1)) & set('<>&"\''), f"captured {m.group(1)!r}"
    for ch in "<>&\"'":
        assert not re.compile(_extract_eta_pattern("app.py")).fullmatch(ch)


def test_encode_progress_has_out_time_fallback_on_all_platforms():
    """_pump_encode_progress must handle ffmpeg builds that emit only
    'out_time=HH:MM:SS.micro' (no out_time_us=/out_time_ms=) -- without this
    fallback, those builds silently never report encode progress at all
    (the pump would just sit idle, no error, no percentage)."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        i = src.index('def _pump_encode_progress')
        block = src[i:i + 2000]
        assert 'out_time=' in block, f"{p}: missing the out_time= fallback branch"
        assert 'encode progress reporting active' in block, (
            f"{p}: missing the one-time observability log line -- without it, "
            f"whether the pump is actually live has to be guessed rather than "
            f"confirmed from the debug log"
        )


def test_out_time_hhmmss_parses_to_correct_microseconds():
    """Directly exercises the HH:MM:SS.micro -> microseconds conversion
    (extracted and re-run here since it's inline in a Python source string,
    not its own importable function) against known-correct values."""
    def parse(value):
        hh, mm, ss = value.split(":")
        return int((int(hh) * 3600 + int(mm) * 60 + float(ss)) * 1_000_000)

    assert parse("00:00:05.000000") == 5_000_000
    assert parse("00:01:23.500000") == 83_500_000
    assert parse("01:00:00.000000") == 3_600_000_000
    assert parse("00:00:00.000000") == 0

    for bad in ("N/A", "", "garbage", "00:00", "00:00:00:00"):
        try:
            parse(bad)
            raised = False
        except (ValueError, IndexError):
            raised = True
        assert raised, f"{bad!r} should have raised ValueError/IndexError, matching the guarded except clause in app.py"


# ── Behavioral: the REAL pump function, not a re-implemented copy ─────────────
#
# test_out_time_hhmmss_parses_to_correct_microseconds above re-implements the
# conversion, which guards the *math* but not the *wiring* -- if the branch
# structure in _pump_encode_progress drifts (a fallthrough lost to an early
# continue, the shared pct block moved, the out_time= branch orphaned), a
# copy-based test stays green while the app silently stops reporting. This is
# the instrumenting-the-wrong-layer class the v1.3 pre-release review caught
# in the hw-slots guard. These tests feed synthetic ffmpeg -progress output
# through the actual function via the imported app module.

import io


class _FakeProc:
    def __init__(self, payload: bytes):
        self.stdout = io.BytesIO(payload)


def test_pump_end_to_end_us_form(app_module):
    job = {}
    feed = (b"out_time_us=N/A\n"          # pre-first-frame: must not crash or write
            b"out_time_us=30000000\n"     # 30s of 60s -> 50.0
            b"progress=continue\n"
            b"progress=end\n")            # -> 100
    app_module._pump_encode_progress(_FakeProc(feed), job, 60.0)
    assert job["progress"] == 100


def test_pump_end_to_end_out_time_fallback(app_module):
    """A build emitting ONLY out_time= must still produce percentages --
    through the real function, so a lost fallthrough or orphaned branch
    fails here even if the source still contains the substring."""
    job = {}
    app_module._pump_encode_progress(_FakeProc(b"out_time=00:00:30.000000\n"), job, 60.0)
    assert job.get("progress") == 50.0


def test_pump_stays_silent_without_duration_or_match(app_module):
    job = {}
    app_module._pump_encode_progress(_FakeProc(b"out_time=N/A\nout_time_us=N/A\nfps=30\n"), job, 60.0)
    assert "progress" not in job
    job2 = {}
    app_module._pump_encode_progress(_FakeProc(b"out_time_us=30000000\n"), job2, None)
    assert "progress" not in job2   # no duration -> badge stays indeterminate


def test_pump_clamps_past_duration_positions(app_module):
    job = {}
    app_module._pump_encode_progress(_FakeProc(b"out_time_us=999000000\n"), job, 60.0)
    assert job["progress"] == 99.0  # never shows 100 before progress=end
