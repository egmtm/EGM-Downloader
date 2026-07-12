"""HDR quality-selection bucketing guard.

_build_formats sorts yt-dlp formats into an SDR bucket and an HDR bucket per
height. The original implementation bucketed by dynamic_range.startswith("HDR"),
which correctly caught HDR10 but silently MISFILED Dolby Vision and HLG into
the SDR bucket (their dynamic_range values are "DV" and "HLG", neither starts
with "HDR"). Since each bucket keeps the highest-bitrate format per height, a
DV/HLG stream -- typically the fattest at its height -- could displace the
genuine SDR entry outright. A user picking the resulting "plain" quality row
would silently download DV/HLG video that then runs through the H.264 compat
pass with no tone-mapping: the classic washed-out/green output.

Found and fixed via Claude Code's round-10 delta review, verified by manual
reproduction at the time but never given a permanent guard until now.
"""
from conftest import read_source


def _formats(*, sdr_tbr=5000, hdr10_tbr=None, dv_tbr=None, hlg_tbr=None, height=1080):
    fmts = [{"format_id": "sdr", "height": height, "tbr": sdr_tbr,
              "vcodec": "avc1", "acodec": "mp4a", "dynamic_range": "SDR"}]
    if hdr10_tbr is not None:
        fmts.append({"format_id": "hdr10", "height": height, "tbr": hdr10_tbr,
                      "vcodec": "vp09", "acodec": "opus", "dynamic_range": "HDR10"})
    if dv_tbr is not None:
        fmts.append({"format_id": "dv", "height": height, "tbr": dv_tbr,
                      "vcodec": "dvh1", "acodec": "opus", "dynamic_range": "DV"})
    if hlg_tbr is not None:
        fmts.append({"format_id": "hlg", "height": height, "tbr": hlg_tbr,
                      "vcodec": "vp09", "acodec": "opus", "dynamic_range": "HLG"})
    return {"formats": fmts}


def test_dv_does_not_displace_real_sdr_entry(app_module):
    # DV has the highest bitrate at this height -- the exact displacement scenario.
    result = app_module._build_formats(_formats(sdr_tbr=5000, dv_tbr=8000))
    sdr_rows = [r for r in result if not r.get("hdr")]
    hdr_rows = [r for r in result if r.get("hdr")]
    assert any(r["id"] == "sdr" for r in sdr_rows), \
        "the genuine SDR entry was displaced -- DV bucketing regression"
    assert any(r["id"] == "dv" for r in hdr_rows), \
        "DV format was not given HDR-row treatment"


def test_hlg_bucketed_as_hdr_not_sdr(app_module):
    result = app_module._build_formats(_formats(sdr_tbr=2000, hlg_tbr=3000))
    hlg_row = next(r for r in result if r["id"] == "hlg")
    sdr_row = next((r for r in result if r["id"] == "sdr"), None)
    assert hlg_row.get("hdr") is True, "HLG must be treated as HDR, not SDR"
    assert sdr_row is not None, "the genuine SDR entry was displaced by HLG"


def test_hdr10_still_works(app_module):
    result = app_module._build_formats(_formats(sdr_tbr=3000, hdr10_tbr=6000))
    hdr_row = next(r for r in result if r["id"] == "hdr10")
    sdr_row = next((r for r in result if r["id"] == "sdr"), None)
    assert hdr_row.get("hdr") is True
    assert sdr_row is not None


def test_missing_dynamic_range_stays_sdr(app_module):
    fmts = {"formats": [{"format_id": "unknown", "height": 480, "tbr": 1000,
                          "vcodec": "avc1", "acodec": "mp4a"}]}
    result = app_module._build_formats(fmts)
    row = next(r for r in result if r["id"] == "unknown")
    assert not row.get("hdr"), "missing/absent dynamic_range must default to SDR"


def test_hdr10_and_dv_coexisting_never_loses_the_sdr_row(app_module):
    # Documented accepted nuance: within the HDR bucket, highest-bitrate wins,
    # so DV can out-rank HDR10 at the same height and only one HDR row shows.
    # That's fine (both routes are safe stream-copy-into-MKV) -- what must NOT
    # happen is the SDR row disappearing too.
    result = app_module._build_formats(_formats(sdr_tbr=8000, hdr10_tbr=12000, dv_tbr=15000, height=2160))
    assert any(r["id"] == "sdr" and not r.get("hdr") for r in result)
    hdr_rows = [r for r in result if r.get("hdr")]
    assert len(hdr_rows) == 1 and hdr_rows[0]["id"] == "dv"


def test_bucketing_fix_present_on_all_platforms():
    """The startswith('HDR') regression must not silently return -- checked
    directly on mac/linux source, not just root (which app_module covers)."""
    for platform_file in ("mac/app.py", "linux/app.py"):
        source = read_source(platform_file)
        assert 'dr and dr != "SDR"' in source, (
            f"{platform_file}: HDR bucketing fix (dr and dr != 'SDR') not found -- "
            "may have regressed to the DV/HLG-displacement bug"
        )
