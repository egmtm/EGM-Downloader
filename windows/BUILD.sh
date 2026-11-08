#!/bin/bash
# EGM Downloader — Windows Build Script
# Run from repo root: bash windows/BUILD.sh
# Or from the windows/ directory: bash BUILD.sh
# Produces: dist/EGMd.zip + dist/egm-version.json
#           dist/EGMd-portable.zip + dist/egm-portable-version.json
#
# Requirements (Linux/Mac/WSL):
#   - makensis (sudo apt install nsis  OR  brew install makensis)
#   - python3 with pip (pip fetches the Windows wheels of the installer's bundled Python)
#   - Node.js with npm (electron-builder packages the installer's Electron)
#   - curl and tar
#   - osslsigncode (optional but recommended: sudo apt install osslsigncode)
#     — lets --continue and --finish verify that the exes are actually signed,
#     with a timestamp, before they get baked in, instead of just trusting a
#     flag was passed.
#
# The installer edition ships Electron, Python and its packages inside the app
# folder (windows/installer/build-folder.sh builds it as dist/win-unpacked). The
# portable edition is unchanged: launcher, launch.py, and everything else
# downloaded on first launch.
#
# THREE PHASE BUILD (added for EGM's Windows code-signing question, v1.3.2+):
# Previously this script compiled "EGM Downloader.exe" (the native launcher)
# and immediately packed the UNSIGNED copy into egm-setup.exe via NSIS. EGM
# could then only sign the outer installer wrapper afterward — the launcher
# actually running on a user's machine post-install was never signed, since
# it was already sealed inside the installer by the time signing happened.
#
# Fixed by splitting the build into three stops:
#   1. bash windows/BUILD.sh              — compiles the launcher (portable)
#      and builds the installer folder (dist/win-unpacked), then STOPS.
#      -> EGM signs the two files named "EGM Downloader.exe" now:
#         windows/EGM Downloader.exe              (the portable launcher)
#         dist/win-unpacked/EGM Downloader.exe    (the installer's Electron)
#   2. bash windows/BUILD.sh --continue   — skips recompiling and rebuilding
#      (electron-builder never runs again, so the signed bytes reach the
#      installer unchanged), verifies BOTH are actually signed if osslsigncode
#      is available, builds egm-setup.exe with NSIS, then STOPS again.
#      -> EGM signs dist/egm-setup.exe now.
#   3. bash windows/BUILD.sh --finish     — verifies egm-setup.exe the same
#      way (and the launcher again, which the portable zip packs here), then
#      makes EGMd.zip, its SHA-256 and size, egm-version.json, EGMd-portable.zip
#      and egm-portable-version.json. The feeds come out UNSIGNED: sign them
#      with scripts/sign-manifest.py before uploading anything.
#   To sign more files later, add them to the SIGNED_FILES lists below.
#
# Stopping by default (no flag) is deliberate: a forgotten flag fails safe
# (nothing gets packaged) rather than failing silent (an unsigned exe
# quietly ships). --continue and --finish have to be typed on purpose, and
# any other argument is refused: a mistyped flag would otherwise start
# phase 1 and throw the signed files away.

set -e

RESUME=0
FINISH=0
for arg in "$@"; do
    case "$arg" in
        --continue) RESUME=1 ;;
        --finish)   RESUME=1; FINISH=1 ;;
        *) echo "❌ Unknown argument: $arg (run with nothing, --continue or --finish)"; exit 1 ;;
    esac
done

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
if [ "$FINISH" -eq 1 ]; then
    echo "   Mode: --finish (resuming after egm-setup.exe was signed)"
elif [ "$RESUME" -eq 1 ]; then
    echo "   Mode: --continue (resuming after the two exes were signed)"
else
    echo "   Mode: phase 1 (will stop after compiling the launcher and building the installer folder, for signing)"
fi
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

# ── The phases run on one commit ─────────────────────────────────────────────
# Phase 1 writes the commit it built from. --continue and --finish refuse to run on another one:
# the installer would otherwise be built from newer files than the folder that was signed.
if [ "$RESUME" -eq 1 ]; then
    if [ ! -f "$REPO_ROOT/dist/.build-commit" ]; then
        echo "❌ dist/.build-commit not found: run phase 1 (bash windows/BUILD.sh) on this commit first."
        exit 1
    fi
    PHASE1_COMMIT=$(cat "$REPO_ROOT/dist/.build-commit")
    if [ "$PHASE1_COMMIT" != "${HEAD_LINE%% *}" ]; then
        echo "❌ Phase 1 built commit $PHASE1_COMMIT, but this checkout is at ${HEAD_LINE%% *}."
        echo "   Check out the first one again (git checkout $PHASE1_COMMIT), or start over with phase 1."
        exit 1
    fi
