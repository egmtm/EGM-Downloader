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
- 🎨 **260 Themes** - 250 permanent across 20+ categories + 10 seasonal easter eggs with smooth transitions
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

> 📸 *Screenshots captured on v0.99.11 running on Linux. The UI is identical across Windows, macOS, and Linux.*

<table>
  <tr>
    <td align="center" width="50%">
      <a href="screenshots/01-loading.png">
        <img src="screenshots/01-loading.png" width="340" alt="Loading Screen"/>
      </a>
      <br/><sub><b>Loading Screen</b></sub>
    </td>
    <td align="center" width="50%">
      <a href="screenshots/02-main-ui-ghost-theme.png">
        <img src="screenshots/02-main-ui-ghost-theme.png" width="340" alt="Main UI — Ghost Theme"/>
      </a>
      <br/><sub><b>Main UI — Ghost Theme</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/03-themes-window.png">
        <img src="screenshots/03-themes-window.png" width="340" alt="Themes Window — 260 Themes"/>
      </a>
      <br/><sub><b>Themes Window — 260 Themes</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/04-fetching-videos.png">
        <img src="screenshots/04-fetching-videos.png" width="340" alt="Fetching Videos"/>
      </a>
      <br/><sub><b>Fetching Videos</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/05-fetched-videos.png">
        <img src="screenshots/05-fetched-videos.png" width="340" alt="Fetched Videos — Ready to Download"/>
      </a>
      <br/><sub><b>Fetched Videos — Ready to Download</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/06-downloading-videos.png">
        <img src="screenshots/06-downloading-videos.png" width="340" alt="Downloading Videos"/>
      </a>
      <br/><sub><b>Downloading Videos</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/07-hamburger-history.png">
        <img src="screenshots/07-hamburger-history.png" width="340" alt="Hamburger Panel — Download History"/>
      </a>
      <br/><sub><b>Hamburger — Download History</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/08-hamburger-themes.png">
        <img src="screenshots/08-hamburger-themes.png" width="340" alt="Hamburger Panel — Themes"/>
      </a>
      <br/><sub><b>Hamburger — Themes Tab</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/09-hamburger-advanced.png">
        <img src="screenshots/09-hamburger-advanced.png" width="340" alt="Hamburger Panel — Advanced Settings"/>
      </a>
      <br/><sub><b>Hamburger — Advanced Settings</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/10-expanded-history.png">
        <img src="screenshots/10-expanded-history.png" width="340" alt="Expanded Download History"/>
      </a>
      <br/><sub><b>Expanded Download History</b></sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <a href="screenshots/11-plugins-panel.png">
        <img src="screenshots/11-plugins-panel.png" width="340" alt="Plugins Update Panel"/>
      </a>
      <br/><sub><b>Plugins Update Panel</b></sub>
    </td>
    <td align="center">
      <a href="screenshots/12-video-output.png">
        <img src="screenshots/12-video-output.png" width="340" alt="Video Output"/>
      </a>
      <br/><sub><b>Video Output</b></sub>
    </td>
  </tr>
</table>

---

## 📥 Download

### Windows
**Latest:** v0.99.13 Build 121  
**Download:** [EGMd.zip](https://egerena.com/apps/EGMd.zip) (346 KB · ~800 MB after install)  
**SHA256:** `ef6fd4f7edc2bb178e65d40899cda6630a07045355665e2a41c05899351addb6`  
**Requirements:** Windows 10/11 (64-bit)  
**Code Signed:** Installer is signed with an IV certificate (SSL.com) — SmartScreen warnings may still appear until the certificate builds reputation. EV certificate planned for broader recognition.

### Windows Portable
**Latest:** v0.99.13 Build 121  
**Download:** [EGMd-portable.zip](https://egerena.com/apps/EGMd-portable.zip) (351 KB · ~800 MB after first run)  
**SHA256:** `9b973f6bdb054c402b29ea0670f4f482eca5f976dc9f2e01e6e5ed71281515a4`  
**Requirements:** Windows 10/11 (64-bit)  
**No installer, no registry** — runs from any folder or USB drive  
**Code Signed:** Portable is signed with an IV certificate (SSL.com) — SmartScreen warnings may still appear until the certificate builds reputation. EV certificate planned for broader recognition.

### macOS
**Latest:** v0.99.13 Build 121  
**Download:** [EGMdM.zip](https://egerena.com/apps/EGMdM.zip) (126 MB · ~300 MB after install)  
**SHA256:** `87438655ea173bc7a656fdd44c69454131890a249126710860973e2ebbaa9d5e`  
**Requirements:** macOS 11.0 (Big Sur) or later · Apple Silicon (M1–M5) only
**Signed & Notarized:** This build is Apple notarized — runs without Gatekeeper warnings

### Linux
**Latest:** v0.99.13 Build 121  
**Download:** [EGMdL.zip](https://egerena.com/apps/EGMdL.zip) (140 MB · ~300 MB after install)  
**SHA256:** `73b1fc8782579eb7f0f7a38db746d25859578e6a8fa042a390421259991f97b6`  
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
- 🎨 67 new themes total — bringing the library to 230+ (260 with v0.99.13 OS themes)
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

**v1.0 — CORNERSTONE:** 🔨 In progress
- 🧱 The foundation release — everything built since v0.93 comes together here
- 🪟 Windows portable fully isolated — state, themes, and cache stay in the portable folder, never leak to `%APPDATA%`
- 🪟 Windows app identity — shows as EGM Downloader across all system views (Task Manager, taskbar, notifications)
- ⭐ Theme Favorites — mark your favorites and optionally launch with a random theme
- 🎨 300 themes milestone
- ✨ Startup and interface polish
- *More items TBD*

**v1.1 — IGNITION:**
- 📡 Subscriptions — save any channel or playlist once, automatically download what's new
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
| Windows (Installer) | ✅ Live | Build 121 | EGMd.zip | ✅ Yes |
| Windows (Portable)  | ✅ Live | Build 121 | EGMd-portable.zip | ❌ Manual |
| macOS    | ✅ Live | Build 121 | EGMdM.zip | ✅ Yes |
| Linux    | ✅ Live | Build 121 | EGMdL.zip | ❌ Manual |

**All platforms are production-ready and actively maintained.**

---

## 🏗️ Built With

EGM Downloader is powered by incredible open source projects:

- **[yt-dlp](https://github.com/yt-dlp/yt-dlp)** - Download engine (1000+ sites)
- **[bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider)** - YouTube PO Token generation (proof-of-origin)
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

- **Version:** 0.99.13
- **Build:** 121
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
