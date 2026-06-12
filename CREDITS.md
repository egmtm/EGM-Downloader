# Credits & Acknowledgments

EGM Downloader is built on the shoulders of giants. This project would not be possible without the incredible open source community and the following projects:

---

## 💡 Inspiration

### ReClip
**The spark that started it all**

- **Project:** https://github.com/averygan/reclip
- **Author:** [@averygan](https://github.com/averygan)
- **License:** MIT
- **What we borrowed:** The concept of wrapping yt-dlp in a user-friendly interface
- **What we built differently:** Native multi-platform desktop apps with installers, auto-updates, and zero setup required

EGM Downloader was inspired by ReClip's elegant approach to video downloading. While ReClip is a self-hosted web app perfect for developers, EGM Downloader takes the concept in a different direction—native desktop applications for non-technical users who just want to download videos without the setup hassle.

**Thank you, [@averygan](https://github.com/averygan), for showing what was possible!** 🙏

---

## 🎯 Core Technologies

### yt-dlp
**The heart of the download engine**

- **What it does:** Powers downloads from 1000+ websites
- **License:** Unlicense (Public Domain)
- **Repository:** https://github.com/yt-dlp/yt-dlp
- **Website:** https://github.com/yt-dlp/yt-dlp

yt-dlp is an actively maintained fork of youtube-dl with additional features and fixes. It's the engine that makes downloading from YouTube, TikTok, Instagram, and hundreds of other sites possible.

**Thank you** to the yt-dlp team for maintaining such a robust and feature-rich download library.

---

### yt-dlp/ejs
**EJS remote components for YouTube signature solving**

- **What it does:** Provides the EJS runtime components used by yt-dlp to solve YouTube's signature cipher, enabling downloads of signature-protected content
- **License:** MIT
- **Repository:** https://github.com/yt-dlp/ejs

**Thank you** to the yt-dlp team for maintaining this companion component.

---

### Flask
**Web framework for the backend**

- **What it does:** Powers the HTTP server and API
- **License:** BSD-3-Clause
- **Repository:** https://github.com/pallets/flask
- **Website:** https://flask.palletsprojects.com/

Flask provides the lightweight, flexible web framework that runs our backend, handles API requests, and serves the UI.

**Thank you** to the Pallets team for creating such an elegant and powerful web framework.

---

### Electron
**Cross-platform desktop wrapper**

- **What it does:** Packages the web app as native desktop applications
- **License:** MIT
- **Repository:** https://github.com/electron/electron
- **Website:** https://www.electronjs.org/

Electron enables us to build native Windows, macOS, and Linux applications using web technologies, providing a consistent experience across all platforms.

**Thank you** to the Electron team and OpenJS Foundation for making cross-platform desktop development accessible.

---

### FFmpeg
**Multimedia processing**

- **What it does:** Converts, merges, and processes video/audio files
- **License:** LGPL/GPL (depending on build configuration)
- **Repository:** https://github.com/FFmpeg/FFmpeg
- **Website:** https://ffmpeg.org/

FFmpeg is the industry-standard multimedia framework that handles all video and audio processing, from format conversion to quality optimization.

**Thank you** to the FFmpeg team for decades of excellence in multimedia processing.

---

### Deno
**JavaScript/TypeScript runtime**

- **What it does:** Enables YouTube PO token generation for age-restricted content
- **License:** MIT
- **Repository:** https://github.com/denoland/deno
- **Website:** https://deno.com/

Deno provides the secure runtime environment needed for bgutil-ytdlp-pot-provider to generate proof-of-origin tokens for YouTube downloads.

**Thank you** to the Deno team for creating a modern, secure JavaScript runtime.

---

## 🔧 Python Dependencies

### bgutil-ytdlp-pot-provider
**YouTube proof-of-origin token provider**

- **License:** MIT
- **Repository:** https://github.com/coletdjnz/bgutil-ytdlp-pot-provider
- **Purpose:** Enables downloads of age-restricted YouTube content

**Thank you** to coletdjnz for solving the YouTube age-restriction challenge.

---

### mutagen
**Audio metadata tagging**

- **License:** GPL-2.0
- **Repository:** https://github.com/quodlibet/mutagen
- **Purpose:** Embeds thumbnail, chapter markers, and title/artist/date metadata into downloaded files

**Thank you** to the quodlibet team for a robust and well-maintained metadata library.

---

## 🎨 Build Tools & Infrastructure

### electron-builder
**Electron application packager**

- **License:** MIT
- **Repository:** https://github.com/electron-userland/electron-builder
- **Purpose:** Builds native installers for all platforms (DMG, AppImage, NSIS)

**Thank you** to the electron-userland team for making Electron packaging straightforward.

---

### Python Build Standalone
**Portable Python distributions**

- **License:** Various (Python PSF License + others)
- **Repository:** https://github.com/indygreg/python-build-standalone
- **Purpose:** Provides bundled Python for Mac and Linux builds

**Thank you** to Gregory Szorc for creating standalone Python distributions.

---

### BtbN FFmpeg Builds
**Pre-compiled FFmpeg binaries**

- **License:** LGPL/GPL
- **Repository:** https://github.com/BtbN/FFmpeg-Builds
- **Purpose:** Provides optimized FFmpeg builds for Windows and Linux

**Thank you** to BtbN for maintaining high-quality FFmpeg builds.

---

## 🧪 Development Tools

### flake8
**Python code linting**

- **License:** MIT
- **Repository:** https://github.com/PyCQA/flake8
- **Purpose:** Ensures code quality and PEP 8 compliance

---

### ESLint
**JavaScript linting**

- **License:** MIT
- **Repository:** https://github.com/eslint/eslint
- **Purpose:** Ensures JavaScript code quality

---

## 🏗️ Infrastructure

### GitHub Actions
**Continuous Integration platform**

- **Provider:** GitHub
- **Purpose:** Automated testing, linting, and quality checks

**Thank you** to GitHub for providing free CI/CD for open source projects.

---

## 📦 Node.js Ecosystem

### Node.js
**JavaScript runtime**

- **License:** MIT
- **Repository:** https://github.com/nodejs/node
- **Website:** https://nodejs.org/

**Thank you** to the Node.js Foundation and contributors.

---

## 🌟 Special Thanks

### Open Source Community
To everyone who contributes to open source software - from bug reports to documentation to code contributions - **thank you**. Projects like this are only possible because of the culture of sharing and collaboration you've built.

### Standards Bodies
- **W3C** - Web standards that make cross-platform development possible
- **ECMA International** - JavaScript/ECMAScript standards
- **Python Software Foundation** - Python language development
- **OpenJS Foundation** - JavaScript ecosystem governance

### Platform Providers
- **GitHub** - Repository hosting, Actions, community features
- **npm** - Node.js package management
- **PyPI** - Python package distribution

---

## 📄 License Compliance

EGM Downloader is released under the **GNU Affero General Public License v3.0 (AGPL-3.0)**, which is compatible with all the dependencies listed above.

### License Summary:
- **MIT License:** Electron, Deno, bgutil-ytdlp-pot-provider, yt-dlp/ejs, electron-builder, flake8, ESLint, Node.js
- **BSD-3-Clause:** Flask (Pallets)
- **GPL-2.0:** mutagen
- **Unlicense (Public Domain):** yt-dlp
- **LGPL/GPL:** FFmpeg (dynamically linked, separate binary)
- **Python Software Foundation License:** Python

All licenses are compatible with the AGPL-3.0 License under which EGM Downloader is distributed.

---

## 🤝 Contributing

If you use EGM Downloader in your project or find it helpful, consider:

1. **Star the repositories** of the projects listed above
2. **Contribute** to these upstream projects when you can
3. **Report bugs** to help improve the ecosystem
4. **Share** your knowledge with others

**The open source community thrives on collaboration. Pay it forward!** 🌍

---

## 📝 Keeping This Updated

If you notice any missing attributions or outdated information, please:
1. Open an issue
2. Submit a pull request
3. Let us know via contact methods in README

We strive to properly credit all contributions to this project.

---

**Last Updated:** June 12, 2026

**Thank you to everyone who makes open source possible!** ❤️
