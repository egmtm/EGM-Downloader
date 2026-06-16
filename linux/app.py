import os
import sys
import uuid
import glob
import json
import hmac
import subprocess
import re as _re
import time
import copy
import threading
import concurrent.futures
import urllib.request
import urllib.parse
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

# Outbound HTTP whitelist — every external host this app contacts must be listed.
# Enforced before urlopen() and after redirect resolution. When adding a new host,
# document why it's needed alongside the entry.
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
        log_dir  = DATA_DIR / 'logs'
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
    """Return True if the URL\'s hostname is in the outbound whitelist."""
    try:
        return (urllib.parse.urlparse(url).hostname or "") in _ALLOWED_DOWNLOAD_HOSTS
    except Exception:
        return False

def _safe_urlopen(req_or_url, timeout):
    """urlopen with host whitelist enforcement (pre-request and post-redirect).
    Raises RuntimeError if the URL or its redirect target isn\'t whitelisted."""
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
    Python\'s zipfile already sanitizes by default; this makes the assumption explicit
    and guards against accidental future use of extractall() or raw namelist iteration."""
    if member not in z.namelist():
        raise RuntimeError(f"{member!r} not found in archive")
    name = z.getinfo(member).filename
    if ".." in name or name.startswith(("/", "\\")):
        raise RuntimeError(f"Suspicious archive member path: {name!r}")
    z.extract(member, target_dir)

def _verify_upstream_checksum(local_path, checksum_url, filename):
    """Fetch upstream checksum file, parse for filename, verify local download.
    Returns (ok: bool, message: str).
    Fail-closed: any fetch failure, parse error, missing entry, or mismatch returns False."""
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            lines = r.read().decode().splitlines()
        expected = None
        for line in lines:
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

def _chmod_owner_only(path):
    """Set sensitive file to owner read/write only (POSIX). No-op on Windows."""
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

def _atomic_write_text(path: Path, content: str, *, owner_only: bool = False) -> None:
    """Write text atomically via tmp + os.replace — prevents truncated files on crash or kill -9.
    Sets permissions on tmp before rename so the final file has correct perms from the moment
    it exists (no race window). Cleans up the tmp file on failure and re-raises."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())          # durability parity w/ Windows
        if owner_only:
            _chmod_owner_only(tmp)
        tmp.replace(path)
    except Exception:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        raise

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
# APP_DIR: read-only — inside the AppImage squashfs mount.
#          Safe to read files from here; never write here.
# DATA_DIR: writable — persists in the user's home across AppImage updates.
APP_DIR  = Path(__file__).parent
DATA_DIR = Path.home() / ".local" / "share" / "egm-downloader"
DATA_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_DIR    = DATA_DIR / "ffmpeg_bin"

# ── App version ───────────────────────────────────────────────────────────────
APP_VERSION           = "1.0.3"
APP_BUILD             = 126
APP_UPDATE_URL = "https://egerena.com/apps/egmlinux-update.json"

# Settings and cookies: writable user data under DATA_DIR
SETTINGS_FILE = DATA_DIR / "egm_settings.json"
HISTORY_FILE  = DATA_DIR / "egm_history.json"
SUBS_FILE     = DATA_DIR / "egm_subscriptions.json"
COOKIES_FILE  = DATA_DIR / "cookies.txt"

_settings_cache: dict = {}
_settings_lock  = threading.Lock()

