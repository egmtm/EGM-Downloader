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
import urllib.parse
import zipfile
import hashlib
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

# Outbound HTTP whitelist for *app maintenance/update* traffic only.
#
# Scope — what this whitelist DOES and DOES NOT cover (keep this accurate):
#   • COVERED: every request made through _safe_urlopen() — update feed, GitHub
#     release metadata/binaries (ffmpeg, Deno), PyPI version checks, app installer.
#     Enforced both before urlopen() AND after redirect resolution.
#   • NOT COVERED by host allowlist, by design:
#       - yt-dlp subprocesses: contact arbitrary user-supplied sites/CDNs — that is
#         the app's core function, so they cannot be host-restricted.
#       - pip installs (yt-dlp/ffmpeg-deps/mutagen updates): pip talks to PyPI/CDNs
#         on its own; not routed through _safe_urlopen.
#       - thumbnail fetches: come from third-party metadata, so they use a separate
#         guard (_is_internal_host below: HTTPS-only + private/loopback IP blocking)
#         rather than this allowlist, since thumbnail CDNs are open-ended.
# When adding a new maintenance host, document why it's needed alongside the entry.
_ALLOWED_DOWNLOAD_HOSTS = {
    "api.github.com",                        # GitHub API — release metadata (BtbN ffmpeg, Deno)
    "github.com",                            # GitHub release download URLs (pre-redirect)
    "objects.githubusercontent.com",         # GitHub release CDN (typical redirect target)
    "release-assets.githubusercontent.com",  # Newer GitHub release CDN
    "pypi.org",                              # mutagen version check (JSON API)
    "ffmpeg.martin-riedl.de",                # Mac ffmpeg downloads + checksum
    "egerena.com",                           # App update feed + binary downloads
}

# Outbound HTTP timeouts — applied via _safe_urlopen
HTTP_TIMEOUT_SHORT = 15   # metadata, API calls, checksums, redirect resolution
HTTP_TIMEOUT_LONG  = 120  # binary downloads (ffmpeg, deno, app installer)

# Bound jobs dict growth to keep memory predictable over long sessions
MAX_JOBS = 1000

# ── Structured security event logging ────────────────────────────────────────
def _sec_event(event: str) -> None:
    """Emit a structured security log entry to stdout and a rotating file.
    Never raises — logging must never crash the app."""
    import time as _time
    ts   = _time.strftime('%Y-%m-%dT%H:%M:%S')
    line = f"[{ts}] [SECURITY] {event}"
    print(line, flush=True)
    try:
        log_dir  = get_data_dir() / 'logs'
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / 'security.log'
        if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
            for i in range(2, 0, -1):
                src = log_dir / f'security.log.{i}'
                if src.exists(): src.rename(log_dir / f'security.log.{i + 1}')
            log_path.rename(log_dir / 'security.log.1')
        with log_path.open('a', encoding='utf-8') as _f:
            _f.write(line + '\n')
    except Exception:
        pass

# ── Signed manifest public key + verification ─────────────────────────────────
_MANIFEST_PUBLIC_KEY_PEM = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MCowBQYDK2VwAyEAFiI0KygA+dzE3dAFiL2jYFg5XDtkLHpY5WAX0GgC+xM=\n"
    b"-----END PUBLIC KEY-----\n"
)

def _verify_manifest(data: dict) -> bool:
    """Verify the ed25519 signature on an update manifest.
    Returns True if signature is present and valid, False otherwise."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        import base64, json as _json
        sig_b64 = data.get('signature', '')
        if not sig_b64:
            return False
        payload_dict = {k: v for k, v in data.items() if k != 'signature'}
        payload  = _json.dumps(payload_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')
        pub_key  = load_pem_public_key(_MANIFEST_PUBLIC_KEY_PEM)
        pub_key.verify(base64.b64decode(sig_b64), payload)
        return True
    except Exception:
        return False

def _is_allowed_host(url):
    """Return True if the URL's hostname is in the outbound whitelist."""
    try:
        return (urllib.parse.urlparse(url).hostname or "") in _ALLOWED_DOWNLOAD_HOSTS
    except Exception:
        return False

def _safe_urlopen(req_or_url, timeout):
    """urlopen with host whitelist enforcement (pre-request and post-redirect).
    Raises RuntimeError if the URL or its redirect target isn't whitelisted."""
    url = req_or_url if isinstance(req_or_url, str) else req_or_url.full_url
    if not _is_allowed_host(url):
        host = urllib.parse.urlparse(url).hostname or "?"
        raise RuntimeError(f"Outbound request blocked — non-whitelisted host: {host}")
    resp = urllib.request.urlopen(req_or_url, timeout=timeout)
    if not _is_allowed_host(resp.url):
        host = urllib.parse.urlparse(resp.url).hostname or "?"
        resp.close()
        raise RuntimeError(f"Redirect blocked — non-whitelisted target host: {host}")
    return resp

def _safe_extract(z, member, target_dir):
    """Extract a named zip member, asserting it has no path traversal.
    Python's zipfile already sanitizes by default; this makes the assumption explicit
    and guards against accidental future use of extractall() or raw namelist iteration."""
    if member not in z.namelist():
        raise RuntimeError(f"{member!r} not found in archive")
    name = z.getinfo(member).filename
    if ".." in name or name.startswith(("/", "\\")):
        raise RuntimeError(f"Suspicious archive member path: {name!r}")
    z.extract(member, target_dir)
def _chmod_owner_only(path):
    """Set sensitive file to owner read/write only (POSIX). No-op on Windows."""
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