fi

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
for tool in node npm curl tar; do
    if ! command -v "$tool" &> /dev/null; then
        echo "❌ $tool not found! (required for the installer folder)"
        exit 1
    fi
done
if ! command -v x86_64-w64-mingw32-gcc &> /dev/null; then
    echo "❌ mingw-w64 not found! (required for compiling the launcher EXE)"
    echo "   Install: sudo apt install mingw-w64   (Linux)"
    echo "            brew install mingw-w64       (macOS)"
    exit 1
fi
HAVE_OSSLSIGNCODE=0
if command -v osslsigncode &> /dev/null; then
    HAVE_OSSLSIGNCODE=1
fi
echo "   ✓ makensis: $(makensis -VERSION)"
echo "   ✓ Python:   $(python3 --version)"
echo "   ✓ mingw-w64: $(x86_64-w64-mingw32-gcc --version | head -1)"
if [ "$HAVE_OSSLSIGNCODE" -eq 1 ]; then
    echo "   ✓ osslsigncode: available (the signatures and their timestamps are verified on --continue and --finish)"
else
    echo "   ⚠ osslsigncode: not found — --continue and --finish will skip signature verification and"
    echo "     ask for manual confirmation instead (sudo apt install osslsigncode to enable it)"
fi
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
for f in windows/launcher.c windows/launcher.rc windows/launch.py \
         windows/instructions.txt app.py requirements.txt patchnotes.txt README.md LICENSE \
         templates/index.html templates/history.html static/icon.ico static/icon-512.png \
         windows/electron/main.js windows/electron/preload.js windows/electron/package.json \
         windows/app-files.txt windows/requirements-win-lock.txt windows/installer/build-folder.sh; do
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
# Each phase removes what it regenerates (and what a run that failed half way could have left),
# and never a file a signature was just put on:
#   phase 1     everything, the launcher and the installer folder included (both are rebuilt);
#   --continue  egm-setup.exe and the uninstall list (remade by makensis) and the outputs of
#               --finish; the signed launcher, the folder with its signed exe and its manifest stay;
#   --finish    only its own outputs, the zips, the feeds and the portable stage; the signed
#               egm-setup.exe and launcher stay, they are what this phase packages.
echo "🧹 Cleaning old Windows build artifacts..."
mkdir -p "$REPO_ROOT/dist"
rm -f "$REPO_ROOT/dist/EGMd.zip" "$REPO_ROOT/dist/EGMd-portable.zip" \
      "$REPO_ROOT/dist/egm-version.json" "$REPO_ROOT/dist/egm-portable-version.json"
rm -rf "$REPO_ROOT/dist/portable-stage"
if [ "$FINISH" -eq 0 ]; then
    rm -f "$REPO_ROOT/dist/egm-setup.exe" "$REPO_ROOT/dist/win-unpacked-files.nsh"
fi
if [ "$RESUME" -eq 0 ]; then
    rm -f "$WIN_DIR/EGM Downloader.exe" "$REPO_ROOT/dist/.build-commit"
    rm -rf "$REPO_ROOT/dist/win-unpacked" "$REPO_ROOT/dist/win-unpacked.sha256"
fi
echo "   ✓ Cleaned"
echo ""

# ── Compile launcher EXE (replaces .vbs) ─────────────────────────────────────
if [ "$RESUME" -eq 0 ]; then
    echo "🔨 Compiling launcher EXE (EGM Downloader.exe)..."
    cd "$REPO_ROOT/windows"
    x86_64-w64-mingw32-windres launcher.rc -O coff -o launcher.res
    x86_64-w64-mingw32-gcc -O2 -mwindows -municode -s launcher.c launcher.res -o "EGM Downloader.exe"
    LAUNCHER_SIZE=$(stat -c %s "EGM Downloader.exe")
    echo "   ✓ EGM Downloader.exe — $LAUNCHER_SIZE bytes"
    rm -f launcher.res
    cd "$REPO_ROOT"
    echo ""
    # ── Build the installer folder (Electron + Python + packages) ──
    bash "$WIN_DIR/installer/build-folder.sh"
    echo "${HEAD_LINE%% *}" > "$REPO_ROOT/dist/.build-commit"
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║  STOP — launcher compiled, not yet signed                  ║"
    echo "║         installer folder built, its exe not yet signed     ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "   Commit: $HEAD_LINE"
    echo ""
    echo "   → Sign BOTH files named EGM Downloader.exe now:"
    echo "       windows/EGM Downloader.exe              (portable launcher)"
    echo "       dist/win-unpacked/EGM Downloader.exe    (installer: Electron)"
    echo "   → Then re-run:  bash windows/BUILD.sh --continue"
    echo ""
    exit 0
