# DEFERRED ITEMS

Internal reference — items intentionally deferred from active cycles.
**Not for public repo.** Last updated: June 24, 2026.

---

## v1.3 POLYGLOT (active — next cycle)

- **Language switcher** — wire `data-i18n` hooks across all templates (CODEMASTER)
- **Language selector in footer** — first row, Option A pill style, accented border
- **OS locale auto-detect** — on first launch, detect OS locale and apply; user can override via footer selector
- **Hide language selector** toggle in Advanced → General, below Import settings, above Reinstall Deno; inline confirmation modal; subtitle clarifies it's reversible
- **Corpus ready** — 316 keys × 10 locales on `translations/v1.2-strings`, pending merge after Linguist pass
- **Native-speaker review** — design-vocab terms (`Surface`, `Accent`, `Danger`) flagged for v1.3 native-tester pass; plan in `POLYGLOT_Native_Tester_Plan_v0_1.md`

---

## Deferred — no ETA

### Custom Windows installer UI
Replace NSIS default gray wizard with a dark, on-brand installer matching the app aesthetic.
Full mockup designed (June 24, 2026) — sidebar progress, dark background, styled dropdown,
language selection on first step. Requires either NSIS plugin (Modern UI 2, ~70% of mockup)
or Electron-rendered installer window (full mockup, significant effort).
**Note:** Custom installer UI has its own security surface — OVERSEER review required.
Parked until after POLYGLOT ships.

### EV code-signing certificate
Addresses Windows Defender false positive (heuristic targeting Electron + embedded Python).
Planned for next year. No action until procurement.

### Browser extension
Moved back from v1.2. Scope and design TBD. No ETA.

### PHP webhook automation (egerena.com)
Eliminates manual 2-click cPanel deploy. WEBHOOK_HANDOFF.md has the spec.
~30–45 min session. Date TBD — coordinate with Web Wizard.

### Puerto Rico theme collection (14 themes — personal, no rush)
Deeply personal. Treat with care. No ETA.
- Holidays: San Sebastián, Noche de San Juan, Las Parrandas
- Nature: El Yunque
- Icons: Bad Bunny, Tito Trinidad
- Ponce: Parque de Bombas, La Cruceta del Vigía, La Guancha, Las Letras de Ponce
- Island: Old San Juan, La Perla, Isla de Culebra, El Morro

---

## Completed (reference)

- ✅ v1.1 IGNITION — shipped June 15, 2026
- ✅ v1.1.1 TRULY YOURS — shipped June 20, 2026
- ✅ v1.1.2 YOURS TO KEEP — shipped June 21, 2026
- ✅ v1.2.0 CANVAS — shipped June 23, 2026
- ✅ v1.2.1 CANVAS RELOADED — shipped June 24, 2026
- ✅ Electron 42.5.0 bump — shipped with v1.2.1
- ✅ Theme Creator (in-page docked panel)
- ✅ Universal MP4 H.264
- ✅ Multi-theme Save to app with favorites
- ✅ index_scripts.html split into 8 modules
- ✅ validate-version-sync.py + pre-commit/pre-push hooks