def _atomic_write_text(path: Path, content: str, *, owner_only: bool = False) -> None:
    """Write text atomically via tmp + fsync + os.replace — prevents truncated files
    on crash or kill -9. fsync forces the tmp file's bytes to disk before the rename,
    so a power loss can't leave a renamed-but-empty file (matters on Linux/macOS).
    Sets permissions on tmp before rename so the final file has correct perms from the
    moment it exists (no race window). Cleans up the tmp file on failure and re-raises."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if owner_only:
            _chmod_owner_only(tmp)
        tmp.replace(path)
    except Exception:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        raise

def _verify_upstream_checksum(local_path, checksum_url, filename):
    """Fetch upstream checksum file, parse for filename, verify local download.
    Returns (ok: bool, message: str).
    Fail-closed: any fetch failure, parse error, missing entry, or mismatch returns False.

    Handles two checksum file formats:
      1. Standard:    <hash>  <filename>           (BtbN, martin-riedl.de, sha256sum tool)
      2. PowerShell:  Algorithm : SHA256           (Deno's Windows builds)
                      Hash      : <hash>
                      Path      : ...\\<filename>
    """
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            text = r.read().decode()
        expected = None

        # Try PowerShell Get-FileHash format first (Algorithm/Hash/Path block)
        if "Hash" in text and "Path" in text:
            hash_val = None
            path_val = None
            for line in text.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip()
                    val = val.strip()
                    if key == "Hash":   hash_val = val.lower()
                    elif key == "Path": path_val = val
            if hash_val and path_val:
                # Match by trailing filename
                if path_val.replace("\\", "/").split("/")[-1] == filename:
                    expected = hash_val

        # Fall back to standard format
        if not expected:
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
                    expected = parts[0].lower()
                    break

        if not expected:
            _sec_event(f"Checksum: no entry found for {filename!r} in {checksum_url}")
            return False, f"No checksum entry found for {filename} — install aborted (try again later)"
        actual = hashlib.sha256(local_path.read_bytes()).hexdigest().lower()
        if actual != expected:
            _sec_event(f"Checksum mismatch for {filename!r}: expected {expected}, got {actual}")
            return False, (f"Checksum mismatch for {filename}. "
                           "The download may be corrupted or tampered — install aborted.")
        return True, f"OK Checksum verified ({filename})"
    except Exception as e:
        _sec_event(f"Checksum verification error for {filename!r}: {e}")
        return False, f"Could not verify checksum ({e}) — install aborted (check network and retry)"
_API_TOKEN       = os.environ.get("EGM_API_TOKEN", "")
# /api/show-window is exempt because launch.py (second-instance signaler) has no token access
_TOKEN_EXEMPT        = {"/api/show-window"}
_TOKEN_EXEMPT_PREFIX = ("/api/thumbnail/",)
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
        _sec_event(f"Host header rejected: {request.host!r} on {request.path}")
        abort(403)
    # 2. API token check (per-session Electron token)
    if _API_TOKEN and request.path.startswith("/api/") and request.path not in _TOKEN_EXEMPT and not request.path.startswith(_TOKEN_EXEMPT_PREFIX):
        if not hmac.compare_digest(
            request.headers.get("X-EGM-Token", ""), _API_TOKEN
        ):
            _sec_event(f"Token mismatch on {request.path}")
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
BASE_DIR   = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
FFMPEG_DIR = BASE_DIR / "ffmpeg_bin"

# ── Portable mode detection ────────────────────────────────────────────────────
def is_portable():
    """Return True if running as a portable installation.

    Detection logic (Windows):
      1. If a .portable marker file exists next to app.py → portable.
      2. If running from %LOCALAPPDATA%\\EGM Downloader → installed (not portable).
      3. Otherwise → installed (defensive default).
    """
    app_dir = Path(__file__).parent.resolve()
    if (app_dir / ".portable").exists():
        return True
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            installed_path = Path(local_appdata) / "EGM Downloader"
            try:
                if app_dir.resolve() == installed_path.resolve():
                    return False
            except (OSError, ValueError):
                pass
    return False

PORTABLE_MODE = is_portable()

def get_data_dir() -> Path:
    """Return the directory used for settings, history, cookies, and downloads list.

    Portable installs keep data inside the portable folder (./data/) so the
    entire app can be moved or run from USB without leaving traces elsewhere.
    Installed builds use the standard BASE_DIR (beside app.py inside $INSTDIR).
    """
    if PORTABLE_MODE:
        d = Path(__file__).parent.resolve() / "data"
        d.mkdir(exist_ok=True)
        return d
    return BASE_DIR

# ── App version — keep in sync with index.html build stamp ───────────────────
APP_VERSION           = "1.0.1"
APP_BUILD             = 125
APP_UPDATE_URL        = "https://egerena.com/apps/egm-version.json"
APP_UPDATE_ZIP_URL    = "https://egerena.com/apps/EGMd.zip"

# ── Update temp dir — cleaned up on startup if present ───────────────────────
UPDATE_TMP_DIR = Path(os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))) / "egm-update"

# Settings / history / cookies — routed through get_data_dir() for portable support
SETTINGS_FILE = get_data_dir() / "egm_settings.json"
HISTORY_FILE  = get_data_dir() / "egm_history.json"
SUBS_FILE     = get_data_dir() / "egm_subscriptions.json"

# ── Cookies: path to cookies.txt — managed via Settings UI ───────────────────
COOKIES_FILE = get_data_dir() / "cookies.txt"

_settings_cache: dict = {}
_settings_lock  = threading.Lock()

# ── History ────────────────────────────────────────────────────────────────────
_history_lock = threading.Lock()
_HISTORY_MAX  = 500  # soft cap on stored entries
THUMBNAILS_DIR = get_data_dir() / "thumbnails"
THUMBNAILS_DIR.mkdir(exist_ok=True)

def _load_history() -> list:
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []

def _save_history(items: list):
    try:
        _atomic_write_text(HISTORY_FILE, json.dumps(items, indent=2), owner_only=True)
    except Exception:
        pass

def _is_internal_host(host: str) -> bool:
    """Return True if host resolves to a loopback/private/link-local/reserved
    address. Thumbnail URLs come from extractor metadata (and are accepted from
    the /api/download caller), so a hostile value could otherwise make the
    backend fetch internal services (SSRF). Fail-closed: resolution failure → internal."""
    import socket, ipaddress
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True
    for info in infos:
        addr = info[4][0].split("%")[0]  # strip IPv6 zone id
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return True
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return True
    return False

def _clamp_int(value, default, lo, hi):
    """Parse value to int and clamp to [lo, hi]; return default on bad/empty input.
    Prevents a malformed request field from raising and 500-ing the route."""
    try:
        return max(lo, min(int(value), hi))
    except (TypeError, ValueError):
        return default

def _download_thumbnail(url: str, entry_id: str) -> str:
    """Download a thumbnail image and save it locally. Returns filename or empty string."""
    if not url or not url.startswith("https://"):
        if url:
            _sec_event(f"Thumbnail URL rejected (non-HTTPS): scheme={url.split(':')[0]!r}")
        return ""
    # SSRF guard: never let a thumbnail URL point the backend at an internal host.
    _thumb_host = urllib.parse.urlparse(url).hostname or ""
    if _is_internal_host(_thumb_host):
        _sec_event(f"Thumbnail URL rejected (internal/unresolvable host): {_thumb_host!r}")
        return ""
    CAP = 512_000  # 500 KB hard cap on thumbnail size
    try:
        req = urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_SHORT)
        # Re-check the FINAL host after any redirects — a whitelisted host could
        # 302 to an internal address (mirrors _safe_urlopen's redirect guard).
        final_host = urllib.parse.urlparse(req.url).hostname or ""
        if _is_internal_host(final_host):
            _sec_event(f"Thumbnail redirect rejected (internal host): {final_host!r}")
            req.close()
            return ""
        # Reject non-image responses before reading the body
        ctype = req.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype not in ("image/jpeg", "image/png", "image/webp"):
            req.close()
            return ""
        # Reject early if the server advertises a size over the cap.
        try:
            clen = int(req.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            clen = 0
        if clen > CAP:
            req.close()
            return ""
        # Read one byte past the cap: if we get more than CAP the source lied about
        # (or omitted) its length, so reject rather than save a truncated image.
        data = req.read(CAP + 1)
        req.close()
        if len(data) > CAP:
            return ""
        # Strict magic byte detection at exact offset
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            ext = ".png"
        elif data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
            ext = ".webp"
        elif data[:3] == b"\xff\xd8\xff":
            ext = ".jpg"
        else:
            return ""  # Unknown format — reject rather than mis-tag
        fname = f"{entry_id}{ext}"
        thumb_path = THUMBNAILS_DIR / fname
        thumb_path.write_bytes(data)
        return fname
    except Exception:
        return ""

def _append_history(job: dict, final_path):
    """Append a completed download to history JSON. Newest-first, capped at _HISTORY_MAX."""
    try:
        size_bytes = 0
        try: size_bytes = final_path.stat().st_size
        except Exception: pass
        entry_id = str(uuid.uuid4())
        thumb = _download_thumbnail(job.get("thumbnail", ""), entry_id)
        entry = {
            "id":           entry_id,
            "url":          job.get("url", ""),
            "title":        job.get("title", ""),
            "filename":     final_path.name,
            "format":       final_path.suffix.lstrip(".").lower(),
            "download_dir": str(final_path.parent),
            "file_path":    str(final_path),
            "size_bytes":   size_bytes,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "thumbnail":    thumb,
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
            _atomic_write_text(SETTINGS_FILE, json.dumps(_settings_cache, indent=2), owner_only=True)
        except Exception:
            pass

def _get_last_folder() -> str:
    return _load_settings().get("last_folder", "")

# ── Subscriptions data ────────────────────────────────────────────────────────
_subs_cache = None
_subs_lock  = threading.Lock()

def _load_subscriptions() -> list:
    global _subs_cache
    with _subs_lock:
        if _subs_cache is None:
            try:
                data = json.loads(SUBS_FILE.read_text(encoding="utf-8"))
                _subs_cache = data.get("subscriptions", []) if isinstance(data, dict) else []
            except Exception:
                _subs_cache = []
        return list(_subs_cache)

def _save_subscriptions(subs: list):
    global _subs_cache
    with _subs_lock:
        _subs_cache = subs
        _atomic_write_text(SUBS_FILE, json.dumps({"subscriptions": subs}, indent=2), owner_only=True)

jobs: dict = {}
_jobs_lock = threading.Lock()

# ── Active process registry — used to kill yt-dlp+ffmpeg trees on cancel/quit ─
# Maps job_id → proc. Maintained by run_download; cleared when proc exits.
_active_procs: dict = {}
_active_procs_lock  = threading.Lock()

# ── Jobs cleanup — remove stale completed entries after ~10 minutes ───────────
def _jobs_cleanup_worker():
    """Background thread: sweep jobs dict every 60s and evict entries that
    have been in a terminal state for over 10 minutes. Prevents unbounded
    growth during long playlist sessions."""
    TERMINAL = {"done", "error", "cancelled"}
    MAX_AGE  = 600  # seconds
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

# ── ffmpeg: auto-download on first run ────────────────────────────────────────
FFMPEG_URL_NIGHTLY = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                     "ffmpeg-master-latest-win64-gpl.zip")
FFMPEG_URL_STABLE  = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                      "ffmpeg-n8.1-latest-win64-gpl-8.1.zip")

def _get_ffmpeg_url():
    ch = _load_settings().get("ffmpeg_channel", "stable")
    return FFMPEG_URL_NIGHTLY if ch == "nightly" else FFMPEG_URL_STABLE

# Keep FFMPEG_URL as the default for ensure_ffmpeg (first-run uses stable)
FFMPEG_URL = FFMPEG_URL_STABLE
FFMPEG_TAG_FILE = FFMPEG_DIR / "build_tag.txt"

# ── Deno: bundled JS runtime required for YouTube (no admin, no PATH needed) ──
DENO_DIR     = BASE_DIR / "runtime"
DENO_EXE     = DENO_DIR / "deno.exe"
# Direct zip URL — single deno.exe, no installer, no UAC required
DENO_ZIP_URL = ("https://github.com/denoland/deno/releases/latest/download/"
                "deno-x86_64-pc-windows-msvc.zip")

def ensure_ffmpeg():
    if (FFMPEG_DIR / "ffmpeg.exe").exists() and (FFMPEG_DIR / "ffprobe.exe").exists():
        print("[EGM] ffmpeg ready.")
        return True
    print("[EGM] Downloading ffmpeg (first run only)...")
    FFMPEG_DIR.mkdir(exist_ok=True)
    tmp = FFMPEG_DIR / "ffmpeg_tmp.zip"
    try:
        ffmpeg_url = _get_ffmpeg_url()
        req = urllib.request.Request(ffmpeg_url, headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_LONG) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        ok, msg = _verify_upstream_checksum(tmp, "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256", os.path.basename(ffmpeg_url))
        print(f"[EGM] {msg}")
        if not ok:
            tmp.unlink(missing_ok=True)
            return
        with zipfile.ZipFile(tmp, "r") as z:
            for m in z.namelist():
                # Zip slip guard: skip any entry with path traversal or absolute path
                if ".." in m.replace("\\", "/").split("/") or m.startswith(("/", "\\")):
                    continue
                fn = Path(m).name
                if fn in ("ffmpeg.exe", "ffprobe.exe"):
                    with z.open(m) as src, open(FFMPEG_DIR / fn, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        tmp.unlink(missing_ok=True)
        try: FFMPEG_TAG_FILE.write_text(_get_latest_ffmpeg_tag())
        except Exception: pass
        print("[EGM] ffmpeg ready.")
        return True
    except Exception as e:
        print(f"[EGM] ffmpeg download failed: {e}")
        try: tmp.unlink(missing_ok=True)
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
    return _run_yt(sys.executable, "-m", "yt_dlp",
                   "--remote-components", "ejs:github",
                   *_ffmpeg_args(), *_deno_args(), *_cookies_args(),
                   *_bgutil_args(), *extra, timeout=timeout)

# ── Helpers ────────────────────────────────────────────────────────────────────
def _safe_thumb_url(url) -> str:
    """Validate thumbnail URL — reject chars that could break out of a CSS url()
    or style attribute context. Rejecting ')' is context-independent: safe
    regardless of whether the interpolation is quoted or unquoted.
    Note: only validates scheme + chars; internal-host SSRF guard is applied
    at download time via _download_thumbnail (Phase 3)."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    # Must be http(s), no breakout chars (quotes, parens, spaces, angle brackets)
    if not url.startswith(("https://", "http://")) or any(c in url for c in ('"', "'", ' ', '<', '>', '(', ')')):
        return ""
    return url

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

    # Parallel fragment downloads — speeds up individual video downloads on fast connections
    if concurrent_fragments > 1:
        args += ["--concurrent-fragments", str(concurrent_fragments)]

    # Defense in depth — endpoint validates format_id at /api/download.
    # This guards future callers that might construct run_download invocations
    # without going through that endpoint.
    if format_id and not _re.fullmatch(r'[A-Za-z0-9_+\-]+', format_id):
        raise ValueError(f"invalid format_id reached run_download: {format_id!r}")

    if format_choice == "audio":
        # audio_quality: "128"/"192"/"320" (MP3 kbps), "flac", "m4a_256" (M4A), "opus_128" (OPUS)
        if audio_quality == "flac":
            args += ["-x", "--audio-format", "flac"]
        elif audio_quality.startswith("m4a_"):
            bitrate = audio_quality.split("_", 1)[1]
            if not (bitrate.isdigit() and 32 <= int(bitrate) <= 320):
                raise ValueError(f"invalid bitrate reached run_download: {audio_quality!r}")
            args += ["-x", "--audio-format", "m4a",
                     "--postprocessor-args", f"ffmpeg:-b:a {bitrate}k"]
        elif audio_quality.startswith("opus_"):
            bitrate = audio_quality.split("_", 1)[1]
            if not (bitrate.isdigit() and 32 <= int(bitrate) <= 320):
                raise ValueError(f"invalid bitrate reached run_download: {audio_quality!r}")
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
        # If the selected format's paired audio is already AAC, remux with -c copy.
        # Otherwise (opus, vorbis, unknown) re-encode audio to AAC for mp4 compatibility.
        # Video is always stream-copied (-c:v copy) — never re-encoded.
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

    cmd = [sys.executable, "-m", "yt_dlp", "--remote-components", "ejs:github"] + _ffmpeg_args() + _deno_args() + _cookies_args() + _bgutil_args() + args
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
        # Cap at 200 lines — only the last line matters for error reporting.
        stderr_lines = deque(maxlen=200)
        def _drain_stderr():
            for l in proc.stderr:
                stderr_lines.append(l)
        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        # Patterns for yt-dlp stdout
        # [download]  47.3% of 1.23GiB at 2.34MiB/s ETA 00:30
        pct_re   = _re.compile(r"\[download\]\s+([\d.]+)%")
        speed_re = _re.compile(r"at\s+([\d.]+\s*[KMG]iB/s)")
        eta_re   = _re.compile(r"ETA\s+(\d+:\d+)")
        size_re  = _re.compile(r"of\s+([\d.]+\s*[KMGiB]+)")
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
                em = eta_re.search(line)
                if em: job["eta"] = em.group(1)
                szm = size_re.search(line)
                if szm: job["filesize"] = szm.group(1).strip()

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
def index(): return render_template("index.html", egm_token=_API_TOKEN, platform_url="https://egerena.com/apps/egm.html")

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
    # Gate: ffmpeg must be ready before downloads can start (it runs in a
    # background thread on first launch — see ensure_ffmpeg).
    if not (FFMPEG_DIR / "ffmpeg.exe").exists():
        return jsonify({"error": "ffmpeg is still downloading — please wait a moment and try again"}), 503
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
        if len(jobs) >= MAX_JOBS:
            return jsonify({"error": "Too many jobs — please restart the app to clear history"}), 429
        jobs[job_id] = {"status": "queued", "url": url,
                        "title": data.get("title",""), "proc": None, "cancelled": False,
                        "download_dir": dl_dir, "format": data.get("format", "video"),
                        "thumbnail": data.get("thumbnail", "")}
    threading.Thread(target=run_download,
                     args=(job_id, url, data.get("format","video"),
                           data.get("format_id") or None, dl_dir,
                           data.get("audio_codec") or "",
                           _clamp_int(data.get("concurrent_fragments"), 1, 1, 16),
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
    with _jobs_lock:
        job = jobs.get(job_id)
        if not job: return jsonify({"error": "Job not found"}), 404
        status = job["status"]
        resp = {"status": status, "error": job.get("error"),
                "filename": job.get("filename"), "progress": job.get("progress", 0),
                "speed": job.get("speed", ""), "eta": job.get("eta", ""),
                "filesize": job.get("filesize", "")}
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
        "last_folder":             s.get("last_folder", ""),
        "concurrency":             s.get("concurrency", 6),
        "fragments":               s.get("fragments", 4),
        "settings_open":           s.get("settings_open", True),
        "upd_open":                s.get("upd_open", False),
        "ck_open":                 s.get("ck_open", False),
        "quit_on_done":            s.get("quit_on_done", False),
        "check_updates_on_launch": s.get("check_updates_on_launch", False),
        "last_seen_version":       s.get("last_seen_version", ""),
        # Promoted UI controls — must be returned so frontend can restore on init.
        # Without these, defaults always win regardless of what was saved.
        "subtitles":               s.get("subtitles", False),
        "embed_metadata":          s.get("embed_metadata", True),
        "output_format":           s.get("output_format", "mp4"),
        "default_audio_format":    s.get("default_audio_format", "320"),
        "theme":                   s.get("theme", ""),
        "yt_dlp_channel":          s.get("yt_dlp_channel", "stable"),
        "ffmpeg_channel":          s.get("ffmpeg_channel", "stable"),
        "favorite_themes":         s.get("favorite_themes", []),
        "random_theme_on_launch":  s.get("random_theme_on_launch", False),
        "random_theme_scope":      s.get("random_theme_scope", "favorites"),
    })

@app.route("/api/settings/save", methods=["POST"])
def save_settings():
    data = request.get_json(silent=True) or {}
    ALLOWED = {"last_folder", "concurrency", "fragments", "settings_open",
               "upd_open", "ck_open", "quit_on_done",
               "last_seen_version", "window_bounds", "window_maximized", "check_updates_on_launch", "theme",
               "subtitles", "embed_metadata", "output_format",
               "default_audio_format", "default_video_format",
               "yt_dlp_channel", "ffmpeg_channel",
               "favorite_themes", "random_theme_on_launch", "random_theme_scope"}
    if "last_folder" in data:
        folder = data["last_folder"]
        if folder:
            try: Path(folder).mkdir(parents=True, exist_ok=True)
            except Exception: pass
    # Sanitize favorites / random-theme settings — defense-in-depth (the UI already
    # validates, but never trust client input). Keep only valid theme keys, capped.
    if "favorite_themes" in data:
        fav = data.get("favorite_themes")
        if isinstance(fav, list):
            cleaned, seen = [], set()
            for _k in fav:
                if isinstance(_k, str) and _re.fullmatch(r"[a-z0-9-]+", _k) and _k not in seen:
                    seen.add(_k); cleaned.append(_k)
                    if len(cleaned) >= 1000: break
            data["favorite_themes"] = cleaned
        else:
            data.pop("favorite_themes", None)
    if data.get("random_theme_scope") not in (None, "favorites", "all"):
        data.pop("random_theme_scope", None)
    if "random_theme_on_launch" in data:
        data["random_theme_on_launch"] = bool(data["random_theme_on_launch"])
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
        if sys.platform == "win32": os.startfile(str(path))
        elif sys.platform == "darwin": _popen("open", str(path))
        else: _popen("xdg-open", str(path))
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

# ── Update system ──────────────────────────────────────────────────────────────
def _get_ytdlp_version():
    try: return _run(sys.executable, "-m", "yt_dlp", "--version", timeout=10).stdout.strip()
    except Exception: return "unknown"

def _get_ffmpeg_version():
    exe = FFMPEG_DIR / "ffmpeg.exe"
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
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            return json.loads(r.read()).get("tag_name","unknown")
    except Exception: return "unknown"

def _get_latest_ytdlp_version(channel=None):
    if channel is None:
        channel = _load_settings().get("yt_dlp_channel", "stable")
    repo = "yt-dlp/yt-dlp-nightly-builds" if channel == "nightly" else "yt-dlp/yt-dlp"
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest",
            headers={"User-Agent":"EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            return json.loads(r.read()).get("tag_name","unknown")
    except Exception: return "unknown"

update_status: dict = {}

def _get_mutagen_version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("mutagen")
    except Exception:
        return "not installed"


def _get_latest_mutagen_version() -> str:
    try:
        with _safe_urlopen("https://pypi.org/pypi/mutagen/json", HTTP_TIMEOUT_SHORT) as r:
            return json.loads(r.read())["info"]["version"]
    except Exception:
        return "unknown"


def _run_update(do_ytdlp, do_ffmpeg, do_mutagen=False):
    global update_status
    update_status = {"running": True, "log": [], "done": False, "error": None}
    def log(m): print(f"[EGM] {m}"); update_status["log"].append(m)
    try:
        if do_ytdlp:
            channel = _load_settings().get("yt_dlp_channel", "stable")
            if channel == "nightly":
                log("Installing yt-dlp nightly...")
                r = _run(sys.executable, "-m", "pip", "install", "--upgrade",
                         "--force-reinstall",
                         "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.tar.gz",
                         timeout=120)
            else:
                latest_ver = _get_latest_ytdlp_version("stable")
                if latest_ver and latest_ver != "unknown":
                    log(f"Installing yt-dlp stable {latest_ver}...")
                    r = _run(sys.executable, "-m", "pip", "install",
                             f"yt-dlp=={latest_ver}", "--force-reinstall",
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
            log("Downloading latest ffmpeg...")
            FFMPEG_DIR.mkdir(exist_ok=True)
            tmp = FFMPEG_DIR / "ffmpeg_update.zip"
            ffmpeg_url = _get_ffmpeg_url()
            req = urllib.request.Request(ffmpeg_url, headers={"User-Agent": "EGM-Downloader"})
            with _safe_urlopen(req, HTTP_TIMEOUT_LONG) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            ok, msg = _verify_upstream_checksum(tmp, "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256", os.path.basename(ffmpeg_url))
            log(msg)
            if not ok:
                tmp.unlink(missing_ok=True)
                update_status["error"] = "Checksum mismatch — update aborted"
                update_status["done"]  = True
                return
            log("Extracting...")
            with zipfile.ZipFile(tmp, "r") as z:
                for m in z.namelist():
                    if ".." in m.replace("\\", "/").split("/") or m.startswith(("/", "\\")):
                        continue
                    fn = Path(m).name
                    if fn in ("ffmpeg.exe","ffprobe.exe"):
                        with z.open(m) as src, open(FFMPEG_DIR/fn,"wb") as dst:
                            shutil.copyfileobj(src, dst)
            tmp.unlink(missing_ok=True)
            try: FFMPEG_TAG_FILE.write_text(_get_latest_ffmpeg_tag())
            except Exception: pass
            log(f"ffmpeg -> {_get_ffmpeg_version()}")
        if do_mutagen:
            log("Updating mutagen...")
            r = _run(sys.executable, "-m", "pip", "install", "--upgrade",
                     "mutagen", "--break-system-packages", timeout=60)
            if r.returncode == 0:
                log(f"mutagen -> {_get_mutagen_version()}")
            else:
                err = (r.stderr.strip().splitlines() or ["unknown error"])[-1]
                log(f"mutagen update failed: {err}")
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
    cm      = _get_mutagen_version()
    lm      = _get_latest_mutagen_version()
    settings = _load_settings()
    ytdlp_ch  = settings.get("yt_dlp_channel", "stable")
    ffmpeg_ch = settings.get("ffmpeg_channel", "stable")
    ytdlp_ok   = cy != "unknown" and cy == ly
    mutagen_ok = cm != "not installed" and lm != "unknown" and cm == lm
    return jsonify({
        "ytdlp":   {"current": cy, "latest": ly, "up_to_date": ytdlp_ok, "channel": ytdlp_ch},
        "ffmpeg":  {"current": cf, "latest": lf,
                    "up_to_date": cf not in ("not installed","unknown") and lf != "unknown" and cf == lf, "channel": ffmpeg_ch},
        "mutagen": {"current": cm, "latest": lm, "up_to_date": mutagen_ok},
    })

@app.route("/api/run-update", methods=["POST"])
def run_update():
    if update_status.get("running"): return jsonify({"error": "Already running"}), 409
    data = request.get_json(silent=True) or {}
    threading.Thread(target=_run_update,
                     args=(bool(data.get("ytdlp", True)),
                           bool(data.get("ffmpeg", False)),
                           bool(data.get("mutagen", False))),
                     daemon=True).start()
    return jsonify({"started": True})

@app.route("/api/cookies/status")
def cookies_status():
    """Return whether cookies.txt is present — for optional UI use."""
    exists = COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0
    age_days = None
    if exists:
        saved_at = _load_settings().get("cookies_saved_at")
        if saved_at is None:
            # Fallback: use file mtime when settings don't have the timestamp
            # (fresh install or settings reset while cookies are loaded)
            saved_at = int(COOKIES_FILE.stat().st_mtime)
        age_days = int((time.time() - saved_at) / 86400)
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
        _atomic_write_text(COOKIES_FILE, text, owner_only=True)
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
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            release = json.loads(r.read())
        tag = release.get("tag_name", "")
        assets = release.get("assets", [])
        url = next(
            (a["browser_download_url"] for a in assets
             if a["name"] == "deno-x86_64-pc-windows-msvc.zip"),
            DENO_ZIP_URL)  # fallback to latest redirect URL
        version_label = tag or "latest"
        log(f"Downloading Deno {version_label} (~35 MB)...")
        deno_filename = url.split("/")[-1]
        deno_checksum_url = url + ".sha256sum"

        # Stream download with progress logging every 5 MB
        downloaded = 0
        chunk = 1024 * 256  # 256 KB chunks
        with _safe_urlopen(url, HTTP_TIMEOUT_LONG) as resp, open(tmp, "wb") as f:
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

        ok, msg = _verify_upstream_checksum(tmp, deno_checksum_url, deno_filename)
        log(msg)
        if not ok:
            tmp.unlink(missing_ok=True)
            deno_install_status["error"] = "Checksum mismatch — install aborted"
            deno_install_status["done"]  = True
            return
        log("Extracting deno.exe...")
        with zipfile.ZipFile(tmp, "r") as z:
            if "deno.exe" not in z.namelist():
                raise RuntimeError("deno.exe not found in zip archive")
            _safe_extract(z, "deno.exe", DENO_DIR)
        tmp.unlink(missing_ok=True)

        # Verify it actually runs
        ver = _get_deno_version()
        if ver in ("unknown", "not installed"):
            raise RuntimeError("deno.exe extracted but failed to run")

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
    cm = _get_mutagen_version()
    deno_installed = DENO_EXE.exists()
    deno_version   = _get_deno_version() if deno_installed else "not installed"
    return jsonify({
        "ytdlp":   {"current": cy, "latest": None, "up_to_date": None},
        "ffmpeg":  {"current": cf, "latest": None, "up_to_date": None},
        "mutagen": {"current": cm, "latest": None, "up_to_date": None},
        "deno":    {"installed": deno_installed, "version": deno_version},
    })


@app.route("/api/portable-status")
def portable_status():
    """Return whether the app is running in portable mode and its data directory."""
    return jsonify({
        "portable": PORTABLE_MODE,
        "data_dir": str(get_data_dir()),
    })


@app.route("/api/whats-new")
def whats_new():
    """Return _version_notes from the platform JSON feed for the What's New modal.
    Falls back to empty list gracefully — modal stays shown but with no bullets."""
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
                                     headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            data = json.loads(r.read())
        # Verify the signed manifest before trusting any of its content — keeps the
        # trust model consistent with /api/check-app-update. On failure, fall back to
        # showing no notes rather than rendering unverified feed data.
        if not _verify_manifest(data):
            _sec_event("whats-new: manifest signature INVALID or MISSING — notes suppressed")
            return jsonify({"version": APP_VERSION, "notes_list": []})
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
    """Fetch egm-version.json and compare to running version.
    Returns portable:True and suppresses update in portable mode."""
    if PORTABLE_MODE:
        return jsonify({
            "portable": True,
            "up_to_date": True,
            "current_version": APP_VERSION,
            "current_build": APP_BUILD,
            "notes": "",
        })
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
                                     headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            data = json.loads(r.read())
        # Verify manifest signature before trusting any content
        if not _verify_manifest(data):
            _sec_event("Manifest signature INVALID or MISSING — update check aborted")
            return jsonify({"error": "Manifest verification failed"}), 502
        latest_ver   = str(data.get("version", "")).strip()
        latest_build = int(data.get("build", 0))
        # _version_notes (new format) is a list; old "notes" was a plain string — handle both
        notes        = data.get("_version_notes", data.get("notes", []))
        if isinstance(notes, list): notes = "\n".join(notes)
        else: notes = str(notes).strip()
        # "download" was a web page URL in old format — new format has no equivalent; leave blank
        download     = str(data.get("download", "")).strip()
        # "downloadUrl" in new format; "zip_url" in old format; fallback to hardcoded constant
        zip_url      = str(data.get("downloadUrl", data.get("zip_url", APP_UPDATE_ZIP_URL))).strip()
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
            "_checksums":      data.get("_checksums"),
        })
    except urllib.error.URLError:
        return jsonify({"error": "Could not reach update server"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/download-update", methods=["POST"])
def download_update():
    """Download EGMd.zip, verify SHA256 checksum, extract egm-setup.exe, return installer path."""
    if PORTABLE_MODE:
        return jsonify({"error": "Auto-update is disabled in portable mode. Download the latest portable zip from egerena.com/apps."}), 400
    data    = request.get_json(silent=True) or {}
    zip_url = data.get("zip_url", APP_UPDATE_ZIP_URL).strip()
    expected_checksum = data.get("expected_checksum", "").strip().lower()
    if not zip_url:
        return jsonify({"error": "No zip URL provided"}), 400
    if not expected_checksum:
        return jsonify({"error": "Checksum required for update verification"}), 400
    # SSRF guard: only allow downloads from the official distribution server
    if not zip_url.startswith("https://egerena.com/"):
        return jsonify({"error": "Invalid update URL"}), 400

    UPDATE_TMP_DIR.mkdir(parents=True, exist_ok=True)
    zip_path       = UPDATE_TMP_DIR / "EGMd.zip"
    installer_path = UPDATE_TMP_DIR / "egm-setup.exe"

    try:
        # Download zip — LONG timeout: this is a multi-MB installer payload, not
        # a metadata call. SHORT (15s) would spuriously fail on slow connections.
        req = urllib.request.Request(zip_url, headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_LONG) as r, open(zip_path, "wb") as f:
            shutil.copyfileobj(r, f)

        # Verify SHA256 checksum (required — fail-closed)
        h = hashlib.sha256()
        h.update(zip_path.read_bytes())
        actual_checksum = h.hexdigest().lower()
        if actual_checksum != expected_checksum:
            zip_path.unlink(missing_ok=True)
            return jsonify({"error": "Checksum verification failed — download may be corrupted or tampered. Please try again."}), 500

        # Extract egm-setup.exe using standard zipfile
        with zipfile.ZipFile(zip_path, "r") as z:
            names = z.namelist()
            if "egm-setup.exe" not in names:
                zip_path.unlink(missing_ok=True)
                return jsonify({"error": "egm-setup.exe not found in zip"}), 500
            _safe_extract(z, "egm-setup.exe", UPDATE_TMP_DIR)

        zip_path.unlink(missing_ok=True)
        return jsonify({"success": True, "installer_path": str(installer_path)})

    except Exception as e:
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        return jsonify({"error": str(e)}), 500

@app.route("/api/cache/clear", methods=["POST"])
def cache_clear():
    """Clear temp update files and orphaned partial download files."""
    cleared = []
    try:
        if UPDATE_TMP_DIR.exists():
            shutil.rmtree(UPDATE_TMP_DIR, ignore_errors=True)
            cleared.append("update cache")
    except Exception: pass
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
        _atomic_write_text(SETTINGS_FILE, "{}", owner_only=True)
        global _settings_cache
        with _settings_lock:
            _settings_cache = {}
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

@app.route("/api/electron/reinstall", methods=["POST"])
def electron_reinstall():
    """Create marker so launch.py strips Electron on next restart."""
    try:
        marker = BASE_DIR / ".electron-update"
        marker.write_text("reinstall", encoding="utf-8")
        return jsonify({"ok": True, "message": "Electron will reinstall on next restart"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Show-window signal (Windows tray) ────────────────────────────────────────
# launch.py POSTs /api/show-window when the user launches the shortcut while
# the app is already running. main.js polls /api/show-window-check every 500ms
# and shows the window when the flag is set. This avoids spawning a second
# Electron process and prevents the Tkinter "launching" splash from appearing.
_show_window_flag = threading.Event()

@app.route("/api/show-window", methods=["POST"])
def show_window():
    """Signal from launch.py — app already running, bring window to front."""
    _show_window_flag.set()
    return jsonify({"ok": True})

@app.route("/api/show-window-check")
def show_window_check():
    """Polled by main.js every 500ms — returns show:true once, then clears."""
    if _show_window_flag.is_set():
        _show_window_flag.clear()
        return jsonify({"show": True})
    return jsonify({"show": False})

# ── History routes ────────────────────────────────────────────────────────────
@app.route("/api/history")
def get_history():
    page     = _clamp_int(request.args.get("page"), 1, 1, 10_000_000)
    per_page = _clamp_int(request.args.get("per_page"), 10, 1, 500)
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
        # Find and delete associated thumbnail
        for i in items:
            if i.get("id") == entry_id and i.get("thumbnail"):
                try: (THUMBNAILS_DIR / i["thumbnail"]).unlink(missing_ok=True)
                except Exception: pass
        items = [i for i in items if i.get("id") != entry_id]
        _save_history(items)
    return jsonify({"ok": True})

@app.route("/api/history/clear", methods=["POST"])
def clear_history():
    with _history_lock:
        _save_history([])
    # Clear all thumbnails
    try:
        for f in THUMBNAILS_DIR.iterdir():
            try: f.unlink()
            except Exception: pass
    except Exception: pass
    return jsonify({"ok": True})

@app.route("/api/thumbnail/<filename>")
def serve_thumbnail(filename):
    """Serve a cached thumbnail image."""
    # Validate filename — only allow safe characters
    if not _re.match(r'^[a-f0-9\-]+\.(jpg|png|webp)$', filename):
        _sec_event(f"Thumbnail filename rejected (invalid pattern): {filename!r}")
        return "Not found", 404
    thumb_path = THUMBNAILS_DIR / filename
    if not thumb_path.exists():
        return "Not found", 404
    ext = thumb_path.suffix.lower()
    mime = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext.lstrip("."), "image/jpeg")
    resp = app.response_class(thumb_path.read_bytes(), mimetype=mime)
    resp.headers["Cache-Control"] = "max-age=86400"
    return resp

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
def themes_page(): return render_template("themes.html", egm_token=_API_TOKEN)

@app.route("/subscriptions-page")
def subscriptions_page(): return render_template("subscriptions.html", egm_token=_API_TOKEN)

# ── Subscriptions API ─────────────────────────────────────────────────────────

@app.route("/api/subscriptions", methods=["GET"])
def get_subscriptions():
    return jsonify({"subscriptions": _load_subscriptions()})

@app.route("/api/subscriptions/add", methods=["POST"])
def add_subscription():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return jsonify({"error": "Valid HTTP(S) URL is required"}), 400

    name = (data.get("name") or "")[:200].strip()

    subs = _load_subscriptions()

    if len(subs) >= 500:
        return jsonify({"error": "Subscription limit reached (500)"}), 400

    # Prevent duplicates
    if any(s.get("url") == url for s in subs):
        return jsonify({"error": "Already subscribed"}), 409

    sub = {
        "id": str(uuid.uuid4()),
        "url": url,
        "name": name,
        "description": "",
        "thumbnail_url": "",
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_fetched": None,
        "auto_fetch_on_open": False,
        "download_folder": None,
        "format": "video",
        "videos": []
    }

    # Get channel metadata — dump-single-json gives playlist-level data (name, avatar)
    if not name:
        try:
            r = _ytdlp("--flat-playlist", "--dump-single-json",
                       "--playlist-end", "1", url, timeout=30)
            if r.returncode == 0 and r.stdout:
                meta = json.loads(r.stdout.strip())
                # Channel name from playlist-level field
                cname = (meta.get("channel") or meta.get("uploader") or meta.get("title") or "")
                cname = cname.replace(" - Videos", "").replace(" - Playlists", "").strip()[:200]
                sub["name"] = cname
                # Channel avatar — playlist-level thumbnails (not entry thumbnails)
                thumbs = meta.get("thumbnails") or []
                if thumbs and isinstance(thumbs, list):
                    # Filter for likely avatar (square-ish, not banners)
                    avatars = [t for t in thumbs if isinstance(t, dict) and
                               t.get("id", "").startswith("avatar")]
                    src = avatars[-1] if avatars else thumbs[-1]
                    sub["thumbnail_url"] = _safe_thumb_url(src.get("url", "") if isinstance(src, dict) else "")
        except Exception:
            pass

    subs.append(sub)
    _save_subscriptions(subs)
    return jsonify({"subscription": sub})

@app.route("/api/subscriptions/remove", methods=["POST"])
def remove_subscription():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    if not sub_id:
        return jsonify({"error": "ID is required"}), 400

    subs = _load_subscriptions()
    before = len(subs)
    subs = [s for s in subs if s.get("id") != sub_id]
    if len(subs) == before:
        return jsonify({"error": "Not found"}), 404

    _save_subscriptions(subs)
    return jsonify({"ok": True})

@app.route("/api/subscriptions/update", methods=["POST"])
def update_subscription():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    if not sub_id:
        return jsonify({"error": "ID is required"}), 400

    allowed = {"name", "download_folder", "format", "auto_fetch_on_open"}
    subs = _load_subscriptions()
    for s in subs:
        if s.get("id") == sub_id:
            for k, v in data.items():
                if k not in allowed:
                    continue
                if k == "name":
                    v = str(v)[:200].strip()
                elif k == "format":
                    v = v if v in ("video", "audio") else "video"
                elif k == "auto_fetch_on_open":
                    v = bool(v)
                s[k] = v
            _save_subscriptions(subs)
            return jsonify({"subscription": s})
    return jsonify({"error": "Not found"}), 404

@app.route("/api/subscriptions/fetch", methods=["POST"])
def fetch_subscription_videos():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    force = bool(data.get("force", False))
    if not sub_id:
        return jsonify({"error": "ID is required"}), 400

    subs = _load_subscriptions()
    sub = next((s for s in subs if s.get("id") == sub_id), None)
    if not sub:
        return jsonify({"error": "Not found"}), 404

    url = sub.get("url", "")
    if not url:
        return jsonify({"error": "No URL"}), 400

    try:
        # Flat-playlist with approximate_date — fast and gives dates for sorting
        # Drop cookies/ejs/deno for listing (no formats/signatures needed)
        r = _run_yt(
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist", "-j",
            "--playlist-end", "200",
            "--extractor-args", "youtubetab:approximate_date",
            url, timeout=90
        )
        if r.returncode != 0:
            return jsonify({"error": "Failed to fetch videos", "detail": (r.stderr or "")[:500]}), 502

        existing_ids = set()
        if not force:
            existing_ids = {v.get("video_id") for v in (sub.get("videos") or [])}

        new_videos = []
        channel_name = sub.get("name") or ""
        channel_thumb = sub.get("thumbnail_url") or ""

        for line in (r.stdout or "").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue

            vid = entry.get("id", "")
            if not vid or (vid in existing_ids and not force):
                continue

            # Extract channel info from first entry if not set
            if not channel_name:
                channel_name = (entry.get("channel") or entry.get("uploader") or "")[:200]
                channel_name = channel_name.replace(" - Videos", "").replace(" - Playlists", "").strip()

            # Thumbnail
            vid_thumb = ""
            vid_thumbs = entry.get("thumbnails") or []
            if vid_thumbs and isinstance(vid_thumbs, list):
                vid_thumb = _safe_thumb_url(vid_thumbs[-1].get("url", "") if isinstance(vid_thumbs[-1], dict) else "")
            if not vid_thumb:
                vid_thumb = _safe_thumb_url(entry.get("thumbnail") or "")

            # upload_date from approximate_date (returns int timestamp or ISO string)
            upload_date = ""
            if entry.get("upload_date"):
                upload_date = str(entry["upload_date"])
            elif entry.get("timestamp"):
                # Convert unix timestamp to YYYYMMDD
                import datetime as dt
                upload_date = dt.datetime.utcfromtimestamp(entry["timestamp"]).strftime("%Y%m%d")

            new_videos.append({
                "video_id": vid,
                "title": (entry.get("title") or "Untitled")[:300],
                "duration": entry.get("duration") or 0,
                "upload_date": upload_date,
                "thumbnail_url": vid_thumb,
                "formats": [],
                "downloaded": False,
                "download_path": None
            })

        # Merge
        if force:
            sub["videos"] = new_videos
        else:
            sub["videos"] = new_videos + (sub.get("videos") or [])

        if channel_name and not sub.get("name"):
            sub["name"] = channel_name
        sub["last_fetched"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        _save_subscriptions(subs)
        return jsonify({
            "subscription": sub,
            "new_count": len(new_videos),
            "total": len(sub["videos"])
        })

    except Exception as e:
        return jsonify({"error": str(e)[:500]}), 500

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

    threading.Thread(target=ensure_ffmpeg, daemon=True, name="ffmpeg-setup").start()
    # Electron launches Flask with PORT in the env and then polls that exact port.
    # The env value MUST win over the persisted flask_port setting — otherwise a
    # stale or hand-edited setting binds Flask to a port Electron never connects
    # to, bricking the app with no visible error. Settings value is the fallback
    # only when launched outside Electron (e.g. bare `python app.py`).
    # Safe port resolution: env PORT (from Electron) wins; persisted flask_port is
    # the fallback. Parse defensively and validate the range so a corrupted or
    # hand-edited setting can never crash startup — fall back to 8899 if invalid.
    def _resolve_port():
        for candidate in (os.environ.get("PORT"), _load_settings().get("flask_port")):
            try:
                p = int(candidate)
            except (TypeError, ValueError):
                continue
            if 1024 <= p <= 65535:
                return p
        return 8899
    port = _resolve_port()
    host = "127.0.0.1"  # always localhost — never exposed to network
    threading.Thread(target=lambda: app.run(host=host,port=port,use_reloader=False),
                     daemon=True, name="flask").start()

    # Under Electron: keep Flask alive; Electron manages the window and lifecycle.
    print(f"[EGM Downloader] running on http://{host}:{port}")
    try: threading.Event().wait()
    except KeyboardInterrupt: pass
