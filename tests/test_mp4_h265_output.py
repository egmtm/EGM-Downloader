"""MP4 · H.265: the second video output, built like MP4 · H.264.

* At download it asks for an HEVC stream (hvc1 or hev1) with AAC audio, and takes the best
  available when the site has none.
* After download a file already in HEVC is not reencoded; one tagged hev1 only gets its tag set to
  hvc1 by a stream copy, because Apple players need hvc1. Anything else is encoded to HEVC: the
  hardware encoder when one probes healthy (the H.264 encoders' HEVC versions, same settings), or
  libx265 at preset veryfast and crf 28.
* Upscale encodes H.265 when this output is selected.
* The hardware cache is per codec: a GPU that fails HEVC keeps its H.264 encoder.
"""
import importlib.util
import io
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import read_source

ROOT = Path(__file__).resolve().parent.parent
APP_FILES = ("app.py", "linux/app.py", "mac/app.py")
FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")


def _has_libx265():
    if not FFMPEG:
        return False
    r = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True)
    return " libx265 " in r.stdout


needs_x265 = pytest.mark.skipif(not (FFPROBE and _has_libx265()), reason="ffmpeg with libx265 not installed")


@pytest.fixture(scope="module", params=APP_FILES)
def backend(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location(
            "egm_h265_" + request.param.split("/")[0], ROOT / request.param)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    return mod


def _exe(backend):
    return ".exe" if Path(backend.__file__).resolve() == ROOT / "app.py" else ""


# ── wiring ────────────────────────────────────────────────────────────────────

def test_the_option_sits_right_under_h264():
    html = read_source("templates/index.html")
    sel = re.search(r'<select id="output-format-sel".*?</select>', html, re.S).group(0)
    values = re.findall(r'<option value="([^"]+)"', sel)
    assert values == ["mp4_h264", "mp4_h265", "mp4", "mkv"], values
    assert 'value="mp4_h265" data-i18n="card.format.video.h265">MP4 · H.265<' in sel


@pytest.mark.parametrize("path", APP_FILES)
def test_the_backend_accepts_the_setting(path):
    assert '"output_format":        ("mp4_h264", "mp4_h265", "mp4", "mkv"),' in read_source(path)


@pytest.mark.parametrize("path", APP_FILES)
def test_hevc_encoders_are_the_h264_ones_with_the_same_settings(path):
    src = read_source(path)
    block = re.search(r'candidates = \{\n(.*?)\n    \}\[codec\]', src, re.S).group(1)
    h264 = re.findall(r'\("(h264_\w+)", (\[.*?\])\)', block)
    hevc = re.findall(r'\("(hevc_\w+)", (\[.*?\])\)', block)
    assert h264, f"{path}: no H.264 hardware encoders found"
    assert [(n.replace("h264_", "hevc_"), a.replace("h264_", "hevc_")) for n, a in h264] == hevc, (path, h264, hevc)


@pytest.mark.parametrize("path", APP_FILES)
def test_software_hevc_is_libx265_veryfast_crf_28_tagged_hvc1(path):
    src = read_source(path)
    assert 'sw = ["-c:v", "libx265", "-preset", "veryfast", "-crf", "28"]' in src
    assert 'tag = ["-tag:v", "hvc1"]' in src
    assert "cmd += codec_args + tag + [" in src, f"{path}: the hvc1 tag is not on the encode command"


# ── the codec pass, with stand-in tools ───────────────────────────────────────

@pytest.fixture
def tools(backend, tmp_path, monkeypatch):
    ff = tmp_path / "ffbin"
    ff.mkdir()
    for n in ("ffmpeg", "ffprobe"):
        (ff / f"{n}{_exe(backend)}").write_text("")
    monkeypatch.setattr(backend, "FFMPEG_DIR", ff)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"original")
    calls = {"encode": [], "tag": []}

    def probe_says(text):
        monkeypatch.setattr(backend, "_run", lambda *a, **k: subprocess.CompletedProcess(list(a), 0, text, ""))

    def fake_encode(job_id, job, ffmpeg, src, dst, level=None, vf=None, ffprobe=None, codec="h264"):
        calls["encode"].append((Path(dst).name, level, codec))
        if calls.get("encode_ok", True):
            Path(dst).write_bytes(b"converted")
            return True
        return False
    monkeypatch.setattr(backend, "_run_video_encode", fake_encode)
    monkeypatch.setattr(backend, "_tag_hvc1", lambda ffmpeg, p: calls["tag"].append(Path(p).name) or True)
    return backend, video, calls, probe_says


