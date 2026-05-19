import os
import sys
import uuid
import glob
import json
import hmac
import subprocess
import re as _re
import time
import threading
import urllib.request
import zipfile
import hashlib
import tarfile
import shutil
from collections import deque
from pathlib import Path
from flask import Flask, request, jsonify, render_template, abort

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB global request body limit

# ── Defensive Host header check (DNS rebinding / CSRF protection) ─────────────
# We bind only to 127.0.0.1, but a malicious page could still target this port
# via a DNS-rebinding attack. Reject any request whose Host header isn't a
# loopback address. Cheap belt-and-suspenders.
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}

def _verify_upstream_checksum(local_path, checksum_url, filename):
    """Fetch upstream checksum file, parse for filename, verify local download.
    Returns (ok: bool, message: str).
    Fail-closed: any fetch failure, parse error, missing entry, or mismatch returns False."""
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=8) as r:
            lines = r.read().decode().splitlines()
        expected = None
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
                expected = parts[0].lower()
                break
        if not expected:
            return False, f"No checksum entry found for {filename} — install aborted (try again later)"
        actual = hashlib.sha256(local_path.read_bytes()).hexdigest().lower()
        if actual != expected:
            return False, (f"Checksum mismatch for {filename}. "
                           "The download may be corrupted or tampered — install aborted.")
        return True, f"OK Checksum verified ({filename})"
    except Exception as e:
        return False, f"Could not verify checksum ({e}) — install aborted (check network and retry)"

def _chmod_owner_only(path):
    """Set sensitive file to owner read/write only (POSIX). No-op on Windows."""
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
_API_TOKEN       = os.environ.get("EGM_API_TOKEN", "")
# /api/show-window is exempt because launch.py (second-instance signaler) has no token access
_TOKEN_EXEMPT    = {"/api/show-window"}
_IS_DEV          = os.environ.get("EGM_DEV_MODE") == "1"
if not _API_TOKEN and not _IS_DEV:
    raise RuntimeError("EGM_API_TOKEN is required — set EGM_DEV_MODE=1 for local development")

def _extract_host(host):
    """IPv6-aware host extraction: [::1]:8899 → [::1], 127.0.0.1:8899 → 127.0.0.1"""
    host = (host or "").strip().lower()
    if host.startswith("["):
        end = host.find("]")
        return host[:end + 1] if end != -1 else host
    return host.split(":", 1)[0]

@app.before_request
def _verify_host_header():
    host_only = _extract_host(request.host)
    if host_only and host_only not in _ALLOWED_HOSTS:
        abort(403)
    # 2. API token check (per-session Electron token)
    if _API_TOKEN and request.path.startswith("/api/") and request.path not in _TOKEN_EXEMPT:
        if not hmac.compare_digest(
            request.headers.get("X-EGM-Token", ""), _API_TOKEN
        ):
            abort(403)

@app.after_request
def _no_cache_html(response):
    """Prevent Electron's Chromium from serving stale templates after app updates.
    HTML routes only — API JSON responses can cache normally."""
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# ── Paths ──────────────────────────────────────────────────────────────────────
# APP_DIR: read-only — inside the AppImage squashfs mount.
#          Safe to read files from here; never write here.
# DATA_DIR: writable — persists in the user's home across AppImage updates.
APP_DIR  = Path(__file__).parent
DATA_DIR = Path.home() / ".local" / "share" / "egm-downloader"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_DIR    = DATA_DIR / "ffmpeg_bin"

# ── App version ───────────────────────────────────────────────────────────────
APP_VERSION           = "0.99.4"
APP_BUILD             = 112
APP_UPDATE_URL = "https://egerena.com/apps/egmlinux-update.json"

# Settings and cookies: writable user data under DATA_DIR
SETTINGS_FILE = DATA_DIR / "egm_settings.json"
HISTORY_FILE  = DATA_DIR / "egm_history.json"
COOKIES_FILE  = DATA_DIR / "cookies.txt"

_settings_cache: dict = {}
_settings_lock  = threading.Lock()

# ── History ────────────────────────────────────────────────────────────────────
_history_lock = threading.Lock()
_HISTORY_MAX  = 500

def _load_history() -> list:
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_history(items: list):
    try:
        HISTORY_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")
        _chmod_owner_only(HISTORY_FILE)
    except Exception:
        pass

