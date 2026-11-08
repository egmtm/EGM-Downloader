#!/bin/bash
# EGM Downloader — Windows installer folder: Electron, Python and the Python packages in one folder.
# windows/BUILD.sh runs this in phase 1; it can also run alone: bash windows/installer/build-folder.sh
#
# Produces dist/win-unpacked:
#   EGM Downloader.exe      Electron (renamed, icon and version strings set), NOT signed yet
#   resources/app.asar      main.js, preload.js, splash.html
#   resources/app/          the app files listed in windows/app-files.txt
#   resources/python/       CPython (python-build-standalone) with the packages of
#                           windows/requirements-win-lock.txt
# ffmpeg and Deno are not bundled: the app downloads them on first launch, as on Mac and Linux.
#
# Runs on Linux or macOS, no Wine: no Windows program is started. Needs Node.js with npm, python3 with
# pip, curl and tar. Downloads: npm packages from windows/electron's lock, the Electron Windows zip
# (checked against the locked electron package), the pinned Python archive (checked against the pin
# and the release's SHA256SUMS) and the wheels of the hashed lock (pip --require-hashes).
#
# PRECOMPILE=1 also writes checked-hash .pyc files into the bundled Python (needs a CPython 3.11 on
# the build machine, HOST_PYTHON311, default python3.11). Default 0: Python writes its own
# __pycache__ under resources at runtime; the uninstaller removes resources as a whole.
#
# The exe is not signed here and electron-builder never runs after this script: the signed bytes go
# into the installer unchanged (see windows/BUILD.sh).

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WIN_DIR/.." && pwd)"
STAGE="$REPO_ROOT/dist/installer-stage"
OUT="$REPO_ROOT/dist/win-unpacked"
PRECOMPILE="${PRECOMPILE:-0}"
SHA256SUM="sha256sum"
command -v sha256sum &> /dev/null || SHA256SUM="shasum -a 256"

echo "📦 Building the installer folder (Electron + Python + packages)..."
for tool in node npm npx curl tar python3; do
    if ! command -v "$tool" &> /dev/null; then
        echo "❌ $tool not found (needed for the installer folder)"
        exit 1
    fi
done
if ! python3 -m pip --version &> /dev/null; then
    echo "❌ python3 has no pip (needed to fetch the Windows wheels)"
    exit 1
fi
VERSION=$(python3 -c "import json; print(json.load(open('$REPO_ROOT/version.json'))['version'])")
BUILD_NUM=$(python3 -c "import json; print(json.load(open('$REPO_ROOT/version.json'))['build'])")

rm -rf "$STAGE" "$OUT"
mkdir -p "$STAGE/electron" "$STAGE/app"

# ── App files (the same list the portable stage copies) ───────────────────────
while IFS= read -r f; do
    case "$f" in ''|'#'*) continue ;; esac
    mkdir -p "$STAGE/app/$(dirname "$f")"
    cp "$REPO_ROOT/$f" "$STAGE/app/$f"
done < "$WIN_DIR/app-files.txt"
echo "   ✓ App files: $(find "$STAGE/app" -type f | wc -l | tr -d ' ')"

# ── Python (python-build-standalone, Windows x64) ─────────────────────────────
PYTHON_DIR="$STAGE/python"
# Pinned: version, release and SHA-256 (from that release's SHA256SUMS). The same version and release
# as mac/BUILD.sh and linux/BUILD.sh, Windows install_only archive. (The portable edition's launch.py
# pins its own archive of that release, install_only_stripped; the two pins are separate.)
PYTHON_VERSION="3.11.18"
PYTHON_RELEASE="20261026"
PYTHON_SHA256="75cb501dc11c7b55c6b447c58e4910bce5b1f609f1017328b4f3a858dfaf5428"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-x86_64-pc-windows-msvc-install_only.tar.gz"
echo "🐍 Downloading Python ${PYTHON_VERSION} (${PYTHON_RELEASE}, Windows x64)..."
cd "$STAGE"
curl -L --progress-bar "$PYTHON_URL" -o python.tar.gz
echo "$PYTHON_SHA256  python.tar.gz" | $SHA256SUM -c - || { echo "   ✗ python.tar.gz does not match the pinned SHA-256"; rm -f python.tar.gz; exit 1; }
# The pin must also be the value the release itself publishes
curl -fsSL "https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/SHA256SUMS" -o SHA256SUMS
grep -qxF "$PYTHON_SHA256  ${PYTHON_URL##*/}" SHA256SUMS || { echo "   ✗ the pinned SHA-256 is not the one in the release's SHA256SUMS"; rm -f python.tar.gz; exit 1; }
mkdir -p "$PYTHON_DIR"
tar -xzf python.tar.gz -C "$PYTHON_DIR" --strip-components=1
rm -f python.tar.gz SHA256SUMS
echo "   ✓ Python unpacked"

