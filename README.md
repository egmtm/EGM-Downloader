<div align="center">
  <img src=".github/images/logo-512.png" alt="EGM Downloader Logo" width="180"/>
  
  <h1>EGM Downloader</h1>
  
  <p>
    <img src="https://img.shields.io/badge/dynamic/json?url=https://egerena.com/version.json&query=version&label=version&style=flat-square&color=0078b0" alt="Version"/>
    <img src="https://github.com/egmtm/EGM-Downloader/workflows/Validate%20Version%20Sync/badge.svg" alt="Version Sync"/>
    <img src="https://github.com/egmtm/EGM-Downloader/workflows/Lint%20Python/badge.svg" alt="Python Lint"/>
    <img src="https://github.com/egmtm/EGM-Downloader/workflows/Lint%20JavaScript/badge.svg" alt="JavaScript Lint"/>
    <img src="https://github.com/egmtm/EGM-Downloader/workflows/Tests/badge.svg" alt="Tests"/>
    <a href="https://www.gnu.org/licenses/agpl-3.0"><img src="https://img.shields.io/badge/License-AGPL_3.0-blue.svg" alt="License"/></a>
    <a href="https://github.com/egmtm/EGM-Downloader/discussions"><img src="https://img.shields.io/github/discussions/egmtm/EGM-Downloader?logo=github&label=discussions" alt="GitHub Discussions"/></a>
    <img src="https://img.shields.io/badge/Electron-42+-47848F?logo=electron&logoColor=white" alt="Electron"/>
    <img src="https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white" alt="Windows"/>
    <img src="https://img.shields.io/badge/Windows-Code_Signed-0078D6?logo=windows&logoColor=white" alt="Windows Code Signed"/>
    <img src="https://img.shields.io/badge/macOS-Big_Sur+-000000?logo=apple&logoColor=white" alt="macOS"/>
    <img src="https://img.shields.io/badge/macOS-Notarized-000000?logo=apple&logoColor=white" alt="macOS Notarized"/>
    <img src="https://img.shields.io/badge/Linux-AppImage-FCC624?logo=linux&logoColor=black" alt="Linux"/>
  </p>

  <p><strong>A powerful, multi-platform video and audio downloader for 1000+ websites.</strong></p>
  
  <p>Download videos or extract audio from YouTube, TikTok, Instagram, Twitter, Facebook, and hundreds of other platforms with a beautiful, easy-to-use interface.</p>
  <p><em>Powered by yt-dlp · runs locally · no cloud · no tracking · no accounts</em></p>
</div>

---

<p align="center">
  <a href="#-download">⬇ Downloads</a> ·
  <a href="#️-screenshots">📸 Screenshots</a> ·
  <a href="#-quick-start">🚀 Quick Start</a> ·
  <a href="#️-roadmap">🗺️ Roadmap</a> ·
  <a href="#-system-requirements">📋 Requirements</a>
</p>

## ✨ Features

- 🌐 **1000+ Supported Sites** - Download from YouTube, TikTok, Instagram, Twitter, Vimeo, and more
- 🎬 **Video & Audio Downloads** - MP4 or MKV video; MP3, M4A, OPUS, or FLAC audio
- 📊 **Quality Selection** - Video up to 8K/4K/2K/1080p; audio up to FLAC or 320 kbps MP3
- 📋 **Playlist Support** - Download entire playlists with one click
- ⚡ **Batch Downloads** - Queue multiple URLs and download them all at once
- 🖱️ **Drag & Drop + Keyboard Shortcuts** - Drop URLs directly into the app; Ctrl+V / ⌘V fetches, Ctrl+Enter / ⌘Return starts, Esc clears
- 🎨 **400 Themes** - 390 permanent across 20+ categories + 10 seasonal easter eggs with smooth transitions
- 📜 **Download History** - Track all downloads with search, filter, and re-download capability
- 🔤 **Subtitles & Metadata** - Embed subtitles and rich metadata (thumbnail, chapters, title/artist/date) directly into video files
- 🔄 **Auto-Updates** - Built-in update checker with SHA256 checksum verification (Windows/Mac)
- 📝 **Custom Filenames** - Edit filenames before downloading
- 🛠️ **Plugin Updates** - Update yt-dlp and ffmpeg without reinstalling
- 🧹 **Smart Cleanup** - Automatic removal of temporary files and failed downloads
- 💼 **Windows Portable** - Run from any folder or USB drive — no installer, no registry
- 🖥️ **Cross-Platform** - Native apps for Windows, macOS, and Linux
- 🔒 **Privacy First** - Runs entirely on your machine. No account required, no cloud processing, no analytics, no data transmitted anywhere. Site cookies are handled locally and never pass through our servers or any other network.

