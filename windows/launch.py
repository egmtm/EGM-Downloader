"""EGM Downloader — launcher (no console window)"""
import os, sys, subprocess
from pathlib import Path

# ── Python version gate ───────────────────────────────────────────────────────
# This guards the interpreter that is *running this script*. Installer: the system
# Python, which also runs the app, so it has to be one yt-dlp still supports (3.11 or
# newer; yt-dlp dropped 3.10). Portable: on the FIRST run that's the system Python used
# only to bootstrap (it then downloads a private embedded Python and runs everything on
# that), so 3.10 is still enough there; on warm runs the launcher re-enters via the
# embedded 3.12, which always passes. Fail fast with a clear native dialog instead of a
# confusing traceback. (Uses %-formatting + ctypes only, so it runs on old ones.)
_PY_MIN = (3, 10) if (Path(__file__).resolve().parent / ".portable").exists() else (3, 11)
if sys.version_info < _PY_MIN:
    _msg = ("EGM Downloader needs Python %d.%d or newer.\n\n"
            "Detected: Python %d.%d.%d\n\n"
            "Install Python %d.%d+ from https://python.org\n"
            "(tick \"Add Python to PATH\" during install), then relaunch."
            % (_PY_MIN[0], _PY_MIN[1], sys.version_info[0], sys.version_info[1],
               sys.version_info[2], _PY_MIN[0], _PY_MIN[1]))
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, _msg, "EGM Downloader", 0x10)  # MB_ICONERROR
    except Exception:
        sys.stderr.write(_msg + "\n")
    sys.exit(1)

# Re-exec under pythonw.exe (no console) if not already silent. This sits above the
# heavier imports below on purpose: the first interpreter only hands over to pythonw.exe,
# which imports everything again, so it should not load them first.
if sys.platform == "win32" and not os.environ.get("EGM_SILENT"):
    pw = Path(sys.executable).with_name("pythonw.exe")
    if pw.exists():
        subprocess.Popen([str(pw), str(__file__)] + sys.argv[1:],
                         env={**os.environ, "EGM_SILENT":"1"})
        sys.exit(0)

import shutil, zipfile, urllib.request, urllib.parse, urllib.error, json, time, hashlib, re
import errno, http.client
import socket, threading

ROOT         = Path(__file__).parent.resolve()
NODE_DIR     = ROOT / "node_bin"
ELECTRON_DIR = ROOT / "electron"
NODE_MIN     = (22, 12, 0)  # minimum Node.js version (Electron's installer, @electron/get 5, needs 22.12+)
NODE_VERSION = "24.22.0"    # version to download if not found / outdated (Node 24 LTS)
NODE_ZIP_NAME = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_ZIP_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ZIP_NAME}"
# PINNED SHA-256 of the exact zip above, keyed by the Node version it was taken from
# (same fail-closed model as PY_SHA256 and PIP_SHA256). The pin ships inside the signed
# installer, so the node.exe that ends up running Electron (and our whole app) is checked
# against a hash nobody can swap on the way, and no manifest is fetched at run time.
# To bump NODE_VERSION: copy the win-x64.zip line of
# https://nodejs.org/dist/v<version>/SHASUMS256.txt into this table, in the same commit.
# Then check it against nodejs.org (a mistyped pin is not caught by the tests):
#   python3 scripts/check-node-pin.py --download
NODE_ZIP_SHA256 = {
    "24.22.0": "f9683a19877e12a9b167305c8db71040d812876359de21f0d2e97c3f321f80c3",
}
NODE_ZIP_DIR = f"node-v{NODE_VERSION}-win-x64"
NODE_EXE     = NODE_DIR / "node.exe"
NO_WIN       = 0x08000000 if sys.platform == "win32" else 0

