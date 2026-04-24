#!/bin/bash
# EGM Downloader — Linux x64 Build Script
# Run from repo root: bash linux/BUILD.sh
# Or from the linux/ directory: bash BUILD.sh
# Produces: dist/EGMdL.zip + dist/egmlinux-update.json

set -e

# Resolve repo root regardless of where script is called from
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LINUX_DIR="$SCRIPT_DIR"
ELECTRON_DIR="$LINUX_DIR/electron"

echo ""
echo "╔════════════════════════════════════════╗"
echo "║  EGM Downloader — Linux x64 Build     ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "   Repo root: $REPO_ROOT"
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────────
echo "📋 Checking prerequisites..."
for cmd in python3 node curl; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "❌ $cmd not found!"
        case "$cmd" in
            python3) echo "   Install: sudo apt install python3" ;;
            node)    echo "   Install: sudo apt install nodejs npm" ;;
            curl)    echo "   Install: sudo apt install curl" ;;
        esac
        exit 1
    fi
done
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
rm -rf "$ELECTRON_DIR/dist" "$ELECTRON_DIR/node_modules" "$LINUX_DIR/python"
echo "   ✓ Cleaned"
echo ""

# ── Install Node deps ─────────────────────────────────────────────────────────
echo "📦 Installing Node dependencies..."
cd "$ELECTRON_DIR"
npm install --quiet
echo "   ✓ Installed"
echo ""

# ── Download bundled Python Linux x64 ────────────────────────────────────────
echo "🐍 Downloading Python 3.11 Linux x64..."
cd "$LINUX_DIR"
PYTHON_DIR="$LINUX_DIR/python"

if [ ! -d "$PYTHON_DIR" ]; then
    PYTHON_VERSION="3.11.9"
    PYTHON_URL="https://github.com/indygreg/python-build-standalone/releases/download/20240415/cpython-${PYTHON_VERSION}+20240415-x86_64-unknown-linux-gnu-install_only.tar.gz"
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
"$PYTHON_DIR/bin/python3" -m pip install --quiet -r "$LINUX_DIR/requirements.txt" 2>/dev/null || \
"$PYTHON_DIR/bin/python3" -m pip install --quiet -r "$REPO_ROOT/requirements.txt"
echo "   ✓ Dependencies installed"
echo ""

# ── Build Electron AppImage ───────────────────────────────────────────────────
echo "🔨 Building Electron AppImage..."
cd "$ELECTRON_DIR"
node ./node_modules/.bin/electron-builder --linux AppImage --x64 --publish never
echo "   ✓ AppImage built"
echo ""

# ── Package into zip ──────────────────────────────────────────────────────────
echo "📦 Packaging EGMdL.zip..."
mkdir -p "$REPO_ROOT/dist"

APPIMAGE=$(ls "$ELECTRON_DIR/dist/"*.AppImage 2>/dev/null | head -1)
if [ -z "$APPIMAGE" ]; then
    echo "❌ No .AppImage found in linux/electron/dist/"
    exit 1
fi

# Linux zip — no password (per EGM build rules)
cd "$ELECTRON_DIR/dist"
zip -r "$REPO_ROOT/dist/EGMdL.zip" "$(basename "$APPIMAGE")"
echo "   ✓ dist/EGMdL.zip created"
echo ""

# ── Generate update JSON ──────────────────────────────────────────────────────
echo "📄 Generating Linux update JSON..."
python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform linux
echo ""

# ── Push to GitHub ────────────────────────────────────────────────────────────
echo "🚀 Pushing to GitHub..."
cd "$REPO_ROOT"
git add -A
git commit -m "Linux v$VERSION Build $BUILD_NUM"
git push origin main

echo ""
echo "╔════════════════════════════════════════╗"
echo "║       ✅  LINUX BUILD DONE!            ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "   Upload to egerena.com/apps/:"
echo "   → dist/EGMdL.zip"
echo "   → dist/egmlinux-update.json"
echo ""
