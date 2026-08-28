#!/bin/bash
# EGM Downloader — macOS Build Script
# Run from repo root: bash mac/BUILD.sh
# Or from the mac/ directory: bash BUILD.sh

set -e

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
npm run build --quiet
echo "   ✓ App built"
echo ""

# ── Package into zip ─────────────────────────────────────────────────────────
echo "📦 Packaging EGMdM.zip..."
mkdir -p "$REPO_ROOT/dist"
DMG=$(ls "$ELECTRON_DIR/dist/"*.dmg 2>/dev/null | head -1)
if [ -z "$DMG" ]; then
    echo "❌ No .dmg found in electron/dist/"
    exit 1
fi

# ── Code signing verification ─────────────────────────────────────────────────
echo "🔐 Verifying code signature..."
APP_PATH="$ELECTRON_DIR/dist/mac-arm64/EGM Downloader.app"
if codesign --verify --deep --strict "$APP_PATH" 2>/dev/null; then
    SIGNING_ID=$(codesign -dvv "$APP_PATH" 2>&1 | grep "Authority=" | head -1 | sed 's/Authority=//')
    echo "   ✓ App is code-signed: $SIGNING_ID"
else
    echo "   ⚠ App signature not found — skipping notarization"
fi
echo ""

# ── Notarization + Stapling ───────────────────────────────────────────────────
if codesign --verify --deep --strict "$APP_PATH" 2>/dev/null; then
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

# ── Create end-user INSTRUCTIONS.txt ──────────────────────────────────────────
cd "$ELECTRON_DIR/dist"
cat > INSTRUCTIONS.txt << 'EOF'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  EGM DOWNLOADER FOR MACOS - INSTALLATION INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERSION: v1.3.8
PLATFORM: macOS (Apple Silicon - M1/M2/M3/M4/M5)
MINIMUM MACOS: 13.0 (Ventura) or later

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INSTALLATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Double-click "EGM Downloader.dmg"

2. Drag "EGM Downloader" to your Applications folder

3. Open Applications folder and launch "EGM Downloader"

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

# ── Create zip with DMG + INSTRUCTIONS ────────────────────────────────────────
zip -r "$REPO_ROOT/dist/EGMdM.zip" "$(basename "$DMG")" INSTRUCTIONS.txt
echo "   ✓ dist/EGMdM.zip created (with INSTRUCTIONS.txt)"
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
