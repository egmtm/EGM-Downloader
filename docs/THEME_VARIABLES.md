# Theme CSS Variable Discipline

This document explains the intended use of theme CSS variables, particularly
around the distinction between `--muted` and `--text2`. The `--muted` rule
is CI-enforced; the rest is convention.

## Variable reference

| Variable | Intended use |
|---|---|
| `--bg` | Page background |
| `--surf` / `--surf2` / `--surf3` | Surface layers (cards, panels) |
| `--border` / `--border2` | Hairline borders, dividers |
| `--acc` / `--acc-h` | Accent color (CTAs, highlights), accent hover |
| `--text` | Primary visible text — full readability priority |
| `--text2` | Secondary visible text — placeholders, labels, helpers, sidebar categories. Apply `opacity: 0.55-0.70` if you need secondary-text visual weight. |
| `--muted` | **Two valid uses:** (a) scaffolding-quiet text — footers, empty states, hints, loading messages, decorative icons, supplementary metadata, ghost buttons; (b) borders/dividers/hairlines. **Not for functional text users actively read.** |
| `--shadow` | Drop shadows |
| `--thumb-bg` / `--log-bg` / `--log-text` | Specialized surfaces |
| `--modal-overlay` / `--modal-shadow` | Modal/dialog chrome |
| `--btn-primary-text` / `--btn-on-accent` / `--btn-red-border` | Button-specific tokens |

## The `--muted` rule (CI-enforced)

**Every `color: var(--muted)` in template files must be annotated within 5 preceding lines:**

```css
/* lint-allow-muted: <reason> */
.example { color: var(--muted); ... }
```

```html
<!-- lint-allow-muted: <reason> -->
<div style="color:var(--muted)">…</div>
```

```javascript
// lint-allow-muted: <reason>
el.style.cssText = 'color:var(--muted);…';
```

CI fails on push or PR if any `color: var(--muted)` lacks the annotation. The lint is `scripts/lint-css-muted.sh`.

**Why this rule exists:** four bugs across v0.99.11–v0.99.13 traced to the same root cause — `--muted` applied to functional text users need to read (placeholders, option labels, sidebar categories, table headers). On most themes `--muted` is intentionally close to the background, so it becomes unreadable when used as `color:` for primary or functional text. The annotation requirement forces explicit reasoning at the point of writing CSS.

## Standard reasons

Use a short-tag reason that fits one of these categories:

| Tag | When to use |
|---|---|
| `ghost-button` | Quiet button visually quiet until hover reveals the action color |
| `hint` | Hint text supposed to recede |
| `empty-state` | "No items" / "Nothing found" messaging |
| `decorative-icon` | Icons that are purely visual scaffolding |
| `footer` | Footer text and links |
| `loading-state` | "Loading…" or similar transient state messages |
| `supplementary-note` | Small notes / asides secondary to primary content |
| `supplementary-metadata` | Counts, sizes, statusbar text — non-interactive metadata |

If a new use case doesn't fit any of these, add a new tag to this doc and use it in the annotation. The categories evolve with the codebase.

## When you reach for `--muted` and pause

Ask yourself: *will users need to actively read this text, or is it supposed to recede visually?*

- **Recede (use `--muted`):** decorative, scaffolding, hint, status, metadata
- **Read (use `--text2` with opacity):** placeholders prompting input, navigation labels, option labels users select among, button text, table column headers, error messages

If you can't decide → `--text2 + opacity` is the safer default. Erroneously prominent is preferable to erroneously unreadable.

## Adding a new theme variable

If you're adding a new theme CSS variable:

1. Add it to **all theme blocks** in `theme_styles.html` (currently 259 CSS-backed themes + `custom`)
2. Add it to the reference table in this doc
3. State the intended use AND what it should NOT be used for
4. Consider whether CI should enforce its scope (like `--muted` is enforced)

## Related discipline

- `tests/test_parity.py` — Tier 1 parity tests requiring every theme have all required variables
- `scripts/lint-css-muted.sh` — the CI-enforced `--muted:color` rule
- `templates/theme_styles.html` — the 259 CSS-backed theme definitions, source of truth
- `templates/themes.html` — theme registry (must stay in sync with `theme_styles.html`)
- `templates/index.html` — also holds THEME_DATA and the THEMES array (260 entries including `custom`)

## History

- **v0.99.11:** First bug — `textarea#urls::placeholder` + `.opt-label` using `--muted`. Fixed.
- **v0.99.12:** Second bug — sidebar `.cat-section` + `.section-caret` same pattern. Fixed.
- **v0.99.13:** Third + fourth bugs — `.qual-label`, themes search placeholder, history search placeholder, table headers `.th`. Fixed. Full audit performed across all 4 template files (21 instances audited, 4 bugs fixed, 17 kept as legitimate `--muted`).
- **v0.99.13 + this doc:** Discipline locked in CI via `scripts/lint-css-muted.sh`. Every legitimate `--muted` use now annotated. Zero borderline cases in the audit.