# ── Embedded Python (PORTABLE edition only) ───────────────────────────────────
# The portable edition runs the app on its OWN private Python, downloaded +
# SHA-256-verified + cached on first run exactly like Node.js, so it can never
# share site-packages with (or depend on) a system/installer Python — that was
# the cause of the yt-dlp cross-contamination. main.js's findPython() already
# prefers <app>/python/python.exe, so app.py runs on this interpreter too.
#
# IMPORTANT: this is gated to portable (see _is_portable()). The INSTALLER
# edition is left completely untouched — it must NOT create a runtime python/
# dir, because the uninstaller doesn't know about it (it isn't in the install
# manifest), so a stale copy would survive uninstall and break the next install's
# findPython(). Installer keeps using the system Python via sys.executable.
PY_DIR        = ROOT / "python"
PY_EXE        = PY_DIR / "python.exe"
PY_VERSION    = "3.12.10"   # embeddable build to download (cp312 wheels on PyPI)
PY_ZIP_NAME   = f"python-{PY_VERSION}-embed-amd64.zip"
PY_ZIP_URL    = f"https://www.python.org/ftp/python/{PY_VERSION}/{PY_ZIP_NAME}"
# python.org has no machine-readable SHASUMS file for the embed zips, so the hash
# is PINNED (same fail-closed model as the rcedit hash). It MUST be set to the
# real SHA-256 of the exact zip above before building a portable — compute with:
#   certutil -hash python-3.12.10-embed-amd64.zip SHA256   (Windows)
#   sha256sum  python-3.12.10-embed-amd64.zip              (Linux/Mac)
PY_SHA256     = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"
# pip is set up from a PINNED wheel, so no downloaded script is ever run unverified
# (same fail-closed model as PY_SHA256). To bump: take the newest pip that supports
# PY_VERSION, and copy the py3-none-any.whl URL and sha256 from
# https://pypi.org/pypi/pip/<version>/json. Bump it together with PY_VERSION/PY_SHA256.
PIP_VERSION    = "26.2.1"
PIP_WHEEL_NAME = f"pip-{PIP_VERSION}-py3-none-any.whl"   # pip rejects a non-wheel file name
PIP_WHEEL_URL  = "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl"
PIP_SHA256     = "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e"
# How the wheel installs itself. On Windows pip refuses to modify pip when its
# sys.argv[0] is named "pip" ("To modify pip, please run python -m pip ..."), which is
# what `python <wheel>\pip install` gives it. `python -c` makes argv[0] "-c", so the
# guard stays quiet; argv[1] is the wheel, which goes on sys.path so pip imports from it.
PIP_BOOTSTRAP_CODE = ("import sys; sys.path.insert(0, sys.argv[1]); "
                      "from pip._internal.cli.main import main; sys.exit(main(sys.argv[2:]))")
# Setup diagnostics land here (next to the launcher) so a failed first-run pip
# bootstrap is debuggable instead of silent. Survives a PY_DIR wipe/retry.
PY_SETUP_LOG  = ROOT / "embedded-python-setup.log"


def _is_portable():
    """True only for the portable edition (BUILD.sh drops a .portable marker)."""
    return (ROOT / ".portable").exists()


