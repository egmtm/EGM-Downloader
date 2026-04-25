import os
import sys
import uuid
import glob
import json
import subprocess
import re as _re
import time
import threading
import urllib.request
import zipfile
import shutil
import platform as _platform
from pathlib import Path
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)

# ── Platform detection (Mac build — arm64 primary, x86_64 fallback) ───────────
IS_ARM = _platform.machine().lower() in ("arm64", "aarch64")

# ── Paths ──────────────────────────────────────────────────────────────────────
# BASE_DIR: read-only bundle root (templates, static, python binary).
# DATA_DIR: mutable user data that must survive app updates.
#
# When packaged inside Electron (.app bundle), app.py lives at
# Resources/app/app.py — BASE_DIR goes up to Resources/.
# Mutable files (ffmpeg, Deno, settings, cookies) are stored in
# ~/Library/Application Support/EGM Downloader/ so they survive
# every update (dragging a new .app never touches that directory).
if os.environ.get("EGM_ELECTRON") == "1":
    BASE_DIR = Path(__file__).parent.parent  # Resources/
    DATA_DIR = Path.home() / "Library" / "Application Support" / "EGM Downloader"
else:
    BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    DATA_DIR = BASE_DIR

DATA_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_DIR = DATA_DIR / "ffmpeg_bin"

# ── App version — keep in sync with index.html build stamp ───────────────────
APP_VERSION           = "0.94"
APP_BUILD             = 96
APP_UPDATE_URL        = "https://egerena.com/apps/egmac-update.json"
APP_UPDATE_ZIP_URL    = "https://egerena.com/apps/EGMdM.zip"
APP_UPDATE_PASSWORD   = "EGMsterling"

# ── Update temp dir — cleaned up on startup if present ───────────────────────
UPDATE_TMP_DIR = Path(os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))) / "egm-update"

# Settings file: persists last used folder — lives in DATA_DIR so it
# survives app updates (DATA_DIR is never touched when dragging a new .app).
SETTINGS_FILE = DATA_DIR / "egm_settings.json"

# ── Cookies: path to cookies.txt — managed via Settings UI ───────────────────
COOKIES_FILE = DATA_DIR / "cookies.txt"

_settings_cache: dict = {}
_settings_lock  = threading.Lock()

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
        except Exception:
            pass

def _get_last_folder() -> str:
    return _load_settings().get("last_folder", "")

jobs: dict = {}

# ── Active process registry — used to kill yt-dlp+ffmpeg trees on cancel/quit ─
# Maps job_id → proc. Maintained by run_download; cleared when proc exits.
_active_procs: dict = {}
_active_procs_lock  = threading.Lock()

def _kill_proc(proc: subprocess.Popen) -> None:
    """Kill a yt-dlp process and its entire child tree (including ffmpeg).
    On Windows uses taskkill /F /T which traverses the process tree.
    On other platforms falls back to proc.kill() (Unix signals propagate via
    process groups when yt-dlp is not detached, which is our case)."""
    if proc is None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, creationflags=_NO_WINDOW
            )
        else:
            proc.kill()
    except Exception:
        pass

# ── No console window on Windows ──────────────────────────────────────────────
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

