# EGM Downloader

![Version Sync](https://github.com/egmtm/EGM-Downloader/workflows/Validate%20Version%20Sync/badge.svg)
![Python Lint](https://github.com/egmtm/EGM-Downloader/workflows/Lint%20Python/badge.svg)
![JavaScript Lint](https://github.com/egmtm/EGM-Downloader/workflows/Lint%20JavaScript/badge.svg)

**v0.91** — Video downloader for 1000+ sites.

> **Unified repository** — Windows live · macOS coming · Linux coming

---

## Repository Structure

```
EGM-Downloader/
│
├── app.py                      ← Flask backend         [shared — all platforms]
├── templates/index.html        ← UI                    [shared — Windows + Mac]
├── static/                     ← CSS, JS, icons        [shared — all platforms]
│
├── windows/                    ← Windows platform
│   ├── electron/               ← Windows Electron shell
│   │   ├── main.js
│   │   ├── package.json
│   │   └── preload.js
│   ├── launch.py               ← Windows launcher (downloads Node/Electron)
│   ├── launch.bat
│   ├── EGM Downloader.vbs
│   └── instructions.txt
│
├── mac/                        ← macOS platform
│   ├── electron/               ← Mac Electron shell + electron-builder config
│   │   ├── main.js
│   │   ├── package.json
│   │   ├── preload.js
│   │   ├── splash.html
│   │   └── entitlements.mac.plist
│   ├── BUILD.sh                ← Mac build script
│   └── BUILD_NOTES.txt
│
├── linux/                      ← Linux platform
│   ├── electron/               ← Linux Electron shell + electron-builder config
│   │   ├── main.js
│   │   ├── package.json
│   │   ├── preload.js
│   │   ├── splash.html
│   │   └── build/after-pack.js ← AppImage sandbox fix
│   ├── app.py                  ← Linux-specific backend (AppImage paths)
│   ├── templates/index.html    ← Linux-specific UI
│   ├── requirements.txt        ← Linux deps (no pyzipper)
│   ├── BUILD.sh                ← Linux build script
│   └── INSTRUCTIONS.txt
│
├── scripts/                    ← Build automation      [all platforms]
│   ├── bump-version.py         ← Increment build, sync all version strings
│   ├── gen-update-json.py      ← Generate platform update JSONs
│   └── add-patchnote.py        ← Prepend to patchnotes.txt
│
├── version.json                ← Single source of truth for version/build
├── requirements.txt            ← Python deps (Windows + Mac)
└── patchnotes.txt
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

## Platform Status

| Platform | Status | Build | Shell | Distribution |
|----------|--------|-------|-------|--------------|
| Windows  | ✅ Live | Build 88 | Electron | EGMd.zip |
| macOS    | ✅ Live | Build 88 | Electron | EGMdM.zip |
| Linux    | ✅ Live | Build 92 | Electron + AppImage | EGMdL.zip |

**All platforms are production-ready and actively maintained.**

---

## Version Management

`version.json` is the master record. Never edit version numbers manually in individual files — always run `scripts/bump-version.py`.

---

## Continuous Integration

Automated checks run on every push and pull request:

- **Version Sync Validation** - Ensures version.json stays in sync with all platform files
- **Python Linting** - Code quality checks (flake8, isort)
- **JavaScript Linting** - Frontend code quality (ESLint)
- **First Contributor Welcome** - Automated greeting for new contributors

See [GITHUB_ACTIONS_TODO.md](GITHUB_ACTIONS_TODO.md) for planned workflows.
