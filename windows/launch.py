"""EGM Downloader — launcher (no console window)"""
import os, sys, shutil, zipfile, subprocess, urllib.request, json, time, hashlib, re
from pathlib import Path

ROOT         = Path(__file__).parent.resolve()
NODE_DIR     = ROOT / "node_bin"
ELECTRON_DIR = ROOT / "electron"
NODE_MIN     = (18, 0, 0)   # minimum Node.js version
NODE_VERSION = "20.19.1"    # version to download if not found / outdated
NODE_ZIP_NAME = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_ZIP_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ZIP_NAME}"
# Official per-release checksum manifest. We download this over TLS and match the
# zip's SHA-256 before extracting, so a tampered/corrupted mirror response can
# never produce the node.exe that ends up running Electron (and our whole app).
NODE_SHASUMS_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/SHASUMS256.txt"
NODE_ZIP_DIR = f"node-v{NODE_VERSION}-win-x64"
NODE_EXE     = NODE_DIR / "node.exe"
NO_WIN       = 0x08000000 if sys.platform == "win32" else 0


def _verify_node_zip(zip_path):
    """Return True if zip_path's SHA-256 matches the official SHASUMS256.txt entry.
    Fail-closed: any network/parse error or mismatch returns False."""
    try:
        with urllib.request.urlopen(NODE_SHASUMS_URL, timeout=30) as r:
            sums = r.read().decode("utf-8", "replace")
        expected = None
        for line in sums.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == NODE_ZIP_NAME:
                expected = parts[0].lower()
                break
        if not expected:
            return False
        h = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().lower() == expected
    except Exception:
        return False

# Re-exec under pythonw.exe (no console) if not already silent
if sys.platform == "win32" and not os.environ.get("EGM_SILENT"):
    pw = Path(sys.executable).with_name("pythonw.exe")
    if pw.exists():
        subprocess.Popen([str(pw), str(__file__)] + sys.argv[1:],
                         env={**os.environ, "EGM_SILENT":"1"})
        sys.exit(0)

# ── Tkinter GUI helpers ───────────────────────────────────────────────────────
_root = None
_lbl  = None
_gui_tried = False   # one-shot guard — a failed Tk init isn't retried per message

def _gui_init(title="EGM Downloader"):
    global _root, _lbl, _gui_tried
    _gui_tried = True
    try:
        import tkinter as tk
        _root = tk.Tk()
        _root.title(title)
        _root.configure(bg="#0d1421")
        _root.resizable(False, False)
        _root.attributes("-topmost", True)
        # Center
        w, h = 420, 120
        sw = _root.winfo_screenwidth(); sh = _root.winfo_screenheight()
        _root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        import tkinter.font as tkf
        tk.Label(_root, text="EGM Downloader", fg="#3b82f6", bg="#0d1421",
                 font=tkf.Font(family="Segoe UI", size=14, weight="bold")).pack(pady=(16,4))
        _lbl = tk.Label(_root, text="Starting…", fg="#94a3b8", bg="#0d1421",
                         font=tkf.Font(family="Segoe UI", size=9))
        _lbl.pack()
        _root.update()
    except Exception: pass

def _gui_msg(msg):
    # Lazy init: the window is only created the first time there is actual
    # progress to report (first-run installs, downloads, errors). A warm start
    # never calls this, so no pre-splash window flashes — launch goes straight
    # to the Electron splash, matching Mac/Linux.
    if _root is None and not _gui_tried:
        _gui_init()
    if _lbl:
        try: _lbl.config(text=msg); _root.update()
        except Exception: pass

def _gui_progress(pct):
    _gui_msg(f"Downloading… {pct}%")

def _gui_close():
    if _root:
        try: _root.destroy()
        except Exception: pass