---

## 🖼️ Screenshots

> 📸 *Screenshots captured on v1.0.4 — Sharp. The UI is identical across Windows, macOS, and Linux.*

<table>
  <tr>
    <td align="center" width="50%">
      <a href="screenshots/01-main-ui-the-10s-theme.png">
        <img src="screenshots/01-main-ui-the-10s-theme.png" width="340" alt="Main UI — The 10s Theme"/>
      </a>
      <br/><sub><b>Main UI — The 10s Theme</b></sub>
    </td>
    <td align="center" width="50%">
      <a href="screenshots/02-main-ui-settings-hidden-millenium-bug-theme.png">
        <img src="screenshots/02-main-ui-settings-hidden-millenium-bug-theme.png" width="340" alt="Main UI — Millennium Bug Theme"/>
      </a>
      <br/><sub><b>Main UI — Millennium Bug Theme</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/03-fetching-videos-ghost-theme.png">
        <img src="screenshots/03-fetching-videos-ghost-theme.png" width="340" alt="Fetching Videos — Ghost Theme"/>
      </a>
      <br/><sub><b>Fetching Videos — Ghost Theme</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/04-download-all-videos-zion-theme.png">
        <img src="screenshots/04-download-all-videos-zion-theme.png" width="340" alt="Download All Videos — Zion Theme"/>
      </a>
      <br/><sub><b>Download All Videos — Zion Theme</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/05-downloading-videos-midnight-theme.png">
        <img src="screenshots/05-downloading-videos-midnight-theme.png" width="340" alt="Downloading Videos — Midnight Theme"/>
      </a>
      <br/><sub><b>Downloading Videos — Midnight Theme</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/06-download-history-la-guancha-theme.png">
        <img src="screenshots/06-download-history-la-guancha-theme.png" width="340" alt="Download History — La Guancha Theme"/>
      </a>
      <br/><sub><b>Download History — La Guancha Theme</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/07-themes-main-ui-the-witness-theme.png">
        <img src="screenshots/07-themes-main-ui-the-witness-theme.png" width="340" alt="Themes — The Witness Theme"/>
      </a>
      <br/><sub><b>Themes Window — The Witness Theme</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/08-all-themes-n64-theme.png">
        <img src="screenshots/08-all-themes-n64-theme.png" width="340" alt="All Themes — N64 Theme"/>
      </a>
      <br/><sub><b>All Themes — N64 Theme</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/09-advanced-options-old-san-juan-theme.png">
        <img src="screenshots/09-advanced-options-old-san-juan-theme.png" width="340" alt="Advanced Options — Old San Juan Theme"/>
      </a>
      <br/><sub><b>Advanced Options — Old San Juan Theme</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/10-plugins-update-advanced-bauhaus-theme.png">
        <img src="screenshots/10-plugins-update-advanced-bauhaus-theme.png" width="340" alt="Plugins Update — Bauhaus Theme"/>
      </a>
      <br/><sub><b>Plugins Update — Bauhaus Theme</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/11-plugin-update-success-brutalist-theme.png">
        <img src="screenshots/11-plugin-update-success-brutalist-theme.png" width="340" alt="Plugin Update Success — Brutalist Theme"/>
      </a>
      <br/><sub><b>Plugin Update Success — Brutalist Theme</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/12-deno-reinstall-button-blue-bird-theme.png">
        <img src="screenshots/12-deno-reinstall-button-blue-bird-theme.png" width="340" alt="Deno Reinstall Button — Blue Bird Theme"/>
      </a>
      <br/><sub><b>Deno Reinstall — Blue Bird Theme</b></sub>
    </td>
  </tr>
</table>
## 📥 Download