# ── Strip what the app never uses ─────────────────────────────────────────────
# Same idea as mac/BUILD.sh and linux/BUILD.sh, plus the Windows-only debug symbols, Tcl/Tk, C headers
# and import libraries. pip and ensurepip stay: Update Plugins runs the bundled Python's pip, and pip
# needs its launcher stubs (pip/_vendor/distlib/*.exe) to replace packages that have console scripts.
SITE="$PYTHON_DIR/Lib/site-packages"
find "$PYTHON_DIR" -name "*.pdb" -delete
rm -rf "$PYTHON_DIR/tcl" "$PYTHON_DIR/include" "$PYTHON_DIR/libs"
rm -f "$PYTHON_DIR/DLLs/_tkinter.pyd" "$PYTHON_DIR/DLLs/tcl86t.dll" "$PYTHON_DIR/DLLs/tk86t.dll"
rm -f "$PYTHON_DIR"/DLLs/_test*.pyd "$PYTHON_DIR/DLLs/_ctypes_test.pyd"
rm -rf "$PYTHON_DIR/Lib/idlelib" "$PYTHON_DIR/Lib/tkinter" "$PYTHON_DIR/Lib/turtledemo" "$PYTHON_DIR/Lib/lib2to3" "$PYTHON_DIR/Lib/turtle.py"
rm -rf "$SITE/setuptools" "$SITE"/setuptools-*.dist-info "$SITE/pkg_resources" "$SITE/_distutils_hack" "$SITE/distutils-precedence.pth"
find "$PYTHON_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
echo "   ✓ Python stripped"

# ── Packages: Windows wheels from the hashed lock ─────────────────────────────
# The lock is resolved for Windows (uv pip compile --python-platform x86_64-pc-windows-msvc), so no
# environment marker is evaluated on this machine. Every wheel must match a hash in the lock.
echo "📚 Installing the locked packages (Windows wheels)..."
PLAT=(--only-binary=:all: --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 --abi abi3 --abi none)
python3 -m pip download --quiet --disable-pip-version-check --require-hashes --no-deps "${PLAT[@]}" \
    -r "$WIN_DIR/requirements-win-lock.txt" -d "$STAGE/wheels"
python3 -m pip install --quiet --disable-pip-version-check --no-index --find-links "$STAGE/wheels" \
    --require-hashes --no-deps --no-compile "${PLAT[@]}" --target "$SITE" -r "$WIN_DIR/requirements-win-lock.txt"
# pip wrote this machine's console scripts and man pages; the app runs "python -m yt_dlp"
rm -rf "$SITE/bin" "$SITE/share"
# yt-dlp loads its solver script from yt-dlp-ejs only at the exact version it names. The lock is
# resolved without yt-dlp's extras, so a regenerated lock can pin a newer yt-dlp-ejs than yt-dlp
# accepts: stop here instead of shipping a pair yt-dlp refuses (it would fetch the script from GitHub).
python3 - "$SITE" <<'PYEOF' || exit 1
import glob, os, re, sys
site = sys.argv[1]
def meta(name):
    found = glob.glob(os.path.join(site, name + "-*.dist-info", "METADATA"))
    return open(found[0], encoding="utf-8").read() if len(found) == 1 else None
ytdlp, ejs = meta("yt_dlp"), meta("yt_dlp_ejs")
if ytdlp is None:
    sys.exit("   ✗ yt-dlp is not installed exactly once in site-packages")
named = re.search(r"^Requires-Dist: yt-dlp-ejs==([0-9][0-9A-Za-z.]*)\s*;\s*extra\s*==\s*['\"]default['\"]\s*$", ytdlp, re.M)
if named is None:
    print("   ⚠ yt-dlp names no yt-dlp-ejs version, so it will download its solver script when needed")
    sys.exit(0)
have = re.search(r"^Version: (\S+)$", ejs, re.M).group(1) if ejs else None
if have != named.group(1):
    sys.exit(f"   ✗ yt-dlp names yt-dlp-ejs {named.group(1)}, the lock installed {have}: fix windows/requirements-win-lock.txt")
print(f"   ✓ yt-dlp-ejs {have} (the version yt-dlp names)")
PYEOF
echo "   ✓ $(ls -d "$SITE"/*.dist-info | wc -l | tr -d ' ') distributions in site-packages"

if [ "$PRECOMPILE" = 1 ]; then
    "${HOST_PYTHON311:-python3.11}" -I -m compileall -q -j0 --invalidation-mode checked-hash -s "$PYTHON_DIR" "$PYTHON_DIR/Lib"
    echo "   ✓ Precompiled (checked-hash .pyc)"
else
    find "$PYTHON_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
    find "$PYTHON_DIR" -name "*.pyc" -delete
fi

# ── Electron (from windows/electron's lock, through a staging package) ────────
echo "⚡ Packaging Electron..."
cd "$STAGE/electron"
python3 "$SCRIPT_DIR/stage_package.py" "$REPO_ROOT" "$STAGE/electron"
cp "$WIN_DIR/electron/main.js" "$WIN_DIR/electron/preload.js" "$WIN_DIR/electron/splash.html" .
ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci --no-audit --no-fund --ignore-scripts --loglevel=error
python3 "$SCRIPT_DIR/stage_package.py" --electron-checksum "$STAGE/electron"
npx --no-install electron-builder --win dir --x64 --publish never
mv "$STAGE/electron/out/win-unpacked" "$OUT"

echo "🏷  Exe version strings..."
node "$SCRIPT_DIR/exe_strings.js" "$STAGE/electron" "$OUT/EGM Downloader.exe" "$VERSION" "$BUILD_NUM"

# ── Check and clean up ────────────────────────────────────────────────────────
if ! diff -r "$STAGE/app" "$OUT/resources/app" > /dev/null; then
    echo "❌ resources/app differs from the app files"
    exit 1
fi
cd "$REPO_ROOT"
rm -rf "$STAGE"
echo "   ✓ dist/win-unpacked: $(find "$OUT" -type f | wc -l | tr -d ' ') files, $(du -sh "$OUT" | cut -f1)"
echo "   ✓ EGM Downloader.exe SHA-256 $($SHA256SUM "$OUT/EGM Downloader.exe" | cut -d' ' -f1)"