def _progress(count, block, total):
    if total > 0: _gui_progress(min(100, count*block*100//total))

# ── Python deps ───────────────────────────────────────────────────────────────
def ensure_python_deps():
    # Keep this list in sync with requirements.txt. cryptography is REQUIRED for
    # signed-manifest verification (Windows auto-update); mutagen for audio
    # metadata/thumbnail embedding. The sentinel imports must include them so a
    # missing one triggers (re)install. (pyzipper was unused and is dropped.)
    try:
        import flask, yt_dlp, cryptography, mutagen; return
    except ImportError: pass
    _gui_msg("Installing Python packages…")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "flask", "yt-dlp", "bgutil-ytdlp-pot-provider", "mutagen", "cryptography"],
                   check=True, timeout=300, creationflags=NO_WIN)

# ── Node.js ───────────────────────────────────────────────────────────────────
VERSION_CACHE = NODE_DIR / ".node_version"   # persists detected node path across runs

def _node_version(exe):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                           timeout=10, creationflags=NO_WIN)
        if r.returncode == 0:
            v = r.stdout.strip().lstrip("v")
            parts = [int(x) for x in v.split(".")[:3]]
            return tuple(parts)
    except Exception: pass
    return (0,0,0)

def ensure_node():
    # Fast path: if cached node path exists and version matches, skip subprocess check
    if VERSION_CACHE.exists():
        try:
            cached = json.loads(VERSION_CACHE.read_text())
            exe    = cached.get("exe", "")
            ver    = tuple(cached.get("ver", [0,0,0]))
            if ver >= NODE_MIN and (exe in ("node","node.exe") or Path(exe).exists()):
                return exe
        except Exception: pass

    # Check system node
    for candidate in ["node", "node.exe"]:
        ver = _node_version(candidate)
        if ver >= NODE_MIN:
            try: VERSION_CACHE.write_text(json.dumps({"exe": candidate, "ver": list(ver)}))
            except Exception: pass
            return candidate
        if ver > (0,0,0):
            _gui_msg(f"Node.js {'.'.join(map(str,ver))} too old, updating…")
            break

    # Check portable node
    if NODE_EXE.exists():
        ver = _node_version(str(NODE_EXE))
        if ver >= NODE_MIN:
            try: VERSION_CACHE.write_text(json.dumps({"exe": str(NODE_EXE), "ver": list(ver)}))
            except Exception: pass
            return str(NODE_EXE)
        _gui_msg(f"Portable Node.js outdated, updating…")
        # Remove old to re-download
        try: shutil.rmtree(NODE_DIR, ignore_errors=True)
        except Exception: pass

    _gui_msg(f"Downloading Node.js {NODE_VERSION}…")
    NODE_DIR.mkdir(exist_ok=True)
    tmp = NODE_DIR / "node_tmp.zip"
    try:
        urllib.request.urlretrieve(NODE_ZIP_URL, tmp, reporthook=_progress)
        _gui_msg("Verifying Node.js download…")
        if not _verify_node_zip(tmp):
            _gui_msg("ERROR: Node.js checksum verification failed")
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            time.sleep(4); sys.exit(1)
        _gui_msg("Extracting Node.js…")
        with zipfile.ZipFile(tmp, "r") as z:
            for m in z.namelist():
                rel  = m[len(NODE_ZIP_DIR):].lstrip("/\\")
                if not rel: continue
                # Zip-slip guard: reject traversal / absolute paths, and confirm the
                # resolved destination stays inside NODE_DIR before writing.
                rel_path = Path(rel)
                if ".." in rel_path.parts or rel_path.is_absolute():
                    continue
                dest = NODE_DIR / rel
                try:
                    dest.resolve().relative_to(NODE_DIR.resolve())
                except ValueError:
                    continue
                if m.endswith("/"):
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as src, open(dest,"wb") as dst:
                        shutil.copyfileobj(src, dst)
        tmp.unlink(missing_ok=True)
        return str(NODE_EXE)
    except Exception as e:
        _gui_msg(f"ERROR: {e}")
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        time.sleep(4); sys.exit(1)

# ── npm packages ──────────────────────────────────────────────────────────────
def _clean_electron_locales():
    """Remove non-English locale .pak files from Electron dist (~15 MB saved)."""
    locales = ELECTRON_DIR / "node_modules" / "electron" / "dist" / "locales"
    if not locales.exists(): return
    keep = {"en-US.pak", "en-GB.pak"}
    for f in locales.iterdir():
        if f.suffix == ".pak" and f.name not in keep:
            try: f.unlink()
            except Exception: pass