@pytest.mark.parametrize("probe", ["hevc,hvc1\n", "hevc,hev1\n"])
def test_a_file_already_in_hevc_is_not_reencoded(tools, probe):
    backend, video, calls, probe_says = tools
    probe_says(probe)
    job = {"status": "downloading"}
    assert backend._ensure_codec("j", str(video), job, "hevc") == str(video)
    assert calls["encode"] == [] and job["status"] == "downloading"
    assert calls["tag"] == ([] if "hvc1" in probe else ["v.mp4"]), "only hev1 gets the tag copy"


@pytest.mark.parametrize("probe", ["av1,av01\n", "vp9,vp09\n", "h264,avc1\n"])
def test_anything_else_is_encoded_to_hevc(tools, probe):
    backend, video, calls, probe_says = tools
    probe_says(probe)
    job = {"status": "downloading"}
    backend._ensure_codec("j", str(video), job, "hevc")
    assert calls["encode"] == [("v.mp4.h265.mp4", None, "hevc")]
    assert video.read_bytes() == b"converted" and job["status"] == "converting"
    assert "warning" not in job


def test_h264_output_is_unchanged(tools):
    backend, video, calls, probe_says = tools
    probe_says("hevc,hvc1\n")
    backend._ensure_codec("j", str(video), {"status": "downloading"})
    assert calls["encode"] == [("v.mp4.h264.mp4", "4.0", "h264")] and calls["tag"] == []
    calls["encode"].clear()
    probe_says("h264,avc1\n")
    backend._ensure_codec("j", str(video), {"status": "downloading"}, "h264")
    assert calls["encode"] == []


def test_a_failed_hevc_encode_keeps_the_file_and_says_h265(tools):
    backend, video, calls, probe_says = tools
    probe_says("vp9,vp09\n")
    calls["encode_ok"] = False
    job = {"status": "downloading"}
    assert backend._ensure_codec("j", str(video), job, "hevc") == str(video)
    assert video.read_bytes() == b"original"
    assert job["warning_key"] == "download.warning.source_codec_h265" and "H.265" in job["warning"]


# ── the hardware cache is per codec ───────────────────────────────────────────

def test_a_failed_hevc_gpu_encode_keeps_the_h264_encoder(backend, monkeypatch, tmp_path):
    backend._HW_ENCODER_CACHE.clear()
    backend._HW_ENCODER_CACHE.update({"h264": ("fake_h264", ["-c:v", "fake_h264"]),
                                      "hevc": ("fake_hevc", ["-c:v", "fake_hevc"])})
    cmds = []

    class P:
        pid = 1

        def __init__(self, cmd):
            self.stdout, self.stderr = io.BytesIO(b""), io.BytesIO(b"")
            self.returncode = 1 if "fake_hevc" in cmd else 0
            if self.returncode == 0:
                Path(cmd[-1]).write_bytes(b"ok")

        def wait(self, timeout=None):
            return self.returncode

    monkeypatch.setattr(backend, "_popen", lambda *cmd, **k: cmds.append(cmd) or P(list(cmd)))
    try:
        job = {}
        ok = backend._run_video_encode("j", job, "ffmpeg", "in.mp4", str(tmp_path / "out.mp4"), codec="hevc")
        assert ok and job["encoder"] == "libx265"
        assert [c[c.index("-c:v") + 1] for c in cmds] == ["fake_hevc", "libx265"]
        assert all(c[c.index("-tag:v") + 1] == "hvc1" for c in cmds), "every HEVC attempt is tagged hvc1"
        assert backend._HW_ENCODER_CACHE["hevc"] == (None, None)
        assert backend._HW_ENCODER_CACHE["h264"] == ("fake_h264", ["-c:v", "fake_h264"])
    finally:
        backend._HW_ENCODER_CACHE.clear()


def test_the_hardware_probe_tries_the_hevc_encoders_for_hevc(backend, monkeypatch):
    backend._HW_ENCODER_CACHE.clear()
    tried = []

    def fake_run(*cmd, **k):
        tried.append(cmd[cmd.index("-c:v") + 1])
        return subprocess.CompletedProcess(list(cmd), 1, "", "no device")
    monkeypatch.setattr(backend, "_run", fake_run)
    try:
        assert backend._detect_hw_encoder("hevc") == (None, None)
        assert tried and all(t.startswith("hevc_") for t in tried), tried
        tried.clear()
        backend._detect_hw_encoder("h264")
        assert tried and all(t.startswith("h264_") for t in tried), tried
    finally:
        backend._HW_ENCODER_CACHE.clear()