def _hidden(path):
    """True when `path` already carries the Windows hidden attribute, so `attrib +h` would
    change nothing. False on any doubt (no attribute support, unreadable path), so the
    caller runs attrib exactly as before."""
    try:
        import stat
        return bool(os.stat(path).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
    except (AttributeError, OSError):
        return False


def _py_log(msg):
    """Append a timestamped diagnostic line; best-effort, never raises."""
    try:
        with open(PY_SETUP_LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


def _verify_node_zip(zip_path):
    """Return True iff zip_path's SHA-256 equals the pinned NODE_ZIP_SHA256 for NODE_VERSION.
    Fail-closed: no pin for this version, a malformed pin, an unreadable file or any
    mismatch returns False. Nothing is fetched."""
    expected = (NODE_ZIP_SHA256.get(NODE_VERSION) or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return False
    try:
        return _sha256_file(zip_path) == expected
    except Exception:
        return False

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
# Minimum versions of the packages whose old copies matter. An install whose imports already
# work is never touched by the sentinels below, so without these floors it would keep an old
# copy for good. Keep in sync with requirements.txt and the two pip lists (a test compares
# them): yt-dlp 2026.10.21 has the reworked Kick extractor, brotli 1.2.1 fixes CVE-2026-111497.
PY_DEP_FLOORS = {"yt-dlp": (2026, 10, 21), "brotli": (1, 2, 1)}

def _version_tuple(s):
    try: return tuple(int(p) for p in str(s).split(".")[:3])
    except ValueError: return None

def _deps_below_floor(read):
    """True when an installed floor package is older than its floor. read(name) returns the
    installed version tuple, or None when unknown (unknown is not 'below': the sentinels
    already cover a missing package)."""
    return any((read(n) or f) < f for n, f in PY_DEP_FLOORS.items())

def _meta_version(name):
    try:
        import importlib.metadata
        return _version_tuple(importlib.metadata.version(name))
    except Exception: return None

_DEP_MODULES = ("flask", "yt_dlp", "cryptography", "mutagen", "curl_cffi", "brotli", "Cryptodome", "websockets", "certifi")

def _modules_present(names):
    """True when every module can be found on disk. find_spec looks, it does not import."""
    try:
        import importlib.util
        return all(importlib.util.find_spec(n) for n in names)
    except (ImportError, ValueError): return False

def _pip_install(cmd, upgrading, timeout):
    """Run pip. A missing package is fatal, but a failed floor upgrade (offline, say) must not
    stop the start: the app runs on the old copy and the next launch tries again."""
    if upgrading: cmd = cmd + ["--retries", "1", "--timeout", "15"]
    try:
        subprocess.run(cmd, check=not upgrading, timeout=timeout, creationflags=NO_WIN)
    except (subprocess.SubprocessError, OSError):
        if not upgrading: raise

def ensure_python_deps():
    # Keep this list in sync with requirements.txt. cryptography is REQUIRED for
    # signed-manifest verification (Windows auto-update); mutagen for audio
    # metadata/thumbnail embedding. The sentinel imports must include them so a
    # missing one triggers (re)install. (pyzipper was unused and is dropped.)
    # Floors first, from package metadata, before anything is imported: importing brotli or
    # curl_cffi maps their .pyd/.dll files into this process, and Windows will not let pip
    # replace a file that is in use. Only when every package is there: a missing one must
    # stay fatal, which is the sentinel route below (same rule as the portable path).
    upgrading = _deps_below_floor(_meta_version) and _modules_present(_DEP_MODULES)
    if not upgrading:
        try:
            import flask, yt_dlp, cryptography, mutagen, curl_cffi, brotli, Cryptodome, websockets, certifi; return
        except ImportError: pass
    _gui_msg("Installing Python packages…")
    _pip_install([sys.executable, "-m", "pip", "install", "-q",
                  "flask", "yt-dlp>=2026.10.21", "bgutil-ytdlp-pot-provider", "mutagen", "cryptography", "curl_cffi<0.17.0", "brotli>=1.2.1", "pycryptodomex", "websockets", "certifi"],
                 upgrading, 300)

# ── Embedded Python (portable only) ───────────────────────────────────────────
def _verify_sha256(path, pin, label):
    """Return True iff path's SHA-256 matches the pinned hex digest `pin`.
    Fail-closed: an unset/invalid pin, an unreadable file or any mismatch returns
    False, so we never run anything unverified."""
    expected = (pin or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        _py_log(f"{label}: pinned SHA-256 is unset/invalid — refusing to use the download (fail-closed)")
        return False
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest().lower() == expected:
            return True
        _py_log(f"{label}: checksum mismatch")
        return False
    except Exception as e:
        _py_log(f"{label}: checksum read failed: {e}")
        return False


def _verify_py_zip(zip_path):
    """Return True iff zip_path matches the pinned PY_SHA256 (fail-closed)."""
    return _verify_sha256(zip_path, PY_SHA256, "Python zip")


def _py_version(exe):
    try:
        r = subprocess.run([str(exe), "-c", "import sys;print('%d.%d.%d'%sys.version_info[:3])"],
                           capture_output=True, text=True, timeout=10, creationflags=NO_WIN)
        if r.returncode == 0 and r.stdout.strip():
            return tuple(int(x) for x in r.stdout.strip().split("."))
    except Exception:
        pass
    return (0, 0, 0)


def _setup_embedded_pip():
    """Make pip usable in the embedded Python: (1) enable `import site` and add
    Lib\\site-packages in the pythonNNN._pth so installed packages are importable,
    (2) set up pip from the pinned wheel (downloaded, SHA-256 verified, then run
    to install itself). Returns True on success; logs the real error to
    PY_SETUP_LOG on any failure (so "could not enable pip" is debuggable)."""
    try:
        # (1) ._pth: uncomment `import site`, ensure Lib\site-packages is present.
        pths = list(PY_DIR.glob("python*._pth"))
        if not pths:
            _py_log("no python*._pth file in the extracted embeddable package")
            return False
        pth = pths[0]
        out, has_site, has_sp = [], False, False
        for ln in pth.read_text(encoding="utf-8", errors="replace").splitlines():
            t = ln.strip()
            if t in ("#import site", "# import site", "import site"):
                out.append("import site"); has_site = True
            else:
                out.append(ln)
                if t.lower() in ("lib\\site-packages", "lib/site-packages"):
                    has_sp = True
        if not has_sp:
            out.append("Lib\\site-packages")
        if not has_site:
            out.append("import site")
        pth.write_text("\n".join(out) + "\n", encoding="utf-8")
        (PY_DIR / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)

        # (2) Pinned pip wheel: download, verify (fail-closed), then run pip from
        # inside the wheel with the embedded interpreter to install itself (see
        # PIP_BOOTSTRAP_CODE). Nothing is executed before the SHA-256 check passes.
        _gui_msg("Setting up pip…")
        wheel = PY_DIR / PIP_WHEEL_NAME
        try:
            urllib.request.urlretrieve(PIP_WHEEL_URL, wheel)
        except Exception as e:
            _py_log(f"pip wheel download failed from {PIP_WHEEL_URL}: {e}")
            return False
        if not _verify_sha256(wheel, PIP_SHA256, "pip wheel"):
            try: wheel.unlink(missing_ok=True)
            except Exception: pass
            return False
        r = subprocess.run([str(PY_EXE), "-c", PIP_BOOTSTRAP_CODE, str(wheel), "install",
                            "--no-index", "--no-warn-script-location", str(wheel)],
                           capture_output=True, text=True, timeout=300, creationflags=NO_WIN)
        if r.returncode != 0:
            _py_log("pip wheel install failed (rc=%s)\nSTDOUT:\n%s\nSTDERR:\n%s"
                    % (r.returncode, (r.stdout or "")[-2000:], (r.stderr or "")[-2000:]))
            return False
        chk = subprocess.run([str(PY_EXE), "-m", "pip", "--version"],
                             capture_output=True, text=True, timeout=60, creationflags=NO_WIN)
        if chk.returncode != 0:
            _py_log("pip --version failed after bootstrap (rc=%s)\nSTDOUT:\n%s\nSTDERR:\n%s"
                    % (chk.returncode, (chk.stdout or ""), (chk.stderr or "")))
            return False
        try: wheel.unlink(missing_ok=True)
        except Exception: pass
        return True
    except Exception as e:
        _py_log(f"_setup_embedded_pip exception: {e}")
        return False


def ensure_python():
    """Ensure the portable's embedded Python exists (download → verify → extract →
    enable pip), cached across runs like ensure_node(). Returns the python.exe path
    str, or None on failure (caller shows an error)."""
    # Fast path: a good cached interpreter.
    if PY_EXE.exists() and _py_version(PY_EXE) >= _PY_MIN:
        return str(PY_EXE)
    if PY_DIR.exists():
        _gui_msg("Updating bundled Python…")           # present but broken/old — rebuild
        try: shutil.rmtree(PY_DIR, ignore_errors=True)
        except Exception: pass

    _gui_msg(f"Downloading Python {PY_VERSION}…")
    PY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PY_DIR / "py_tmp.zip"
    try:
        urllib.request.urlretrieve(PY_ZIP_URL, tmp, reporthook=_progress)
        _gui_msg("Verifying Python download…")
        if not _verify_py_zip(tmp):
            _gui_msg("ERROR: Python checksum verification failed")
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            time.sleep(4); return None
        _gui_msg("Extracting Python…")
        # The embeddable zip extracts flat (no top-level folder). Zip-slip guarded.
        with zipfile.ZipFile(tmp, "r") as z:
            for m in z.namelist():
                rel = m.lstrip("/\\")
                if not rel or ".." in Path(rel).parts or Path(rel).is_absolute():
                    continue
                dest = PY_DIR / rel
                try: dest.resolve().relative_to(PY_DIR.resolve())
                except ValueError: continue
                if m.endswith("/"):
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(m) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        tmp.unlink(missing_ok=True)
        if not PY_EXE.exists():
            _py_log("python.exe missing after extract"); _gui_msg("ERROR: Python extract failed")
            time.sleep(4); return None
        if not _setup_embedded_pip():
            _gui_msg("ERROR: could not enable pip (see embedded-python-setup.log)")
            time.sleep(4); return None
        if _py_version(PY_EXE) < _PY_MIN:
            _py_log("embedded Python older than required"); _gui_msg("ERROR: bundled Python too old")
            time.sleep(4); return None
        return str(PY_EXE)
    except Exception as e:
        _py_log(f"ensure_python exception: {e}")
        _gui_msg(f"ERROR: {e}")
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        time.sleep(4); return None


def ensure_python_deps_embedded(py_exe):
    """Install the app's deps into the EMBEDDED interpreter's own site-packages
    (isolated from any system/installer Python).

    The sentinel is a FILESYSTEM check of the embedded Lib\\site-packages — NOT a
    subprocess `import`. The embeddable's ._pth has `import site` enabled (pip needs
    it, and it's what makes Lib\\site-packages importable), and with site active even
    `-I`/`-E`/`-s` don't reliably hide a system-installed copy — so an import sentinel
    can PASS against the system's yt_dlp, pip then gets skipped, and the embedded
    interpreter never receives its own copy (the exact bug we hit). Checking the
    package directories on disk is unambiguous: it's true only when the packages live
    in OUR site-packages, and is unsatisfiable by anything on the system. (The ._pth +
    `import site` setup is left intact — only this check changes; pip still installs
    into the embedded interpreter exactly as before.)
    """
    site_packages = PY_DIR / "Lib" / "site-packages"
    # Top-level names pip drops in site-packages. NB import name, not pip name:
    # the "yt-dlp" distribution installs the "yt_dlp" package directory. Most are
    # package DIRS, but some ship as a single top-level MODULE file instead — e.g.
    # "brotli" installs brotli.py (+ a _brotli extension), not a brotli/ dir — so a
    # dir-only check would never pass for it and pip would re-run on every launch.
    required = ("flask", "yt_dlp", "cryptography", "mutagen", "curl_cffi", "brotli", "Cryptodome", "websockets", "certifi")
    def _present(pkg):
        return ((site_packages / pkg).is_dir()
                or (site_packages / f"{pkg}.py").is_file()
                or bool(list(site_packages.glob(f"{pkg}.*.pyd")))
                or bool(list(site_packages.glob(f"{pkg}.*.so"))))
    def _dist_version(name):
        # Same on-disk logic as _present: read the dist-info folder names, never import.
        norm = name.replace("-", "_").lower()
        found = [_version_tuple(d.name[len(norm) + 1:-len(".dist-info")]) for d in site_packages.iterdir()
                 if d.name.lower().startswith(norm + "-") and d.name.endswith(".dist-info")]
        return max([v for v in found if v], default=None)
    upgrading = False
    if site_packages.is_dir() and all(_present(pkg) for pkg in required):
        if not _deps_below_floor(_dist_version): return
        upgrading = True   # everything is there, but a floor package is old
    _gui_msg("Installing Python packages…")
    _pip_install([str(py_exe), "-m", "pip", "install", "-q", "--no-warn-script-location",
                  "flask", "yt-dlp>=2026.10.21", "bgutil-ytdlp-pot-provider", "mutagen", "cryptography", "curl_cffi<0.17.0", "brotli>=1.2.1", "pycryptodomex", "websockets", "certifi"],
                 upgrading, 600)

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
    except (urllib.error.URLError, ConnectionError, TimeoutError, http.client.HTTPException):
        # Offline, a failed name lookup, a timeout or a connection that dropped in the middle
        # of the download. Nothing is kept (no node.exe, no partial zip), so the next start
        # simply tries again. Say what to do instead of showing the raw network error.
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        _gui_msg("Node.js could not be downloaded. Check your internet connection "
                 "and start EGM Downloader again.")
        time.sleep(8); sys.exit(1)
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

def _ver_key(v):
    """Sortable key for an Electron version such as 44.7.2 or 45.0.0-beta.3;
    None when it is not that shape."""
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?", str(v).strip())
    if not m:
        return None
    stage = {"alpha": 0, "beta": 1, "rc": 2}.get(m.group(4), 3)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), stage, int(m.group(5) or 0))

def _electron_install_complete(mod):
    """True when `mod` (node_modules\\electron) holds a runnable binary AND the
    path.txt that Electron's own installer writes LAST, after unpacking the zip. A
    first install that was killed, or cut off on a slow link, leaves a package.json
    without these. The launcher renames electron.exe after its first launch, so
    either name counts."""
    dist = mod / "dist"
    return ((dist / "electron.exe").exists() or (dist / "EGM Downloader.exe").exists()) \
        and (mod / "path.txt").exists()

_LAUNCH_LOCK = None   # held for the life of this launcher (the OS drops it on exit, also on a crash)

def _take_launcher_lock():
    """False when another launcher is already setting up. _signal_running_instance()
    only sees a running app (Flask answers once Electron is up), not a launcher that is
    still installing or updating Electron: a second double click would then delete the
    install or the update folder the first one is filling."""
    global _LAUNCH_LOCK
    try:
        ELECTRON_DIR.mkdir(parents=True, exist_ok=True)
        fh = open(ELECTRON_DIR / ".launcher.lock", "a+b")
    except OSError:
        return True   # no lock file at all: never block the start over it
    try:
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        fh.close()
        # Only "someone else holds it" means another launcher. Any other failure (a share or a
        # redirected folder that cannot lock files) must not keep the app from ever starting.
        return e.errno not in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK)
    _LAUNCH_LOCK = fh
    return True

def _electron_update_kind():
    """What the installed Electron needs: None (nothing), "missing" (not installed,
    or its install never finished: no binary or no path.txt),
    "major" (its major differs from package.json: the app needs the new one) or
    "update" (same major but older than the version the shipped package-lock.json
    pins, e.g. 44.7.1 against 44.7.2). Never "update" for a newer one, so a
    fallback `npm install` that landed on a newer release cannot cause a loop."""
    installed_pkg = ELECTRON_DIR / "node_modules" / "electron" / "package.json"
    if not installed_pkg.exists() or not _electron_install_complete(installed_pkg.parent):
        return "missing"
    try:
        installed = json.loads(installed_pkg.read_text(encoding="utf-8"))["version"]
        declared  = json.loads((ELECTRON_DIR / "package.json").read_text(encoding="utf-8"))
        spec = (declared.get("dependencies", {}).get("electron")
                or declared.get("devDependencies", {}).get("electron")
                or "")
        if int(installed.split(".")[0]) != int(spec.lstrip("^~ ").split(".")[0]):
            return "major"
        lock = json.loads((ELECTRON_DIR / "package-lock.json").read_text(encoding="utf-8"))
        have = _ver_key(installed)
        want = _ver_key(lock["packages"]["node_modules/electron"]["version"])
        if have and want and have < want:
            return "update"
    except Exception:
        pass   # on any parse error, don't force a reinstall: let the install proceed
    return None

# An Electron update needs two hosts: the npm registry (the package) and GitHub (the
# binary). A TCP connect does not prove GitHub's download servers work; it only catches
# the plain "blocked" case, which is the one worth skipping an optional update for.
_UPDATE_HOSTS = ("registry.npmjs.org", "github.com")

def _update_hosts_reachable(timeout=6, targets=None):
    """True when every (host, port) an Electron install needs accepts a connection within
    `timeout` seconds (default: _update_targets()). Each is tried in its own thread (all
    together, one shared wait) because a name lookup can't be time limited directly, and
    a PC that is offline can sit in it for minutes (npm then looks stuck)."""
    targets = list(_update_targets() if targets is None else targets)
    ok = set()
    def probe(target):
        try:
            socket.create_connection(target, timeout=timeout).close()
            ok.add(target)
        except Exception:
            pass
    threads = [threading.Thread(target=probe, args=(t,), daemon=True) for t in targets]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout + 1
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return all(t in ok for t in targets)

_PROXY_VARS = ("npm_config_https_proxy", "npm_config_proxy", "HTTPS_PROXY", "https_proxy")   # npm's order

def _proxy_configured():
    """True when the environment names a proxy (npm then goes through it)."""
    return any(os.environ.get(n) for n in _PROXY_VARS)

def _proxy_endpoint():
    """(host, port) of the proxy npm will use, or None when none is set or it cannot be read."""
    for n in _PROXY_VARS:
        v = (os.environ.get(n) or "").strip()
        if v:
            try:   # urlparse itself raises on a broken IPv6 literal ("http://[::1"), .port on a bad port
                u = urllib.parse.urlparse(v if "://" in v else "http://" + v)
                port = u.port
            except ValueError:
                return None
            return (u.hostname, port or (443 if u.scheme == "https" else 80)) if u.hostname else None
    return None

def _update_targets():
    """Where an Electron install connects. npm fetches the package from the registry, or
    through the proxy when one is set. Electron's install.js fetches the binary from
    GitHub DIRECTLY even then: @electron/get only uses a proxy when ELECTRON_GET_USE_PROXY
    is set, and Node's own fetch ignores HTTPS_PROXY. So behind a proxy the proxy itself is
    checked (a dead one stalled every start), and GitHub stays in the list either way."""
    github = ("github.com", 443)
    if not _proxy_configured():
        return [("registry.npmjs.org", 443), github]
    proxy = _proxy_endpoint()
    hops = [proxy] if proxy else []
    return hops if os.environ.get("ELECTRON_GET_USE_PROXY") else hops + [github]

def _npm_env(node_exe):
    return _find_npm(node_exe), {**os.environ, "PATH": str(NODE_DIR) + os.pathsep + os.environ.get("PATH","")}

def _npm_output(r):
    """What a finished npm run printed, as text (bytes on a real run)."""
    return "\n".join(x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or "")
                     for x in (r.stdout, r.stderr))