fi

# ── Resuming after signing: verify, don't just trust ─────────────────────────
# The tool's report goes to a file of its own, removed on every exit path by the trap.
VERIFY_OUT=$(mktemp)
trap 'rm -f "$VERIFY_OUT"' EXIT
verify_signed() {
    # Every file given must carry a valid signature with a verified timestamp; otherwise the build
    # stops here (or, with no osslsigncode, after an explicit confirmation). osslsigncode exits 0 for
    # a signature without a timestamp ("Timestamp is not available") and also when the timestamp's
    # own chain does not verify, so its two result lines are read as well as its exit code. Without
    # a timestamp the signature stops verifying the day the certificate expires.
    if [ "$HAVE_OSSLSIGNCODE" -eq 1 ]; then
        for SIGNED in "$@"; do
            SIGNED_SIZE=$(stat -c %s "$SIGNED")
            if osslsigncode verify -in "$SIGNED" > "$VERIFY_OUT" 2>&1 \
                && grep -qE '^Signature verification: ok[[:space:]]*$' "$VERIFY_OUT" \
                && grep -qE '^Timestamp Server Signature verification: ok[[:space:]]*$' "$VERIFY_OUT"; then
                echo "   ✓ Signature and timestamp verified — ${SIGNED#"$REPO_ROOT"/} ($SIGNED_SIZE bytes)"
            else
                echo "   ❌ No valid signature with a verified timestamp on ${SIGNED#"$REPO_ROOT"/}:"
                sed 's/^/     /' "$VERIFY_OUT"
                echo ""
                if grep -q 'Timestamp is not available' "$VERIFY_OUT"; then
                    echo "   The signature carries no timestamp. Sign again with a timestamp server"
                    echo "   (osslsigncode sign -ts <url>, or signtool sign /tr <url> /td sha256)."
                    echo ""
                fi
                echo "   Sign it before continuing — packaging an unsigned exe is exactly the"
                echo "   gap this build's stops exist to close."
                exit 1
            fi
        done
    else
        echo "   ⚠ osslsigncode not installed — can't verify automatically."
        for SIGNED in "$@"; do
            echo "     ${SIGNED#"$REPO_ROOT"/}"
        done
        read -r -p "   Have you signed every file above? [y/N] " CONFIRM
        if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
            echo "   Aborting — sign them first, or install osslsigncode for automatic checks."
            exit 1
        fi
        echo "   ✓ Manual confirmation received"
    fi
    echo ""
}

