#!/bin/bash
# EGM Downloader — macOS Build Script
# Run from repo root: bash mac/BUILD.sh
# Or from the mac/ directory: bash BUILD.sh

set -e

# ── Temporary zip-only mode (macOS 27 Golden Gate / 26 Tahoe hdiutil issue) ───
# Set to 1 to skip the DMG target entirely and ship EGMdM.zip containing the
# signed+stapled .app instead of a signed+stapled .dmg. electron-builder's
# `dmg-builder` shells out to `hdiutil` for the DMG's intermediate image, and
# hdiutil has been hanging indefinitely (no error, no completion) on macOS 27
# even after switching that intermediate image to APFS
# (electron-userland/electron-builder#9615 -- fixed the *documented* HFS+
# mounting bug, but this hang persists past that fix, so it's a different,
# undocumented failure as of this writing).
#
# Before flipping this back to 0: run scripts/check-dmg-toolchain.sh on the
# actual build Mac. It prints PASS the day the underlying hdiutil pipeline
# works again -- that's the signal to re-enable DMG, not a calendar guess.
#
# Flipping this flag changes three things together, in one place: the
# electron-builder target (dmg+zip -> zip only), the notarize/staple target
# (the .dmg -> the .app directly, since a bare zip can't be stapled), and the
# INSTALLATION section of the shipped INSTRUCTIONS.txt. Nothing in
# mac/electron/package.json changes -- the "dmg" target and settings block
# stay exactly as committed, correct and ready for the day this flips back.
#
# Set: 2026-09-16. Ref: EGM_v1.4.0_dmg_consult.md (Sept 2026 consultation).
DMG_TOOLCHAIN_BROKEN=1

# Resolve repo root regardless of where script is called from
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MAC_DIR="$SCRIPT_DIR"
ELECTRON_DIR="$MAC_DIR/electron"

echo ""
echo "╔════════════════════════════════════╗"
echo "║  EGM Downloader — macOS ARM64 Build║"
echo "╚════════════════════════════════════╝"
echo ""
echo "   Repo root: $REPO_ROOT"
if [ "$DMG_TOOLCHAIN_BROKEN" = "1" ]; then
    echo "   ⚠ DMG_TOOLCHAIN_BROKEN=1 — building zip-only (see comment at top of this script)"
fi
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────────
echo "📋 Checking prerequisites..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found! Install: brew install python3"
    exit 1
fi
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found! Install: brew install node"
    exit 1
fi
echo "   ✓ Python: $(python3 --version)"
echo "   ✓ Node: $(node --version)"
echo ""

# ── Read version from version.json (single source of truth) ──────────────────
echo "🔢 Reading version from version.json..."
VERSION=$(python3 -c "import json; d=json.load(open('$REPO_ROOT/version.json')); print(d['version'])")
BUILD_NUM=$(python3 -c "import json; d=json.load(open('$REPO_ROOT/version.json')); print(d['build'])")
BUILD_DATE=$(python3 -c "import json; d=json.load(open('$REPO_ROOT/version.json')); print(d['date'] + ' ' + d['time'])")
echo "   ✓ v$VERSION Build $BUILD_NUM — $BUILD_DATE"
echo ""

# ── Clean old builds ──────────────────────────────────────────────────────────
echo "🧹 Cleaning old builds..."
rm -rf "$ELECTRON_DIR/dist" "$ELECTRON_DIR/node_modules" "$MAC_DIR/python"
echo "   ✓ Cleaned"
echo ""

# ── Install Node deps ─────────────────────────────────────────────────────────
echo "📦 Installing Node dependencies..."
cd "$ELECTRON_DIR"
npm install --quiet
echo "   ✓ Installed"
echo ""

# ── Download bundled Python ARM64 ─────────────────────────────────────────────
echo "🐍 Downloading Python 3.11 ARM64..."
cd "$MAC_DIR"
PYTHON_DIR="$MAC_DIR/python"

if [ ! -d "$PYTHON_DIR" ]; then
    PYTHON_VERSION="3.11.9"
    PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240415/cpython-${PYTHON_VERSION}+20240415-aarch64-apple-darwin-install_only.tar.gz"
    echo "   Downloading from GitHub..."
    curl -L --progress-bar "$PYTHON_URL" -o python.tar.gz
    echo "   Extracting..."
    mkdir -p "$PYTHON_DIR"
    tar -xzf python.tar.gz -C "$PYTHON_DIR" --strip-components=1
    rm python.tar.gz
    echo "   ✓ Python downloaded"
else
    echo "   ✓ Using existing Python"
fi
echo ""

# ── Install Python deps ───────────────────────────────────────────────────────
echo "📚 Installing Python dependencies..."
"$PYTHON_DIR/bin/python3" -m pip install --quiet --upgrade pip
"$PYTHON_DIR/bin/python3" -m pip install --quiet -r "$REPO_ROOT/requirements.txt"
echo "   ✓ Dependencies installed"
echo ""

