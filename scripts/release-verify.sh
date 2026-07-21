#!/usr/bin/env bash
# release-verify.sh — the standard pre-release verification sweep, one pass.
#
# Packages the existing manual sequence so no step can be partially skipped
# under time pressure. Adds NO new checks — every step below is the same
# command the team already runs by hand at each release cut (see
# FUTURE_FIXES_NO_ETA item 3 + CODEMASTER's addendum for the exact spec).
#
# Out of scope by design: scripts/apply-signed-checksums.py and
# scripts/verify-theme-batch.py — those run at different times
# (post-signing, per theme batch), not in the standard sweep.
#
# Usage: bash scripts/release-verify.sh   (from repo root)
# Exit:  0 = all checks passed, 1 = at least one failed.

set -u
cd "$(dirname "$0")/.." || exit 1

PASS=()
FAIL=()

run_check() {
  local name="$1"; shift
  echo ""
  echo "══ ${name} ════════════════════════════════════════"
  if "$@"; then
    echo "── ✅ PASS: ${name}"
    PASS+=("${name}")
  else
    echo "── ❌ FAIL: ${name}"
    FAIL+=("${name}")
  fi
}

# 1. Clean dist/ — stale feeds/binaries must not survive into a fresh cut
clean_dist() {
  rm -f dist/*.json dist/*.zip dist/*.exe 2>/dev/null
  echo "dist/ cleaned (json/zip/exe)"
  return 0
}

# 2. Version sync across every platform file
version_sync() {
  python3 scripts/validate-version-sync.py
}

# 3. Full test suite — CI-matching invocation (cd tests + run inside it;
#    this generates real dummy feeds first, which changes whether the one
#    feed-dependent test skips — a repo-root PYTHONPATH run gives a
#    DIFFERENT skip/pass count and is not equivalent)
test_suite() {
  ( cd tests && EGM_API_TOKEN=ci-test-token-not-secret python3 -m pytest -v --tb=short )
}

# 4. flake8 — syntax-error-class checks only (E9,F63,F7,F82), scoped exactly
#    like CI; a bare `flake8 .` floods the summary with unrelated style noise
flake8_syntax() {
  flake8 . --count --select=E9,F63,F7,F82 --exclude='*/electron/dist/*,linux/python/*'
}

# 5. CSS lint — every color: var(--muted) use must carry its annotation
css_lint() {
  bash scripts/lint-css-muted.sh
}

# 6. Root ↔ Linux mirror parity — exhaustive over every file pair that is
#    supposed to mirror (NOT scoped to git-touched files: full tree diff)
root_linux_parity() {
  # templates tree: byte-identical rule (requirements drift is version-sync's
  # check, which normalizes blank lines/comments — a raw diff here would be
  # stricter than the actual rule and produce false failures)
  if diff -rq templates linux/templates; then
    echo "root↔linux template mirrors byte-identical"
    return 0
  fi
  return 1
}

# JS syntax + patchnotes header/bullet-count guards: covered inside the
# pytest run above (tests/test_js_syntax.py, tests/test_parity.py) — no
# separate steps, per the addendum.

run_check "clean dist/"            clean_dist
run_check "version sync"           version_sync
run_check "test suite (CI-match)"  test_suite
run_check "flake8 syntax class"    flake8_syntax
run_check "CSS muted-lint"         css_lint
run_check "root↔linux parity"      root_linux_parity

echo ""
echo "════════════════════════════════════════════════════"
echo " Release verification summary"
echo "════════════════════════════════════════════════════"
for c in "${PASS[@]:-}"; do [ -n "$c" ] && echo "  ✅ $c"; done
for c in "${FAIL[@]:-}"; do [ -n "$c" ] && echo "  ❌ $c"; done
echo "────────────────────────────────────────────────────"
if [ "${#FAIL[@]}" -gt 0 ]; then
  echo " ❌ RELEASE VERIFY FAILED — ${#FAIL[@]} check(s) failed"
  exit 1
fi
echo " ✅ ALL CHECKS PASSED — clear to cut the release"
exit 0