if [ "$FINISH" -eq 0 ]; then
    # ── Phase 2: the two exes were signed ────────────────────────────────────
    # Every exe in this list must be signed before it is packaged in: the portable
    # launcher and the installer's Electron (both named EGM Downloader.exe). To sign
    # more files later (the bundled python.exe, say), add them here.
    SIGNED_FILES=(
        "$WIN_DIR/EGM Downloader.exe"
        "$REPO_ROOT/dist/win-unpacked/EGM Downloader.exe"
    )
    for SIGNED in "${SIGNED_FILES[@]}"; do
        if [ ! -f "$SIGNED" ]; then
            echo "❌ $SIGNED not found — run without --continue first to build it."
            exit 1
        fi
    done
    echo "🔒 Verifying the exes are actually signed before packaging them in..."
    verify_signed "${SIGNED_FILES[@]}"

    # ── The folder is the one phase 1 built ──────────────────────────────────
    # Only its exe may have changed (signed above). Anything else, such as settings, history, logs
    # or __pycache__ written by starting the exe from dist/win-unpacked, would ship to every user.
    echo "📋 Checking the installer folder against phase 1's manifest..."
    python3 "$WIN_DIR/installer/folder_manifest.py" check "$REPO_ROOT/dist/win-unpacked" "$REPO_ROOT/dist/win-unpacked.sha256"
    echo ""

    # ── Compile NSIS installer ───────────────────────────────────────────────
    echo "🔨 Compiling NSIS installer (egm-setup.exe)..."
    # The uninstaller's list of the folder's top level files and folders, read from the folder itself
    python3 "$WIN_DIR/installer/uninstall_list.py" "$REPO_ROOT/dist/win-unpacked" "$REPO_ROOT/dist/win-unpacked-files.nsh"
    makensis -V2 \
        -DVERSION="$VERSION" \
        -DBUILD="$BUILD_NUM" \
        -DREPO_ROOT="$REPO_ROOT" \
        -DAPP_FOLDER="$REPO_ROOT/dist/win-unpacked" \
        -DAPP_FOLDER_LIST="$REPO_ROOT/dist/win-unpacked-files.nsh" \
        -DOUTFILE="$REPO_ROOT/dist/egm-setup.exe" \
        "$WIN_DIR/setup.nsi"

    if [ ! -f "$REPO_ROOT/dist/egm-setup.exe" ]; then
        echo "❌ NSIS compilation failed — egm-setup.exe not produced"
        exit 1
    fi
    SETUP_SIZE=$(du -h "$REPO_ROOT/dist/egm-setup.exe" | cut -f1)
    echo "   ✓ egm-setup.exe built ($SETUP_SIZE)"
    echo ""
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║  STOP — egm-setup.exe built, not yet signed                ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo ""
    echo "   Commit: $HEAD_LINE"
    echo ""
    echo "   → Sign dist/egm-setup.exe now."
    echo "   → Then run:  bash windows/BUILD.sh --finish"
    echo ""
    exit 0
fi

# ── Phase 3: egm-setup.exe was signed ────────────────────────────────────────
# What this phase packages is verified here, so the bytes zipped and hashed are the ones checked:
# the signed installer (EGMd.zip) and the signed launcher (the portable zip).
SIGNED_FILES=(
    "$REPO_ROOT/dist/egm-setup.exe"
    "$WIN_DIR/EGM Downloader.exe"
)
for SIGNED in "${SIGNED_FILES[@]}"; do
    if [ ! -f "$SIGNED" ]; then
        echo "❌ $SIGNED not found — run --continue first to build it (and phase 1 before that)."
        exit 1
    fi
done
echo "🔒 Verifying the installer is signed before it is zipped and hashed..."
verify_signed "${SIGNED_FILES[@]}"

# ── Package into zip ─────────────────────────────────────────────────────────
echo "📦 Packaging EGMd.zip..."
python3 - <<PYZIP
import zipfile
from pathlib import Path

repo_root = Path("$REPO_ROOT")
zip_path  = repo_root / "dist" / "EGMd.zip"
exe_path  = repo_root / "dist" / "egm-setup.exe"
ins_path  = repo_root / "windows" / "instructions.txt"
lic_path  = repo_root / "LICENSE"

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    zf.write(exe_path, "egm-setup.exe")
    zf.write(ins_path, "instructions.txt")
    zf.write(lic_path, "LICENSE")

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
    expected = {"egm-setup.exe", "instructions.txt", "LICENSE"}
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
SIZE=$(python3 -c "import os; print(os.path.getsize('$REPO_ROOT/dist/EGMd.zip'))")
echo "   ✓ size: $SIZE bytes"
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
            m = re.match(r'^((?:\[[A-Z]+\]\s*)+)(.+)\$', text)
            if m and ({'ALL', 'WINDOWS'} & set(re.findall(r'\[([A-Z]+)\]', m.group(1)))):
                bullets.append(m.group(2).strip())
        elif line.strip() == '' and bullets:
            break
print('|||'.join(bullets))
")
if [ -n "$NOTES" ]; then
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform windows --notes "$NOTES" --checksum "$CHECKSUM" --size-bytes "$SIZE"
else
    echo "   ⚠️  No [WINDOWS] or [ALL] bullets found in patchnotes.txt — generating with empty notes"
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform windows --checksum "$CHECKSUM" --size-bytes "$SIZE"
fi
echo ""

# ── Build portable variant ────────────────────────────────────────────────────
echo "📦 Building Windows portable variant..."
PORTABLE_STAGE="$REPO_ROOT/dist/portable-stage"
rm -rf "$PORTABLE_STAGE"
mkdir -p "$PORTABLE_STAGE/templates" "$PORTABLE_STAGE/static" "$PORTABLE_STAGE/electron"

