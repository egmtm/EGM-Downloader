#!/usr/bin/env python3
"""Verify a theme-batch delivery before wiring it in.

Every theme batch this cycle got the same checks written ad hoc: does each
theme have the full current CSS variable set, do THEME_DATA's swatch colors
actually match the CSS block's real values, and does every new key collide
with something already in the catalog. This script runs exactly that
sequence against the delivery doc directly, before any wiring happens.

Usage:
    python3 scripts/verify-theme-batch.py path/to/themes_batch.md
    python3 scripts/verify-theme-batch.py --polish path/to/themes_batch.md

The default mode checks NEW themes: every key must be absent from the catalog.

--polish checks replacements for themes that already exist:
  - every key must already be in the catalog (a new key is an error);
  - the THEME_DATA block is optional. Without it the CSS --bg/--surf/--acc must
    equal the catalog's current swatch data, so a color change that forgets the
    THEME_DATA entry is caught; with it, label and category must be unchanged;
  - a gradient --bg is accepted only for a key whose swatch data is already a
    gradient, and the swatch is compared with the first color stop.

Expects the fenced code blocks every delivery doc has used: the CSS blocks in
a ```css fence and the THEME_DATA entries in a ```js fence (headings are not read):
    ```css
    body.somekey { --bg: #...; ... }
    ```
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

# A THEME_DATA entry. The key may be quoted (aurora-deep) and the label may use
# double quotes when it holds an apostrophe, so both forms are parsed.
_LABEL = r"""(?:'((?:[^'\\]|\\.)*)'|"([^"]*)")"""
_ENTRY = re.compile(
    r"^\s*['\"]?([\w-]+)['\"]?\s*:\s*\{\s*label:\s*" + _LABEL
    + r",\s*bg:\s*'([^']*)',\s*surf:\s*'([^']*)',\s*acc:\s*'([^']*)',\s*cat:\s*'([^']*)'\s*\}",
    re.MULTILINE,
)
_BLOCK = re.compile(r"^\s*body\.([\w-]+)\s*\{(.*?)\n\s*\}", re.DOTALL | re.MULTILINE)
# A declaration starts a line or follows a ';' (some blocks keep two on one line).
_START = r"(?:^|(?<=;))[ \t]*"
_DECL = re.compile(_START + r"(--[\w-]+):\s*([^;\n]*);", re.MULTILINE)
_STRAY = re.compile(r"""[{}<>;"'`\\]""")
_HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def parse_theme_data(text: str) -> dict:
    """key -> (label, bg, surf, acc, cat) for every THEME_DATA entry in text."""
    out = {}
    for m in _ENTRY.finditer(text):
        g = m.groups()
        out[g[0]] = (g[1] if g[1] is not None else g[2],) + g[3:]
    return out


def get_catalog() -> dict:
    return parse_theme_data((ROOT / "templates" / "theme_data.html").read_text(encoding="utf-8"))


def count_vars(body: str) -> int:
    return len(re.findall(_START + r"--[\w-]+\s*:", body, re.MULTILINE))


def get_reference_var_count() -> int:
    """The current canonical CSS variable count, read from the live 'void'
    theme rather than hardcoded -- stays correct if the schema ever grows."""
    styles = (ROOT / "templates" / "theme_styles.html").read_text(encoding="utf-8")
    m = re.search(r"^body\.void \{(.*?)\n\}", styles, re.DOTALL | re.MULTILINE)
    if not m:
        raise RuntimeError("Could not find body.void in theme_styles.html to establish the reference schema")
    return count_vars(m.group(1))


def get_existing_keys() -> set:
    theme_js = (ROOT / "templates" / "js" / "_theme.html").read_text(encoding="utf-8")
    return set(re.findall(r"'([a-z0-9]+)'", theme_js))


def parse_delivery(doc: str, polish: bool = False):
    """The fenced ```css block(s) hold the CSS, the ```js block(s) the THEME_DATA
    entries. Headings are not read, so any section heading works."""
    css = re.findall(r"```css\n(.*?)\n```", doc, re.DOTALL)
    data = re.findall(r"```js\n(.*?)\n```", doc, re.DOTALL)
    if not css or (not data and not polish):
        raise RuntimeError("Could not find a ```css block and a ```js block (the CSS and the THEME_DATA entries)")
    return dict(_BLOCK.findall("\n".join(css))), parse_theme_data("\n".join(data))


def first_stop(value: str):
    m = re.search(r"#[0-9a-fA-F]{3,8}\b", value)
    return m.group(0) if m else None


def swatch_problem(var_name, actual, claimed, polish):
    """None when the CSS value agrees with the swatch data, else the message."""
    if polish and claimed.startswith("linear-gradient("):
        # Gradient themes keep their gradient. THEME_DATA holds a shorter gradient
        # for most of them, so the check is the first color stop.
        if not actual.startswith("linear-gradient("):
            return f"{var_name} = {actual!r} but this theme's swatch data is a gradient (gradient themes keep their gradient)"
        a, c = first_stop(actual), first_stop(claimed)
        if not a or not c or a.lower() != c.lower():
            return f"{var_name} first color stop is {a}, swatch data says {c}"
        return None
    if not _HEX.match(actual):
        return f"{var_name} = {actual!r} is not a valid hex color (malformed value?)"
    if actual.lower() != claimed.lower():
        return f"{var_name} mismatch -- THEME_DATA says {claimed}, CSS says {actual}"
    return None


