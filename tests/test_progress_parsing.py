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