# Root files of this edition only (the instructions are rewritten below)
cp "$REPO_ROOT/windows/EGM Downloader.exe"   "$PORTABLE_STAGE/"
cp "$REPO_ROOT/windows/launch.py"             "$PORTABLE_STAGE/"
cp "$REPO_ROOT/windows/instructions.txt"      "$PORTABLE_STAGE/"

# App files: windows/app-files.txt, in its order. The installer folder is built from the same
# list (windows/installer/build-folder.sh); validate-version-sync.py checks both editions against it.
while IFS= read -r f; do
    case "$f" in ''|'#'*) continue ;; esac
    mkdir -p "$PORTABLE_STAGE/$(dirname "$f")"
    cp "$REPO_ROOT/$f" "$PORTABLE_STAGE/$f"
done < "$REPO_ROOT/windows/app-files.txt"

# Electron
cp "$REPO_ROOT/windows/electron/main.js"      "$PORTABLE_STAGE/electron/"
cp "$REPO_ROOT/windows/electron/preload.js"   "$PORTABLE_STAGE/electron/"
cp "$REPO_ROOT/windows/electron/splash.html"  "$PORTABLE_STAGE/electron/"
cp "$REPO_ROOT/windows/electron/package.json" "$PORTABLE_STAGE/electron/"
cp "$REPO_ROOT/windows/electron/package-lock.json" "$PORTABLE_STAGE/electron/"

# Languages folder intentionally excluded until POLYGLOT (v1.3) lands

# Portable marker — is_portable() in app.py detects this file
echo "$VERSION-portable-build-$BUILD_NUM" > "$PORTABLE_STAGE/.portable"

# Portable-specific instructions.txt — overwrites the installer version copied above
# Portable users must see the correct steps, not "run egm-setup.exe"
cat > "$PORTABLE_STAGE/instructions.txt" << PORTINS
EGM Downloader v$VERSION — Portable Edition
================================================================
https://egerena.com/apps/egm.html

This is the portable edition. No installation required.
Runs from any folder, USB stick, or network drive.


REQUIREMENTS
─────────────
  • Windows 10 or 11 (64-bit)
  • Python 3.10 or newer — for the FIRST launch only
      Download: https://www.python.org/downloads/
      IMPORTANT: During install, check "Add Python to PATH"

      The first launch uses your system Python just to bootstrap. It then
      downloads its OWN private copy of Python and installs every package
      into it, so the app is fully self-contained from then on — it never
      shares packages with (or depends on) your system Python again.

  Everything else (a private Python, Node.js, Electron, ffmpeg, Deno) is
  downloaded automatically on first launch — no manual setup required.


HOW TO RUN
─────────────
  1. Extract this zip to any folder (Desktop, USB stick, etc.)
  2. Double-click "EGM Downloader.exe" to launch
  3. On first launch, the app downloads required components:

       Private Python      ~40 MB   (one time only)
       Node.js + Electron  ~190 MB  (one time only)
       ffmpeg              ~185 MB  (one time only, background)
       Deno                ~40 MB   (one time only, background)

     This may take a few minutes. An internet connection is required.
  4. Subsequent launches are near-instant.


WHERE YOUR DATA IS STORED
──────────────────────────
  Settings, download history, cookies, saved themes, history pins and the
  window position are stored in:
    data\  (inside this folder, next to EGM Downloader.exe)

  Moving or copying this entire folder preserves all your settings.

  The data folder is hidden once the app has run. To see it, open this
  folder in File Explorer, click View, then Show, then turn on Hidden items.


DIFFERENCES FROM THE INSTALLER VERSION
────────────────────────────────────────
  • No Start Menu or Desktop shortcuts are created.
  • No entry in Windows "Add or Remove Programs".
  • Auto-update is disabled. To update:
      1. Download the latest EGMd-portable.zip from egerena.com/apps
      2. Extract to a new folder
      3. Copy your old data\ folder into the new folder (it is hidden,
         see WHERE YOUR DATA IS STORED above)
         Updating from v1.5.2.1 or older? Also copy your old electron-data\ folder
         into the new folder, next to data\ (not inside it). The app moves it
         into data\ on the first start. It holds your saved themes, history
         pins and sidebar layout. Copy it before you start the new version
         for the first time: once that version has run, it keeps the
         electron-data it made and leaves the copied one unused.
      4. Delete the old folder
  • "Update Plugins" panel is hidden in portable mode.
    To manually update yt-dlp or mutagen, open a command prompt
    in this folder and run (note: target the app's OWN bundled Python,
    not your system Python — that is the copy the app actually uses):
        python\python.exe -m pip install --upgrade yt-dlp mutagen


