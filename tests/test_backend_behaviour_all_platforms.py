"""Two fixes that used to be guarded on Mac and Linux only by grepping their source for the fix's exact text.

Both now run their real behaviour on all three backends (root app.py, mac/app.py, linux/app.py),
the way test_failed_download_leftover_streams.py does, so a harmless refactor of the code no longer
fails a text match and a real regression on any backend fails a behaviour check.

* Cancel during conversion: /api/cancel must accept a job in the "converting" phase.
  History and the Windows only checks: test_cancel_during_conversion.py.
* HDR bucketing: Dolby Vision and HLG formats must be treated as HDR rows and must not displace the
  genuine SDR row at their height. History and the Windows only checks: test_hdr_bucketing.py.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    # Linux and Mac create their data folders at import: point them at a temporary home.
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_all_platforms_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


def test_cancel_route_accepts_a_converting_job_on_every_backend(backend):
    backend.jobs["t_conv"] = {"status": "converting", "cancelled": False}
    try:
        with backend.app.test_client() as client:
            r = client.post("/api/cancel/t_conv", headers={"X-EGM-Token": backend._API_TOKEN})
        assert r.status_code == 200, r.data
        assert backend.jobs["t_conv"]["cancelled"] is True
    finally:
        backend.jobs.pop("t_conv", None)


def _formats(sdr_tbr, dv_tbr=None, hlg_tbr=None, height=1080):
    fmts = [{"format_id": "sdr", "height": height, "tbr": sdr_tbr,
             "vcodec": "avc1", "acodec": "mp4a", "dynamic_range": "SDR"}]
    if dv_tbr is not None:
        fmts.append({"format_id": "dv", "height": height, "tbr": dv_tbr,
                     "vcodec": "dvh1", "acodec": "opus", "dynamic_range": "DV"})
    if hlg_tbr is not None:
        fmts.append({"format_id": "hlg", "height": height, "tbr": hlg_tbr,
                     "vcodec": "vp09", "acodec": "opus", "dynamic_range": "HLG"})
    return {"formats": fmts}


def test_dv_and_hlg_do_not_displace_the_sdr_row_on_every_backend(backend):
    # In each case the HDR stream has the higher bitrate, the exact displacement scenario.
    for fmts in (_formats(5000, dv_tbr=8000), _formats(2000, hlg_tbr=3000)):
        result = backend._build_formats(fmts)
        assert any(r["id"] == "sdr" and not r.get("hdr") for r in result), result
        assert all(r.get("hdr") is True for r in result if r["id"] in ("dv", "hlg")), result