# ── History ────────────────────────────────────────────────────────────────────
_history_lock = threading.Lock()
_HISTORY_MAX  = 500
THUMBNAILS_DIR = DATA_DIR / "thumbnails"
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
    backend fetch internal services (SSRF). Fail-closed: resolution failure -> internal."""
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

def _load_subscriptions_unlocked() -> list:
    global _subs_cache
    if _subs_cache is None:
        try:
            data = json.loads(SUBS_FILE.read_text(encoding="utf-8"))
            _subs_cache = data.get("subscriptions", []) if isinstance(data, dict) else []
        except Exception:
            _subs_cache = []
    return list(_subs_cache)

def _save_subscriptions_unlocked(subs: list):
    global _subs_cache
    _subs_cache = subs
    _atomic_write_text(SUBS_FILE, json.dumps({"subscriptions": subs}, indent=2), owner_only=True)

def _load_subscriptions() -> list:
    with _subs_lock:
        return _load_subscriptions_unlocked()

def _save_subscriptions(subs: list):
    with _subs_lock:
        _save_subscriptions_unlocked(subs)

class _AbortMutation(Exception):
    """Raised inside a _mutate_subscriptions callback to abort WITHOUT saving
    (e.g. a validation failure). Its .result is returned to the caller."""
    def __init__(self, result):
        self.result = result

def _mutate_subscriptions(fn):
    """Atomic read-modify-write of the subscriptions list under a single lock
    hold. The server is multi-threaded, so concurrent writers would otherwise
    clobber each other (each previously did load -> modify -> save with the lock
    released in between, losing updates). fn(subs) mutates a private deep copy in
    place; the change is committed (cache + file) only if fn returns normally.
    Raise _AbortMutation(result) to abort without saving. NEVER run slow work
    (yt-dlp) inside fn — do that first, then merge the result here."""
    with _subs_lock:
        subs = copy.deepcopy(_load_subscriptions_unlocked())
        try:
            result = fn(subs)
        except _AbortMutation as a:
            return a.result
        _save_subscriptions_unlocked(subs)
        return result

jobs: dict = {}
_jobs_lock = threading.Lock()

# ── Active process registry ───────────────────────────────────────────────────
_active_procs: dict = {}
_active_procs_lock  = threading.Lock()

_MAX_CONCURRENT_DOWNLOADS = 24
_download_sem = threading.BoundedSemaphore(_MAX_CONCURRENT_DOWNLOADS)

_update_lock       = threading.Lock()
_deno_install_lock = threading.Lock()

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
    (_re.compile(r"No video formats found|No formats found",          _re.I), "No downloadable formats found. This is usually a members-only video — if you're a member of this channel, load your account cookies in Settings and try again. It may also be private, region-locked, or otherwise restricted."),
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
FFMPEG_URL_NIGHTLY = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                     "ffmpeg-master-latest-linux64-gpl.tar.xz")
FFMPEG_URL_STABLE  = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
                      "ffmpeg-n8.1-latest-linux64-gpl-8.1.tar.xz")

def _get_ffmpeg_url():
    ch = _load_settings().get("ffmpeg_channel", "stable")
    return FFMPEG_URL_NIGHTLY if ch == "nightly" else FFMPEG_URL_STABLE

FFMPEG_URL = FFMPEG_URL_STABLE
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
        ffmpeg_url = _get_ffmpeg_url()
        req = urllib.request.Request(ffmpeg_url, headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_LONG) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f)
        ok, msg = _verify_upstream_checksum(tmp, "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256", os.path.basename(ffmpeg_url))
        print(f"[EGM] {msg}")
        if not ok:
            tmp.unlink(missing_ok=True)
            return
        print("[EGM] Extracting ffmpeg...")
        with tarfile.open(tmp, "r:xz") as t:
            for member in t.getmembers():
                # Tar slip guard: skip path traversal / absolute paths
                if ".." in member.name.split("/") or member.name.startswith("/"):
                    continue
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
    return _run_yt(sys.executable, "-m", "yt_dlp", "--remote-components", "ejs:github", *_ffmpeg_args(), *_deno_args(),
                   *_cookies_args(), *_bgutil_args(), *extra, timeout=timeout)

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

_VIDEO_ID_RE = _re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

def _safe_video_id(vid) -> str:
    """Validate a video id from yt-dlp metadata before storing it. Allowlist
    covers YouTube ids ([A-Za-z0-9_-]) plus '.' and ':' used by some other
    extractors; rejects quotes/spaces/HTML chars that could break out of an
    attribute context when the id is interpolated in subscriptions.html."""
    if not vid or not isinstance(vid, str):
        return ""
    return vid if _VIDEO_ID_RE.fullmatch(vid) else ""

_SYSTEM_ROOTS = ("/etc", "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/boot",
                 "/sys", "/proc",
                 "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
                 "C:\\System32")

def _validate_download_dir(dl_dir):
    """Validate a download directory. Returns (ok, resolved_path_str, error).

    1. RESOLVE first (collapses '..', follows symlinks) so the system-root check
       can't be bypassed via 'C:\\Users\\..\\Windows' or a symlinked folder.
    2. Boundary-aware system-root check on the RESOLVED path — '/etc/x' is
       rejected but '/etcetera' is fine (the old prefix match got this wrong,
       which is also why 'Program Files (x86)' is now listed explicitly).
    3. Reachability + writability probe on the deepest EXISTING ancestor (the
       directory itself may not exist yet — run_download creates it). Catches
       unplugged drives, read-only mounts and permission errors up front with a
       clear message instead of a mid-download worker failure. os.access is a
       best-effort probe (Windows ACLs may not be fully reflected); the worker's
       mkdir remains the final arbiter.

    Also used by subscriptions per-channel download folders (Phase 3).
    """
    if not dl_dir or not isinstance(dl_dir, str) or not dl_dir.strip():
        return False, "", "No download directory provided."
    try:
        p = Path(dl_dir).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False, "", "Invalid download directory path."
    rs = str(p).replace("\\", "/").rstrip("/").lower()
    for root in _SYSTEM_ROOTS:
        rn = root.replace("\\", "/").rstrip("/").lower()
        if rs == rn or rs.startswith(rn + "/"):
            return False, "", (f"Download directory '{dl_dir}' resolves to a system "
                               "path. Please choose a different folder.")
    probe = p
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    if not probe.exists():
        return False, "", (f"Download directory '{dl_dir}' is not reachable "
                           "(drive disconnected?). Please choose a different folder.")
    if not probe.is_dir():
        return False, "", f"'{dl_dir}' is not a valid folder location."
    if not os.access(str(probe), os.W_OK):
        return False, "", (f"Download directory '{dl_dir}' is not writable. "
                           "Please choose a different folder.")
    return True, str(p), ""

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
def _run_download_slot(job_id, *rest):
    """Hold a concurrency slot for the whole download and wait out first-run ffmpeg."""
    _download_sem.acquire()
    try:
        job = jobs.get(job_id)
        if not job:
            return
        if job.get("cancelled"):
            job["status"] = "cancelled"; job["_finished_at"] = time.time()
            return
        ff = FFMPEG_DIR / "ffmpeg"
        if not ff.exists():
            waited = 0
            while not ff.exists() and waited < 180:
                if job.get("cancelled"):
                    job["status"] = "cancelled"; job["_finished_at"] = time.time()
                    return
                time.sleep(1); waited += 1
            if not ff.exists():
                job["status"] = "error"
                job["error"]  = "ffmpeg is still installing (first-run setup). Please try again in a moment."
                job["_finished_at"] = time.time()
                return
        run_download(job_id, *rest)
    finally:
        _download_sem.release()

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

    ok, resolved_dir, err = _validate_download_dir(dl_dir)
    if not ok:
        return jsonify({"error": err}), 400
    dl_dir = resolved_dir

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
    threading.Thread(target=_run_download_slot,
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

def _run_update(do_ytdlp, do_ffmpeg):
    global update_status
    update_status = {"running": True, "log": [], "done": False, "error": None}
    def log(m): print(f"[EGM] {m}"); update_status["log"].append(m)
    try:
        if do_ytdlp:
            PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
            channel = _load_settings().get("yt_dlp_channel", "stable")
            if channel == "nightly":
                log("Installing yt-dlp nightly...")
                # Download tar.gz first — bundled pip may not handle GitHub URLs/redirects
                nightly_url = "https://github.com/yt-dlp/yt-dlp-nightly-builds/releases/latest/download/yt-dlp.tar.gz"
                tmp_tar = PACKAGES_DIR / "yt-dlp-nightly.tar.gz"
                try:
                    req = urllib.request.Request(nightly_url, headers={"User-Agent": "EGM-Downloader"})
                    with _safe_urlopen(req, HTTP_TIMEOUT_LONG) as resp, open(tmp_tar, "wb") as f:
                        shutil.copyfileobj(resp, f)
                except Exception as e:
                    log(f"yt-dlp nightly download failed: {e}")
                    try: tmp_tar.unlink(missing_ok=True)
                    except Exception: pass
                    return
                r = _run(sys.executable, "-m", "pip", "install",
                         str(tmp_tar), "--target", str(PACKAGES_DIR),
                         "--upgrade", "--force-reinstall", timeout=120)
                try: tmp_tar.unlink(missing_ok=True)
                except Exception: pass
            else:
                latest_ver = _get_latest_ytdlp_version("stable")
                if latest_ver and latest_ver != "unknown":
                    log(f"Installing yt-dlp stable {latest_ver}...")
                    r = _run(sys.executable, "-m", "pip", "install",
                             f"yt-dlp=={latest_ver}", "--target", str(PACKAGES_DIR),
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
            ffmpeg_url = _get_ffmpeg_url()
            req = urllib.request.Request(ffmpeg_url, headers={"User-Agent": "EGM-Downloader"})
            with _safe_urlopen(req, HTTP_TIMEOUT_LONG) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            ok, msg = _verify_upstream_checksum(tmp,
                "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256",
                os.path.basename(ffmpeg_url))
            log(msg)
            if not ok:
                tmp.unlink(missing_ok=True)
                update_status["error"] = "Checksum mismatch — update aborted"
                update_status["done"]  = True
                return
            log("Extracting...")
            with tarfile.open(tmp, "r:xz") as t:
                for member in t.getmembers():
                    if ".." in member.name.split("/") or member.name.startswith("/"):
                        continue
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
    ytdlp_ch  = _load_settings().get("yt_dlp_channel", "stable")
    ffmpeg_ch = _load_settings().get("ffmpeg_channel", "stable")
    ytdlp_ok = cy != "unknown" and cy == ly
    return jsonify({
        "ytdlp":   {"current": cy, "latest": ly, "up_to_date": ytdlp_ok, "channel": ytdlp_ch},
        "ffmpeg":  {"current": cf, "latest": lf,
                    "up_to_date": cf not in ("not installed","unknown") and lf != "unknown" and cf == lf, "channel": ffmpeg_ch},
        "mutagen": {"current": cm, "latest": None, "up_to_date": None},
    })

@app.route("/api/run-update", methods=["POST"])
def run_update():
    with _update_lock:
        if update_status.get("running"): return jsonify({"error": "Already running"}), 409
        update_status["running"] = True
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
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
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
        with _safe_urlopen(url, HTTP_TIMEOUT_LONG) as resp, open(tmp, "wb") as f:
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

        # Verify SHA-256 against Deno's published <asset>.sha256sum (parity w/ Windows).
        ok, msg = _verify_upstream_checksum(tmp, url + ".sha256sum", "deno-x86_64-unknown-linux-gnu.zip")
        log(msg)
        if not ok:
            tmp.unlink(missing_ok=True)
            deno_install_status["error"] = "Checksum mismatch — install aborted"
            deno_install_status["done"]  = True
            return

        log("Extracting deno...")
        with zipfile.ZipFile(tmp, "r") as z:
            if "deno" not in z.namelist():
                raise RuntimeError("deno binary not found in zip archive")
            _safe_extract(z, "deno", DENO_DIR)
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
    with _deno_install_lock:
        if deno_install_status.get("running"):
            return jsonify({"error": "Install already running"}), 409
        if DENO_EXE.exists():
            return jsonify({"error": "Deno already installed"}), 400
        deno_install_status["running"] = True
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

# ── Check for app update (informational only — Linux has no auto-install) ─────

@app.route("/api/whats-new")
def whats_new():
    """Return _version_notes from the platform JSON feed for the What's New modal.
    Falls back to empty list gracefully — modal stays shown but with no bullets."""
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
                                     headers={"User-Agent": "EGM-Downloader"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            data = json.loads(r.read())
        # Verify signed manifest before trusting release-notes content (parity w/ Windows)
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
    try:
        req = urllib.request.Request(APP_UPDATE_URL,
            headers={"User-Agent": f"EGMDownloader/{APP_VERSION}"})
        with _safe_urlopen(req, HTTP_TIMEOUT_SHORT) as r:
            data = json.loads(r.read().decode())
        # Verify manifest signature before trusting any content
        if not _verify_manifest(data):
            _sec_event("Manifest signature INVALID or MISSING — update check aborted")
            return jsonify({"error": "Manifest verification failed"}), 502
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
    # Robust parse — bad query params must not 500; clamp to sane bounds (parity w/ Windows)
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
    try:
        for f in THUMBNAILS_DIR.iterdir():
            try: f.unlink()
            except Exception: pass
    except Exception: pass
    return jsonify({"ok": True})

@app.route("/api/thumbnail/<filename>")
def serve_thumbnail(filename):
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

    # Add is INSTANT: validate + append atomically and return immediately. The
    # channel name + avatar are filled in by the first fetch (kicked off by the
    # client right after add). Previously this route ran a blocking yt-dlp
    # metadata fetch (up to 30s) that froze the add UI.
    def _add(subs):
        if len(subs) >= 500:
            raise _AbortMutation(("Subscription limit reached (500)", 400))
        if any(s.get("url") == url for s in subs):
            raise _AbortMutation(("Already subscribed", 409))
        subs.append(sub)
        return None
    err = _mutate_subscriptions(_add)
    if err:
        return jsonify({"error": err[0]}), err[1]
    return jsonify({"subscription": sub})

@app.route("/api/subscriptions/remove", methods=["POST"])
def remove_subscription():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    if not sub_id:
        return jsonify({"error": "ID is required"}), 400

    def _remove(subs):
        before = len(subs)
        subs[:] = [s for s in subs if s.get("id") != sub_id]
        return len(subs) != before
    removed = _mutate_subscriptions(_remove)
    if not removed:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})

@app.route("/api/subscriptions/update", methods=["POST"])
def update_subscription():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    if not sub_id:
        return jsonify({"error": "ID is required"}), 400

    allowed = {"name", "download_folder", "format", "auto_fetch_on_open"}

    def _update(subs):
        for s in subs:
            if s.get("id") == sub_id:
                for k, v in data.items():
                    if k not in allowed:
                        continue
                    if k == "name":
                        v = str(v)[:200].strip()
                    elif k == "download_folder":
                        if v:
                            ok, resolved, err = _validate_download_dir(str(v))
                            if not ok:
                                raise _AbortMutation(("err", err))
                            v = resolved
                        else:
                            v = None
                    elif k == "format":
                        v = v if v in ("video", "audio") else "video"
                    elif k == "auto_fetch_on_open":
                        v = bool(v)
                    s[k] = v
                return ("ok", s)
        return ("notfound", None)
    status, payload = _mutate_subscriptions(_update)
    if status == "err":
        return jsonify({"error": payload}), 400
    if status == "notfound":
        return jsonify({"error": "Not found"}), 404
    return jsonify({"subscription": payload})


# ── Subscription fetch jobs ───────────────────────────────────────────────────
# A channel fetch calls yt-dlp (up to ~90s). Running it inside the HTTP request
# would hold a browser connection that whole time, saturating the per-host pool
# and freezing add/delete. So we run fetches as background jobs and let the
# client poll a tiny status endpoint — every HTTP request stays sub-second.
_subfetch_jobs: dict = {}
_subfetch_lock = threading.Lock()
_subfetch_pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="subfetch")

def _run_subfetch(fetch_id, sub_id, url, force, need_meta):
    try:
        meta_name, meta_thumb = "", ""
        if need_meta:
            try:
                mr = _ytdlp("--flat-playlist", "--dump-single-json",
                            "--playlist-end", "1", url, timeout=30)
                if mr.returncode == 0 and mr.stdout:
                    meta = json.loads(mr.stdout.strip())
                    cname = (meta.get("channel") or meta.get("uploader") or meta.get("title") or "")
                    meta_name = cname.replace(" - Videos", "").replace(" - Playlists", "").strip()[:200]
                    thumbs = meta.get("thumbnails") or []
                    if thumbs and isinstance(thumbs, list):
                        avatars = [t for t in thumbs if isinstance(t, dict) and
                                   t.get("id", "").startswith("avatar")]
                        src = avatars[-1] if avatars else thumbs[-1]
                        meta_thumb = _safe_thumb_url(src.get("url", "") if isinstance(src, dict) else "")
            except Exception:
                pass

        r = _run_yt(
            sys.executable, "-m", "yt_dlp",
            "--flat-playlist", "-j",
            "--playlist-end", "200",
            "--extractor-args", "youtubetab:approximate_date",
            url, timeout=90
        )
        if r.returncode != 0:
            result = {"status": "error", "error": "Failed to fetch videos",
                      "detail": (r.stderr or "")[:500]}
        else:
            fetched = []          # all parsed entries; dedup happens in the atomic merge
            entry_channel = ""
            for line in (r.stdout or "").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                vid = _safe_video_id(entry.get("id", ""))
                if not vid:
                    continue
                if not entry_channel:
                    entry_channel = (entry.get("channel") or entry.get("uploader") or "")[:200]
                    entry_channel = entry_channel.replace(" - Videos", "").replace(" - Playlists", "").strip()
                vid_thumb = ""
                vid_thumbs = entry.get("thumbnails") or []
                if vid_thumbs and isinstance(vid_thumbs, list):
                    vid_thumb = _safe_thumb_url(vid_thumbs[-1].get("url", "") if isinstance(vid_thumbs[-1], dict) else "")
                if not vid_thumb:
                    vid_thumb = _safe_thumb_url(entry.get("thumbnail") or "")
                upload_date = ""
                if entry.get("upload_date"):
                    upload_date = str(entry["upload_date"])
                elif entry.get("timestamp"):
                    import datetime as dt
                    upload_date = dt.datetime.utcfromtimestamp(entry["timestamp"]).strftime("%Y%m%d")
                fetched.append({
                    "video_id": vid,
                    "title": (entry.get("title") or "Untitled")[:300],
                    "duration": entry.get("duration") or 0,
                    "upload_date": upload_date,
                    "thumbnail_url": vid_thumb,
                    "availability": entry.get("availability") or "public",
                    "is_new": True,
                    "formats": [],
                    "downloaded": False,
                    "download_path": None
                })

            def _merge(subs):
                sub = next((s for s in subs if s.get("id") == sub_id), None)
                if sub is None:
                    return None
                for v in (sub.get("videos") or []):
                    v["is_new"] = False
                if force:
                    new_videos = fetched
                    sub["videos"] = list(new_videos)
                else:
                    cur_ids = {v.get("video_id") for v in (sub.get("videos") or [])}
                    new_videos = [v for v in fetched if v["video_id"] not in cur_ids]
                    sub["videos"] = new_videos + (sub.get("videos") or [])
                if meta_name and not sub.get("name"):
                    sub["name"] = meta_name
                if meta_thumb and not sub.get("thumbnail_url"):
                    sub["thumbnail_url"] = meta_thumb
                if entry_channel and not sub.get("name"):
                    sub["name"] = entry_channel
                sub["last_fetched"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                return {"sub": sub, "new_count": len(new_videos)}
            merged = _mutate_subscriptions(_merge)
            if merged is None:
                result = {"status": "error", "error": "Subscription not found"}
            else:
                result = {"status": "done", "subscription": merged["sub"],
                          "new_count": merged["new_count"], "total": len(merged["sub"]["videos"])}
    except Exception as e:
        result = {"status": "error", "error": str(e)[:500]}
    result["_ts"] = time.time()
    with _subfetch_lock:
        _subfetch_jobs[fetch_id] = result

@app.route("/api/subscriptions/fetch", methods=["POST"])
def fetch_subscription_videos():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    force = bool(data.get("force", False))
    if not sub_id:
        return jsonify({"error": "ID is required"}), 400
    sub0 = next((s for s in _load_subscriptions() if s.get("id") == sub_id), None)
    if not sub0:
        return jsonify({"error": "Not found"}), 404
    url = sub0.get("url", "")
    if not url:
        return jsonify({"error": "No URL"}), 400
    need_meta = (not sub0.get("name")) or (not sub0.get("thumbnail_url"))

    fetch_id = str(uuid.uuid4())
    now = time.time()
    with _subfetch_lock:
        # Lazy GC: drop finished jobs whose result was never collected (window closed).
        for k in [k for k, v in _subfetch_jobs.items()
                  if v.get("status") in ("done", "error") and now - v.get("_ts", now) > 120]:
            _subfetch_jobs.pop(k, None)
        _subfetch_jobs[fetch_id] = {"status": "pending", "_ts": now}
    _subfetch_pool.submit(_run_subfetch, fetch_id, sub_id, url, force, need_meta)
    return jsonify({"fetch_id": fetch_id})

@app.route("/api/subscriptions/fetch-status", methods=["POST"])
def fetch_subscription_status():
    data = request.get_json(silent=True) or {}
    fetch_id = (data.get("fetch_id") or "").strip()
    with _subfetch_lock:
        job = _subfetch_jobs.get(fetch_id)
        if job and job.get("status") in ("done", "error"):
            job = _subfetch_jobs.pop(fetch_id)   # one-shot delivery of the terminal result
    if job is None:
        return jsonify({"status": "unknown"}), 200
    return jsonify({k: v for k, v in job.items() if k != "_ts"})

@app.route("/api/subscriptions/mark-downloaded", methods=["POST"])
def mark_downloaded():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("sub_id") or "").strip()
    video_id = (data.get("video_id") or "").strip()
    if not sub_id or not video_id:
        return jsonify({"error": "sub_id and video_id required"}), 400
    downloaded = data.get("downloaded", True) is True

    def _mark(subs):
        for s in subs:
            if s.get("id") == sub_id:
                for v in (s.get("videos") or []):
                    if v.get("video_id") == video_id:
                        v["downloaded"] = downloaded
                        return "ok"
                return "novideo"
        return "nosub"
    res = _mutate_subscriptions(_mark)
    if res == "novideo":
        return jsonify({"error": "Video not found"}), 404
    if res == "nosub":
        return jsonify({"error": "Subscription not found"}), 404
    return jsonify({"ok": True})


@app.route("/api/subscriptions/reorder", methods=["POST"])
def reorder_subscription():
    data = request.get_json(silent=True) or {}
    sub_id = (data.get("id") or "").strip()
    direction = (data.get("direction") or "").strip()
    if not sub_id or direction not in ("top", "up", "down", "bottom"):
        return jsonify({"error": "id and direction (top/up/down/bottom) required"}), 400
    def _reorder(subs):
        idx = next((i for i, s in enumerate(subs) if s.get("id") == sub_id), None)
        if idx is None:
            return False
        item = subs.pop(idx)
        if direction == "top":
            subs.insert(0, item)
        elif direction == "up" and idx > 0:
            subs.insert(idx - 1, item)
        elif direction == "down" and idx < len(subs):
            subs.insert(idx + 1, item)
        elif direction == "bottom":
            subs.append(item)
        else:
            subs.insert(idx, item)
        return True
    ok = _mutate_subscriptions(_reorder)
    if not ok:
        return jsonify({"error": "Subscription not found"}), 404
    return jsonify({"ok": True})
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

    threading.Thread(target=ensure_ffmpeg, daemon=True, name="ffmpeg-setup").start()
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
    threading.Thread(target=lambda: app.run(host=host, port=port, threaded=True, use_reloader=False),
                     daemon=True, name="flask").start()
    print(f"[EGM Downloader] running on http://{host}:{port}")
    try: threading.Event().wait()
    except KeyboardInterrupt: pass
