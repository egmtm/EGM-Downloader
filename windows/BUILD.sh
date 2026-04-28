#!/bin/bash
# EGM Downloader — Windows Build Script
# Run from repo root: bash windows/BUILD.sh
# Or from the windows/ directory: bash BUILD.sh
# Produces: dist/EGMd.zip + dist/egm-version.json
#
# Requirements (Linux/Mac/WSL):
#   - makensis (sudo apt install nsis  OR  brew install makensis)
#   - python3 (standard library only)

set -e

# Resolve repo root regardless of where script is called from
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WIN_DIR="$SCRIPT_DIR"

echo ""
echo "╔════════════════════════════════════════╗"
echo "║  EGM Downloader — Windows Build       ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "   Repo root: $REPO_ROOT"
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────────
echo "📋 Checking prerequisites..."
if ! command -v makensis &> /dev/null; then
    echo "❌ makensis not found!"
    echo "   Install: sudo apt install nsis   (Linux)"
    echo "            brew install makensis   (macOS)"
    exit 1
fi
if ! command -v python3 &> /dev/null; then
    echo "❌ python3 not found!"
    exit 1
fi
echo "   ✓ makensis: $(makensis -VERSION)"
echo "   ✓ Python:   $(python3 --version)"
echo ""

# ── Read version from version.json (single source of truth) ──────────────────
echo "🔢 Reading version from version.json..."
VERSION=$(python3 -c "import json; d=json.load(open('$REPO_ROOT/version.json')); print(d['version'])")
BUILD_NUM=$(python3 -c "import json; d=json.load(open('$REPO_ROOT/version.json')); print(d['build'])")
BUILD_DATE=$(python3 -c "import json; d=json.load(open('$REPO_ROOT/version.json')); print(d['date'] + ' ' + d['time'])")
echo "   ✓ v$VERSION Build $BUILD_NUM — $BUILD_DATE"
echo ""

# ── Verify all source files present ─────────────────────────────────────────
echo "📋 Verifying source files..."
MISSING=0
for f in "windows/EGM Downloader.vbs" windows/launch.bat windows/launch.py \
         windows/instructions.txt app.py requirements.txt patchnotes.txt README.md \
         templates/index.html templates/history.html static/icon.ico static/icon-512.png \
         windows/electron/main.js windows/electron/preload.js windows/electron/package.json; do
    if [ ! -e "$REPO_ROOT/$f" ]; then
        echo "   ❌ MISSING: $f"
        MISSING=$((MISSING+1))
    fi
done
if [ $MISSING -gt 0 ]; then
    echo ""
    echo "❌ $MISSING file(s) missing — aborting build"
    exit 1
fi
echo "   ✓ All source files present"
echo ""

# ── Clean old build artifacts ────────────────────────────────────────────────
echo "🧹 Cleaning old Windows build artifacts..."
mkdir -p "$REPO_ROOT/dist"
rm -f "$REPO_ROOT/dist/egm-setup.exe" "$REPO_ROOT/dist/EGMd.zip"
echo "   ✓ Cleaned"
echo ""

# ── Compile NSIS installer ───────────────────────────────────────────────────
echo "🔨 Compiling NSIS installer (egm-setup.exe)..."
makensis -V2 \
    -DVERSION="$VERSION" \
    -DBUILD="$BUILD_NUM" \
    -DREPO_ROOT="$REPO_ROOT" \
    -DOUTFILE="$REPO_ROOT/dist/egm-setup.exe" \
    "$WIN_DIR/setup.nsi"

if [ ! -f "$REPO_ROOT/dist/egm-setup.exe" ]; then
    echo "❌ NSIS compilation failed — egm-setup.exe not produced"
    exit 1
fi
SETUP_SIZE=$(du -h "$REPO_ROOT/dist/egm-setup.exe" | cut -f1)
echo "   ✓ egm-setup.exe built ($SETUP_SIZE)"
echo ""

# ── Package into zip ─────────────────────────────────────────────────────────
echo "📦 Packaging EGMd.zip..."
python3 - <<PYZIP
import zipfile
from pathlib import Path

repo_root = Path("$REPO_ROOT")
zip_path  = repo_root / "dist" / "EGMd.zip"
exe_path  = repo_root / "dist" / "egm-setup.exe"
ins_path  = repo_root / "windows" / "instructions.txt"

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    zf.write(exe_path, "egm-setup.exe")
    zf.write(ins_path, "instructions.txt")

print(f"   ✓ EGMd.zip created ({zip_path.stat().st_size / 1024 / 1024:.2f} MB)")
PYZIP
echo ""

# ── Verify zip contents ──────────────────────────────────────────────────────
echo "🔍 Verifying EGMd.zip contents..."
python3 - <<PYVER
import zipfile
from pathlib import Path

zip_path = Path("$REPO_ROOT/dist/EGMd.zip")
with zipfile.ZipFile(zip_path, "r") as zf:
    names = zf.namelist()
    print(f"   Files: {names}")
    expected = {"egm-setup.exe", "instructions.txt"}
    actual   = set(names)
    if expected != actual:
        raise SystemExit(f"❌ Unexpected zip contents. Expected {expected}, got {actual}")
    for name in names:
        with zf.open(name) as f:
            head = f.read(8)
            if not head:
                raise SystemExit(f"❌ Could not read {name}")
print("   ✓ Verified — EGMd.zip is valid")
PYVER
echo ""

# ── Compute SHA256 checksum ───────────────────────────────────────────────────
echo "🔒 Computing SHA256 checksum..."
CHECKSUM=$(python3 -c "
import hashlib
h = hashlib.sha256()
h.update(open('$REPO_ROOT/dist/EGMd.zip', 'rb').read())
print(h.hexdigest())
")
echo "   ✓ SHA256: $CHECKSUM"
echo ""

# ── Generate update JSON ─────────────────────────────────────────────────────
echo "📄 Generating Windows update JSON..."
# Pull bullets from the most recent patchnotes.txt entry (matches current build).
# Filter to ONLY include [WINDOWS] and [ALL] tagged bullets — never cross-reference
# other OS changes per JSON_UPDATE_FEED_RULE.
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
            # Only include bullets tagged [WINDOWS] or [ALL] for the Windows feed
            m = re.match(r'^\[(WINDOWS|ALL)\]\s+(.+)\$', text)
            if m:
                bullets.append(m.group(2))
        elif line.strip() == '' and bullets:
            break
print('|||'.join(bullets))
")
if [ -n "$NOTES" ]; then
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform windows --notes "$NOTES" --checksum "$CHECKSUM"
else
    echo "   ⚠️  No [WINDOWS] or [ALL] bullets found in patchnotes.txt — generating with empty notes"
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform windows --checksum "$CHECKSUM"
fi
echo ""

# ── Push to GitHub ───────────────────────────────────────────────────────────
echo "🚀 Pushing to GitHub..."
cd "$REPO_ROOT"
if git status --porcelain | grep -q .; then
    git add -A
    git commit -m "Windows v$VERSION Build $BUILD_NUM"
    git push origin main
    echo "   ✓ Pushed"
else
    echo "   ✓ No source changes to commit (binaries are gitignored)"
fi

echo ""
echo "╔════════════════════════════════════════╗"
echo "║      ✅  WINDOWS BUILD DONE!           ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "   Upload to egerena.com/apps/:"
echo "   → dist/EGMd.zip"
echo "   → dist/egm-version.json"
echo ""