# ── Strip Python bundle bloat ─────────────────────────────────────────────────
echo "🗜  Stripping unused Python packages and bytecache..."
SITE="$PYTHON_DIR/lib/python3.11/site-packages"

# Package managers — kept for runtime yt-dlp updates via Update Plugins
# rm -rf "$SITE/pip" "$SITE/pip-"*.dist-info  # DO NOT STRIP — needed at runtime
rm -rf "$SITE/setuptools" "$SITE/setuptools-"*.dist-info
rm -rf "$SITE/pkg_resources" "$SITE/_distutils_hack"

# Stdlib modules unused at runtime
# rm -rf "$PYTHON_DIR/lib/python3.11/ensurepip"  # DO NOT STRIP — needed for pip
rm -rf "$PYTHON_DIR/lib/python3.11/idlelib"
rm -rf "$PYTHON_DIR/lib/python3.11/tkinter"
rm -rf "$PYTHON_DIR/lib/python3.11/lib2to3"
rm -rf "$PYTHON_DIR/lib/python3.11/turtledemo"
rm -rf "$PYTHON_DIR/lib/python3.11/turtle.py"

# DO NOT bulk-strip .dist-info directories — werkzeug calls
# importlib.metadata.version('werkzeug') at server startup; flask 3.x and many
# other packages do similar metadata lookups. Stripping their .dist-info breaks
# Flask boot silently and the splash screen hangs forever waiting for the port.
# Only pip/setuptools/wheel dist-info is safe to strip (done above by exact name).

# Bytecache (regenerated on demand, wastes space in bundle)
find "$PYTHON_DIR" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PYTHON_DIR" -name "*.pyc" -delete 2>/dev/null || true

# Test directories inside packages — only plural 'tests/'.
# Singular 'test/' is sometimes a runtime module name (e.g. unittest.test) —
# don't risk stripping it.
find "$SITE" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true

echo "   ✓ Python bundle stripped"
echo ""

# ── Build Electron app ────────────────────────────────────────────────────────
echo "🔨 Building Electron app..."
cd "$ELECTRON_DIR"
if [ "$DMG_TOOLCHAIN_BROKEN" = "1" ]; then
    # CLI target override beats package.json's mac.target (dmg+zip) --
    # package.json itself is untouched, so this reverts by flipping the flag,
    # nothing to remember to undo here.
    npx electron-builder --mac zip --arm64
else
    npm run build --quiet
fi
echo "   ✓ App built"
echo ""

# ── Code signing verification ─────────────────────────────────────────────────
echo "🔐 Verifying code signature..."
APP_PATH="$ELECTRON_DIR/dist/mac-arm64/EGM Downloader.app"
APP_IS_SIGNED=0
if codesign --verify --deep --strict "$APP_PATH" 2>/dev/null; then
    SIGNING_ID=$(codesign -dvv "$APP_PATH" 2>&1 | grep "Authority=" | head -1 | sed 's/Authority=//')
    echo "   ✓ App is code-signed: $SIGNING_ID"
    APP_IS_SIGNED=1
else
    echo "   ⚠ App signature not found — skipping notarization"
fi
echo ""

mkdir -p "$REPO_ROOT/dist"

if [ "$DMG_TOOLCHAIN_BROKEN" = "1" ]; then
    # ── Notarization + Stapling (zip-only: staple the .app itself) ───────────
    # A bare zip can't hold a notarization ticket -- Apple's stapler only
    # accepts a .app or .dmg. So: wrap the .app in a temporary zip just to
    # submit it (ditto -k preserves the code signature; plain `zip` can
    # corrupt it), staple the ticket to the real .app once notarization
    # comes back, then build the actual shipped EGMdM.zip from the now
    # -stapled .app afterward.
    if [ "$APP_IS_SIGNED" = "1" ]; then
        NOTARIZE_ZIP="$ELECTRON_DIR/dist/notarize-submission.zip"
        echo "📤 Submitting app for Apple notarization (this takes 2-5 min)..."
        ditto -c -k --keepParent "$APP_PATH" "$NOTARIZE_ZIP"
        if xcrun notarytool submit "$NOTARIZE_ZIP" \
            --keychain-profile "EGM-Notarize" \
            --wait; then
            echo "   ✓ Notarization accepted"
            echo "📌 Stapling notarization ticket to the app..."
            xcrun stapler staple "$APP_PATH"
            echo "   ✓ Ticket stapled — app will pass Gatekeeper without warnings"
        else
            echo "   ⚠ Notarization failed — app is signed but not notarized"
        fi
        rm -f "$NOTARIZE_ZIP"
        echo ""
    fi