def _clear_npm_cache(npm, env):
    """Clear npm's global download cache after first install (~50-200 MB freed)."""
    try:
        subprocess.run(npm + ["cache", "clean", "--force"], env=env,
                       capture_output=True, timeout=60, creationflags=NO_WIN)
    except Exception: pass

def _electron_needs_reinstall():
    """Return True if installed Electron major version doesn't match the major declared in package.json.
    Used to trigger a fresh install when we ship a new Electron major (e.g. 29 -> 41)."""
    installed_pkg = ELECTRON_DIR / "node_modules" / "electron" / "package.json"
    declared_pkg  = ELECTRON_DIR / "package.json"
    if not installed_pkg.exists():
        return True
    try:
        installed = json.loads(installed_pkg.read_text(encoding="utf-8"))
        declared  = json.loads(declared_pkg.read_text(encoding="utf-8"))
        installed_major = int(installed["version"].split(".")[0])
        spec = (declared.get("dependencies", {}).get("electron")
                or declared.get("devDependencies", {}).get("electron")
                or "")
        declared_major = int(spec.lstrip("^~ ").split(".")[0])
        return installed_major != declared_major
    except Exception:
        # On any parse error, don't force reinstall — let existing install proceed normally
        return False

def ensure_npm(node_exe):
    if (ELECTRON_DIR / "node_modules" / "electron").exists() and not _electron_needs_reinstall():
        return
    # Either fresh install, or Electron major version changed — wipe node_modules and reinstall
    nm = ELECTRON_DIR / "node_modules"
    if nm.exists():
        _gui_msg("Updating Electron to new major version…")
        shutil.rmtree(nm, ignore_errors=True)
    else:
        _gui_msg("Installing Electron (first run, ~250 MB)…")
    npm = _find_npm(node_exe)
    env = {**os.environ, "PATH": str(NODE_DIR) + os.pathsep + os.environ.get("PATH","")}
    # Prefer `npm ci` for deterministic installs straight from package-lock.json
    # (we now ship the lockfile). `ci` requires a lockfile that is present and in
    # sync; if it's missing/out-of-sync it errors, so fall back to `install`.
    lockfile = ELECTRON_DIR / "package-lock.json"
    if lockfile.exists():
        r = subprocess.run(npm + ["ci", "--omit=dev"], cwd=str(ELECTRON_DIR), env=env,
                           capture_output=True, timeout=600, creationflags=NO_WIN)
        if r.returncode != 0:
            _gui_msg("Lockfile out of sync — falling back to npm install…")
            r = subprocess.run(npm + ["install", "--omit=dev"], cwd=str(ELECTRON_DIR), env=env,
                               capture_output=True, timeout=600, creationflags=NO_WIN)
    else:
        r = subprocess.run(npm + ["install", "--omit=dev"], cwd=str(ELECTRON_DIR), env=env,
                           capture_output=True, timeout=600, creationflags=NO_WIN)
    if r.returncode != 0:
        _gui_msg("npm install failed"); time.sleep(4); sys.exit(1)
    # Electron 42+ removed the postinstall auto-download of the binary.
    # Explicitly run install.js to download it if missing. Idempotent —
    # install.js exits immediately if the binary already exists (Electron 41).
    electron_exe = ELECTRON_DIR / "node_modules" / "electron" / "dist" / "electron.exe"
    electron_renamed = ELECTRON_DIR / "node_modules" / "electron" / "dist" / "EGM Downloader.exe"
    install_js   = ELECTRON_DIR / "node_modules" / "electron" / "install.js"
    if not electron_exe.exists() and not electron_renamed.exists() and install_js.exists():
        _gui_msg("Downloading Electron runtime…")
        subprocess.run([node_exe, str(install_js)],
                       cwd=str(ELECTRON_DIR / "node_modules" / "electron"),
                       env=env, capture_output=True, timeout=300, creationflags=NO_WIN)
    # First-time cleanup: remove non-English Electron locales (~15 MB saved)
    _clean_electron_locales()
    # Clear npm's global download cache (~50-200 MB) — not needed after install
    _clear_npm_cache(npm, env)

