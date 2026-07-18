#!/usr/bin/env python3
"""Verify an Artist theme-batch delivery before wiring it in.

Every theme batch this cycle got the same checks written ad hoc: does each
theme have the full current CSS variable set, do THEME_DATA's swatch colors
actually match the CSS block's real values, and does every new key collide
with something already in the catalog. This script runs exactly that
sequence against the delivery doc directly, before any wiring happens.

Usage:
    python3 scripts/verify-theme-batch.py path/to/themes_batch.md

Expects the same two fenced code blocks every delivery doc has used all
cycle:
    ## CSS — paste into theme_styles.html
    ```css
    body.somekey { --bg: #...; ... }
    ```
    ## THEME_DATA entries
    ```js
    somekey: {label:'Some Key', bg:'#...', surf:'#...', acc:'#...', cat:'...'},
    ```

Does NOT wire anything in, does NOT touch the repo's theme files, and does
NOT replace judgment calls this cycle needed a human for (typo fixes,
differentiation-from-existing-theme calls, category placement). It only
mechanizes the repetitive structural checks that preceded those calls every
single batch.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def get_reference_var_count() -> int:
    """The current canonical CSS variable count, read from the live 'void'
    theme rather than hardcoded -- stays correct if the schema ever grows."""
    styles = (ROOT / "templates" / "theme_styles.html").read_text()
    m = re.search(r"^body\.void \{(.*?)\n\}", styles, re.DOTALL | re.MULTILINE)
    if not m:
        raise RuntimeError("Could not find body.void in theme_styles.html to establish the reference schema")
    return len(re.findall(r"^\s*--[\w-]+:", m.group(1), re.MULTILINE))


def get_existing_keys() -> set:
    theme_js = (ROOT / "templates" / "js" / "_theme.html").read_text()
    return set(re.findall(r"'([a-z0-9]+)'", theme_js))


def parse_delivery(doc: str):
    css_m = re.search(r"## CSS.*?\n\n```css\n(.*?)\n```", doc, re.DOTALL)
    data_m = re.search(r"## THEME_DATA entries.*?\n```js\n(.*?)\n```", doc, re.DOTALL)
    if not css_m or not data_m:
        raise RuntimeError("Could not find both '## CSS' and '## THEME_DATA entries' fenced blocks")

    css_blocks = dict(re.findall(r"body\.(\w+) \{(.*?)\n\}", css_m.group(1), re.DOTALL))
    entries = re.findall(
        r"(\w+):\s*\{label:\s*['\"]([^'\"]+)['\"],\s*bg:\s*'(#[0-9a-fA-F]+)',\s*surf:\s*'(#[0-9a-fA-F]+)',\s*acc:\s*'(#[0-9a-fA-F]+)'",
        data_m.group(1),
    )
    return css_blocks, entries


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/verify-theme-batch.py path/to/themes_batch.md")
        sys.exit(1)

    doc_path = Path(sys.argv[1])
    doc = doc_path.read_text()

    ref_vars = get_reference_var_count()
    existing_keys = get_existing_keys()
    css_blocks, entries = parse_delivery(doc)

    print(f"Reference schema: {ref_vars} CSS variables (from the live 'void' theme)")
    print(f"Parsed {len(entries)} THEME_DATA entries, {len(css_blocks)} CSS blocks\n")

    problems = []

    # THEME_DATA entries without a matching CSS block, or vice versa
    data_keys = {k for k, *_ in entries}
    css_keys = set(css_blocks)
    only_in_data = data_keys - css_keys
    only_in_css = css_keys - data_keys
    if only_in_data:
        problems.append(f"THEME_DATA entries with no matching CSS block: {sorted(only_in_data)}")
    if only_in_css:
        problems.append(f"CSS blocks with no matching THEME_DATA entry: {sorted(only_in_css)}")

    for key, label, bg, surf, acc in entries:
        row = [f"{key:22s} ({label})"]

        # Collision check against the existing catalog
        if key in existing_keys:
            problems.append(f"{key}: COLLISION — already exists in templates/js/_theme.html")
            row.append("COLLISION")

        body = css_blocks.get(key)
        if body is None:
            row.append("no CSS block")
        else:
            var_count = len(re.findall(r"^\s*--[\w-]+:", body, re.MULTILINE))
            if var_count != ref_vars:
                problems.append(f"{key}: {var_count} CSS vars, expected {ref_vars}")
                row.append(f"vars: {var_count}/{ref_vars} MISMATCH")
            else:
                row.append(f"vars: {var_count}/{ref_vars} ok")

            # Swatch-vs-CSS consistency for the 3 vars THEME_DATA duplicates
            for var_name, claimed in (("--bg", bg), ("--surf", surf), ("--acc", acc)):
                vm = re.search(rf"{re.escape(var_name)}:\s*(\S+?);", body)
                if not vm:
                    problems.append(f"{key}: {var_name} not found in its own CSS block")
                    continue
                actual = vm.group(1)
                if not re.match(r"^#[0-9a-fA-F]{3,8}$", actual):
                    problems.append(f"{key}: {var_name} = {actual!r} is not a valid hex color (malformed value?)")
                elif actual.lower() != claimed.lower():
                    problems.append(f"{key}: {var_name} mismatch — THEME_DATA says {claimed}, CSS says {actual}")

            # General malformed-value check across EVERY variable in the block,
            # not just the 3 swatch ones -- catches the exact real bug found in
            # a prior batch (a stray '--40a870' instead of '#40a870' in
            # --green, which the swatch-only check above would never see since
            # --green isn't one of the 3 duplicated-in-THEME_DATA vars).
            for vm in re.finditer(r"^\s*(--[\w-]+):\s*(\S+?);", body, re.MULTILINE):
                var_name, value = vm.group(1), vm.group(2)
                if value.startswith("--"):
                    problems.append(
                        f"{key}: {var_name} = {value!r} looks like a typo — a CSS value "
                        f"starting with '--' is never valid (missing '#' before a hex color?)"
                    )
            if not problems or not any(p.startswith(key) for p in problems):
                row.append("swatch: ok")

        print("  " + "  ".join(row))

    print()
    if problems:
        print(f"{len(problems)} problem(s) found:")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    else:
        print(f"All {len(entries)} themes check out clean. Safe to wire in.")


if __name__ == "__main__":
    main()