def _npm_install_electron(node_exe, where):
    """Install Electron (and fetch its binary) into where/node_modules, using the
    package.json and package-lock.json in `where`. True iff the binary is there."""
    npm, env = _npm_env(node_exe)
    # Prefer `npm ci` for deterministic installs straight from package-lock.json
    # (we now ship the lockfile). `ci` requires a lockfile that is in sync with
    # package.json; when it is not, npm reports EUSAGE and `install` is the way out.
    # Any other failure (offline, a bad download) would fail the same way again after
    # the same wait, so it is not retried and the lockfile message is not shown.
    if (where / "package-lock.json").exists():
        r = subprocess.run(npm + ["ci", "--omit=dev"], cwd=str(where), env=env,
                           capture_output=True, timeout=600, creationflags=NO_WIN)
        if r.returncode != 0 and "EUSAGE" in _npm_output(r):
            _gui_msg("Lockfile out of sync — falling back to npm install…")
            r = subprocess.run(npm + ["install", "--omit=dev"], cwd=str(where), env=env,
                               capture_output=True, timeout=600, creationflags=NO_WIN)
    else:
        r = subprocess.run(npm + ["install", "--omit=dev"], cwd=str(where), env=env,
                           capture_output=True, timeout=600, creationflags=NO_WIN)
    if r.returncode != 0:
        return False
    # Electron 42+ removed the postinstall auto-download of the binary.
    # Explicitly run install.js to download it if missing. Idempotent —
    # install.js exits immediately if the binary already exists (Electron 41).
    mod = where / "node_modules" / "electron"
    electron_exe = mod / "dist" / "electron.exe"
    electron_renamed = mod / "dist" / "EGM Downloader.exe"
    install_js = mod / "install.js"
    if not electron_exe.exists() and not electron_renamed.exists() and install_js.exists():
        _gui_msg("Downloading Electron runtime…")
        subprocess.run([node_exe, str(install_js)], cwd=str(mod),
                       env=env, capture_output=True, timeout=300, creationflags=NO_WIN)
    return _electron_install_complete(mod)

