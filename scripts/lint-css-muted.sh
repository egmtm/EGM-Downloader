#!/usr/bin/env bash
# CSS discipline check — every `color:var(--muted)` use must be preceded
# (within 5 lines) by an annotation: `lint-allow-muted: <reason>`.
#
# Rule: --muted is for scaffolding-quiet text (footers, hints, empty states,
# loading messages, decorative icons, supplementary metadata, ghost buttons)
# AND for borders/dividers/hairlines (not subject to this lint — we only
# check `color:` uses). For functional text users actively read, use
# --text2 with opacity tuning (0.55-0.70) instead.
#
# History: bug pattern surfaced 4 times across 3 release cycles before
# this lint was added (v0.99.11 placeholders/labels, v0.99.12 sidebar,
# v0.99.13 qual-label/search/table-headers). Lockdown to prevent #5.

set -euo pipefail

VIOLATIONS=()

# Iterate over every line containing `color:` followed by var(--muted)
while IFS= read -r match; do
    file="${match%%:*}"
    rest="${match#*:}"
    line_num="${rest%%:*}"

    # Look at the 5 lines immediately preceding the match
    start=$((line_num - 5 > 0 ? line_num - 5 : 1))
    end=$((line_num - 1))

    if [[ $start -le $end ]]; then
        preceding=$(sed -n "${start},${end}p" "$file")
    else
        preceding=""
    fi

    if ! grep -q "lint-allow-muted:" <<< "$preceding"; then
        VIOLATIONS+=("$file:$line_num")
    fi
done < <(grep -rn "color:\s*var(--muted)" templates/ linux/templates/ 2>/dev/null || true)

if [[ ${#VIOLATIONS[@]} -gt 0 ]]; then
    echo "❌ CSS lint failed — 'color: var(--muted)' without 'lint-allow-muted:' annotation"
    echo ""
    printf '   %s\n' "${VIOLATIONS[@]}"
    echo ""
    echo "Rule: every 'color: var(--muted)' must be annotated within 5 preceding lines:"
    echo ""
    echo "      /* lint-allow-muted: <reason> */     ← for CSS blocks"
    echo "      <!-- lint-allow-muted: <reason> -->  ← for HTML inline style"
    echo "      // lint-allow-muted: <reason>        ← for JS style.cssText"
    echo ""
    echo "Suggested reasons: ghost-button, hint, empty-state, decorative-icon,"
    echo "footer, loading-state, supplementary-note, supplementary-metadata"
    echo ""
    echo "For visible text users need to read, use --text2 with opacity 0.55-0.70."
    echo "See docs/THEME_VARIABLES.md for the full discipline."
    exit 1
fi

echo "✅ CSS lint passed — all 'color: var(--muted)' uses are annotated"