# ── the download: stream choice, codec pass and Upscale ───────────────────────

class _Proc:
    pid = 4343

    def __init__(self, on_start=None, binary=False):
        if on_start:
            on_start()
        self.stdout = io.BytesIO(b"") if binary else io.StringIO("[download] 100% of 1.00MiB\n")
        self.stderr = io.BytesIO(b"") if binary else io.StringIO("")
        self.returncode = None

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def poll(self):
        return self.returncode

    def kill(self):
        pass


def test_a_download_asks_for_hevc_then_encodes_and_upscales_in_hevc(backend, tmp_path, monkeypatch):
    out = tmp_path / "downloads"
    out.mkdir()
    ff = tmp_path / "ffbin"
    ff.mkdir()
    for n in ("ffmpeg", "ffprobe"):
        (ff / f"{n}{_exe(backend)}").write_text("")
    monkeypatch.setattr(backend, "FFMPEG_DIR", ff)
    for name in ("HISTORY_FILE", "SETTINGS_FILE"):
        monkeypatch.setattr(backend, name, tmp_path / Path(getattr(backend, name)).name)
    monkeypatch.setattr(backend, "_settings_cache", {"upscale_to_quality": True})
    monkeypatch.setattr(backend, "_fetch_thumbnail", lambda *a: b"")
    monkeypatch.setattr(backend, "_detect_hw_encoder", lambda codec="h264": (None, None))
    job_id = "0123456789"
    backend.jobs[job_id] = job = {"status": "queued", "url": "https://example.invalid/v", "title": "T",
                                  "proc": None, "cancelled": False, "live": False}
    yt_cmds, encodes = [], []

    def fake_popen_yt(*cmd, **k):
        yt_cmds.append(list(cmd))
        return _Proc(on_start=lambda: (out / f"{job_id}.mp4").write_bytes(b"x" * 5000))
    monkeypatch.setattr(backend, "_popen_yt", fake_popen_yt)

    def fake_run(*cmd, timeout=None, **kw):
        line = " ".join(map(str, cmd))
        if "codec_name" in line:
            return subprocess.CompletedProcess(list(cmd), 0, "vp9,vp09\n", "")
        if "width,height" in line:
            return subprocess.CompletedProcess(list(cmd), 0, "640,360\n", "")
        return subprocess.CompletedProcess(list(cmd), 0, "100.0\n", "")
    monkeypatch.setattr(backend, "_run", fake_run)

    def fake_popen(*cmd, **kw):
        encodes.append((Path(cmd[-1]).name, cmd[cmd.index("-c:v") + 1]))
        return _Proc(on_start=lambda: Path(cmd[-1]).write_bytes(b"y"), binary=True)
    monkeypatch.setattr(backend, "_popen", fake_popen)
    try:
        backend.run_download(job_id, "https://example.invalid/v", "video", None, str(out),
                             video_height=1080, output_format="mp4_h265")
    finally:
        backend.jobs.pop(job_id, None)
    cmd = yt_cmds[0]
    fmt = cmd[cmd.index("-f") + 1]
    assert fmt == ("bestvideo[vcodec~='^(hvc1|hev1)']+bestaudio[acodec^=mp4a]/"
                   "bestvideo[vcodec~='^(hvc1|hev1)']+bestaudio/"
                   "best[vcodec~='^(hvc1|hev1)']/bestvideo+bestaudio/best"), fmt
    assert cmd[cmd.index("--remux-video") + 1] == "mp4"
    assert [e[1] for e in encodes] == ["libx265", "libx265"], f"codec pass then Upscale, both HEVC: {encodes}"
    assert encodes[0][0].endswith(".h265.mp4") and encodes[1][0].endswith(".up.mp4"), encodes
    assert job["status"] == "done", job


