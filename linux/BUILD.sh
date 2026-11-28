#!/bin/bash
# EGM Downloader — Linux x64 Build Script
# Run from repo root: bash linux/BUILD.sh
# Or from the linux/ directory: bash BUILD.sh
# Produces: dist/EGMdL.zip + dist/EGMdL.deb + dist/EGMdL.rpm + dist/egmlinux-update.json

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

# ── The checkout must be committed ───────────────────────────────────────────
# Every phase builds from a commit, so a build can be traced to one: a change that is not
# committed (a modified or staged file, or an untracked file that is not ignored) stops it here.
cd "$REPO_ROOT"
HEAD_LINE=$(git log -1 --format='%H %s')
DIRTY=$(git status --porcelain)
if [ -n "$DIRTY" ]; then
    echo "❌ The checkout has uncommitted changes. Commit (or stash) them first: the build must come from a commit."
    echo "$DIRTY" | sed 's/^/     /'
    exit 1
fi
echo "   Commit: $HEAD_LINE"
echo ""

# ── Prerequisites ─────────────────────────────────────────────────────────────
echo "📋 Checking prerequisites..."
for cmd in python3 node curl rpmbuild objdump; do
    if ! command -v "$cmd" &> /dev/null; then
        echo "❌ $cmd not found!"
        case "$cmd" in
            python3) echo "   Install: sudo apt install python3" ;;
            node)    echo "   Install: sudo apt install nodejs npm" ;;
            curl)    echo "   Install: sudo apt install curl" ;;
            rpmbuild) echo "   Install: sudo apt install rpm   (the .rpm is made with rpmbuild)" ;;
            objdump) echo "   Install: sudo apt install binutils   (objdump reads the glibc each binary needs)" ;;
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
# Pinned: version, release and SHA-256 (from that release's SHA256SUMS). Keep in step with mac/BUILD.sh.
# The Python bundle brings its own pip, so this pin also decides the pip version.
PYTHON_VERSION="3.11.18"
PYTHON_RELEASE="20261026"
PYTHON_SHA256="a87ee63646c8f8438b7af3954b2135ed2af91d033c631f12a8f20af903046d06"

if [ ! -d "$PYTHON_DIR" ]; then
    PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/cpython-${PYTHON_VERSION}+${PYTHON_RELEASE}-x86_64-unknown-linux-gnu-install_only.tar.gz"
    echo "   Downloading from GitHub..."
    HTTP=$(curl -fL --progress-bar -w '%{http_code}' "$PYTHON_URL" -o python.tar.gz) \
        || { echo "   ✗ downloading the Python archive failed (HTTP status ${HTTP:-000})"; rm -f python.tar.gz; exit 1; }
    echo "$PYTHON_SHA256  python.tar.gz" | sha256sum -c - || { echo "   ✗ python.tar.gz does not match the pinned SHA-256"; rm -f python.tar.gz; exit 1; }
    echo "   Extracting..."
    mkdir -p "$PYTHON_DIR"
    tar -xzf python.tar.gz -C "$PYTHON_DIR" --strip-components=1
    rm python.tar.gz
    echo "   ✓ Python downloaded"
else
    echo "   ✓ Using existing Python"
fi
echo ""

# ── Strip terminfo + manpages from Python bundle ──────────────────────────────
# The terminfo and share/man directories contain relative symlinks.
# electron-builder processes extraResources in parallel and can hit ENOENT
# when a symlink target hasn't been written yet. These files are unused by
# Flask/yt-dlp at runtime — safe to remove.
if [ -d "$PYTHON_DIR/share/terminfo" ]; then
    rm -rf "$PYTHON_DIR/share/terminfo"
    echo "   ✓ Stripped terminfo (unused, causes symlink race in packager)"
fi
if [ -d "$PYTHON_DIR/share/man" ]; then
    rm -rf "$PYTHON_DIR/share/man"
    echo "   ✓ Stripped manpages (unused, causes symlink race in packager)"
fi
# Strip any other share/ subdirs that might contain stale symlinks too.
# Keep the directory itself — Python links some legitimate stuff here.
find "$PYTHON_DIR/share" -mindepth 1 -maxdepth 1 -type d \
    \( -name "doc" -o -name "info" -o -name "locale" \) \
    -exec rm -rf {} + 2>/dev/null || true
