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
rm -rf "$ELECTRON_DIR/dist" "$ELECTRON_DIR/node_modules" "$LINUX_DIR/python" 2>/dev/null || true
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

# ── Strip terminfo from Python bundle ────────────────────────────────────────
# The terminfo directory contains relative symlinks. electron-builder processes
# extraResources in parallel and can hit ENOENT when a symlink target hasn't
# been written yet. These files are unused by Flask/yt-dlp — safe to remove.
if [ -d "$PYTHON_DIR/share/terminfo" ]; then
    rm -rf "$PYTHON_DIR/share/terminfo"
    echo "   ✓ Stripped terminfo (unused, causes symlink race in packager)"
fi
echo ""

# ── Install Python deps ───────────────────────────────────────────────────────
echo "📚 Installing Python dependencies..."
# Note: do NOT upgrade pip — pip 26 has a resolvelib regression that breaks installs
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
# Must contain: AppImage + INSTRUCTIONS.txt
cd "$ELECTRON_DIR/dist"
zip -r "$REPO_ROOT/dist/EGMdL.zip" "$(basename "$APPIMAGE")"
cd "$LINUX_DIR"
zip -j "$REPO_ROOT/dist/EGMdL.zip" "$LINUX_DIR/INSTRUCTIONS.txt"
echo "   ✓ dist/EGMdL.zip created (AppImage + INSTRUCTIONS.txt)"
echo ""

# ── Generate update JSON ──────────────────────────────────────────────────────
echo "📄 Generating Linux update JSON..."
# Pull bullets from latest patchnotes.txt entry, filtered to [LINUX] and [ALL] only
# per JSON_UPDATE_FEED_RULE — never cross-reference other OS changes.
NOTES=$(python3 -c "
import re
from pathlib import Path
pn = Path('$REPO_ROOT/patchnotes.txt').read_text(encoding='utf-8')
bullets = []
in_block = False
for line in pn.splitlines():
    if re.match(r'^v\d', line):
        if in_block: break
        in_block = True
        continue
    if in_block:
        if line.startswith('  \u2022 '):
            text = line[4:].strip()
            m = re.match(r'^\[(LINUX|ALL)\]\s+(.+)\$', text)
            if m:
                bullets.append(m.group(2))
        elif line.strip() == '' and bullets:
            break
print('|||'.join(bullets))
")
if [ -n "$NOTES" ]; then
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform linux --notes "$NOTES"
else
    echo "   ⚠️  No [LINUX] or [ALL] bullets found in patchnotes.txt — generating with empty notes"
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform linux
fi
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