else
    # ── Package into zip ───────────────────────────────────────────────────
    echo "📦 Packaging EGMdM.zip..."
    DMG=$(ls "$ELECTRON_DIR/dist/"*.dmg 2>/dev/null | head -1)
    if [ -z "$DMG" ]; then
        echo "❌ No .dmg found in electron/dist/"
        exit 1
    fi

    # ── Notarization + Stapling ───────────────────────────────────────────────
    if [ "$APP_IS_SIGNED" = "1" ]; then
        echo "📤 Submitting DMG for Apple notarization (this takes 2-5 min)..."
        # Use `if <cmd>` so a transient notarization failure does not trip `set -e`
        # and abort the build — a signed-but-not-notarized DMG is still shippable.
        if xcrun notarytool submit "$DMG" \
        --keychain-profile "EGM-Notarize" \
        --wait; then
        echo "   ✓ Notarization accepted"
        echo "📌 Stapling notarization ticket to DMG..."
        xcrun stapler staple "$DMG"
        echo "   ✓ Ticket stapled — app will pass Gatekeeper without warnings"
    else
        echo "   ⚠ Notarization failed — DMG is signed but not notarized"
    fi
    echo ""
    fi
fi

# ── Create end-user INSTRUCTIONS.txt ──────────────────────────────────────────
cd "$ELECTRON_DIR/dist"
if [ "$DMG_TOOLCHAIN_BROKEN" = "1" ]; then
    INSTALL_STEPS='1. Unzip this file if your browser has not already done so

2. Drag "EGM Downloader" to your Applications folder

3. Open Applications folder and launch "EGM Downloader"'
else
    INSTALL_STEPS='1. Double-click "EGM Downloader.dmg"

2. Drag "EGM Downloader" to your Applications folder

3. Open Applications folder and launch "EGM Downloader"'
fi
cat > INSTRUCTIONS.txt << EOF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EGM DOWNLOADER FOR MACOS - INSTALLATION INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERSION: v1.4.0
PLATFORM: macOS (Apple Silicon - M1/M2/M3/M4/M5)
MINIMUM MACOS: 13.0 (Ventura) or later

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INSTALLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$INSTALL_STEPS

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  FIRST RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

On first launch, the app will:
• Install required components (yt-dlp, ffmpeg, Deno)
• This takes ~30 seconds
• Progress shown in the app
• After completion, app is ready to use

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Paste a video URL (YouTube, Vimeo, TikTok, 1000+ sites)
2. Choose quality (video) or audio-only (MP3)
3. Click Download
4. Files save to your Downloads folder by default

FEATURES:
• 1000+ supported sites via yt-dlp
• Quality selector with real format IDs
• Playlist support (individual or bulk download)
• Filename editing before download
• Cancel downloads anytime
• Update plugins (yt-dlp, ffmpeg) from app

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SYSTEM REQUIREMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• macOS 13.0 (Ventura) or later
• Apple Silicon (M1/M2/M3/M4/M5)
• ~200 MB disk space
• Internet connection (for downloads)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  SUPPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Website: https://egerena.com/apps/egmac.html
GitHub: https://github.com/egmtm/EGM-Downloader
X: https://x.com/EGMDownloader

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LICENSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GNU Affero General Public License v3.0 (AGPL-3.0)
This is copyleft software. Modifications must be released under the
same license. See the LICENSE file in the GitHub repository for the
full terms: https://github.com/egmtm/EGM-Downloader/blob/main/LICENSE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

© 2026 EGM - www.egerena.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EOF

# ── Create final EGMdM.zip ─────────────────────────────────────────────────
if [ "$DMG_TOOLCHAIN_BROKEN" = "1" ]; then
    echo "📦 Packaging EGMdM.zip (app, not DMG)..."
    cd "$ELECTRON_DIR/dist/mac-arm64"
    cp "$ELECTRON_DIR/dist/INSTRUCTIONS.txt" .
    zip -r "$REPO_ROOT/dist/EGMdM.zip" "EGM Downloader.app" INSTRUCTIONS.txt
    echo "   ✓ dist/EGMdM.zip created (app + INSTRUCTIONS.txt)"
else
    # Create zip with DMG + INSTRUCTIONS
    echo "📦 Packaging EGMdM.zip..."
    zip -r "$REPO_ROOT/dist/EGMdM.zip" "$(basename "$DMG")" INSTRUCTIONS.txt
    echo "   ✓ dist/EGMdM.zip created (with INSTRUCTIONS.txt)"
fi
echo ""

# ── Compute SHA256 checksum ───────────────────────────────────────────────────
echo "🔒 Computing SHA256 checksum..."
MAC_CHECKSUM=$(python3 -c "
import hashlib
h = hashlib.sha256()
h.update(open('$REPO_ROOT/dist/EGMdM.zip', 'rb').read())
print(h.hexdigest())
")
echo "   ✓ SHA256: $MAC_CHECKSUM"
MAC_SIZE=$(python3 -c "import os; print(os.path.getsize('$REPO_ROOT/dist/EGMdM.zip'))" 2>/dev/null || echo "")
echo "   ✓ size: ${MAC_SIZE:-?} bytes"
echo "   → Provide this checksum AND size when generating egmac-update.json"
echo ""

echo ""
echo "╔════════════════════════════════════╗"
echo "║        ✅  MAC BUILD DONE!         ║"
echo "╚════════════════════════════════════╝"
echo ""
echo "   Upload to egerena.com/apps/:"
echo "   → dist/EGMdM.zip"
echo ""