def _swap_electron(new_nm):
    """Put new_nm in place of the live node_modules. The old one is kept as
    node_modules.old until the new one is in place, and put back if the swap fails."""
    nm = ELECTRON_DIR / "node_modules"
    old = ELECTRON_DIR / "node_modules.old"
    try:
        os.replace(nm, old)
    except Exception:
        return False
    try:
        os.replace(new_nm, nm)
    except Exception:
        try: os.replace(old, nm)
        except Exception: pass
        return False
    shutil.rmtree(old, ignore_errors=True)
    return True

def ensure_npm(node_exe, force=False):
    """Make sure Electron is installed and current. A first install goes straight into
    electron\\node_modules. An existing install (new major, an older version than the
    shipped lockfile, or force=True from Advanced > Reinstall Electron) is rebuilt
    NEXT TO the live one and swapped in only when it works, so a failed or offline
    download never leaves the app without Electron."""
    nm  = ELECTRON_DIR / "node_modules"
    old = ELECTRON_DIR / "node_modules.old"
    if old.exists():
        # An earlier run stopped in the middle of a swap: put the previous Electron
        # back, or drop the leftover when the live one is intact.
        if (nm / "electron").exists():
            shutil.rmtree(old, ignore_errors=True)
        else:
            shutil.rmtree(nm, ignore_errors=True)
            try: os.replace(old, nm)
            except Exception: pass
    # A launcher stopped while npm was filling the stage leaves up to ~250 MB there.
    # Clear it on every start, before any early return (offline, nothing to update).
    shutil.rmtree(ELECTRON_DIR / ".electron-stage", ignore_errors=True)
    kind = _electron_update_kind()
    if kind is None and force:
        kind = "update"
    if kind is None:
        return
    if kind == "missing":
        # Fresh install (or a damaged node_modules): nothing to keep. Offline, npm would
        # sit in name lookups for minutes and then fail: say so at once instead.
        if not _update_hosts_reachable():
            _gui_msg("Electron is not installed yet and its download servers cannot be reached. "
                     "Connect to the internet and start EGM Downloader again.")
            time.sleep(8); sys.exit(1)
        shutil.rmtree(nm, ignore_errors=True)
        _gui_msg("Installing Electron (first run, ~150 MB)…")
        if not _npm_install_electron(node_exe, ELECTRON_DIR):
            _gui_msg("Electron install failed"); time.sleep(4); sys.exit(1)
    else:
        if kind == "update" and not force and not _update_hosts_reachable():
            # Offline, GitHub blocked or the proxy down: keep the current Electron without
            # starting npm (which can look stuck for minutes). Nothing is shown; the next
            # launch that can reach them tries again.
            return
        _gui_msg("Updating Electron to new major version…" if kind == "major"
                 else "Updating Electron…")
        stage = ELECTRON_DIR / ".electron-stage"
        shutil.rmtree(stage, ignore_errors=True)
        ok = False
        try:
            stage.mkdir()
            for name in ("package.json", "package-lock.json"):
                if (ELECTRON_DIR / name).exists():
                    shutil.copy2(ELECTRON_DIR / name, stage / name)
            ok = _npm_install_electron(node_exe, stage) and _swap_electron(stage / "node_modules")
        except Exception:
            ok = False
        shutil.rmtree(stage, ignore_errors=True)
        if not ok:
            if kind == "major":
                # The new app needs the new Electron. The old one is still in place,
                # so the next launch simply tries again. Blame the connection only when
                # the download servers really cannot be reached now: a full disk or an
                # antivirus holding the files fails the same way with the network fine.
                if not _update_hosts_reachable():
                    _gui_msg("Electron update failed. Check your internet connection and "
                             "start EGM Downloader again.")
                else:
                    _gui_msg("Electron update failed. Make sure there is enough free disk space "
                             "and that no other program (such as an antivirus) is blocking the "
                             "EGM Downloader folder, then start EGM Downloader again.")
                time.sleep(8); sys.exit(1)
            _gui_msg("Could not update Electron, keeping the current version")
            time.sleep(3)
            return
    # Cleanup: remove non-English Electron locales (~15 MB saved)
    _clean_electron_locales()
    # Clear npm's global download cache (~50-200 MB) — not needed after install
    _clear_npm_cache(*_npm_env(node_exe))

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
            ver = re.search(r'APP_VERSION\s*=\s*["\']([\d.]+)["\']', txt)
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
    # Brief pause lets Electron begin rendering before the Tkinter window goes
    # away — only relevant when the pre-splash was actually shown (first run /
    # installs). On a warm start there is no window, so exit immediately.
    if _root is not None:
        time.sleep(0.5)