def _find_npm(node_exe):
    for p in [NODE_DIR/"npm.cmd", NODE_DIR/"npm"]:
        if p.exists(): return [str(p)]
    js = NODE_DIR/"node_modules"/"npm"/"bin"/"npm-cli.js"
    if js.exists(): return [node_exe, str(js)]
    # System-wide Node: resolve npm.cmd via PATH (bare "npm" fails on Windows
    # because CreateProcess doesn't resolve .cmd extensions)
    which_npm = shutil.which("npm")
    if which_npm: return [which_npm]
    return ["npm"]

# ── Electron process naming (Task Manager) ────────────────────────────────────
# Renaming electron.exe only changes the *filename* (Task Manager → Details tab).
# The Processes tab shows the EXE's PE FileDescription resource, which still reads
# "Electron". rcedit (electron/rcedit, MIT) rewrites that resource. Because every
# Electron sub-process (main, GPU, renderer, utility, crashpad) runs from this one
# shared binary, stamping it once renames the whole tree in both views.
#
# rcedit is downloaded once at runtime (same model as Node/ffmpeg/Deno) and pinned
# + SHA-256 verified, fail-closed. The whole feature is cosmetic: any failure here
# just skips the rename and the app launches normally.
RCEDIT_VERSION = "2.0.0"
RCEDIT_URL     = f"https://github.com/electron/rcedit/releases/download/v{RCEDIT_VERSION}/rcedit-x64.exe"
RCEDIT_SHA256  = "3e7801db1a5edbec91b49a24a094aad776cb4515488ea5a4ca2289c400eade2a"
RCEDIT         = ROOT / "rcedit-x64.exe"

def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()