def _append_history(job: dict, final_path):
    try:
        size_bytes = 0
        try: size_bytes = final_path.stat().st_size
        except Exception: pass
        entry = {
            "id":           str(uuid.uuid4()),
            "url":          job.get("url", ""),
            "title":        job.get("title", ""),
            "filename":     final_path.name,
            "format":       final_path.suffix.lstrip(".").lower(),
            "download_dir": str(final_path.parent),
            "file_path":    str(final_path),
            "size_bytes":   size_bytes,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        with _history_lock:
            items = _load_history()
            items.insert(0, entry)
            if len(items) > _HISTORY_MAX:
                items = items[:_HISTORY_MAX]
            _save_history(items)
    except Exception:
        pass

def _load_settings() -> dict:
    global _settings_cache
    with _settings_lock:
        if not _settings_cache:
            try:
                _settings_cache = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            except Exception:
                _settings_cache = {}
        return dict(_settings_cache)

def _save_settings(data: dict):
    with _settings_lock:
        try:
            _settings_cache.update(data)
            SETTINGS_FILE.write_text(json.dumps(_settings_cache, indent=2), encoding="utf-8")
            _chmod_owner_only(SETTINGS_FILE)
        except Exception:
            pass

def _get_last_folder() -> str:
    return _load_settings().get("last_folder", "")

jobs: dict = {}
_jobs_lock = threading.Lock()

# ── Active process registry ───────────────────────────────────────────────────
_active_procs: dict = {}
_active_procs_lock  = threading.Lock()

# ── Jobs cleanup — remove stale completed entries after ~10 minutes ───────────
def _jobs_cleanup_worker():
    TERMINAL = {"done", "error", "cancelled"}
    MAX_AGE  = 600
    while True:
        time.sleep(60)
        now = time.time()
        with _jobs_lock:
            stale = [jid for jid, j in list(jobs.items())
                     if j.get("status") in TERMINAL
                     and now - j.get("_finished_at", now) > MAX_AGE]
            for jid in stale:
                jobs.pop(jid, None)

threading.Thread(target=_jobs_cleanup_worker, daemon=True, name="jobs-cleanup").start()

# ── Friendly error messages ───────────────────────────────────────────────────
_ERROR_MAP = [
    (_re.compile(r"Sign in to confirm|bot|login required",            _re.I), "YouTube requires sign-in for this video. Try adding cookies in Settings."),
    (_re.compile(r"Private video",                                     _re.I), "This video is private."),
    (_re.compile(r"Video unavailable|has been removed|no longer",     _re.I), "This video is unavailable or has been removed."),
    (_re.compile(r"Requested format is not available|format.*not.*available", _re.I), "The selected quality isn't available. Try a different format."),
    (_re.compile(r"Unable to extract|Could not extract",              _re.I), "Could not extract video info. The page may have changed."),
    (_re.compile(r"HTTP Error 403",                                    _re.I), "Access denied (403). This video may be region-locked or require login."),
    (_re.compile(r"HTTP Error 404",                                    _re.I), "Video not found (404). The URL may be incorrect or the video deleted."),
    (_re.compile(r"HTTP Error 429|Too many requests",                 _re.I), "Too many requests. Please wait a moment before trying again."),
    (_re.compile(r"This live event will begin|premiere",              _re.I), "This video is a scheduled premiere and hasn't started yet."),
    (_re.compile(r"members.only|membership required",                 _re.I), "This video is for channel members only."),
]

def _friendly_error(raw: str) -> str:
    for pattern, friendly in _ERROR_MAP:
        if pattern.search(raw):
            return friendly
    return raw

def _kill_proc(proc: subprocess.Popen) -> None:
    """Kill a yt-dlp process and its entire child tree (including ffmpeg).
    Uses os.killpg to kill the process group on Linux."""
    if proc is None:
        return
    try:
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            proc.kill()
    except Exception:
        pass

def _run(*cmd, timeout=None, **kw):
    return subprocess.run(list(cmd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, **kw)

def _popen(*cmd, **kw):
    return subprocess.Popen(list(cmd), **kw)

def _yt_env() -> dict:
    """Environment for yt-dlp subprocesses.
    Injects bundled deno path and prepends PACKAGES_DIR to PYTHONPATH so an
    updated yt-dlp (installed via pip --target) takes precedence over bundled."""
    env = os.environ.copy()
    if DENO_EXE.exists():
        env["DENO"] = str(DENO_EXE)
    if PACKAGES_DIR.exists():
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(PACKAGES_DIR) + (":" + existing if existing else "")
    return env

def _run_yt(*cmd, timeout=None, **kw):
    return subprocess.run(list(cmd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=_yt_env(), timeout=timeout, **kw)

def _popen_yt(*cmd, **kw):
    return subprocess.Popen(list(cmd), env=_yt_env(), **kw)

# ── ffmpeg: BtbN Linux x64 build ─────────────────────────────────────────────
FFMPEG_URL      = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                   "ffmpeg-master-latest-linux64-gpl.tar.xz")
FFMPEG_TAG_FILE = FFMPEG_DIR / "build_tag.txt"

# ── Deno: stored in DATA_DIR (downloaded on first use) ───────────────────────
DENO_DIR     = DATA_DIR / "runtime"
DENO_EXE     = DENO_DIR / "deno"
DENO_ZIP_URL = ("https://github.com/denoland/deno/releases/latest/download/"
                "deno-x86_64-unknown-linux-gnu.zip")

# ── Python + yt-dlp ──────────────────────────────────────────────────────────
# PYTHON_DIR: bundled Python inside the AppImage (read-only — executing is fine)
# PACKAGES_DIR: writable overlay; pip --target installs updated yt-dlp here
# _yt_env() prepends PACKAGES_DIR to PYTHONPATH so updates take precedence
PYTHON_DIR   = APP_DIR.parent / "python"
PACKAGES_DIR = DATA_DIR / "packages"
YT_DLP_EXE  = PYTHON_DIR / "bin" / "yt-dlp"   # bundled fallback"

def ensure_ffmpeg():
    ffmpeg_bin  = FFMPEG_DIR / "ffmpeg"
    ffprobe_bin = FFMPEG_DIR / "ffprobe"

    if ffmpeg_bin.exists() and ffprobe_bin.exists():
        print("[EGM] ffmpeg ready.")
        return True

    print("[EGM] Downloading ffmpeg (first run only)...")
    FFMPEG_DIR.mkdir(exist_ok=True)
    tmp = FFMPEG_DIR / "ffmpeg_tmp.tar.xz"
    try:
        req = urllib.request.Request(FFMPEG_URL, headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        ok, msg = _verify_upstream_checksum(tmp, "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256", "ffmpeg-master-latest-linux64-gpl.tar.xz")
        print(f"[EGM] {msg}")
        if not ok:
            tmp.unlink(missing_ok=True)
            return
        print("[EGM] Extracting ffmpeg...")
        with tarfile.open(tmp, "r:xz") as t:
            for member in t.getmembers():
                # BtbN archive has a top-level dir: ffmpeg-master-latest-linux64-gpl/bin/ffmpeg
                fn = Path(member.name).name
                if fn in ("ffmpeg", "ffprobe") and member.isfile():
                    member.name = fn   # flatten path
                    t.extract(member, FFMPEG_DIR)
        tmp.unlink(missing_ok=True)
        # Make executable
        os.chmod(ffmpeg_bin,  0o755)
        os.chmod(ffprobe_bin, 0o755)
        try:
            FFMPEG_TAG_FILE.write_text(_get_latest_ffmpeg_tag())
        except Exception:
            pass
        print("[EGM] ffmpeg ready.")
        return True
    except Exception as e:
        print(f"[EGM] ffmpeg download failed: {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False

def _ffmpeg_args():
    return ["--ffmpeg-location", str(FFMPEG_DIR)]

def _deno_args():
    """Return --js-runtimes flag pointing at bundled deno, or [] if not installed."""
    if DENO_EXE.exists():
        return ["--js-runtimes", f"deno:{DENO_EXE}"]
    return []

def _get_deno_version() -> str:
    if not DENO_EXE.exists():
        return "not installed"
    try:
        r = _run(str(DENO_EXE), "--version", timeout=10)
        line = r.stdout.splitlines()[0] if r.stdout else ""
        parts = line.split()
        return parts[1] if len(parts) >= 2 else "unknown"
    except Exception:
        return "unknown"

def _cookies_args() -> list:
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
        return ["--cookies", str(COOKIES_FILE)]
    return []

def _bgutil_args() -> list:
    if not DENO_EXE.exists():
        return ["--extractor-args", "youtube:fetch_pot=never"]
    return []

def _ytdlp(*extra, timeout=None):
    # Use python -m yt_dlp so PYTHONPATH-installed updates take precedence over bundled
    return _run_yt(sys.executable, "-m", "yt_dlp", *_ffmpeg_args(), *_deno_args(),
                   *_cookies_args(), *_bgutil_args(), *extra, timeout=timeout)

# ── Helpers ────────────────────────────────────────────────────────────────────
def _safe_filename(title: str, ext: str) -> str:
    safe = "".join(c for c in title if c not in r'\/:\*?"<>|').strip()[:120].strip()
    return f"{safe}{ext}" if safe else f"download{ext}"

def _build_formats(info):
    best = {}
    for f in info.get("formats", []):
        h = f.get("height")
        if not h or (f.get("vcodec", "none") or "none") == "none": continue
        tbr = f.get("tbr") or 0
        if h not in best or tbr > (best[h].get("tbr") or 0): best[h] = f
    return sorted([{"id": f["format_id"], "label": f"{h}p", "height": h,
                    "has_audio": (f.get("acodec","none") or "none") != "none",
                    "acodec": f.get("acodec") or ""}
                   for h, f in best.items()], key=lambda x: x["height"], reverse=True)

def _build_audio_formats(info):
    seen, audio = set(), []
    for f in info.get("formats", []):
        if (f.get("vcodec","none") or "none") != "none": continue
        if (f.get("acodec","none") or "none") == "none": continue
        abr = f.get("abr") or f.get("tbr") or 0
        key = round(abr / 10) * 10
        if key in seen: continue
        seen.add(key)
        audio.append({"id": f["format_id"], "label": f"{int(abr)}kbps" if abr else "unknown", "abr": abr})
    return sorted(audio, key=lambda x: x["abr"], reverse=True)

# ── Download worker ────────────────────────────────────────────────────────────
def run_download(job_id, url, format_choice, format_id, download_dir, audio_codec="", concurrent_fragments=1, audio_quality="320", video_height=None, subtitles=False, embed_metadata=True, output_format="mp4"):
    job     = jobs.get(job_id)
    if not job:
        return  # Job was removed before worker started
    out_dir = Path(download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"{job_id}.%(ext)s")

    args = ["--no-playlist", "--no-check-formats", "--ignore-no-formats-error",
            "--retries", "5", "--fragment-retries", "5",
            "-o", out_tmpl]

    if concurrent_fragments > 1:
        args += ["--concurrent-fragments", str(concurrent_fragments)]

    if format_choice == "audio":
        # audio_quality: "128"/"192"/"320" (MP3 kbps), "flac", "m4a_256" (M4A), "opus_128" (OPUS)
        if audio_quality == "flac":
            args += ["-x", "--audio-format", "flac"]
        elif audio_quality.startswith("m4a_"):
            bitrate = audio_quality.split("_")[1]
            args += ["-x", "--audio-format", "m4a",
                     "--postprocessor-args", f"ffmpeg:-b:a {bitrate}k"]
        elif audio_quality.startswith("opus_"):
            bitrate = audio_quality.split("_")[1]
            args += ["-x", "--audio-format", "opus",
                     "--postprocessor-args", f"ffmpeg:-b:a {bitrate}k"]
        else:
            q = audio_quality if audio_quality in ("128", "192", "320") else "320"
            args += ["-x", "--audio-format", "mp3",
                     "--postprocessor-args", f"ffmpeg:-b:a {q}k"]
        if format_id: args += ["-f", format_id]
        # Audio thumbnail embedding via mutagen (handles MP3/M4A/OPUS)
        if embed_metadata:
            args += ["--embed-thumbnail", "--embed-metadata"]
    else:
        # 4d: Container — default mp4. --remux-video ensures final container even
        # when format selection picks a progressive stream that doesn't trigger merge.
        container = output_format if output_format in ("mp4", "mkv") else "mp4"
        args += ["--merge-output-format", container, "--remux-video", container]
        audio_is_aac = audio_codec and ("mp4a" in audio_codec or audio_codec == "aac")
        if audio_is_aac:
            args += ["--postprocessor-args", "ffmpeg:-c copy"]
        else:
            args += ["--postprocessor-args", "ffmpeg:-c:v copy -c:a aac -b:a 192k"]
        # Retry hardening for long/throttled video downloads — YouTube CDN throttles
        # high-bitrate streams (4K HDR, 8K, 240fps) which causes default 5-retry
        # tolerance to be exhausted on transient hiccups. 25 retries with linear
        # backoff (1s, 2s, 3s, 4s, 5s) survives ~90s throttle windows gracefully.
        args += ["--retries", "25", "--fragment-retries", "25",
                 "--socket-timeout", "30", "--retry-sleep", "linear=1::5"]
        if format_id:
            args += ["-f", f"{format_id}+bestaudio/{format_id}/bestvideo+bestaudio/best"]
        elif video_height and video_height != 0:
            args += ["-f", f"bestvideo[height<={video_height}]+bestaudio/best[height<={video_height}]/best"]
        else:
            args += ["-f", "bestvideo+bestaudio/best"]
        # 4a: Metadata embedding — chapters + metadata into video
        # Note: --embed-thumbnail removed; bundled ffmpeg lacks MP4 cover art muxer
        if embed_metadata:
            args += ["--embed-metadata", "--embed-chapters"]
        # Subtitles — embed English subs into the video (only meaningful for video downloads)
        if subtitles:
            args += ["--write-subs", "--write-auto-subs", "--sub-langs", "en", "--embed-subs"]
    args.append(url)

    cmd = [sys.executable, "-m", "yt_dlp"] + _ffmpeg_args() + _deno_args() + _cookies_args() + _bgutil_args() + args
    try:
        proc = _popen_yt(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace",
                         start_new_session=True)
        job["proc"]   = proc
        job["status"] = "downloading"
        job["speed"]  = ""

        with _active_procs_lock:
            _active_procs[job_id] = proc

        # Drain stderr in background to prevent pipe buffer deadlock
        # Cap at 200 lines — only the last line matters for error reporting.
        stderr_lines = deque(maxlen=200)
        def _drain_stderr():
            for l in proc.stderr:
                stderr_lines.append(l)
        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        pct_re   = _re.compile(r"\[download\]\s+([\d.]+)%")
        speed_re = _re.compile(r"at\s+([\d.]+\s*[KMG]iB/s)")
        eta_re   = _re.compile(r"ETA\s+(\d+:\d+)")
        size_re  = _re.compile(r"of\s+([\d.]+\s*[KMGiB]+)")
        for line in proc.stdout:
            line = line.rstrip()
            if "[Merger]" in line or "[VideoRemuxer]" in line or "[ExtractAudio]" in line:
                job["status"] = "converting"
                job["speed"]  = ""
                continue
            m = pct_re.search(line)
            if m:
                job["progress"] = float(m.group(1))
                sm = speed_re.search(line)
                job["speed"] = sm.group(1).strip() if sm else ""
                em = eta_re.search(line)
                if em: job["eta"] = em.group(1)
                szm = size_re.search(line)
                if szm: job["filesize"] = szm.group(1).strip()

        proc.wait()
        stderr_thread.join()
        stderr_data = "".join(stderr_lines)
        job["proc"] = None

        with _active_procs_lock:
            _active_procs.pop(job_id, None)

        if job.get("cancelled"):
            _cleanup(job_id, out_dir)
            job["status"] = "cancelled"
            job["_finished_at"] = time.time()
            return

        if proc.returncode != 0:
            # Determine the expected extension before cleanup
            if format_choice == "audio":
                if audio_quality == "flac":              _want = ".flac"
                elif audio_quality.startswith("m4a_"):   _want = ".m4a"
                elif audio_quality.startswith("opus_"):  _want = ".opus"
                else:                                    _want = ".mp3"
            else:
                _want = ".mkv" if output_format == "mkv" else ".mp4"

            # Clean temp/intermediate files; look for a usable main file
            _all = glob.glob(str(out_dir / f"{job_id}.*"))
            _temp_exts = {".vt", ".webp", ".json", ".ytdl", ".part"}
            _main_file = None
            for _f in _all:
                _p = Path(_f)
                if _p.suffix in _temp_exts or ".temp." in _p.name:
                    try: os.remove(_f)
                    except Exception: pass
                elif _p.suffix == _want and not _main_file:
                    _main_file = _f

            if _main_file and os.path.getsize(_main_file) > 0:
                # Download succeeded — only postprocessing (thumbnail/metadata) failed
                # Rename and deliver with a warning instead of hard error
                _ext   = os.path.splitext(_main_file)[1]
                _title = job.get("title", "").strip()
                _fname = _safe_filename(_title, _ext) if _title else os.path.basename(_main_file)
                _fpath = out_dir / _fname
                _stem, _n = Path(_fname).stem, 1
                while _fpath.exists() and str(_fpath) != _main_file:
                    _fpath = out_dir / f"{_stem} ({_n}){_ext}"; _n += 1
                try: os.rename(_main_file, _fpath)
                except OSError: _fpath = Path(_main_file)
                job["file"]        = str(_fpath)
                job["filename"]    = _fpath.name
                job["warning"]     = "Download complete — metadata embedding skipped."
                job["_finished_at"] = time.time()
                _append_history(job, _fpath)
                job["status"]      = "done"
                return

            # No usable file found — clean up and report error
            _cleanup(job_id, out_dir)
            err = [l for l in stderr_data.strip().splitlines()
                   if l.strip() and not l.strip().startswith("WARNING")]
            raw_err = err[-1] if err else stderr_data.strip()
            job["status"] = "error"
            job["error"]  = _friendly_error(raw_err)
            job["_finished_at"] = time.time()
            return

        files = glob.glob(str(out_dir / f"{job_id}.*"))
        if not files:
            job["status"] = "error"; job["error"] = "No output file found."; return

        if format_choice == "audio":
            if audio_quality == "flac":        want = ".flac"
            elif audio_quality.startswith("m4a_"):  want = ".m4a"
            elif audio_quality.startswith("opus_"): want = ".opus"
            else:                              want = ".mp3"
        else:
            want = ".mkv" if output_format == "mkv" else ".mp4"
        preferred = [f for f in files if f.endswith(want)]
        chosen    = preferred[0] if preferred else files[0]
        for f in files:
            if f != chosen:
                try: os.remove(f)
                except Exception: pass

        ext        = os.path.splitext(chosen)[1]
        title      = job.get("title", "").strip()
        final_name = _safe_filename(title, ext) if title else os.path.basename(chosen)
        final_path = out_dir / final_name
        stem, n    = Path(final_name).stem, 1
        while final_path.exists() and str(final_path) != chosen:
            final_path = out_dir / f"{stem} ({n}){ext}"; n += 1
        try: os.rename(chosen, final_path)
        except OSError: final_path = Path(chosen)

        # Safety net — clean up any leftover subtitle temp files yt-dlp didn't remove after --embed-subs
        for ext in (".vtt", ".srt"):
            for sub in out_dir.glob(f"{job_id}*{ext}"):
                try: sub.unlink()
                except OSError: pass
        job["file"]     = str(final_path)
        job["filename"] = final_path.name
        job["_finished_at"] = time.time()
        _append_history(job, final_path)
        job["status"]   = "done"

    except Exception as e:
        with _active_procs_lock:
            _active_procs.pop(job_id, None)
        job["status"] = "error"
        job["error"]  = _friendly_error(str(e))
        job["_finished_at"] = time.time()

def _cleanup(job_id, out_dir):
    for f in glob.glob(str(Path(out_dir) / f"{job_id}.*")):
        try: os.remove(f)
        except Exception: pass

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html", egm_token=_API_TOKEN, platform_url="https://egerena.com/apps/egml.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    if not url: return jsonify({"error": "No URL provided"}), 400
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"error": "Only http and https URLs are supported"}), 400
    try:
        r = _ytdlp("--no-playlist", "-j", url, timeout=60)
        if r.returncode != 0:
            err = [l for l in r.stderr.splitlines() if l.strip() and not l.startswith("WARNING")]
            return jsonify({"error": err[-1] if err else "yt-dlp error"}), 400
        jl = next((l for l in r.stdout.splitlines() if l.strip().startswith("{")), None)
        if not jl: return jsonify({"error": "No metadata returned"}), 400
        info = json.loads(jl)
        return jsonify({"title": info.get("title",""), "thumbnail": info.get("thumbnail",""),
                        "duration": info.get("duration"),
                        "uploader": info.get("uploader") or info.get("channel") or "",
                        "formats": _build_formats(info), "audio_formats": _build_audio_formats(info),
                        "width": info.get("width"), "height": info.get("height")})
    except subprocess.TimeoutExpired: return jsonify({"error": "Timed out"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/playlist", methods=["POST"])
def get_playlist():
    data = request.get_json(silent=True) or {}
    url  = data.get("url", "").strip()
    if not url: return jsonify({"error": "No URL provided"}), 400
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"error": "Only http and https URLs are supported"}), 400
    try:
        r = _ytdlp("--flat-playlist", "-j", url, timeout=90)
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("{")]
        entries = []
        for line in lines:
            try:
                e  = json.loads(line)
                eu = e.get("webpage_url") or e.get("url") or ""
                if eu and not eu.startswith("http"): eu = f"https://www.youtube.com/watch?v={eu}"
                th = (e.get("thumbnails") or [{}])[-1].get("url","") if e.get("thumbnails") else e.get("thumbnail","")
                entries.append({"url": eu, "title": e.get("title") or e.get("id") or "Unknown",
                                 "thumbnail": th, "duration": e.get("duration"),
                                 "uploader": e.get("uploader") or e.get("channel") or ""})
            except Exception: continue
        if not entries: return jsonify({"is_playlist": False}), 200
        pl = ""
        for l in r.stderr.splitlines():
            if "Downloading playlist:" in l: pl = l.split("Downloading playlist:")[-1].strip(); break
        return jsonify({"is_playlist": True, "playlist_title": pl, "entries": entries})
    except subprocess.TimeoutExpired: return jsonify({"error": "Timed out"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    url  = data.get("url","").strip()
    if not url: return jsonify({"error": "No URL provided"}), 400
    if not url.lower().startswith(("http://", "https://")):
        return jsonify({"error": "Only http and https URLs are supported"}), 400
    job_id = uuid.uuid4().hex[:10]
    dl_dir = data.get("download_dir") or _get_last_folder() or str(Path.home())

    # Traversal guard: warn if path looks like a system directory
    _SYSTEM_ROOTS = ("/etc", "/bin", "/sbin", "/usr/bin", "/sys", "/proc",
                     "C:\\Windows", "C:\\Program Files", "C:\\System32")
    dl_str = str(dl_dir).rstrip("/\\")
    for root in _SYSTEM_ROOTS:
        if dl_str.lower().startswith(root.lower()):
            return jsonify({"error": f"Download directory '{dl_dir}' looks like a system path. Please choose a different folder."}), 400

    # #13 — format_id validation: only safe yt-dlp selector characters allowed
    raw_format_id = data.get("format_id") or ""
    if raw_format_id and not _re.fullmatch(r'[A-Za-z0-9_+\-]+', raw_format_id):
        return jsonify({"error": "Invalid format_id"}), 400

    # #12 — bitrate validation: extract bitrate from m4a_NNN / opus_NNN and range-check
    audio_quality = data.get("audio_quality") or "320"
    if audio_quality.startswith(("m4a_", "opus_")):
        _bitrate_str = audio_quality.split("_", 1)[1]
        if not (_bitrate_str.isdigit() and 32 <= int(_bitrate_str) <= 320):
            return jsonify({"error": "Invalid audio bitrate"}), 400

    with _jobs_lock:
        jobs[job_id] = {"status": "queued", "url": url,
                        "title": data.get("title",""), "proc": None, "cancelled": False,
                        "download_dir": dl_dir, "format": data.get("format", "video")}
    threading.Thread(target=run_download,
                     args=(job_id, url, data.get("format","video"),
                           data.get("format_id") or None, dl_dir,
                           data.get("audio_codec") or "",
                           min(max(int(data.get("concurrent_fragments") or 1), 1), 16),
                           data.get("audio_quality") or "320",
                           (int(data.get("video_height")) if str(data.get("video_height","")) in ("360","480","720","1080","1440","2160","4320") else None),
                           bool(data.get("subtitles", False)),
                           bool(data.get("embed_metadata", True)),
                           data.get("output_format", "mp4")),
                     daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel_download(job_id):
    with _jobs_lock:
        job = jobs.get(job_id)
        if not job: return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in ("downloading", "queued"):
            return jsonify({"error": "Not downloading"}), 400
        job["cancelled"] = True
        proc = job.get("proc")
    # Release lock before kill — _kill_proc is slow and shouldn't hold the lock
    if proc:
        _kill_proc(proc)
    # Don't set status here — the worker thread sets it to "cancelled"
    # after proc.wait() confirms the process is dead and temp files are cleaned up.
    # Setting it here would race with the worker and could cause clearCompleted
    # to remove the card before the file cleanup is complete.
    return jsonify({"success": True})

@app.route("/api/status/<job_id>")
def check_status(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({"error": "Job not found"}), 404
    status = job["status"]
    resp = {"status": status, "error": job.get("error"),
            "filename": job.get("filename"), "progress": job.get("progress", 0),
            "speed": job.get("speed", ""), "eta": job.get("eta", ""),
            "filesize": job.get("filesize", "")}
    if status in ("done", "error", "cancelled") and job.get("_ack"):
        with _jobs_lock:
            jobs.pop(job_id, None)
    elif status in ("done", "error", "cancelled"):
        job["_ack"] = True
    return jsonify(resp)

@app.route("/api/settings")
def get_settings():
    s = _load_settings()
    return jsonify({
        "last_folder":             s.get("last_folder", ""),
        "concurrency":             s.get("concurrency", 6),
        "fragments":               s.get("fragments", 4),
        "settings_open":           s.get("settings_open", True),
        "upd_open":                s.get("upd_open", False),
        "ck_open":                 s.get("ck_open", False),
        "quit_on_done":            s.get("quit_on_done", False),
        "check_updates_on_launch": s.get("check_updates_on_launch", False),
        "flask_port":              s.get("flask_port", 8899),
        "last_seen_version":       s.get("last_seen_version", ""),
        # Promoted UI controls — must be returned so frontend can restore on init.
        # Without these, defaults always win regardless of what was saved.
        "subtitles":               s.get("subtitles", False),
        "embed_metadata":          s.get("embed_metadata", True),
        "output_format":           s.get("output_format", "mp4"),
        "default_audio_format":    s.get("default_audio_format", "320"),
        "theme":                   s.get("theme", ""),
    })

@app.route("/api/settings/save", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    ALLOWED = {"last_folder", "concurrency", "fragments", "settings_open",
               "upd_open", "ck_open", "quit_on_done", "flask_port",
               "last_seen_version", "window_bounds", "window_maximized", "check_updates_on_launch", "theme",
               "subtitles", "embed_metadata", "output_format"}
    if "last_folder" in data:
        folder = data["last_folder"]
        if folder:
            try: Path(folder).mkdir(parents=True, exist_ok=True)
            except Exception: pass
    _save_settings({k: v for k, v in data.items() if k in ALLOWED})
    return jsonify({"ok": True})

@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data   = request.get_json(silent=True) or {}
    folder = data.get("folder", _get_last_folder() or str(Path.home()))
    path   = Path(folder)
    if not path.exists() or not path.is_dir():
        return jsonify({"error": "Folder not found"}), 400
    try:
        _popen("xdg-open", str(path))
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/rename", methods=["POST"])
def rename_file():
    data = request.get_json(silent=True) or {}
    job_id, new_name = data.get("job_id","").strip(), data.get("name","").strip()
    if not job_id or not new_name: return jsonify({"error": "job_id and name required"}), 400
    job = jobs.get(job_id)
    if not job or job.get("status") != "done": return jsonify({"error": "Not complete"}), 404
    old_path = Path(job["file"])
    if not old_path.exists(): return jsonify({"error": "File not found"}), 404
    ext  = old_path.suffix
    safe = _safe_filename(new_name.removesuffix(ext), ext)
    new_path = old_path.parent / safe
    n, stem  = 1, Path(safe).stem
    while new_path.exists() and new_path != old_path:
        new_path = old_path.parent / f"{stem} ({n}){ext}"; n += 1
    try:
        old_path.rename(new_path)
        job["file"] = str(new_path); job["filename"] = new_path.name
        return jsonify({"success": True, "filename": new_path.name})
    except Exception as e: return jsonify({"error": str(e)}), 500

# ── Update system (yt-dlp + ffmpeg only — no app self-update on Linux) ─────────
def _get_ytdlp_version():
    try: return _run_yt(sys.executable, "-m", "yt_dlp", "--version", timeout=10).stdout.strip()
    except Exception: return "unknown"

def _get_ffmpeg_version():
    exe = FFMPEG_DIR / "ffmpeg"
    if not exe.exists(): return "not installed"
    tag = _get_ffmpeg_installed_tag()
    if tag: return tag
    try:
        r = _run(str(exe), "-version", timeout=10)
        parts = (r.stdout.splitlines()[0] if r.stdout else "").split()
        return parts[2] if len(parts) > 2 else "unknown"
    except Exception: return "unknown"

def _get_ffmpeg_installed_tag():
    try: return FFMPEG_TAG_FILE.read_text().strip()
    except Exception: return ""

def _get_latest_ffmpeg_tag():
    try:
        req = urllib.request.Request("https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest",
                                     headers={"User-Agent":"EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("tag_name","unknown")
    except Exception: return "unknown"

def _get_latest_ytdlp_version():
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
            headers={"User-Agent":"EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("tag_name","unknown")
    except Exception: return "unknown"

update_status: dict = {}

def _run_update(do_ytdlp, do_ffmpeg):
    global update_status
    update_status = {"running": True, "log": [], "done": False, "error": None}
    def log(m): print(f"[EGM] {m}"); update_status["log"].append(m)
    try:
        if do_ytdlp:
            PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
            stable_ver = _get_latest_ytdlp_version()
            if stable_ver and stable_ver != "unknown":
                log(f"Installing yt-dlp stable {stable_ver}...")
                r = _run(sys.executable, "-m", "pip", "install",
                         f"yt-dlp=={stable_ver}", "--target", str(PACKAGES_DIR),
                         "--upgrade", timeout=120)
            else:
                log("Installing yt-dlp stable (latest)...")
                r = _run(sys.executable, "-m", "pip", "install", "yt-dlp",
                         "--target", str(PACKAGES_DIR), "--upgrade", timeout=120)
            v = _get_ytdlp_version()
            if r.returncode == 0:
                log(f"yt-dlp -> {v}")
            else:
                err = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
                log(f"yt-dlp update failed: {err}")
        if do_ffmpeg:
            log("Downloading latest ffmpeg...")
            FFMPEG_DIR.mkdir(exist_ok=True)
            tmp = FFMPEG_DIR / "ffmpeg_update.tar.xz"
            req = urllib.request.Request(FFMPEG_URL, headers={"User-Agent": "EGM-Downloader"})
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            ok, msg = _verify_upstream_checksum(tmp,
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256",
                "ffmpeg-master-latest-linux64-gpl.tar.xz")
            log(msg)
            if not ok:
                tmp.unlink(missing_ok=True)
                update_status["error"] = "Checksum mismatch — update aborted"
                update_status["done"]  = True
                return
            log("Extracting...")
            with tarfile.open(tmp, "r:xz") as t:
                for member in t.getmembers():
                    fn = Path(member.name).name
                    if fn in ("ffmpeg", "ffprobe") and member.isfile():
                        member.name = fn
                        t.extract(member, FFMPEG_DIR)
            tmp.unlink(missing_ok=True)
            ffmpeg_bin  = FFMPEG_DIR / "ffmpeg"
            ffprobe_bin = FFMPEG_DIR / "ffprobe"
            if ffmpeg_bin.exists():  os.chmod(ffmpeg_bin,  0o755)
            if ffprobe_bin.exists(): os.chmod(ffprobe_bin, 0o755)
            try: FFMPEG_TAG_FILE.write_text(_get_latest_ffmpeg_tag())
            except Exception: pass
            log(f"ffmpeg -> {_get_ffmpeg_version()}")
        log("All done.")
        update_status["done"] = True
    except Exception as e:
        log(f"Error: {e}"); update_status["error"] = str(e)
    finally:
        update_status["running"] = False

@app.route("/api/check-updates")
def check_updates():
    cy, ly = _get_ytdlp_version(), _get_latest_ytdlp_version()
    cf, lf = _get_ffmpeg_version(), _get_latest_ffmpeg_tag()
    cm     = _get_mutagen_version()
    # Mutagen on Linux is informational-only — bundled Python has no pip,
    # so we can't upgrade in-app. latest=None / up_to_date=None tells the UI
    # to render the "—" badge instead of green/red, and prevents the slow
    # endpoint from clobbering the fast endpoint's correct version with
    # undefined → "checking…" placeholder.
    ytdlp_ok = cy != "unknown" and cy == ly
    return jsonify({
        "ytdlp":   {"current": cy, "latest": ly, "up_to_date": ytdlp_ok},
        "ffmpeg":  {"current": cf, "latest": lf,
                    "up_to_date": cf not in ("not installed","unknown") and lf != "unknown" and cf == lf},
        "mutagen": {"current": cm, "latest": None, "up_to_date": None},
    })

@app.route("/api/run-update", methods=["POST"])
def run_update():
    if update_status.get("running"): return jsonify({"error": "Already running"}), 409
    data = request.get_json(silent=True) or {}
    threading.Thread(target=_run_update,
                     args=(bool(data.get("ytdlp",True)), bool(data.get("ffmpeg",False))),
                     daemon=True).start()
    return jsonify({"started": True})

@app.route("/api/update-status")
def get_update_status():
    return jsonify(update_status or {"running": False, "done": False, "log": []})

def _get_mutagen_version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("mutagen")
    except Exception:
        return "not installed"


@app.route("/api/installed-versions")
def installed_versions():
    """Return only locally-installed versions — no network calls. Fast, for panel expand."""
    cy = _get_ytdlp_version()
    cf = _get_ffmpeg_version()
    cm = _get_mutagen_version()
    deno_installed = DENO_EXE.exists()
    deno_version   = _get_deno_version() if deno_installed else "not installed"
    return jsonify({
        "ytdlp":   {"current": cy, "latest": None, "up_to_date": None},
        "ffmpeg":  {"current": cf, "latest": None, "up_to_date": None},
        "mutagen": {"current": cm, "latest": None, "up_to_date": None},
        "deno":    {"installed": deno_installed, "version": deno_version},
    })

@app.route("/api/cookies/status")
def cookies_status():
    exists = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0
    age_days = None
    if exists:
        saved_at = _load_settings().get("cookies_saved_at")
        age_days = int((time.time() - saved_at) / 86400) if saved_at else None
    return jsonify({"active": exists, "path": str(COOKIES_FILE), "age_days": age_days})

@app.route("/api/cookies/save", methods=["POST"])
def cookies_save():
    data = request.get_json(silent=True) or {}
    text = data.get("content", "").strip()
    if not text:
        return jsonify({"error": "No content provided"}), 400
    if len(text) > 1 * 1024 * 1024:  # 1 MB cap for cookies content
        return jsonify({"error": "Cookies file too large (max 1 MB)"}), 413
    try:
        COOKIES_FILE.write_text(text, encoding="utf-8")
        _chmod_owner_only(COOKIES_FILE)
        _save_settings({"cookies_saved_at": int(time.time())})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cookies/clear", methods=["POST"])
def cookies_clear():
    try:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        _save_settings({"cookies_saved_at": None})
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/deno/status")
def deno_status():
    installed = DENO_EXE.exists()
    version   = _get_deno_version() if installed else "not installed"
    return jsonify({"installed": installed, "version": version})

deno_install_status: dict = {}

def _run_deno_install():
    global deno_install_status
    deno_install_status = {"running": True, "log": [], "done": False, "error": None}
    def log(m): print(f"[EGM] {m}"); deno_install_status["log"].append(m)
    tmp = DENO_DIR / "deno_tmp.zip"
    try:
        DENO_DIR.mkdir(parents=True, exist_ok=True)
        log("Fetching latest Deno release info...")

        req = urllib.request.Request(
            "https://api.github.com/repos/denoland/deno/releases/latest",
            headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=15) as r:
            release = json.loads(r.read())
        tag    = release.get("tag_name", "")
        assets = release.get("assets", [])
        url = next(
            (a["browser_download_url"] for a in assets
             if a["name"] == "deno-x86_64-unknown-linux-gnu.zip"),
            DENO_ZIP_URL)
        version_label = tag or "latest"
        log(f"Downloading Deno {version_label} (~95 MB)...")

        downloaded = 0
        chunk = 1024 * 256
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            next_report = 5 * 1024 * 1024
            while True:
                block = resp.read(chunk)
                if not block: break
                f.write(block)
                downloaded += len(block)
                if downloaded >= next_report:
                    mb = downloaded / (1024 * 1024)
                    if total:
                        pct = int(downloaded / total * 100)
                        log(f"  {mb:.0f} MB / {total/1024/1024:.0f} MB ({pct}%)")
                    else:
                        log(f"  {mb:.0f} MB downloaded...")
                    next_report += 5 * 1024 * 1024

        log("Extracting deno...")
        with zipfile.ZipFile(tmp, "r") as z:
            if "deno" not in z.namelist():
                raise RuntimeError("deno binary not found in zip archive")
            z.extract("deno", DENO_DIR)
        tmp.unlink(missing_ok=True)

        log("Setting executable permissions...")
        os.chmod(DENO_EXE, 0o755)

        ver = _get_deno_version()
        if ver in ("unknown", "not installed"):
            raise RuntimeError("deno extracted but failed to run")

        log(f"Deno {ver} ready. Done.")
        deno_install_status["done"] = True
    except Exception as e:
        log(f"Error: {e}")
        deno_install_status["error"] = str(e)
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        try:
            if DENO_EXE.exists(): DENO_EXE.unlink()
        except Exception: pass
    finally:
        deno_install_status["running"] = False

@app.route("/api/deno/install", methods=["POST"])
def install_deno():
    if deno_install_status.get("running"):
        return jsonify({"error": "Install already running"}), 409
    if DENO_EXE.exists():
        return jsonify({"error": "Deno already installed"}), 400
    threading.Thread(target=_run_deno_install, daemon=True).start()
    return jsonify({"started": True})

@app.route("/api/deno/install-status")
def deno_install_progress():
    return jsonify(deno_install_status or {"running": False, "done": False, "log": []})

@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    """Clear orphaned partial download files."""
    cleared = []
    try:
        last_folder = _load_settings().get("last_folder", "")
        if last_folder:
            dl_path = Path(last_folder)
            if dl_path.is_dir():
                for pattern in ("*.part", "*.ytdl"):  # *.f*.mp4 and *.f*.webm removed — too broad for user download folder
                    for f in dl_path.glob(pattern):
                        try: f.unlink(); cleared.append(f.name)
                        except Exception: pass
    except Exception: pass
    return jsonify({"ok": True, "cleared": cleared})

@app.route("/api/settings/reset", methods=["POST"])
def settings_reset():
    """Reset all settings to defaults — keeps downloads and history."""
    try:
        SETTINGS_FILE.write_text("{}", encoding="utf-8")
        _chmod_owner_only(SETTINGS_FILE)
        global _settings_cache
        with _settings_lock:
            _settings_cache = {}
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/ffmpeg/reinstall", methods=["POST"])
def ffmpeg_reinstall():
    """Delete ffmpeg binaries so they are re-downloaded on next launch."""
    try:
        for f in FFMPEG_DIR.glob("*"):
            try: f.unlink()
            except Exception: pass
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/deno/reinstall", methods=["POST"])
def deno_reinstall():
    """Delete Deno binary so it is reinstalled on next launch."""
    try:
        if DENO_EXE.exists(): DENO_EXE.unlink()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Check for app update (informational only — Linux has no auto-install) ─────

@app.route("/api/whats-new")
def whats_new():
    """Return _version_notes from the platform JSON feed for the What's New modal.
    Falls back to empty list gracefully — modal stays shown but with no bullets."""
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
                                     headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        notes = data.get("_version_notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)] if notes else []
        return jsonify({
            "version": data.get("version", APP_VERSION),
            "notes_list": notes,
        })
    except Exception:
        return jsonify({"version": APP_VERSION, "notes_list": []})

@app.route("/api/check-app-update")
def check_app_update():
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
            headers={"User-Agent": f"EGMDownloader/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode())
        latest_ver   = str(data.get("version", "")).strip()
        latest_build = int(data.get("build", 0))
        notes        = data.get("_version_notes", data.get("notes", []))
        if isinstance(notes, list): notes = "\n".join(notes)
        else: notes = str(notes).strip()
        download_url = str(data.get("downloadUrl", "https://egerena.com/apps/egml.html")).strip()
        up_to_date   = (latest_ver == APP_VERSION and latest_build <= APP_BUILD)
        return jsonify({
            "up_to_date":      up_to_date,
            "current_version": APP_VERSION,
            "current_build":   APP_BUILD,
            "latest_version":  latest_ver,
            "latest_build":    latest_build,
            "notes":           notes,
            "download_url":    download_url,
            "_checksums":      data.get("_checksums"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 200

# ── History routes ────────────────────────────────────────────────────────────
@app.route("/api/history")
def get_history():
    page     = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 10))
    with _history_lock:
        items = _load_history()
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page  = max(1, min(page, pages))
    start = (page - 1) * per_page
    return jsonify({"items": items[start:start+per_page], "total": total,
                    "page": page, "pages": pages, "per_page": per_page})

@app.route("/api/history/<entry_id>", methods=["DELETE"])
def delete_history_entry(entry_id):
    with _history_lock:
        items = _load_history()
        items = [i for i in items if i.get("id") != entry_id]
        _save_history(items)
    return jsonify({"ok": True})

@app.route("/api/history/clear", methods=["POST"])
def clear_history():
    with _history_lock:
        _save_history([])
    return jsonify({"ok": True})

@app.route("/api/history/import", methods=["POST"])
def import_history():
    """Replace history with the provided list. Used by Import Settings flow."""
    data = request.get_json(silent=True) or {}
    items = data.get("items", [])
    if not isinstance(items, list):
        return jsonify({"error": "items must be a list"}), 400
    # Light validation — keep only entries with the expected shape
    cleaned = [i for i in items if isinstance(i, dict) and "id" in i]
    with _history_lock:
        _save_history(cleaned)
    return jsonify({"ok": True, "count": len(cleaned)})

@app.route("/history-page")
def history_page(): return render_template("history.html", egm_token=_API_TOKEN)

@app.route("/themes-page")
def themes_page(): return render_template("themes.html")

@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    """Clean shutdown requested by Electron before-quit."""
    def _do_shutdown():
        time.sleep(0.15)
        with _active_procs_lock:
            procs = list(_active_procs.values())
        for p in procs:
            _kill_proc(p)
        os._exit(0)
    threading.Thread(target=_do_shutdown, daemon=True).start()
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Clean up any orphaned .part and .ytdl files left by a crashed session
    try:
        last_folder = _load_settings().get("last_folder", "")
        if last_folder:
            dl_path = Path(last_folder)
            if dl_path.is_dir():
                for pattern in ("*.part", "*.ytdl"):  # *.f*.mp4 and *.f*.webm removed — too broad for user download folder
                    for f in dl_path.glob(pattern):
                        try: f.unlink()
                        except Exception: pass
    except Exception:
        pass

    ensure_ffmpeg()
    port = int(_load_settings().get("flask_port", os.environ.get("PORT", 8899)))
    host = "127.0.0.1"  # always localhost — never exposed to network
    threading.Thread(target=lambda: app.run(host=host, port=port, use_reloader=False),
                     daemon=True, name="flask").start()
    print(f"[EGM Downloader] running on http://{host}:{port}")
    try: threading.Event().wait()
    except KeyboardInterrupt: pass
