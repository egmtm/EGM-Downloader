"""Job warnings must reach the user in their own language.

job["warning"] was set in three places but /api/status never returned it, so
the two old English warnings never showed. Now every warning carries a
translation key (warning_key), /api/status returns both, and the page shows
the translated text. One warning was dropped on purpose ("metadata embedding
skipped": the step it named was not always the one that failed).
These tests stop an unkeyed warning from being added again, and check the one
Universal MP4 notice end to end."""
import glob
import json
import os
import re
import stat

from conftest import PLATFORM_APP_FILES, ROOT, read_source


def _locale_strings():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "languages", "*.json"))):
        with open(f, encoding="utf-8") as fh:
            out[os.path.basename(f)] = json.load(fh)["strings"]
    assert len(out) >= 10
    return out


def test_every_warning_is_set_together_with_its_translation_key():
    for p in PLATFORM_APP_FILES:
        lines = read_source(p).splitlines()
        hits = [i for i, l in enumerate(lines) if re.match(r'\s*job\["warning"\]\s*=', l)]
        assert hits, f"{p}: expected at least one job warning"
        for i in hits:
            assert re.match(r'\s*job\["warning_key"\]\s*=\s*"[a-z0-9_.]+"', lines[i + 1]), (
                f"{p}:{i + 1}: job[\"warning\"] must be followed by job[\"warning_key\"]; "
                "an unkeyed warning is English only and is not shown by /api/status"
            )


def test_every_warning_key_exists_in_every_locale():
    keys = set()
    for p in PLATFORM_APP_FILES:
        keys |= set(re.findall(r'job\["warning_key"\]\s*=\s*"([a-z0-9_.]+)"', read_source(p)))
    assert {"download.warning.live_partial", "download.warning.source_codec"} <= keys
    for name, strings in _locale_strings().items():
        for k in keys:
            assert isinstance(strings.get(k), str) and strings[k].strip(), f"{name}: missing {k}"


def test_the_metadata_warning_stays_dropped():
    for p in PLATFORM_APP_FILES:
        assert "metadata embedding skipped" not in read_source(p), p


def _fake_tools(tmp_path, codec):
    """ffprobe.exe / ffmpeg.exe stand-ins: the backend only needs ffprobe to name the codec."""
    probe = tmp_path / "ffprobe.exe"
    probe.write_text(f"#!/bin/sh\necho {codec}\n")
    probe.chmod(probe.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "ffmpeg.exe").write_text("")
    return tmp_path


def _run_ensure_h264(app_module, monkeypatch, tmp_path, codec, encode_ok):
    monkeypatch.setattr(app_module, "FFMPEG_DIR", _fake_tools(tmp_path, codec))
    monkeypatch.setattr(app_module, "_run_h264_encode", lambda *a, **k: encode_ok)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"not really a video")
    job = {"status": "downloading"}
    out = app_module._ensure_h264("jw", str(video), job)
    return out, job


def test_failed_h264_conversion_keeps_the_file_and_sets_the_keyed_notice(app_module, monkeypatch, tmp_path):
    out, job = _run_ensure_h264(app_module, monkeypatch, tmp_path, "hevc", encode_ok=False)
    assert out == str(tmp_path / "v.mp4") and os.path.exists(out), "the download is never lost"
    assert job["warning_key"] == "download.warning.source_codec" and job["warning"]


def test_no_notice_when_conversion_works_or_is_not_needed(app_module, monkeypatch, tmp_path):
    _, job = _run_ensure_h264(app_module, monkeypatch, tmp_path, "hevc", encode_ok=True)
    assert "warning" not in job and "warning_key" not in job
    _, job = _run_ensure_h264(app_module, monkeypatch, tmp_path, "h264", encode_ok=False)
    assert "warning" not in job and "warning_key" not in job, "already H.264: nothing was attempted"


def test_status_returns_the_notice_so_the_page_can_translate_it(app_module):
    app_module.jobs["t_codec"] = {"status": "done", "warning": "w", "warning_key": "download.warning.source_codec"}
    with app_module.app.test_client() as client:
        d = client.get("/api/status/t_codec", headers={"X-EGM-Token": app_module._API_TOKEN}).get_json()
    assert d["warning_key"] == "download.warning.source_codec" and d["warning"] == "w"