# ── Main ─────────────────────────────────────────────────────────────────────
def _signal_running_instance():
    """Try to signal a running instance via Flask /api/show-window.
    Returns True if the app was already running (signal sent successfully).
    This check runs BEFORE any Tkinter GUI or Electron spawn — if the app is
    already running, we exit silently in milliseconds with no visible flash."""
    try:
        # A listening port completes the connect at once, while a closed one takes about 2 s to be
        # refused on Windows (the TCP stack retries the SYN), which would use up the whole 1 s limit
        # below on every cold start. Nothing listening within 250 ms means the app is not running.
        socket.create_connection(("127.0.0.1", 8899), timeout=0.25).close()
    except OSError:
        return False
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
    # If we are relaunching to reinstall Electron (Advanced -> Reinstall Electron
    # -> "Restart now"), the outgoing instance may still be shutting down. Skip the
    # already-running early-exit in that case, so a transient signal to the dying
    # instance can't abort the reinstall — the marker is processed below.
    _electron_marker = Path(__file__).parent / ".electron-update"
    _reinstalling_electron = _electron_marker.exists()

    # Check if the app is already running — if so, signal it to show and exit.
    # Must happen before _gui_init() so no Tkinter window ever flashes.
    if not _reinstalling_electron and _signal_running_instance():
        sys.exit(0)
    # Another launcher is still installing or updating Electron (the app is not up yet, so
    # the check above cannot see it): leave it alone, it opens the app when it is done.
    if not _take_launcher_lock():
        sys.exit(0)

    # No _gui_init() here — the progress window is created lazily by _gui_msg()
    # the first time setup work needs reporting. Warm starts show no window.
    if _is_portable():
        # Portable: run the app on a private, fully-isolated embedded Python.
        # The Python that starts the first run can hand the embedded one its own user packages folder
        # (seen with the Microsoft Store Python 3.12). pip would then count the app's packages there as
        # installed and leave this folder empty, and the app would run on the user's copies. The pip
        # steps, Electron and the backend all inherit this setting.
        os.environ["PYTHONNOUSERSITE"] = "1"
        py_exe = ensure_python()
        if not py_exe:
            _gui_msg("ERROR: could not set up the bundled Python runtime")
            time.sleep(5); sys.exit(1)
        ensure_python_deps_embedded(py_exe)
    else:
        # Installer: keep using the system Python (untouched legacy behavior).
        ensure_python_deps()
    node_exe = ensure_node()

    # Process the Electron reinstall marker (set by Advanced → Reinstall Electron).
    # ensure_npm builds the new Electron next to the live one and swaps it in only
    # when it works, so a failed download keeps the current one.
    if _reinstalling_electron:
        _gui_msg("Reinstalling Electron…")
        try: _electron_marker.unlink(missing_ok=True)
        except Exception: pass

    ensure_npm(node_exe, force=_reinstalling_electron)

    # In portable mode, hide internal files so users only see the launcher + instructions.
    # Done AFTER all installs complete so npm can access electron/ without any risk.
    _portable_marker = Path(__file__).parent / ".portable"
    if _portable_marker.exists():
        _to_hide = [
            "app.py", "launch.bat", "launch.py", ".portable", "rcedit-x64.exe",
            "electron", "static", "templates", "python",
            "data", "ffmpeg_bin", "node_bin", "runtime", "electron-data",
        ]
        for _name in _to_hide:
            _p = Path(__file__).parent / _name
            if _p.exists():
                if _hidden(_p):
                    continue   # already hidden (every start after the first): attrib would change nothing
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
