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
echo "║  EGM Downloader — macOS ARM64 Build ║"
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

# ── Build Electron app ────────────────────────────────────────────────────────
echo "🔨 Building Electron app..."
cd "$ELECTRON_DIR"
npm run build --quiet
echo "   ✓ App built"
echo ""

# ── Package into password-protected zip ──────────────────────────────────────
echo "📦 Packaging EGMdM.zip..."
mkdir -p "$REPO_ROOT/dist"
DMG=$(ls "$ELECTRON_DIR/dist/"*.dmg 2>/dev/null | head -1)
if [ -z "$DMG" ]; then
    echo "❌ No .dmg found in electron/dist/"
    exit 1
fi

cd "$ELECTRON_DIR/dist"
zip -e -r "$REPO_ROOT/dist/EGMdM.zip" "$(basename "$DMG")" -P "EGMsterling"
echo "   ✓ dist/EGMdM.zip created"
echo ""

# ── Generate update JSON ──────────────────────────────────────────────────────
echo "📄 Generating Mac update JSON..."
python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform mac
echo ""

# ── Push to GitHub ────────────────────────────────────────────────────────────
echo "🚀 Pushing to GitHub..."
cd "$REPO_ROOT"
git add -A
git commit -m "Mac v$VERSION Build $BUILD_NUM"
git push origin main

echo ""
echo "╔════════════════════════════════════╗"
echo "║        ✅  MAC BUILD DONE!         ║"
echo "╚════════════════════════════════════╝"
echo ""
echo "   Upload to egerena.com/apps/:"
echo "   → dist/EGMdM.zip"
echo "   → dist/egmac-update.json"
echo ""
