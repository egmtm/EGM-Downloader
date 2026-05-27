"""EGM Downloader — launcher (no console window)"""
import os, sys, shutil, zipfile, subprocess, urllib.request, json, time
from pathlib import Path

ROOT         = Path(__file__).parent.resolve()
NODE_DIR     = ROOT / "node_bin"
ELECTRON_DIR = ROOT / "electron"
NODE_MIN     = (18, 0, 0)   # minimum Node.js version
NODE_VERSION = "20.19.1"    # version to download if not found / outdated
NODE_ZIP_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}-win-x64.zip"
NODE_ZIP_DIR = f"node-v{NODE_VERSION}-win-x64"
NODE_EXE     = NODE_DIR / "node.exe"
NO_WIN       = 0x08000000 if sys.platform == "win32" else 0

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

def _gui_init(title="EGM Downloader"):
    global _root, _lbl
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
    try:
        import flask, yt_dlp, pyzipper; return
    except ImportError: pass
    _gui_msg("Installing Python packages…")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "flask", "yt-dlp", "bgutil-ytdlp-pot-provider", "pyzipper"],
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
        _gui_msg("Extracting Node.js…")
        with zipfile.ZipFile(tmp, "r") as z:
            for m in z.namelist():
                rel  = m[len(NODE_ZIP_DIR):].lstrip("/\\")
                if not rel: continue
                dest = NODE_DIR / rel
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
    r = subprocess.run(npm + ["install", "--omit=dev"], cwd=str(ELECTRON_DIR), env=env,
                       capture_output=True, timeout=600, creationflags=NO_WIN)
    if r.returncode != 0:
        _gui_msg("npm install failed"); time.sleep(4); sys.exit(1)
    # Electron 42+ removed the postinstall auto-download of the binary.
    # Explicitly run install.js to download it if missing. Idempotent —
    # install.js exits immediately if the binary already exists (Electron 41).
    electron_exe = ELECTRON_DIR / "node_modules" / "electron" / "dist" / "electron.exe"
    install_js   = ELECTRON_DIR / "node_modules" / "electron" / "install.js"
    if not electron_exe.exists() and install_js.exists():
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
    return ["npm"]

# ── Launch Electron ───────────────────────────────────────────────────────────
def launch_electron():
    exe = ELECTRON_DIR / "node_modules" / "electron" / "dist" / "electron.exe"
    if not exe.exists():
        _gui_msg("ERROR: electron.exe not found"); time.sleep(4); sys.exit(1)
    _gui_close()
    env = {**os.environ, "PATH": str(NODE_DIR) + os.pathsep + os.environ.get("PATH","")}
    subprocess.Popen(
        [str(exe), str(ELECTRON_DIR)], cwd=str(ELECTRON_DIR), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=NO_WIN,
    )
    # Don't wait — launcher exits immediately after spawning Electron,
    # removing the idle pythonw.exe process from the process list.

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

    _gui_init()

    # In portable mode, hide internal files so users only see the launcher + instructions
    _portable_marker = Path(__file__).parent / ".portable"
    if _portable_marker.exists():
        _to_hide = [
            "app.py", "launch.bat", "launch.py", ".portable",
            "electron", "static", "templates",
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

    ensure_python_deps()
    node_exe = ensure_node()
    ensure_npm(node_exe)
    _gui_msg("Launching...")
    launch_electron()