def test_yt_dlp_picks_hevc_when_offered_and_the_best_stream_when_not():
    yt_dlp = pytest.importorskip("yt_dlp")
    chain = ("bestvideo[vcodec~='^(hvc1|hev1)']+bestaudio[acodec^=mp4a]/"
             "bestvideo[vcodec~='^(hvc1|hev1)']+bestaudio/"
             "best[vcodec~='^(hvc1|hev1)']/bestvideo+bestaudio/best")

    def f(fid, vcodec, acodec, h, tbr):
        return {"format_id": fid, "url": "https://x.invalid/" + fid, "ext": "mp4", "vcodec": vcodec,
                "acodec": acodec, "height": h, "width": h * 16 // 9 if h else None, "tbr": tbr,
                "protocol": "https"}
    audio = [f("140", "none", "mp4a.40.2", None, 128), f("251", "none", "opus", None, 130)]
    av1 = f("av1", "av01.0.08M.08", "none", 1080, 2000)
    cases = {
        "hvc+140": [av1, f("hvc", "hvc1.1.6.L120.90", "none", 1080, 3000), f("avc", "avc1.640028", "none", 1080, 4000)],
        "hev+140": [av1, f("hev", "hev1.1.6.L120.90", "none", 1080, 3000)],
        "av1+251": [av1, f("avc", "avc1.640028", "none", 720, 1500)],
    }
    for expect, video in cases.items():
        ydl = yt_dlp.YoutubeDL({"quiet": True, "format": chain, "simulate": True})
        r = ydl.process_ie_result({"id": "t", "title": "t", "formats": video + audio, "extractor": "generic",
                                   "extractor_key": "Generic", "webpage_url": "https://x.invalid"}, download=False)
        assert r["format_id"] == expect, (expect, r["format_id"])


# ── real ffmpeg ───────────────────────────────────────────────────────────────

def _probe(path, entries, stream="v:0"):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", stream, "-show_entries", entries,
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return r.stdout.strip()


def _real_tools(backend, tmp_path, monkeypatch):
    ff = tmp_path / "realff"
    ff.mkdir()
    (ff / f"ffmpeg{_exe(backend)}").symlink_to(FFMPEG)
    (ff / f"ffprobe{_exe(backend)}").symlink_to(FFPROBE)
    monkeypatch.setattr(backend, "FFMPEG_DIR", ff)
    monkeypatch.setattr(backend, "_detect_hw_encoder", lambda codec="h264": (None, None))


@needs_x265
def test_real_vp9_download_becomes_hvc1_hevc_with_aac(backend, tmp_path, monkeypatch):
    _real_tools(backend, tmp_path, monkeypatch)
    src = tmp_path / "clip.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "1", "-c:v", "libvpx-vp9",
                    "-c:a", "libopus", str(src)], check=True)
    job = {"status": "downloading"}
    assert backend._ensure_codec("j", str(src), job, "hevc") == str(src)
    assert _probe(src, "stream=codec_name,codec_tag_string,pix_fmt") == "hevc,hvc1,yuv420p"
    assert _probe(src, "stream=codec_name", "a:0") == "aac"
    assert job["encoder"] == "libx265" and "warning" not in job
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4", "realff"], "no temp file left"


@needs_x265
def test_real_hev1_file_is_retagged_without_reencoding_and_keeps_its_tracks(backend, tmp_path, monkeypatch):
    _real_tools(backend, tmp_path, monkeypatch)
    src = tmp_path / "clip.mp4"
    cover = tmp_path / "cover.jpg"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:size=64x64", "-frames:v", "1",
                    str(cover)], check=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-f", "lavfi", "-i", "sine=frequency=880",
                    "-i", str(cover), "-t", "1", "-map", "0", "-map", "1", "-map", "2", "-map", "3",
                    "-c:v:0", "libx265", "-tag:v:0", "hev1", "-c:v:1", "copy", "-disposition:v:1", "attached_pic",
                    "-c:a", "aac", "-x265-params", "log-level=error", str(src)], check=True)
    assert _probe(src, "stream=codec_tag_string") == "hev1"

    def video_hash(p):
        return subprocess.run([FFMPEG, "-v", "error", "-i", str(p), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"],
                              capture_output=True, text=True, check=True).stdout.strip()
    before_hash = video_hash(src)
    streams_before = _probe(src, "stream=codec_type,codec_name", "")
    job = {"status": "downloading"}
    backend._ensure_codec("j", str(src), job, "hevc")
    assert _probe(src, "stream=codec_name,codec_tag_string") == "hevc,hvc1"
    assert video_hash(src) == before_hash, "the video stream is copied, not reencoded"
    assert _probe(src, "stream=codec_type,codec_name", "") == streams_before, "every track is kept"
    assert "encoder" not in job and job["status"] == "downloading"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4", "cover.jpg", "realff"]


@needs_x265
def test_real_upscale_follows_hevc(backend, tmp_path, monkeypatch):
    _real_tools(backend, tmp_path, monkeypatch)
    src = tmp_path / "small.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10",
                    "-t", "1", "-c:v", "libx265", "-tag:v", "hvc1", "-x265-params", "log-level=error",
                    str(src)], check=True)
    backend._upscale_to_preset("j", str(src), {"status": "downloading"}, 360, "hevc")
    assert _probe(src, "stream=codec_name,codec_tag_string,width,height") == "hevc,hvc1,640,360"