def _run(*cmd, timeout=None, **kw):
    return subprocess.run(list(cmd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=_NO_WINDOW, **kw)

def _popen(*cmd, **kw):
    return subprocess.Popen(list(cmd), creationflags=_NO_WINDOW, **kw)

def _yt_env() -> dict:
    """Environment for yt-dlp subprocesses.
    Injects the bundled deno.exe path so bgutil-ytdlp-pot-provider can find it.
    Only set when deno is actually installed — avoids bgutil attempting token
    generation and failing when deno is absent."""
    env = os.environ.copy()
    if DENO_EXE.exists():
        env["DENO"] = str(DENO_EXE)
    return env

def _run_yt(*cmd, timeout=None, **kw):
    """subprocess.run with yt-dlp environment (DENO injected if available)."""
    return subprocess.run(list(cmd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env=_yt_env(), timeout=timeout,
                          creationflags=_NO_WINDOW, **kw)

def _popen_yt(*cmd, **kw):
    """subprocess.Popen with yt-dlp environment (DENO injected if available)."""
    return subprocess.Popen(list(cmd), env=_yt_env(),
                            creationflags=_NO_WINDOW, **kw)

# ── ffmpeg: Mac ARM/Intel builds from evermeet.cx ─────────────────────────────
# Mac delivers ffmpeg and ffprobe as SEPARATE zip downloads (unlike Windows' single zip)
FFMPEG_URL      = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
FFPROBE_URL     = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
FFMPEG_TAG_FILE = FFMPEG_DIR / "build_tag.txt"

# ── Deno: bundled JS runtime required for YouTube (no admin, no PATH needed) ──
DENO_DIR     = DATA_DIR / "runtime"
DENO_EXE     = DENO_DIR / "deno"   # Mac: no .exe suffix
# Apple Silicon (arm64) gets native binary; Intel Mac falls back to x86_64
if IS_ARM:
    DENO_ZIP_NAME = "deno-aarch64-apple-darwin.zip"
else:
    DENO_ZIP_NAME = "deno-x86_64-apple-darwin.zip"
DENO_ZIP_URL = f"https://github.com/denoland/deno/releases/latest/download/{DENO_ZIP_NAME}"

def ensure_ffmpeg():
    ffmpeg_bin  = FFMPEG_DIR / "ffmpeg"
    ffprobe_bin = FFMPEG_DIR / "ffprobe"
    if ffmpeg_bin.exists() and ffprobe_bin.exists():
        print("[EGM] ffmpeg ready.")
        return True
    print("[EGM] Downloading ffmpeg and ffprobe (first run only)...")
    FFMPEG_DIR.mkdir(exist_ok=True)
    tmp_ffmpeg  = FFMPEG_DIR / "ffmpeg_tmp.zip"
    tmp_ffprobe = FFMPEG_DIR / "ffprobe_tmp.zip"
    try:
        # evermeet.cx delivers two separate zips, each containing the single binary
        urllib.request.urlretrieve(FFMPEG_URL, tmp_ffmpeg)
        with zipfile.ZipFile(tmp_ffmpeg, "r") as z:
            if "ffmpeg" not in z.namelist():
                raise RuntimeError("ffmpeg binary not found in evermeet zip")
            z.extract("ffmpeg", FFMPEG_DIR)
        tmp_ffmpeg.unlink(missing_ok=True)

        urllib.request.urlretrieve(FFPROBE_URL, tmp_ffprobe)
        with zipfile.ZipFile(tmp_ffprobe, "r") as z:
            if "ffprobe" not in z.namelist():
                raise RuntimeError("ffprobe binary not found in evermeet zip")
            z.extract("ffprobe", FFMPEG_DIR)
        tmp_ffprobe.unlink(missing_ok=True)

        # Make binaries executable
        os.chmod(ffmpeg_bin,  0o755)
        os.chmod(ffprobe_bin, 0o755)

        try: FFMPEG_TAG_FILE.write_text(_get_latest_ffmpeg_tag())
        except Exception: pass
        print("[EGM] ffmpeg ready.")
        return True
    except Exception as e:
        print(f"[EGM] ffmpeg download failed: {e}")
        for t in (tmp_ffmpeg, tmp_ffprobe):
            try: t.unlink(missing_ok=True)
            except Exception: pass
        return False

def _ffmpeg_args():
    return ["--ffmpeg-location", str(FFMPEG_DIR)]


def _deno_args():
    """Return --js-runtimes flag pointing at bundled deno.exe, or [] if not installed."""
    if DENO_EXE.exists():
        return ["--js-runtimes", f"deno:{DENO_EXE}"]
    return []

def _get_deno_version() -> str:
    """Read version from deno.exe directly — no PATH dependency."""
    if not DENO_EXE.exists():
        return "not installed"
    try:
        r = _run(str(DENO_EXE), "--version", timeout=10)
        # Output: "deno 2.x.x ..."
        line = r.stdout.splitlines()[0] if r.stdout else ""
        parts = line.split()
        return parts[1] if len(parts) >= 2 else "unknown"
    except Exception:
        return "unknown"

def _cookies_args() -> list:
    """Return --cookies flag if cookies.txt exists and is non-empty, else []."""
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
        return ["--cookies", str(COOKIES_FILE)]
    return []

def _bgutil_args() -> list:
    """When deno is absent, tell yt-dlp never to fetch PO Tokens — prevents
    bgutil from attempting token generation and failing silently, which can
    corrupt the format list and cause 'Requested format is not available'.
    When deno IS present, bgutil generates tokens automatically; no extra args needed."""
    if not DENO_EXE.exists():
        return ["--extractor-args", "youtube:fetch_pot=never"]
    return []

def _ytdlp(*extra, timeout=None):
    # Invoke via `sys.executable -m yt_dlp` so we use the bundled Python and its
    # installed yt-dlp, not relying on PATH. On Mac, Resources/python/bin/ is not
    # on PATH when Electron spawns Python, so bare `yt-dlp` would fail.
    return _run_yt(sys.executable, "-m", "yt_dlp", *_ffmpeg_args(), *_deno_args(), *_cookies_args(),
                   *_bgutil_args(), *extra, timeout=timeout)

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
def run_download(job_id, url, format_choice, format_id, download_dir, audio_codec="", concurrent_fragments=1):
    job     = jobs[job_id]
    out_dir = Path(download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"{job_id}.%(ext)s")

    args = ["--no-playlist", "--no-check-formats", "--ignore-no-formats-error",
            "-o", out_tmpl]

    # Parallel fragment downloads — speeds up individual video downloads on fast connections
    if concurrent_fragments > 1:
        args += ["--concurrent-fragments", str(concurrent_fragments)]

    if format_choice == "audio":
        args += ["-x", "--audio-format", "mp3"]
        if format_id: args += ["-f", format_id]
    else:
        args += ["--merge-output-format", "mp4"]
        # If the selected format's paired audio is already AAC, remux with -c copy.
        # Otherwise (opus, vorbis, unknown) re-encode audio to AAC for mp4 compatibility.
        # Video is always stream-copied (-c:v copy) — never re-encoded.
        audio_is_aac = audio_codec and ("mp4a" in audio_codec or audio_codec == "aac")
        if audio_is_aac:
            args += ["--postprocessor-args", "ffmpeg:-c copy"]
        else:
            args += ["--postprocessor-args", "ffmpeg:-c:v copy -c:a aac -b:a 192k"]
        args += ["-f", f"{format_id}+bestaudio/{format_id}/bestvideo+bestaudio/best"
                 if format_id else "bestvideo+bestaudio/best"]
    args.append(url)

    cmd = [sys.executable, "-m", "yt_dlp"] + _ffmpeg_args() + _deno_args() + _cookies_args() + _bgutil_args() + args
    try:
        proc = _popen_yt(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
        job["proc"]    = proc
        job["status"]  = "downloading"
        job["speed"]   = ""

        # Register in active proc registry so cancel and shutdown can kill the tree
        with _active_procs_lock:
            _active_procs[job_id] = proc

        # Drain stderr in a background thread to prevent pipe buffer deadlock.
        # ffmpeg writes extensively to stderr during audio conversion — if nobody
        # reads it the OS pipe buffer fills (~64KB), ffmpeg blocks, yt-dlp blocks,
        # and our stdout loop waits forever (process never exits).
        stderr_lines = []
        def _drain_stderr():
            for l in proc.stderr:
                stderr_lines.append(l)
        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # Patterns for yt-dlp stdout
        # [download]  47.3% of 1.23GiB at 2.34MiB/s ETA 00:30
        pct_re   = _re.compile(r"\[download\]\s+([\d.]+)%")
        speed_re = _re.compile(r"at\s+([\d.]+\s*[KMG]iB/s)")
        for line in proc.stdout:
            line = line.rstrip()
            # Detect merge/convert phase — no percentage available from yt-dlp
            if "[Merger]" in line or "[VideoRemuxer]" in line or "[ExtractAudio]" in line:
                job["status"] = "converting"
                job["speed"]  = ""
                continue
            m = pct_re.search(line)
            if m:
                job["progress"] = float(m.group(1))
                sm = speed_re.search(line)
                job["speed"] = sm.group(1).strip() if sm else ""

        proc.wait()
        stderr_thread.join()
        stderr_data = "".join(stderr_lines)
        job["proc"] = None

        # Deregister — proc has exited, no longer needs to be tracked
        with _active_procs_lock:
            _active_procs.pop(job_id, None)

        if job.get("cancelled"):
            # proc is dead — now safe to clean up partial files
            _cleanup(job_id, out_dir)
            job["status"] = "cancelled"
            return

        if proc.returncode != 0:
            err = [l for l in stderr_data.strip().splitlines()
                   if l.strip() and not l.strip().startswith("WARNING")]
            job["status"] = "error"; job["error"] = err[-1] if err else stderr_data.strip(); return

        files = glob.glob(str(out_dir / f"{job_id}.*"))
        if not files:
            job["status"] = "error"; job["error"] = "No output file found."; return

        want      = ".mp3" if format_choice == "audio" else ".mp4"
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
        except: final_path = Path(chosen)

        job["status"]   = "done"
        job["file"]     = str(final_path)
        job["filename"] = final_path.name

    except Exception as e:
        with _active_procs_lock:
            _active_procs.pop(job_id, None)
        job["status"] = "error"; job["error"] = str(e)

def _cleanup(job_id, out_dir):
    for f in glob.glob(str(Path(out_dir) / f"{job_id}.*")):
        try: os.remove(f)
        except Exception: pass

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json or {}
    url  = data.get("url", "").strip()
    if not url: return jsonify({"error": "No URL provided"}), 400
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
                        "formats": _build_formats(info), "audio_formats": _build_audio_formats(info)})
    except subprocess.TimeoutExpired: return jsonify({"error": "Timed out"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/playlist", methods=["POST"])
def get_playlist():
    data = request.json or {}
    url  = data.get("url", "").strip()
    if not url: return jsonify({"error": "No URL provided"}), 400
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
            except: continue
        if not entries: return jsonify({"is_playlist": False}), 200
        pl = ""
        for l in r.stderr.splitlines():
            if "Downloading playlist:" in l: pl = l.split("Downloading playlist:")[-1].strip(); break
        return jsonify({"is_playlist": True, "playlist_title": pl, "entries": entries})
    except subprocess.TimeoutExpired: return jsonify({"error": "Timed out"}), 400
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url  = data.get("url","").strip()
    if not url: return jsonify({"error": "No URL provided"}), 400
    job_id = uuid.uuid4().hex[:10]
    dl_dir = data.get("download_dir") or _get_last_folder() or str(Path.home())
    jobs[job_id] = {"status": "queued", "url": url,
                    "title": data.get("title",""), "proc": None, "cancelled": False,
                    "download_dir": dl_dir}
    threading.Thread(target=run_download,
                     args=(job_id, url, data.get("format","video"),
                           data.get("format_id") or None, dl_dir,
                           data.get("audio_codec") or "",
                           int(data.get("concurrent_fragments") or 1)),
                     daemon=True).start()
    return jsonify({"job_id": job_id})

@app.route("/api/cancel/<job_id>", methods=["POST"])
def cancel_download(job_id):
    job = jobs.get(job_id)
    if not job: return jsonify({"error": "Job not found"}), 404
    if job.get("status") not in ("downloading", "queued"):
        return jsonify({"error": "Not downloading"}), 400
    job["cancelled"] = True
    proc = job.get("proc")
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
            "speed": job.get("speed", "")}
    # Remove completed jobs from memory once the UI has consumed the result.
    if status in ("done", "error", "cancelled") and job.get("_ack"):
        jobs.pop(job_id, None)
    elif status in ("done", "error", "cancelled"):
        job["_ack"] = True   # mark — will be removed on next poll
    return jsonify(resp)

@app.route("/api/settings")
def get_settings():
    s = _load_settings()
    return jsonify({
        "last_folder": s.get("last_folder", ""),
        "concurrency":    s.get("concurrency", 6),
        "fragments":      s.get("fragments", 4),
        "settings_open":  s.get("settings_open", True),
        "upd_open":       s.get("upd_open", False),
        "ck_open":        s.get("ck_open", False),
        "quit_on_done":   s.get("quit_on_done", False),
    })

@app.route("/api/settings/save", methods=["POST"])
def save_settings():
    data = request.json or {}
    if "last_folder" in data:
        folder = data["last_folder"]
        if folder:
            try: Path(folder).mkdir(parents=True, exist_ok=True)
            except Exception: pass
    _save_settings({k: v for k, v in data.items()})
    return jsonify({"ok": True})

@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    data   = request.json or {}
    folder = data.get("folder", _get_last_folder() or str(Path.home()))
    path   = Path(folder); path.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32": os.startfile(str(path))
        elif sys.platform == "darwin": _popen("open", str(path))
        else: _popen("xdg-open", str(path))
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/rename", methods=["POST"])
def rename_file():
    data = request.json or {}
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

# ── Update system ──────────────────────────────────────────────────────────────
def _get_ytdlp_version():
    try: return _run(sys.executable, "-m", "yt_dlp", "--version", timeout=10).stdout.strip()
    except: return "unknown"

def _get_ffmpeg_version():
    exe = FFMPEG_DIR / "ffmpeg"
    if not exe.exists(): return "not installed"
    tag = _get_ffmpeg_installed_tag()
    if tag: return tag
    try:
        r = _run(str(exe), "-version", timeout=10)
        parts = (r.stdout.splitlines()[0] if r.stdout else "").split()
        return parts[2] if len(parts) > 2 else "unknown"
    except: return "unknown"

def _get_ffmpeg_installed_tag():
    try: return FFMPEG_TAG_FILE.read_text().strip()
    except: return ""

def _get_latest_ffmpeg_tag():
    """Mac: use evermeet.cx release info endpoint."""
    try:
        req = urllib.request.Request("https://evermeet.cx/ffmpeg/info/ffmpeg/release",
                                     headers={"User-Agent":"EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        # evermeet returns {"version":"...", "download":{...}, ...}
        return data.get("version","unknown")
    except: return "unknown"

def _get_latest_ytdlp_version():
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
            headers={"User-Agent":"EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()).get("tag_name","unknown")
    except: return "unknown"

update_status: dict = {}

def _run_update(do_ytdlp, do_ffmpeg):
    global update_status
    update_status = {"running": True, "log": [], "done": False, "error": None}
    def log(m): print(f"[EGM] {m}"); update_status["log"].append(m)
    try:
        if do_ytdlp:
            # Fetch the exact stable version tag first, then pin to it.
            # --upgrade alone skips this if installed version is newer
            # --force-reinstall with an exact version always works.
            stable_ver = _get_latest_ytdlp_version()
            if stable_ver and stable_ver != "unknown":
                log(f"Installing yt-dlp stable {stable_ver}...")
                r = _run(sys.executable, "-m", "pip", "install",
                         f"yt-dlp=={stable_ver}", "--force-reinstall",
                         timeout=120)
            else:
                log("Installing yt-dlp stable (latest)...")
                r = _run(sys.executable, "-m", "pip", "install", "--upgrade",
                         "--force-reinstall", "yt-dlp", timeout=120)
            v = _get_ytdlp_version()
            if r.returncode == 0:
                log(f"yt-dlp -> {v}")
            else:
                err = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
                log(f"yt-dlp update failed: {err}")
        if do_ffmpeg:
            log("Downloading latest ffmpeg + ffprobe...")
            FFMPEG_DIR.mkdir(exist_ok=True)
            tmp_ffmpeg  = FFMPEG_DIR / "ffmpeg_update.zip"
            tmp_ffprobe = FFMPEG_DIR / "ffprobe_update.zip"
            ffmpeg_bin  = FFMPEG_DIR / "ffmpeg"
            ffprobe_bin = FFMPEG_DIR / "ffprobe"
            try:
                urllib.request.urlretrieve(FFMPEG_URL,  tmp_ffmpeg)
                urllib.request.urlretrieve(FFPROBE_URL, tmp_ffprobe)
                log("Extracting...")
                with zipfile.ZipFile(tmp_ffmpeg, "r") as z:
                    z.extract("ffmpeg", FFMPEG_DIR)
                with zipfile.ZipFile(tmp_ffprobe, "r") as z:
                    z.extract("ffprobe", FFMPEG_DIR)
                if ffmpeg_bin.exists():  os.chmod(ffmpeg_bin,  0o755)
                if ffprobe_bin.exists(): os.chmod(ffprobe_bin, 0o755)
            finally:
                for t in (tmp_ffmpeg, tmp_ffprobe):
                    try: t.unlink(missing_ok=True)
                    except Exception: pass
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
    cy, ly  = _get_ytdlp_version(), _get_latest_ytdlp_version()
    cf, lf  = _get_ffmpeg_version(), _get_latest_ffmpeg_tag()
    # Up to date only if installed matches latest stable exactly.
    # Any other version (including newer nightlies) shows "Update available"
    # so the user can install the correct stable release.
    ytdlp_ok = cy != "unknown" and cy == ly
    return jsonify({
        "ytdlp":  {"current": cy, "latest": ly, "up_to_date": ytdlp_ok},
        "ffmpeg": {"current": cf, "latest": lf,
                   "up_to_date": cf not in ("not installed","unknown") and lf != "unknown" and cf == lf},
    })

@app.route("/api/run-update", methods=["POST"])
def run_update():
    if update_status.get("running"): return jsonify({"error": "Already running"}), 409
    data = request.json or {}
    threading.Thread(target=_run_update,
                     args=(bool(data.get("ytdlp",True)), bool(data.get("ffmpeg",False))),
                     daemon=True).start()
    return jsonify({"started": True})

@app.route("/api/cookies/status")
def cookies_status():
    """Return whether cookies.txt is present — for optional UI use."""
    exists = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0
    age_days = None
    if exists:
        age_days = int((time.time() - COOKIES_FILE.stat().st_mtime) / 86400)
    return jsonify({"active": exists, "path": str(COOKIES_FILE), "age_days": age_days})

@app.route("/api/cookies/save", methods=["POST"])
def cookies_save():
    data = request.json or {}
    text = data.get("content", "").strip()
    if not text:
        return jsonify({"error": "No content provided"}), 400
    try:
        COOKIES_FILE.write_text(text, encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/cookies/clear", methods=["POST"])
def cookies_clear():
    try:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/deno/status")
def deno_status():
    """Return installed Deno version and whether the exe exists."""
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

        # Resolve the actual download URL via the GitHub API (avoids 302 redirect issues)
        req = urllib.request.Request(
            "https://api.github.com/repos/denoland/deno/releases/latest",
            headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=15) as r:
            release = json.loads(r.read())
        tag = release.get("tag_name", "")
        assets = release.get("assets", [])
        url = next(
            (a["browser_download_url"] for a in assets
             if a["name"] == DENO_ZIP_NAME),
            DENO_ZIP_URL)  # fallback to latest redirect URL
        version_label = tag or "latest"
        log(f"Downloading Deno {version_label} for {DENO_ZIP_NAME}...")

        # Stream download with progress logging every 5 MB
        downloaded = 0
        chunk = 1024 * 256  # 256 KB chunks
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0))
            next_report = 5 * 1024 * 1024  # report every 5 MB
            while True:
                block = resp.read(chunk)
                if not block:
                    break
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

        log("Extracting deno binary...")
        with zipfile.ZipFile(tmp, "r") as z:
            if "deno" not in z.namelist():
                raise RuntimeError("deno binary not found in zip archive")
            z.extract("deno", DENO_DIR)
        tmp.unlink(missing_ok=True)

        # Make executable
        os.chmod(DENO_EXE, 0o755)

        # Verify it actually runs
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
        # Remove broken exe if present
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

@app.route("/api/update-status")
def get_update_status():
    return jsonify(update_status or {"running": False, "done": False, "log": []})

@app.route("/api/installed-versions")
def installed_versions():
    """Return only locally-installed versions — no network calls. Fast, for panel expand."""
    cy = _get_ytdlp_version()
    cf = _get_ffmpeg_version()
    deno_installed = DENO_EXE.exists()
    deno_version   = _get_deno_version() if deno_installed else "not installed"
    return jsonify({
        "ytdlp":  {"current": cy, "latest": None, "up_to_date": None},
        "ffmpeg": {"current": cf, "latest": None, "up_to_date": None},
        "deno":   {"installed": deno_installed, "version": deno_version},
    })

@app.route("/api/check-app-update")
def check_app_update():
    """Fetch egm-version.json and compare to running version."""
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
                                     headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        latest_ver   = str(data.get("version", "")).strip()
        latest_build = int(data.get("build", 0))
        notes        = str(data.get("notes", "")).strip()
        download     = str(data.get("download", "")).strip()
        zip_url      = str(data.get("zip_url", APP_UPDATE_ZIP_URL)).strip()
        up_to_date   = (latest_ver == APP_VERSION and latest_build <= APP_BUILD)
        return jsonify({
            "up_to_date":      up_to_date,
            "current_version": APP_VERSION,
            "current_build":   APP_BUILD,
            "latest_version":  latest_ver,
            "latest_build":    latest_build,
            "notes":           notes,
            "download":        download,
            "zip_url":         zip_url,
        })
    except urllib.error.URLError:
        return jsonify({"error": "Could not reach update server"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/download-update", methods=["POST"])
def download_update():
    """Download EGMdM.zip, extract the DMG, mount it, and open a Finder
    window so the user can drag EGM Downloader to Applications in one step."""
    data    = request.json or {}
    zip_url = data.get("zip_url", APP_UPDATE_ZIP_URL).strip()
    if not zip_url:
        return jsonify({"error": "No zip URL provided"}), 400
    try:
        import pyzipper
    except ImportError:
        return jsonify({"error": "pyzipper not installed — restart the app to install it"}), 500

    UPDATE_TMP_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = UPDATE_TMP_DIR / "EGMdM.zip"
    dmg_name = "EGM Downloader.dmg"
    dmg_path = UPDATE_TMP_DIR / dmg_name

    try:
        # 1. Download password-protected zip
        req = urllib.request.Request(zip_url, headers={"User-Agent": "EGM-Downloader"})
        with urllib.request.urlopen(req, timeout=120) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)

        # 2. Extract DMG from zip
        with pyzipper.AESZipFile(zip_path, "r") as z:
            z.setpassword(APP_UPDATE_PASSWORD.encode("utf-8"))
            if dmg_name not in z.namelist():
                zip_path.unlink(missing_ok=True)
                return jsonify({"error": f"'{dmg_name}' not found in update zip"}), 500
            z.extract(dmg_name, UPDATE_TMP_DIR)

        zip_path.unlink(missing_ok=True)

        # 3. Mount the DMG (-nobrowse suppresses auto-open so we control it)
        result = subprocess.run(
            ["hdiutil", "attach", str(dmg_path), "-nobrowse"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return jsonify({"error": f"Could not mount update: {result.stderr.strip()}"}), 500

        # 4. Parse mount point from hdiutil output (tab-separated, last field)
        mount_point = None
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and "/Volumes/" in parts[-1]:
                mount_point = parts[-1].strip()
                break

        if not mount_point:
            return jsonify({"error": "DMG mounted but volume path not found"}), 500

        # 5. Open Finder showing the mounted volume — user drags to Applications
        subprocess.Popen(["open", mount_point])

        return jsonify({
            "success":     True,
            "mount_point": mount_point,
            "message":     "Drag 'EGM Downloader' to your Applications folder to update.",
        })

    except subprocess.TimeoutExpired:
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        return jsonify({"error": "DMG mount timed out — please try again"}), 500
    except Exception as e:
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        return jsonify({"error": str(e)}), 500

@app.route("/api/shutdown", methods=["POST"])
def shutdown():
    """Clean shutdown requested by Electron before-quit.
    Kills all active yt-dlp/ffmpeg processes BEFORE os._exit so they don't
    survive as orphans after Flask exits."""
    def _do_shutdown():
        time.sleep(0.15)
        # Kill all active yt-dlp+ffmpeg trees before Flask exits.
        # Must happen before os._exit — once Flask is gone, these become
        # orphans that taskkill /F /T on Flask's PID can no longer reach.
        with _active_procs_lock:
            procs = list(_active_procs.values())
        for p in procs:
            _kill_proc(p)
        os._exit(0)
    threading.Thread(target=_do_shutdown, daemon=True).start()
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Clean up any leftover update temp files from a previous update
    try:
        if UPDATE_TMP_DIR.exists():
            shutil.rmtree(UPDATE_TMP_DIR, ignore_errors=True)
    except Exception:
        pass
    ensure_ffmpeg()
    port = int(os.environ.get("PORT", 8899))
    host = os.environ.get("HOST", "127.0.0.1")
    threading.Thread(target=lambda: app.run(host=host,port=port,use_reloader=False),
                     daemon=True, name="flask").start()

    # Under Electron: keep Flask alive; Electron manages the window and lifecycle.
    print(f"[EGM Downloader] running on http://{host}:{port}")
    try: threading.Event().wait()
    except KeyboardInterrupt: pass