echo ""

# ── Install Python deps ───────────────────────────────────────────────────────
echo "📚 Installing Python dependencies..."
# pip is the one inside the pinned Python above (26.2.2); it is not upgraded here
# PYTHONNOUSERSITE=1: pip must only see the bundled Python's own site-packages. Without it
# a package in the host's user site (~/.local) counts as "already installed" and is left out of the AppImage.
LOCK="$LINUX_DIR/requirements-linux-lock.txt"
# The packages come from the hashed lock for this platform (uv pip compile, the command is on its second
# line): pip installs exactly those versions and stops if a file does not match its hash, so every build
# of a commit bundles the same packages. Regenerate all three locks when requirements.txt changes.
# PYTHONPATH: pip reads linux/pip_glibc_floor/_manylinux.py and takes each package's wheel for glibc 2.17,
# the level the lock is resolved for, not the newest one this machine accepts (see that file).
PYTHONNOUSERSITE=1 PYTHONPATH="$LINUX_DIR/pip_glibc_floor" "$PYTHON_DIR/bin/python3" -m pip install --quiet --require-hashes --no-deps --only-binary :all: -r "$LOCK"
# --no-deps installs only what the lock lists, so pip check makes sure the lock is complete: a
# package another one needs but the lock lacks stops the build here instead of shipping.
PYTHONNOUSERSITE=1 "$PYTHON_DIR/bin/python3" -m pip check
# yt-dlp-ejs: yt-dlp loads its YouTube solver script from this package only at the exact version it
# names (a == requirement in its metadata). The lock is resolved without yt-dlp's extras, so a regenerated
# lock can pin a yt-dlp-ejs that yt-dlp refuses: stop here instead of shipping that pair, as the Windows
# build does. A yt-dlp that names none keeps the GitHub fallback; a failed read stops the build.
EJS_PIN=$(PYTHONNOUSERSITE=1 "$PYTHON_DIR/bin/python3" -c '
import importlib.metadata as m, re
for line in m.requires("yt-dlp") or []:
    hit = re.match(r"\s*yt-dlp-ejs==([0-9][0-9A-Za-z.]*)\s*;\s*extra\s*==\s*[\x27\"]default[\x27\"]\s*$", line)
    if hit:
        print(hit.group(1))
        break
')
EJS_HAVE=$(PYTHONNOUSERSITE=1 "$PYTHON_DIR/bin/python3" -c '
import importlib.metadata as m
try:
    print(m.version("yt-dlp-ejs"))
except m.PackageNotFoundError:
    pass
')
if [ -z "$EJS_PIN" ]; then
    echo "   ⚠ yt-dlp names no yt-dlp-ejs version, so it will download its solver script when needed"
elif [ "$EJS_HAVE" != "$EJS_PIN" ]; then
    echo "   ✗ yt-dlp names yt-dlp-ejs $EJS_PIN, the lock installed ${EJS_HAVE:-none}: regenerate $LOCK"
    exit 1
else
    echo "   ✓ yt-dlp-ejs $EJS_HAVE (the version yt-dlp names)"
fi
echo "   ✓ Dependencies installed"
echo ""

# ── Strip Python bundle bloat ─────────────────────────────────────────────────
echo "🗜  Stripping unused Python packages and bytecache..."
SITE="$PYTHON_DIR/lib/python3.11/site-packages"

# Package managers — kept for runtime yt-dlp updates via Update Plugins
# rm -rf "$SITE/pip" "$SITE/pip-"*.dist-info  # DO NOT STRIP — needed at runtime
rm -rf "$SITE/setuptools" "$SITE/setuptools-"*.dist-info
# distutils-precedence.pth imports _distutils_hack, so it goes with the module (left behind, Python prints an error at every start)
rm -rf "$SITE/pkg_resources" "$SITE/_distutils_hack" "$SITE/distutils-precedence.pth"

# Stdlib modules unused at runtime
# rm -rf "$PYTHON_DIR/lib/python3.11/ensurepip"  # DO NOT STRIP — needed for pip
rm -rf "$PYTHON_DIR/lib/python3.11/idlelib"
rm -rf "$PYTHON_DIR/lib/python3.11/tkinter"
rm -rf "$PYTHON_DIR/lib/python3.11/lib2to3"
rm -rf "$PYTHON_DIR/lib/python3.11/turtledemo"
rm -rf "$PYTHON_DIR/lib/python3.11/turtle.py"

# bin/python3.11 has the interpreter built in; this second 55 MB copy is only for programs that embed Python
rm -f "$PYTHON_DIR/lib/libpython3.11.so"* "$PYTHON_DIR/lib/libpython3.so"

# pip wrote console scripts into bin/ (yt-dlp, flask, the mutagen tools and others), and each one
# starts with this machine's build folder. The app runs "python -m yt_dlp" and Update Plugins runs
# "python -m pip", so they go: only files that start by naming the build folder, never python3.
# pip names it on the first line, or on the second (after #!/bin/sh) when the folder has a space
# in it or is too long for a first line. Matched as written and with any symlink resolved.
PY_REAL="$(cd "$PYTHON_DIR" && pwd -P)"
REMOVED=0
for f in "$PYTHON_DIR"/bin/*; do
    if [ -f "$f" ] && head -n 2 "$f" | grep -qF -e "#!$PYTHON_DIR/" -e "#!$PY_REAL/" -e "'''exec' \"$PYTHON_DIR/" -e "'''exec' \"$PY_REAL/"; then
        rm -f "$f"
        REMOVED=$((REMOVED + 1))
    fi
done
echo "   ✓ $REMOVED console scripts with the build folder in them removed"

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

# ── Build Electron AppImage, .deb and .rpm ────────────────────────────────────
# One electron-builder run packs the app once and makes the three files from that one folder,
# so the AppImage, the .deb and the .rpm hold the same app.
echo "🔨 Building Electron AppImage, .deb and .rpm..."
cd "$ELECTRON_DIR"
node ./node_modules/.bin/electron-builder --linux AppImage deb rpm --x64 --publish never
echo "   ✓ AppImage, .deb and .rpm built"
echo ""

# ── glibc floor ───────────────────────────────────────────────────────────────
# No file of the packed app (the one folder all three are made from) may need a newer glibc than
# Electron's own binary: on a system Electron runs on, that file would fail to load. cryptography's
# newest wheel did that once, and the update check stopped working on older systems.
echo "🔎 Checking the glibc each binary needs..."
UNPACKED="$ELECTRON_DIR/dist/linux-unpacked"
glibc_needed() { objdump -T "$1" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/^GLIBC_//' | sort -V | tail -n 1; }
FLOOR=$(glibc_needed "$UNPACKED/egm-downloader-bin")
if [ -z "$FLOOR" ]; then
    echo "   ✗ could not read the glibc version Electron's binary needs"
    exit 1
fi
# INSTRUCTIONS.txt, shipped in the zip, tells users which glibc they need: it must say Electron's
SAID=$(grep -o 'glibc [0-9][0-9.]*+' "$LINUX_DIR/INSTRUCTIONS.txt" | sed 's/^glibc //; s/+$//' | sort -u | paste -sd ' ' -)
if [ "$SAID" != "$FLOOR" ]; then
    echo "   ✗ linux/INSTRUCTIONS.txt says glibc ${SAID:-nothing}, Electron needs $FLOOR: update the glibc line there"
    exit 1
fi
TOO_NEW=0
while IFS= read -r -d '' f; do
    need=$(glibc_needed "$f")
    if [ -n "$need" ] && [ "$(printf '%s\n%s\n' "$FLOOR" "$need" | sort -V | tail -n 1)" != "$FLOOR" ]; then
        echo "   ✗ ${f#"$UNPACKED"/} needs glibc $need, Electron needs $FLOOR"
        TOO_NEW=$((TOO_NEW + 1))
    fi
done < <(find "$UNPACKED" -type f -print0)
if [ "$TOO_NEW" != 0 ]; then
    exit 1
fi
echo "   ✓ No file needs a newer glibc than Electron's $FLOOR"
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
# Must contain: AppImage + INSTRUCTIONS.txt + LICENSE
cd "$ELECTRON_DIR/dist"
rm -f "$REPO_ROOT/dist/EGMdL.zip"   # zip adds to an existing archive: an older AppImage would stay inside
zip -r "$REPO_ROOT/dist/EGMdL.zip" "$(basename "$APPIMAGE")"
cd "$LINUX_DIR"
zip -j "$REPO_ROOT/dist/EGMdL.zip" "$LINUX_DIR/INSTRUCTIONS.txt" "$REPO_ROOT/LICENSE"
echo "   ✓ dist/EGMdL.zip created (AppImage + INSTRUCTIONS.txt + LICENSE)"
echo ""

# ── Copy the .deb ─────────────────────────────────────────────────────────────
# The .deb ships as it is (no zip): `apt install ./EGMdL.deb` takes the file itself.
echo "📦 Copying EGMdL.deb..."
DEB="$ELECTRON_DIR/dist/EGMdL.deb"
if [ ! -f "$DEB" ]; then
    echo "❌ No EGMdL.deb found in linux/electron/dist/"
    exit 1
fi
rm -f "$REPO_ROOT/dist/EGMdL.deb"
cp "$DEB" "$REPO_ROOT/dist/EGMdL.deb"
echo "   ✓ dist/EGMdL.deb created"
echo "   ✓ SHA256: $(sha256sum "$REPO_ROOT/dist/EGMdL.deb" | cut -d' ' -f1)"
echo "   ✓ size: $(stat -c %s "$REPO_ROOT/dist/EGMdL.deb") bytes"
echo ""

# ── Copy the .rpm ─────────────────────────────────────────────────────────────
# The .rpm ships as it is (no zip): `dnf install ./EGMdL.rpm` takes the file itself.
echo "📦 Copying EGMdL.rpm..."
RPM="$ELECTRON_DIR/dist/EGMdL.rpm"
if [ ! -f "$RPM" ]; then
    echo "❌ No EGMdL.rpm found in linux/electron/dist/"
    exit 1
fi
rm -f "$REPO_ROOT/dist/EGMdL.rpm"
cp "$RPM" "$REPO_ROOT/dist/EGMdL.rpm"
echo "   ✓ dist/EGMdL.rpm created"
echo "   ✓ SHA256: $(sha256sum "$REPO_ROOT/dist/EGMdL.rpm" | cut -d' ' -f1)"
echo "   ✓ size: $(stat -c %s "$REPO_ROOT/dist/EGMdL.rpm") bytes"
echo ""

# ── Compute SHA256 checksum ───────────────────────────────────────────────────
echo "🔒 Computing SHA256 checksum..."
CHECKSUM=$(python3 -c "
import hashlib
h = hashlib.sha256()
h.update(open('$REPO_ROOT/dist/EGMdL.zip', 'rb').read())
print(h.hexdigest())
")
echo "   ✓ SHA256: $CHECKSUM"
SIZE=$(python3 -c "import os; print(os.path.getsize('$REPO_ROOT/dist/EGMdL.zip'))")
echo "   ✓ size: $SIZE bytes"
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
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform linux --notes "$NOTES" --checksum "$CHECKSUM" --size-bytes "$SIZE"
else
    echo "   ⚠️  No [LINUX] or [ALL] bullets found in patchnotes.txt — generating with empty notes"
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform linux --checksum "$CHECKSUM" --size-bytes "$SIZE"
fi
echo ""

# NOTE: last-released-build.txt is intentionally NOT bumped here -- see the matching comment in
# windows/BUILD.sh for why. Bump it as a deliberate, separate, LAST step of the actual release
# process instead.
echo ""
echo "╔════════════════════════════════════════╗"
echo "║       ✅  LINUX BUILD DONE!            ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "   Commit: $HEAD_LINE"
echo ""
echo "   Upload to egerena.com/apps/:"
echo "   → dist/EGMdL.zip"
echo "   → dist/EGMdL.deb"
echo "   → dist/EGMdL.rpm"
echo "   → dist/egmlinux-update.json"
echo ""