def _ensure_rcedit():
    """Return a path to a verified rcedit-x64.exe, or None. Downloads once and
    SHA-256-verifies against the pinned hash; fail-closed on any error/mismatch."""
    expected = (RCEDIT_SHA256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return None  # hash not configured → feature disabled, never guessed
    if RCEDIT.exists():
        # Trust a previously-verified copy; re-verify cheaply to catch corruption.
        try:
            if _sha256_file(RCEDIT) == expected:
                return RCEDIT
            RCEDIT.unlink(missing_ok=True)
        except Exception:
            return None
    tmp = ROOT / "rcedit_tmp.exe"
    try:
        _gui_msg("Setting up app identity…")
        urllib.request.urlretrieve(RCEDIT_URL, tmp)
        if _sha256_file(tmp) != expected:
            tmp.unlink(missing_ok=True)
            return None
        tmp.replace(RCEDIT)
        return RCEDIT
    except Exception:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        return None

def _icon_path():
    for p in (ROOT / "static" / "icon.ico", ROOT.parent / "static" / "icon.ico"):
        if p.exists():
            return p
    return None

def _app_version_tuple():
    """Best-effort APP_VERSION/APP_BUILD read from app.py for the version resource.
    Cosmetic numbers only — falls back to a static value if app.py isn't found."""
    for cand in (ROOT / "app.py", ROOT.parent / "app.py"):
        try:
            txt = cand.read_text(encoding="utf-8", errors="replace")
            ver = re.search(r'APP_VERSION\s*=\s*["\']([\\d.]+)["\']', txt)
            bld = re.search(r'APP_BUILD\s*=\s*(\d+)', txt)
            if ver:
                return ver.group(1), (bld.group(1) if bld else "0")
        except Exception:
            pass
    return "0.99.13", "121"

def _stamp_electron_metadata(exe_path):
    """Rewrite the Electron binary's version resource so all its processes show
    'EGM Downloader'. Idempotent via a version-keyed marker; only re-stamps when the
    version changes or Electron was reinstalled. The exe must be idle — always
    called BEFORE spawning Electron."""
    ver, bld = _app_version_tuple()
    stamp_id = f"{ver}.{bld}"
    marker = exe_path.with_suffix(".stamped")   # inside node_modules → reset on Electron reinstall
    try:
        if marker.exists() and marker.read_text(encoding="utf-8").strip() == stamp_id:
            return
    except Exception:
        pass
    rcedit = _ensure_rcedit()
    if not rcedit:
        return
    args = [str(rcedit), str(exe_path),
            "--set-version-string", "FileDescription",  "EGM Downloader",
            "--set-version-string", "ProductName",      "EGM Downloader",
            "--set-version-string", "CompanyName",      "egerena.com",
            "--set-version-string", "InternalName",     "EGM Downloader",
            "--set-version-string", "OriginalFilename", "EGM Downloader.exe",
            "--set-file-version",    stamp_id,
            "--set-product-version", ver]
    icon = _icon_path()
    if icon:
        args += ["--set-icon", str(icon)]
    try:
        r = subprocess.run(args, capture_output=True, timeout=60, creationflags=NO_WIN)
        if r.returncode == 0:
            marker.write_text(stamp_id, encoding="utf-8")
    except Exception:
        pass

# ── Launch Electron ───────────────────────────────────────────────────────────
def launch_electron():
    dist = ELECTRON_DIR / "node_modules" / "electron" / "dist"
    original = dist / "electron.exe"
    renamed  = dist / "EGM Downloader.exe"

    # Rename so Task Manager shows "EGM Downloader" instead of "electron"
    if original.exists() and not renamed.exists():
        try: original.rename(renamed)
        except Exception: pass

    exe = renamed if renamed.exists() else original
    if not exe.exists():
        _gui_msg("ERROR: electron.exe not found"); time.sleep(4); sys.exit(1)

    # Stamp the version resource (Processes-tab name) while the exe is still idle.
    _stamp_electron_metadata(exe)
    env = {**os.environ, "PATH": str(NODE_DIR) + os.pathsep + os.environ.get("PATH","")}
    subprocess.Popen(
        [str(exe), str(ELECTRON_DIR)], cwd=str(ELECTRON_DIR), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=NO_WIN,
    )
    # Brief pause lets Electron begin rendering before Python/Tkinter exits —
    # bridges the visual gap between the two windows (skip on warm starts
    # where no Tk window was shown)
    if _root is not None:
        time.sleep(0.5)

# ── Main ─────────────────────────────────────────────────────────────────────
def _signal_running_instance():
    """Try to signal a running instance via Flask /api/show-window.
    Returns True if the app was already running (signal sent successfully).
    This check runs BEFORE any Tkinter GUI or Electron spawn — if the app is
    already running, we exit silently in milliseconds with no visible flash."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:8899/api/show-window",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1) as r:
            return r.status == 200
    except Exception:
        return False

if __name__ == "__main__":
    # Check if the app is already running — if so, signal it to show and exit.
    # Must happen before _gui_init() so no Tkinter window ever flashes.
    if _signal_running_instance():
        sys.exit(0)

    ensure_python_deps()
    node_exe = ensure_node()

    # Check for Electron reinstall marker (set by Advanced → Reinstall Electron)
    _electron_marker = Path(__file__).parent / ".electron-update"
    if _electron_marker.exists():
        _gui_msg("Reinstalling Electron…")
        try: shutil.rmtree(ELECTRON_DIR / "node_modules", ignore_errors=True)
        except Exception: pass
        try: _electron_marker.unlink(missing_ok=True)
        except Exception: pass

    ensure_npm(node_exe)

    # In portable mode, hide internal files so users only see the launcher + instructions.
    # Done AFTER all installs complete so npm can access electron/ without any risk.
    _portable_marker = Path(__file__).parent / ".portable"
    if _portable_marker.exists():
        _to_hide = [
            "app.py", "launch.bat", "launch.py", ".portable", "rcedit-x64.exe",
            "electron", "static", "templates",
            "data", "ffmpeg_bin", "node_bin", "runtime", "electron-data",
        ]
        for _name in _to_hide:
            _p = Path(__file__).parent / _name
            if _p.exists():
                try:
                    subprocess.run(
                        ["attrib", "+h", str(_p)],
                        creationflags=0x08000000, check=False
                    )
                except Exception:
                    pass

    if _root is not None:
        _gui_msg("Launching...")
    launch_electron()
