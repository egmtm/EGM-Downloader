# EGM Downloader

**v0.91** — Video downloader for 1000+ sites.

> **Unified repository** — Windows live · macOS coming · Linux coming

---

## Repository Structure

```
EGM-Downloader/
│
├── app.py                      ← Flask backend         [shared — all platforms]
├── templates/index.html        ← UI                    [shared — all platforms]
├── static/                     ← CSS, JS, icons        [shared — all platforms]
│
├── electron/                   ← Electron shell        [Windows — Mac/Linux in Phase 2]
│   ├── main.js
│   ├── package.json
│   └── preload.js
│
├── windows/                    ← Windows packaging     [NSIS spec goes here]
├── mac/                        ← macOS packaging       [Phase 2]
├── linux/                      ← Linux packaging       [Phase 3]
│
├── scripts/                    ← Build automation      [all platforms]
│   ├── bump-version.py         ← Increment build, sync all version strings
│   ├── gen-update-json.py      ← Generate platform update JSONs
│   └── add-patchnote.py        ← Prepend to patchnotes.txt
│
├── version.json                ← Single source of truth for version/build
├── requirements.txt            ← Python deps
├── patchnotes.txt
└── launch.py / launch.bat / EGM Downloader.vbs   ← Windows launchers
```

---

## Build Workflow

### 1. Bump build number (run before every build)
```bash
python scripts/bump-version.py
# Also bump version string:
python scripts/bump-version.py --version 0.92
# Preview without writing:
python scripts/bump-version.py --dry-run
```
Updates: `version.json`, `app.py`, `templates/index.html`, `electron/package.json`

### 2. Add patch notes
```bash
python scripts/add-patchnote.py "Fixed playlist bug" "Improved speed"
```

### 3. Generate update JSONs
```bash
python scripts/gen-update-json.py --notes "Fixed X; Added Y"
# Windows only:
python scripts/gen-update-json.py --platform windows --notes "Fixed X"
```
Outputs to `dist/` — upload to `egerena.com/apps/`.

---

## Platform Notes

| Platform | Status     | Shell       | Distribution   |
|----------|------------|-------------|----------------|
| Windows  | ✅ Live     | Electron    | EGMd.zip       |
| macOS    | 🔜 Phase 2  | Electron    | EGMdM.zip      |
| Linux    | 🔜 Phase 3  | Electron    | EGMdL.zip      |

---

## Version Management

`version.json` is the master record. Never edit version numbers manually in individual files — always run `scripts/bump-version.py`.
