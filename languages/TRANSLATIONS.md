# EGM Downloader — Translation Changelog

Translation files live in this folder as JSON locale files.
Each file covers one language and contains the same set of string keys as `en.json` (the English base).

**Languages:** Arabic · German · Spanish · French · Italian · Japanese · Dutch · Portuguese · Russian

---

## How to contribute a translation

1. In the app: **Advanced → Export language file**
2. Edit the exported JSON — translate the values, leave the keys untouched
3. Test by importing: **Advanced → Import language file**
4. Open a pull request with your changes to the relevant `languages/*.json` file

Rules: keep every key present, preserve `{0}` / `{1}` / `{2}` placeholders exactly, leave brand and tool names untouched (yt-dlp, ffmpeg, Deno, YouTube, etc.).

---

## Changelog

### 2026-06-11 — Quality audit pass (v0.97.5 → 1.0.3)

First review pass against the existing 9 translations. No keys were added or removed.
Fixes applied across 5 languages:

**German (de)**
- `url.btn.download_all_audio`: added missing "Alle" — was "Audio herunterladen", now "Alles Audio herunterladen" (consistent with "Alle Videos herunterladen")

**Italian (it)**
- `quality.option.360.desc`: corrected superlative — was "file più piccoli" (smaller), now "file minimi" (smallest), matching the English "smallest files"

**Russian (ru)**
- `url.btn.paste_fetch`: aligned fetch terminology — was "Вставить и загрузить", now "Вставить и получить" (consistent with `url.btn.fetch` = "Получить инфо")
- `status.bulk_progress`: preserved intentional double space before active-count group, matching all other languages

**Arabic (ar)**
- `status.bulk_progress`: same double-space fix as Russian above

**Dutch (nl)**
- `themes.filter.seasonal`: shortened "Seizoensgebonden ✦" → "Seizoens ✦" for UI fit (filter pill width)


### 2026-06-11 — Fetch term correction in Spanish and Portuguese

- `url.btn.fetch` and `url.btn.paste_fetch`: replaced "Buscar" (search) with "Obtener" (ES) and "Obter" (PT) — more precise distinction between fetch (retrieve metadata) and download (save file)
---

### 2026-04-26 — Initial translation set (v0.97.5)

All 9 languages created with 221 string keys each.