def malformed_values(body: str):
    """Typos across every variable in a block (textures are free-form, skipped)."""
    for vm in _DECL.finditer(body):
        var_name, value = vm.group(1), vm.group(2).strip()
        if var_name.startswith("--bg-texture"):
            continue
        if value.startswith("--"):
            yield (f"{var_name} = {value!r} looks like a typo -- a CSS value "
                   f"starting with '--' is never valid (missing '#' before a hex color?)")
        elif _STRAY.search(value):
            yield f"{var_name} = {value!r} holds a stray quote, semicolon, brace or backslash"
        elif re.match(r"^#[0-9a-fA-F]+$", value) and len(value) - 1 not in (3, 4, 6, 8):
            yield f"{var_name} = {value!r} is not a color (a hex color has 3, 4, 6 or 8 digits)"


def main():
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        sys.exit(0)
    polish = "--polish" in argv
    args = [a for a in argv if a != "--polish"]
    if len(args) != 1 or args[0].startswith("-"):
        print("Usage: python3 scripts/verify-theme-batch.py [--polish] path/to/themes_batch.md")
        sys.exit(1)
    if not Path(args[0]).is_file():
        print(f"File not found: {args[0]}")
        sys.exit(1)

    doc = Path(args[0]).read_text(encoding="utf-8")

    ref_vars = get_reference_var_count()
    existing_keys = get_existing_keys()
    catalog = get_catalog()
    css_blocks, entries = parse_delivery(doc, polish)

    mode = "polish" if polish else "new themes"
    print(f"Mode: {mode}")
    print(f"Reference schema: {ref_vars} CSS variables (from the live 'void' theme)")
    print(f"Parsed {len(entries)} THEME_DATA entries, {len(css_blocks)} CSS blocks\n")

    problems = []

    # THEME_DATA entries without a matching CSS block, or vice versa (a polish
    # batch may leave THEME_DATA out when no swatch color changes)
    css_keys = set(css_blocks)
    only_in_data = set(entries) - css_keys
    only_in_css = css_keys - set(entries)
    if only_in_data:
        problems.append(f"THEME_DATA entries with no matching CSS block: {sorted(only_in_data)}")
    if only_in_css and not polish:
        problems.append(f"CSS blocks with no matching THEME_DATA entry: {sorted(only_in_css)}")

    for key in sorted(css_keys if polish else entries):
        entry = entries.get(key)
        before = len(problems)
        row = [f"{key:22s} ({entry[0] if entry else catalog.get(key, ('?',))[0]})"]

        if polish:
            known = catalog.get(key)
            if known is None:
                problems.append(f"{key}: NEW KEY -- polish mode only changes themes that already exist")
                row.append("NEW KEY")
            elif entry:
                if entry[0] != known[0]:
                    problems.append(f"{key}: label changed ({known[0]!r} to {entry[0]!r}); polish keeps the label")
                if entry[4] != known[4]:
                    problems.append(f"{key}: category changed ({known[4]!r} to {entry[4]!r}); polish keeps the category")
        elif key in existing_keys:
            problems.append(f"{key}: COLLISION -- already exists in templates/js/_theme.html")
            row.append("COLLISION")

        body = css_blocks.get(key)
        if body is None:
            row.append("no CSS block")
        else:
            var_count = count_vars(body)
            if var_count != ref_vars:
                problems.append(f"{key}: {var_count} CSS vars, expected {ref_vars}")
                row.append(f"vars: {var_count}/{ref_vars} MISMATCH")
            else:
                row.append(f"vars: {var_count}/{ref_vars} ok")

            # Swatch-vs-CSS consistency for the 3 vars THEME_DATA duplicates. A
            # polish batch without an entry is checked against the catalog's.
            claimed = entry[1:4] if entry else (catalog[key][1:4] if key in catalog else None)
            if claimed:
                for var_name, want in zip(("--bg", "--surf", "--acc"), claimed):
                    vm = re.search(_START + rf"{re.escape(var_name)}:\s*([^;\n]*);", body, re.MULTILINE)
                    if not vm:
                        problems.append(f"{key}: {var_name} not found in its own CSS block")
                        continue
                    msg = swatch_problem(var_name, vm.group(1).strip(), want, polish)
                    if msg:
                        if polish and not entry:
                            msg += " -- the color changed, so send a THEME_DATA entry (and the static row) with it"
                        problems.append(f"{key}: {msg}")

            # Typos across EVERY variable in the block, not just the 3 swatch ones
            # (a stray '--40a870' for '#40a870', a stray quote, a 7 digit hex).
            for msg in malformed_values(body):
                problems.append(f"{key}: {msg}")
            if len(problems) == before:
                row.append("swatch: ok")

        print("  " + "  ".join(row))

    print()
    if problems:
        print(f"{len(problems)} problem(s) found:")
        for p in problems:
            print(f"  x {p}")
        sys.exit(1)
    else:
        print(f"All {len(entries) if not polish else len(css_blocks)} themes check out clean. Safe to wire in.")


if __name__ == "__main__":
    main()