### Windows
**Latest:** v1.0.4 Build 128  
**Download:** [EGMd.zip](https://egerena.com/apps/EGMd.zip) (422 KB · ~800 MB after install)  
**SHA256:** `45c8010b75cf9c6f5d4212b064cda8f6981a879ca559e52427d3bf89dbac41bb`  
**Requirements:** Windows 10/11 (64-bit)  
**Code Signed:** Installer is signed with an IV certificate (SSL.com) — SmartScreen warnings may still appear until the certificate builds reputation. EV certificate planned for broader recognition.

### Windows Portable
**Latest:** v1.0.4 Build 128  
**Download:** [EGMd-portable.zip](https://egerena.com/apps/EGMd-portable.zip) (394 KB · ~800 MB after first run)  
**SHA256:** `70b8f8f77b7408083860633c69b1ea9017ec9c1bb42cae3d53f541f9f3c8462b`  
**Requirements:** Windows 10/11 (64-bit)  
**No installer, no registry** — runs from any folder or USB drive  
**Code Signed:** Portable is signed with an IV certificate (SSL.com) — SmartScreen warnings may still appear until the certificate builds reputation. EV certificate planned for broader recognition.

### macOS
**Latest:** v1.0.4 Build 128  
**Download:** [EGMdM.zip](https://egerena.com/apps/EGMdM.zip) (128 MB · ~300 MB after install)  
**SHA256:** `82c678fb51003a11e781baf71d017c80f3fe8c6aaae3740a55bfb3e6cdeef924`  
**Requirements:** macOS 11.0 (Big Sur) or later · Apple Silicon (M1–M5) only
**Signed & Notarized:** This build is Apple notarized — runs without Gatekeeper warnings

### Linux
**Latest:** v1.0.4 Build 128  
**Download:** [EGMdL.zip](https://egerena.com/apps/EGMdL.zip) (144 MB · ~300 MB after install)  
**SHA256:** `120a7b0693ad6d19998c2cd0353548ff4beb60ae4de9366ccb864dbc2a6ae6a7`  
**Format:** AppImage (Universal)  
**Supported Distros:** Ubuntu 20.04+, Mint 20+, Pop!_OS, Fedora 39+, Arch, and more

> **Note:** Distributions available on [apps.egerena.com](https://apps.egerena.com)

---

## 🚀 Quick Start

### Windows
1. Extract `EGMd.zip`
2. Run `egm-setup.exe` and follow the installer
3. Paste a video URL and click Download!

### Windows Portable
1. Extract `EGMd-portable.zip` to any folder or USB drive
2. Run `EGM Downloader.exe`
3. Paste a video URL and click Download!

> Settings and data stay in the same folder — take it anywhere.

### macOS
1. Extract `EGMdM.zip`
2. Open the `.dmg` file
3. Drag "EGM Downloader" to Applications
4. Launch from Applications folder

### Linux
1. Extract `EGMdL.zip`
2. Make executable: `chmod +x "EGM Downloader.AppImage"`
3. Double-click to launch (or run from terminal)

**Windows only — first launch:** The installer downloads runtime components (Node.js, Electron, ffmpeg) once into your user data directory (~250 MB). macOS and Linux bundle these dependencies inside the package — no first-launch download required (which is why their file sizes are larger).

---

## 💡 Usage

1. **Paste URL** - Copy any video URL and paste it into the app
2. **Select Format** - Choose video (MP4 or MKV) or audio (MP3, M4A, OPUS, or FLAC)
3. **Select Quality** - Choose resolution (up to 8K) or audio bitrate
4. **Edit Filename** (Optional) - Click the filename to customize it
5. **Download** - Click the download button and wait for completion
6. **Open Folder** - Click "Open Folder" to view your downloaded files

### Advanced Features

**Playlist Downloads:**
- Paste playlist URL
- Select "Download All" or choose specific videos
- Videos download in sequence

**Batch Downloads:**
- Add multiple URLs to the queue
- Select format (MP4/MP3) and quality for each
- Download all at once
- Cancel individual downloads anytime

**Plugin Updates:**
- Click "Update Plugins" in settings
- Update yt-dlp for newest site support
- Update ffmpeg for latest codecs

**Cookies / Login-Required Content:**
- Some sites require browser cookies for premium or age-restricted content
- Import cookies from Chrome, Edge, Brave, or Firefox directly in the app
- Cookies are stored locally on your machine and are never transmitted

---

## 🗺️ Roadmap

**v0.99.9 — COMMAND CENTER:** ✅ Shipped
- 🎛️ Advanced panel moves to dedicated hamburger tab — History | Themes | Advanced
- 🖥️ Splash screen polish and escape fix
- 🎨 +20 new themes
- 🔍 Windows tray menu density research deferred to v0.99.10

**v0.99.10 — DIRECTOR'S CUT:** ✅ Shipped
- 🖼️ Video thumbnails in download history
- 🎵 Expanded audio quality options
- 🎨 +20 new themes

**v0.99.11 — FOUNDER'S EDITION:** ✅ Shipped
- 🇵🇷 Puerto Rico Collection — 22 deeply personal themes celebrating Ponce, the island, holidays, and culture
- 🎨 67 new themes total — bringing the library to 360
- 🖼️ Dedicated Puerto Rico section in the themes sidebar
- 🔒 Thumbnail fetching restricted to HTTPS-only

**v0.99.12 — VAULT:** ✅ Shipped
- 🔧 Theme placeholder + section label contrast fix — as promised from v0.99.11 known issues
- 🔒 Signed update manifests — cryptographically verified (ed25519) before any update installs
- 📋 Structured security event logging — all security-relevant events logged to rotating `security.log`
- 🧪 Unit test suite — ~13 tests covering Tier 1 parity, Tier 2 security, and historical regressions; wired into CI

**v0.99.13 — SOLID:** ✅ Shipped
- ⚛️ Atomic file writes — history, settings, cookies and reset paths hardened against corruption
- 🔍 Strict image magic byte detection — canonical pattern matching replaces loose checks
- 🛡️ Content-Type header validation on thumbnail fetches — defense-in-depth on top of existing HTTPS-only + size cap stack

**v1.0 — CORNERSTONE:** ✅ Shipped
- 🧱 The foundation release — everything built since v0.93 comes together here
- 🎨 400 themes — mythology, sports, decades, memes, cities, space, planets, Conejo Malo series, and more
- ⭐ Theme Favorites + Random Launch — heart any theme, optionally start fresh every session
- 🎮 Keyboard-first themes — arrow keys navigate cards, Enter applies, F favorites, Escape clears search
- 🪟 Windows portable fully isolated — no settings leak between installed and portable versions
- 🪟 Windows app identity — EGM Downloader shows correctly across all system views
- 🔧 YouTube signature fix — yt-dlp remote components resolve playback issues
- 🔧 Save/rename modal stays open on overlay click — Cancel, Save, or Escape only
- ⚡ ffmpeg loads in background — app opens immediately, no frozen splash on slow connections
- 🔄 yt-dlp and ffmpeg channel toggles (Stable / Nightly) in Advanced panel
- 🔒 IPC hardening — sender validation, atomic writes, signed manifest verification, file import cap, zip-slip guard
- 🧪 32 automated tests — security parity across all 3 platforms, theme consistency, template integrity
- ✨ Source split — index, scripts, styles, and theme data in dedicated files; rendered output identical
- ⚡ Electron 42.3.2 — latest stable runtime

**v1.0.1:** ✅ Shipped
- 🔧 Update Plugins panel moved into hamburger → Advanced tab — cleaner main page
- 🔧 Collapsible plugins grid with Show/Hide toggle — state remembered across restarts
- 🔧 Section dividers in Advanced tab — Channels, Plugins, Maintenance grouping
- 🔧 Clear cache moved to maintenance zone
- 🔧 Auto-collapse plugins panel after check when all plugins are current
- 🔧 Update modal now scrollable — max-height 90vh, buttons stay fixed

**v1.0.2:** ✅ Shipped
- 🧭 Direct-access navigation buttons replace the hamburger — one tap to History, Themes, or Advanced
- 🖼️ Enlarged logo (76px) with vertical nav stack — cleaner header layout
- 🔧 History panel loads correctly on every navigation path — tab switch and nav-while-open both handled

**v1.0.3:** ✅ Shipped
- 🔒 Server-side download concurrency cap (BoundedSemaphore) — prevents unbounded process spawns
- 🔒 Resolve-first download directory validation — closes path traversal bypass
- 🔒 TOCTOU locks on update and Deno install — prevents double-spawn race on simultaneous requests
- 🔧 First-run ffmpeg queues downloads instead of 503 — new users can download immediately after install
- ⚡ Electron 42.4.0 — Mac and Linux; includes CVE-2026-9115 + CVE-2026-9116 backports, Chromium 148.0.7778.254, Node.js v24.16.0

**v1.0.4:** ✅ Shipped
- 🎨 Full SVG icon upgrade — all emoji replaced with inline SVGs, theme-compatible via currentColor
- 🧭 Nav buttons 2-column layout — History/Themes stacked left, separator, Advanced isolated right
- 🔧 Card toggle contrast fix — Show/Hide readable across all 400 themes

**v1.1 — IGNITION:**
- 📡 Subscriptions — save any channel or playlist, automatically fetch and display what's new
- 🗂️ Dedicated subscriptions window — sidebar list, detail pane, collapsible, size/position remembered
- 🖼️ Video list with thumbnails, durations, and upload dates — sortable by Latest or Oldest
- 📄 Client-side pagination — 20 videos shown, Load More adds 20 at a time
- 🔄 Auto-fetch-on-open toggle per channel — selects and fetches automatically on window open
- 🔒 Per-channel download folder validated on save — rejects system roots, traversal, unwritable paths
- ⚙️ Site Cookies merged into Settings panel — one toggle controls both
- 🧪 Preload bridge parity test broadened — full function surface locked across all 3 platforms
- The engine fires here. Subscriptions touch backend, UI, and update flow — given room to land right

**v1.2 — [TBD]:**
- 🔭 Next chapter — details after v1.1 ships
- 🧩 *Browser extension in the works — send URLs straight to EGM Downloader without leaving your browser. Details TBD.*

**v1.3 — POLYGLOT:**
- 🌍 In-app language picker — multi-language support, clean and unhurried
- 10 languages at launch: Arabic, German, English, Spanish, French, Italian, Japanese, Dutch, Portuguese, Russian (AR · DE · EN · ES · FR · IT · JA · NL · PT · RU)

**See:** [GitHub Issues](https://github.com/egmtm/EGM-Downloader/issues) for details and progress.

---

## 📖 The Origin Story

EGM Downloader was born from inspiration and a desire to make video downloading accessible to everyone.

**The inspiration:** [ReClip](https://github.com/averygan/reclip) by [@averygan](https://github.com/averygan) beautifully demonstrated what's possible with yt-dlp and a clean web interface.

**The challenge:** ReClip's self-hosted approach is perfect for developers, but I wanted to share this with friends and family who don't use the terminal. Setting up Python, yt-dlp, ffmpeg, and Flask isn't everyone's cup of tea.

**The solution:** What if you could just download an app and go? No terminal. No dependencies. No setup. Just double-click and start downloading.

That's EGM Downloader—native desktop apps for Windows, macOS, and Linux with professional installers, auto-updates, and zero technical knowledge required.

We've taken the concept in a different direction (native apps vs. web-based, end-users vs. developers), but the core inspiration came from ReClip's elegant simplicity.

**Big thanks to [@averygan](https://github.com/averygan) for ReClip—you sparked the idea that became this project!** 🙏

**This is my first major project, and I'm excited to keep learning and building more tools that make technology accessible to everyone.** 🚀

---

## ⚖️ Legal & Responsible Use

EGM Downloader is a tool for downloading video content from the internet. While the software itself is legal, **you are responsible for how you use it.**

### Legitimate Uses

This tool is designed for lawful purposes, including:
- Downloading your own content
- Downloading Creative Commons or public domain content
- Fair use purposes (education, research, criticism, commentary)
- Archiving content you have permission to download
- Backing up content you own or have rights to
- Offline viewing in jurisdictions where personal downloading is legal

### Your Responsibilities

When using this tool, you must:
- **Respect copyright laws** - Only download content you have the right to download
- **Follow Terms of Service** - Many platforms prohibit downloading; check their policies
- **Obtain permission** - When required by law or platform rules
- **Use responsibly** - Do not redistribute, sell, or commercially exploit downloaded content without proper rights

### Disclaimer

**This tool is provided "as-is" for personal, lawful use only.**

The developers:
- Do not encourage or condone copyright infringement
- Are not responsible for how users choose to use this software
- Do not provide legal advice regarding what you can or cannot download
- Assume no liability for user actions or violations of third-party terms

**You are solely responsible for ensuring your use complies with applicable laws, regulations, and terms of service.**

If you're unsure whether your use case is legal, consult a legal professional in your jurisdiction.

---

## 🛠️ For Developers

### Repository Structure

```
EGM-Downloader/
│
├── app.py                          ← Flask backend         [shared — all platforms]
├── templates/                      ← UI templates          [shared — Windows + Mac]
│   ├── index.html                  ← Main UI
│   ├── history.html                ← Version history
│   ├── themes.html                 ← Theme picker
│   └── theme_styles.html           ← Theme CSS definitions
├── static/                         ← App icons             [shared — all platforms]
├── languages/                      ← i18n language files   [shared — all platforms]
│   └── en.json, es.json, fr.json, pt.json, de.json, it.json, ...
│
├── windows/                        ← Windows platform files
├── mac/                            ← macOS platform files
├── linux/                          ← Linux platform files
├── scripts/                        ← Build automation
│   ├── bump-version.py             ← Version management
│   ├── validate-version-sync.py    ← Version sync validator (CI)
│   ├── gen-update-json.py          ← Update JSON generation
│   └── add-patchnote.py            ← Changelog management
│
├── version.json                    ← Single source of truth
├── requirements.txt                ← Python dependencies
└── patchnotes.txt                  ← Version history
```

### Build Workflow

**1. Bump version:**
```bash
python scripts/bump-version.py
# Or bump version string:
python scripts/bump-version.py --version 0.92
```

**2. Add patch notes:**
```bash
python scripts/add-patchnote.py "Fixed bug" "Added feature"
```

**3. Generate update JSONs:**
```bash
python scripts/gen-update-json.py --notes "Fixed X; Added Y"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for complete development guide.

### Build Artifacts

EGM Downloader desktop app build artifacts (`EGMd.zip`, `EGMdM.zip`, `EGMdL.zip`, `EGMd-portable.zip`) are uploaded to the server manually by EGM after each release build. They are **NOT** in this repo and **NOT** touched by the auto-deploy pipeline.

JSON update feeds (`egm-version.json`, `egmac-update.json`, `egmlinux-update.json`, `egm-portable-version.json`) are maintained in the [egerena-website](https://github.com/egmtm/egerena-website) repo and deployed through its pipeline.

---

## 🤝 Contributing

We welcome contributions! Whether it's:
- 🐛 Bug reports
- 💡 Feature requests
- 📝 Documentation improvements
- 🔧 Code contributions

**Get started:**
1. Read [CONTRIBUTING.md](CONTRIBUTING.md)
2. Fork the repository
3. Create a feature branch
4. Make your changes
5. Submit a pull request

**Code Quality:**
- ✅ Python linting (flake8, isort)
- ✅ JavaScript linting (ESLint)
- ✅ Version sync validation
- ✅ Automated quality checks

All pull requests are automatically tested via GitHub Actions.

---

## 📊 Platform Status

| Platform | Status | Build | Distribution | Auto-Update |
|----------|--------|-------|--------------|-------------|
| Windows (Installer) | ✅ Live | Build 128 | EGMd.zip | ✅ Yes |
| Windows (Portable)  | ✅ Live | Build 128 | EGMd-portable.zip | ❌ Manual |
| macOS    | ✅ Live | Build 128 | EGMdM.zip | ✅ Yes |
| Linux    | ✅ Live | Build 128 | EGMdL.zip | ❌ Manual |

**All platforms are production-ready and actively maintained.**

---

## 🏗️ Built With

EGM Downloader is powered by incredible open source projects:

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** - Download engine (1000+ sites)
- **[bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)** - YouTube PO Token generation (proof-of-origin)
- **[yt-dlp/ejs](https://github.com/yt-dlp/ejs)** - EJS remote components for YouTube signature solving
- **[Flask](https://flask.palletsprojects.com/)** - Web framework
- **[Electron](https://www.electronjs.org/)** - Cross-platform desktop wrapper
- **[FFmpeg](https://ffmpeg.org/)** - Video/audio processing
- **[Deno](https://deno.com/)** - JavaScript runtime for YouTube tokens
- **[mutagen](https://mutagen.readthedocs.io/)** - Audio metadata tagging (thumbnail, chapters, title/artist/date)

See [CREDITS.md](CREDITS.md) for complete acknowledgments and licenses.

---

## 🔄 Version Management

`version.json` is the single source of truth. Never edit version numbers manually — always use:

```bash
python scripts/bump-version.py
```

This ensures all platform files stay synchronized.

---

## 🧪 Continuous Integration

Automated quality checks run on every push and pull request:

- **Version Sync Validation** - Prevents version drift across platforms
- **Python Linting** - Code quality (flake8, isort)
- **JavaScript Linting** - Frontend quality (ESLint)
- **First Contributor Welcome** - Automated onboarding

View workflows: [GitHub Actions](https://github.com/egmtm/EGM-Downloader/actions)

---

## 📋 System Requirements

### Windows
- Windows 10 (64-bit) or Windows 11
- ~800 MB free disk space (after first run)
- Internet connection (first launch only)

### macOS
- macOS 11.0 (Big Sur) or later
- Apple Silicon (M1/M2/M3/M4/M5)
- 300 MB free disk space

### Linux
- 64-bit distribution (see supported list below)
- 300 MB free disk space
- FUSE support (pre-installed on most distros)

**Supported Linux Distributions:**
Ubuntu 20.04/22.04/24.04/26.04, Mint 20/21/22, Pop!_OS 22.04, Zorin 16/17, elementary 7, Debian 11/12, KDE Neon, Fedora 39/40/41, openSUSE Leap 15.5/Tumbleweed, Rocky/AlmaLinux 9, Arch, Manjaro, EndeavourOS

> Ubuntu 22.04+ may require `libfuse2`: `sudo apt install libfuse2`

---

## 🐛 Troubleshooting

### Windows
**App won't start:**
- Run `launch.bat` to see error messages
- Check `logs/` folder for details

**Download fails:**
- Update yt-dlp via "Update Plugins"
- Check internet connection
- Try different quality/format

### macOS
**Download stuck:**
- Update plugins
- Restart the app
- Check Console.app for errors

### Linux
**AppImage won't launch:**
- Ensure executable: `chmod +x "EGM Downloader.AppImage"`
- Install FUSE: `sudo apt install libfuse2` (Ubuntu/Debian)
- Run from terminal to see errors

**Need more help?** Open an issue on GitHub!

---

## 📜 License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** - see the [LICENSE](LICENSE) file for details.

**What this means:**
- ✅ Free for personal and non-commercial use
- ✅ Modification allowed (must share modifications)
- ✅ Distribution allowed (must include source code)
- ✅ Patent protection included
- ⚠️ Network use triggers copyleft (modifications must be shared)
- ⚠️ Liability and warranty not provided

---

## 🙏 Acknowledgments

Huge thanks to:
- The **yt-dlp** team for the incredible download engine
- The **open source community** for the amazing tools and libraries
- **Contributors** who help improve this project
- **Users** who report bugs and suggest features

See [CREDITS.md](CREDITS.md) for detailed acknowledgments.

---

## 📞 Support

- 🐛 **Bug Reports:** [Open an Issue](https://github.com/egmtm/EGM-Downloader/issues)
- 💡 **Feature Requests:** [Open an Issue](https://github.com/egmtm/EGM-Downloader/issues)
- 📖 **Documentation:** [Read CONTRIBUTING.md](CONTRIBUTING.md)
- 🔒 **Security Issues:** See [Security Policy](#security)

---

## 🔒 Security

Found a security vulnerability? **Please do not open a public issue.**

Instead:
1. Email security concerns to: contact@egerena.com
2. Include: description, steps to reproduce, potential impact
3. We'll respond within 48 hours
4. We'll work with you on a fix and responsible disclosure

Alternatively, you can report via GitHub's private vulnerability reporting feature.

---

## 📈 Project Stats

- **Version:** 1.0.4
- **Build:** 128
- **Supported Sites:** 1000+
- **Platforms:** 3 (Windows, macOS, Linux)
- **License:** AGPL-3.0
- **Language:** Python + JavaScript

---

## ⭐ Show Your Support

If you find EGM Downloader useful, please consider:
- ⭐ **Starring this repository**
- 🐛 **Reporting bugs** to help improve it
- 💡 **Suggesting features** you'd like to see
- 🤝 **Contributing** code or documentation
- 📢 **Sharing** with others who might find it useful

**Every bit of support helps make this project better!**

---

**Built brick by brick by egmtm**
