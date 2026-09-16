#!/bin/bash
# check-dmg-toolchain.sh — probe whether this Mac's hdiutil pipeline can build a DMG.
#
# Exercises, in miniature and in order, the exact sequence dmgbuild runs inside
# electron-builder's DMG target: create (APFS) -> attach -> detach -> convert to
# UDZO. Each step runs under a watchdog so a hang becomes a labelled TIMEOUT
# instead of a stuck terminal.
#
#   PASS               -> the DMG target can be re-enabled (flip the zip-only
#                         switch in mac/BUILD.sh and rebuild).
#   FAIL/TIMEOUT at N  -> keep shipping zip-only; the failing step name is the
#                         diagnostic. Re-run after every macOS point update and
#                         every electron-builder upgrade.
#
# If a step TIMES OUT and you are connected over SSH: retry once from a GUI
# console session on the machine itself before concluding anything — hdiutil's
# man page has long documented "apparent hangs while trying to access /dev
# entries while logged in remotely (an authorization panel is waiting on
# console)", and major macOS upgrades routinely reset those consents.
set -u

STEP_TIMEOUT="${STEP_TIMEOUT:-90}"   # seconds per step
WORK="$(mktemp -d /tmp/egm-dmg-probe.XXXXXX)"
IMG="$WORK/probe.dmg"
OUT="$WORK/probe-udzo.dmg"
VOL="EGMPROBE-$$"
MOUNTPOINT=""

cleanup() {
  [ -n "$MOUNTPOINT" ] && hdiutil detach "$MOUNTPOINT" -force >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

# run_step <label> <cmd...>  — watchdog-wrapped; rc 137 => killed => TIMEOUT
run_step() {
  local label="$1"; shift
  echo "── $label"
  "$@" >"$WORK/step.log" 2>&1 &
  local pid=$!
  ( sleep "$STEP_TIMEOUT" && kill -9 "$pid" 2>/dev/null ) &
  local wd=$!
  wait "$pid"; local rc=$?
  kill "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
  if [ "$rc" -eq 137 ]; then
    echo "✗ TIMEOUT after ${STEP_TIMEOUT}s at: $label"
    echo "  (hdiutil never returned — check the console session for a pending"
    echo "   authorization dialog, and Console.app for diskarbitrationd /"
    echo "   diskimagesiod errors. 'ps aux | grep hdiutil' + 'sample <pid>'"
    echo "   shows where it is blocked.)"
    exit 2
  elif [ "$rc" -ne 0 ]; then
    echo "✗ FAILED (rc=$rc) at: $label"
    sed 's/^/  | /' "$WORK/step.log" | tail -12
    exit 1
  fi
}

run_step "1/4 hdiutil create (APFS, 64 MB)" \
  hdiutil create -size 64m -fs APFS -volname "$VOL" -format UDRW "$IMG"

run_step "2/4 hdiutil attach (-nobrowse)" \
  hdiutil attach -nobrowse -noverify "$IMG"
MOUNTPOINT="/Volumes/$VOL"
if [ ! -d "$MOUNTPOINT" ]; then
  echo "✗ FAILED: attach reported success but $MOUNTPOINT does not exist"
  exit 1
fi
touch "$MOUNTPOINT/write-test" 2>/dev/null || { echo "✗ FAILED: volume mounted read-only"; exit 1; }

run_step "3/4 hdiutil detach" \
  hdiutil detach "$MOUNTPOINT"
MOUNTPOINT=""

run_step "4/4 hdiutil convert (UDRW -> UDZO)" \
  hdiutil convert "$IMG" -format UDZO -o "$OUT"

echo "✓ PASS — create/attach/detach/convert all completed. The hdiutil pipeline"
echo "  works on this Mac; the electron-builder DMG target can be re-enabled."