TO REMOVE
─────────────
  Delete this folder. Nothing is left behind on your system.
  No registry entries, no AppData files, no traces.


TROUBLESHOOTING
────────────────
  "Python not found" on launch
      → Install Python from python.org and check "Add to PATH"
      → Restart your PC after installing Python

  Downloads fail or show errors
      → Open Update Plugins and update yt-dlp to the latest version
      → For age-restricted content, use the Site Cookies feature

  App won't start after moving the folder
      → Delete the electron\node_modules folder inside this directory,
        then relaunch — it will reinstall automatically

  Blank screen on launch
      → Right-click "EGM Downloader.exe" → Run as administrator

  Need more detail about a problem
      → The log file is egm_debug.log, saved in the data folder inside
        this folder (egm_debug.log.old is the previous one)
      → For a detailed startup error, open a command prompt in this
        folder and run these two commands:
            set EGM_SILENT=1
            python\python.exe launch.py
        (On the very first launch, before the python folder exists,
        use "python launch.py" as the second command instead.)


SUPPORT
────────
  https://egm.egerena.com
  https://egerena.com/apps/egm.html  •  contact@egerena.com
PORTINS

# Package into zip (no password — portable users don't expect one)
echo "   Packaging EGMd-portable.zip..."
python3 - <<PYZIP
import zipfile, os
from pathlib import Path

stage    = Path("$PORTABLE_STAGE")
zip_path = Path("$REPO_ROOT/dist/EGMd-portable.zip")

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
    for root, _, files in os.walk(stage):
        for fname in files:
            full = Path(root) / fname
            arc  = full.relative_to(stage)
            zf.write(full, arc)

size_mb = zip_path.stat().st_size / 1024 / 1024
print(f"   ✓ EGMd-portable.zip created ({size_mb:.2f} MB)")
PYZIP

# SHA256 for portable zip
PORTABLE_CHECKSUM=$(python3 -c "
import hashlib
h = hashlib.sha256()
h.update(open('$REPO_ROOT/dist/EGMd-portable.zip', 'rb').read())
print(h.hexdigest())
")
echo "   ✓ SHA256: $PORTABLE_CHECKSUM"
PORTABLE_SIZE=$(python3 -c "import os; print(os.path.getsize('$REPO_ROOT/dist/EGMd-portable.zip'))")
echo "   ✓ size: $PORTABLE_SIZE bytes"

# Cleanup stage
rm -rf "$PORTABLE_STAGE"

# Generate portable update JSON
echo "   Generating egm-portable-version.json..."
if [ -n "$NOTES" ]; then
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform windows-portable --notes "$NOTES" --checksum "$PORTABLE_CHECKSUM" --size-bytes "$PORTABLE_SIZE"
else
    python3 "$REPO_ROOT/scripts/gen-update-json.py" --platform windows-portable --checksum "$PORTABLE_CHECKSUM" --size-bytes "$PORTABLE_SIZE"
fi
echo ""

# NOTE: last-released-build.txt is intentionally NOT bumped here. This script runs for both
# test builds and the real release build, and there is no way to tell them apart from inside
# the script: bumping the marker on every build once let a test build mark its build number
# as "released", which blocked the real release's own feed validation later (build must be
# greater than last released). Bump the marker as a deliberate, separate, LAST step of the
# actual release process, once the release is genuinely confirmed shipped.
echo ""
echo "╔════════════════════════════════════════╗"
echo "║      ✅  WINDOWS BUILD DONE!           ║"
echo "╚════════════════════════════════════════╝"
echo ""
echo "   Commit: $HEAD_LINE"
echo ""
echo "   The feeds are NOT signed yet. Sign them before uploading anything:"
echo "   → python3 scripts/sign-manifest.py dist/egm-version.json <private key>"
echo "   → python3 scripts/sign-manifest.py dist/egm-portable-version.json <private key>"
echo ""
echo "   Upload to egerena.com/apps/:"
echo "   → dist/EGMd.zip"
echo "   → dist/egm-version.json"
echo "   → dist/EGMd-portable.zip"
echo "   → dist/egm-portable-version.json"
echo ""
