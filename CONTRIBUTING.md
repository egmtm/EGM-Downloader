# Contributing to EGM Downloader

Thank you for your interest in contributing to EGM Downloader! This document will help you get started.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Build System](#build-system)
- [Coding Guidelines](#coding-guidelines)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Project Structure](#project-structure)

---

## 🤝 Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

**Quick summary:**
- **Be respectful** - Treat everyone with respect
- **Be constructive** - Focus on improving the project
- **Be patient** - Remember everyone was a beginner once
- **Be inclusive** - Welcome people of all backgrounds

**Unacceptable behavior includes:**
- Harassment, discrimination, or offensive comments
- Trolling or insulting remarks
- Publishing others' private information
- Other conduct inappropriate for a professional setting

Please read the [full Code of Conduct](CODE_OF_CONDUCT.md) for complete details.

---

## 🎯 How Can I Contribute?

### Reporting Bugs

Found a bug? Please open an issue with:

- **Clear title** - Summarize the problem
- **Steps to reproduce** - What did you do?
- **Expected behavior** - What should have happened?
- **Actual behavior** - What actually happened?
- **Environment** - OS, version, platform (Windows/Mac/Linux)
- **Screenshots** - If applicable

**Example:**
```
Title: Download fails for YouTube playlists over 50 videos

Steps:
1. Paste YouTube playlist URL with 60+ videos
2. Select quality and click Download
3. Wait for download

Expected: All videos download
Actual: Only first 50 videos download

Environment: Windows 11, EGM Downloader v1.3.1 Build 142
```

### Suggesting Features

Have an idea? Open an issue with:

- **Use case** - Why is this needed?
- **Proposed solution** - How would it work?
- **Alternatives** - What other approaches did you consider?
- **Priority** - Nice-to-have or critical?

### Contributing Code

1. **Fork the repository**
2. **Create a feature branch** - `git checkout -b feature/your-feature-name`
3. **Make your changes** - Follow our coding guidelines
4. **Test thoroughly** - On your platform
5. **Commit with clear messages** - See commit guidelines below
6. **Push to your fork** - `git push origin feature/your-feature-name`
7. **Open a Pull Request** - Describe what changed and why

---

## 💻 Development Setup

### Prerequisites

**All Platforms:**
- Python 3.11+
- Node.js 18+
- Git

**Platform-Specific:**
- **Windows:** NSIS (for installer builds)
- **macOS:** Xcode Command Line Tools
- **Linux:** build-essential, libfuse2

### Clone and Setup

```bash
# Clone the repository
git clone https://github.com/egmtm/EGM-Downloader.git
cd EGM-Downloader

# Wire the pre-commit and pre-push hooks (one-time per clone)
# Runs version sync + parity check + full test suite before every commit and push
git config core.hooksPath .githooks

# Install Python dependencies (shared)
pip install -r requirements.txt

# For Linux development (uses separate requirements)
pip install -r linux/requirements.txt
```

### Platform-Specific Setup

#### Windows

```bash
# No additional setup needed
# Runtime dependencies download automatically on first launch
```

#### macOS

```bash
cd mac
chmod +x BUILD.sh
# See mac/BUILD_NOTES.txt for detailed build instructions
```

#### Linux

```bash
cd linux
chmod +x BUILD.sh
# See linux/INSTRUCTIONS.txt for build requirements
```

---

## 🔨 Build System

We use a unified version management system. **Never manually edit version numbers!**

### Standard Build Workflow

```bash
# 1. Bump build number (required before EVERY build)
python scripts/bump-version.py

# 2. Add patch notes
python scripts/add-patchnote.py "Your change 1" "Your change 2"

# 3. Build your platform
# Windows: Use your build process
# Mac: bash mac/BUILD.sh
# Linux: bash linux/BUILD.sh

# 4. Generate update JSONs
python scripts/gen-update-json.py --notes "Your change 1; Your change 2"
```

### Version Bumping

```bash
# Increment build number only (most common)
python scripts/bump-version.py

# Increment version string (e.g., v0.98 → v0.99)
python scripts/bump-version.py --version 0.99

# Preview changes without writing
python scripts/bump-version.py --dry-run
```

### Utility Scripts

All scripts are in `scripts/` directory:

- **bump-version.py** - Increment build/version, sync all files
- **add-patchnote.py** - Add entries to patchnotes.txt
- **gen-update-json.py** - Generate platform update JSONs

Run any script with `--help` for detailed usage.

---

## 📝 Coding Guidelines

### Python (Backend)

- **Style:** PEP 8 compliant
- **Line length:** 100 characters max
- **Docstrings:** All public functions
- **Type hints:** Preferred but not required
- **Imports:** Grouped (stdlib, third-party, local)

**Example:**
```python
def sanitize_filename(name: str, ext: str = "") -> str:
    """
    Remove unsafe characters from filename.
    
    Args:
        name: Raw filename
        ext: File extension (with or without dot)
        
    Returns:
        Sanitized filename with extension
    """
    safe = re.sub(r'[<>:"/\\|?*]', '', name)
    return f"{safe}{ext}" if safe else f"download{ext}"
```

### JavaScript (Frontend)

- **Style:** Standard.js conventions
- **Semicolons:** Consistent usage
- **Quotes:** Single quotes for strings
- **Functions:** Arrow functions for callbacks
- **Comments:** Explain complex logic

**Example:**
```javascript
// Fetch available formats for URL
async function fetchFormats(url) {
  const response = await fetch('/api/formats', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url })
  });
  return response.json();
}
```

### Commit Messages

Follow conventional commits format:

```
type(scope): brief description

Longer description if needed

Examples:
  fix(windows): resolve installer crash on Windows 11
  feat(ui): add dark mode toggle
  docs(readme): update build instructions
  refactor(backend): simplify format parsing logic
```

**Types:**
- `fix` - Bug fixes
- `feat` - New features
- `docs` - Documentation
- `refactor` - Code refactoring
- `test` - Testing
- `chore` - Maintenance

---

## 🧪 Testing

### Manual Testing

Before submitting a PR, test:

1. **Basic functionality** - Does download work?
2. **Your changes** - Does your feature/fix work?
3. **No regressions** - Did you break anything else?
4. **Cross-platform** (if applicable) - Test on your target platform

### Test Cases

**For Download Features:**
- [ ] Single video download
- [ ] Playlist download
- [ ] Quality selection
- [ ] Audio extraction
- [ ] Progress tracking
- [ ] Cancel/resume

**For UI Changes:**
- [ ] Different screen sizes
- [ ] Button states (enabled/disabled)
- [ ] Error messages display correctly
- [ ] Loading indicators work

### Reporting Test Results

In your PR description:
```markdown
## Testing Done
- ✅ Single video download (YouTube)
- ✅ Playlist download (5 videos)
- ✅ Quality selection (1080p, 720p, 480p)
- ✅ Audio extraction to MP3
- ⚠️ Cancel during download (needs review)
```

---

## 🔄 Pull Request Process

> **Important:** For large changes (new features, architecture refactors, or anything touching multiple platforms), please open a discussion or issue first. This helps avoid unreviewable PRs and ensures the change aligns with the project direction.

### Before Submitting

- [ ] Run on your platform - No crashes or errors
- [ ] Code follows style guidelines
- [ ] Comments added for complex logic
- [ ] Commit messages are clear
- [ ] Branch is up to date with main
- [ ] No merge conflicts

### PR Description Template

```markdown
## What Changed
Brief description of your changes

## Why
Why is this change needed? What problem does it solve?

## How to Test
1. Step-by-step testing instructions
2. Include specific URLs or test cases
3. Note any special setup required

## Screenshots (if UI changes)
[Add screenshots here]

## Checklist
- [ ] Tested on [Windows/Mac/Linux]
- [ ] Updated documentation if needed
- [ ] Added entry to patchnotes.txt
- [ ] No breaking changes OR breaking changes documented
```

### Review Process

1. **Automated checks** - Must pass (when implemented)
2. **Code review** - At least one approval required
3. **Testing** - Maintainer may test on other platforms
4. **Merge** - Squash and merge with clear commit message

### After Merge

- Your contribution will be included in the next release
- You'll be credited in the release notes
- Thank you for contributing! 🎉

---

## 📁 Project Structure

```
EGM-Downloader/
│
├── app.py                    # Flask backend (Windows + Mac)
├── templates/                # UI templates (Windows + Mac)
│   ├── index.html            # Main UI
│   ├── history.html          # Version history
│   ├── themes.html           # Theme picker
│   └── theme_styles.html     # Theme CSS definitions
├── static/                   # Icons, assets (all platforms)
├── languages/                # i18n language files (all platforms)
│   └── en.json, es.json, fr.json, pt.json, de.json, it.json, ...
├── screenshots/              # App screenshots
├── scripts/                  # Build automation
│   ├── bump-version.py       # Version management
│   ├── validate-version-sync.py # Version sync validator (CI)
│   ├── gen-update-json.py    # Update JSON generator
│   └── add-patchnote.py      # Changelog helper
│
├── version.json              # SINGLE SOURCE OF TRUTH
│                              # Never edit manually!
│
├── windows/                  # Windows platform
│   ├── electron/             # Electron wrapper
│   ├── launch.py             # Runtime bootstrapper
│   └── instructions.txt      # User instructions
│
├── mac/                      # macOS platform
│   ├── electron/             # Electron wrapper + builder config
│   ├── BUILD.sh              # Build script
│   └── BUILD_NOTES.txt       # Build documentation
│
└── linux/                    # Linux platform
    ├── app.py                # Linux-specific backend
    ├── templates/            # Linux-specific UI
    ├── electron/             # Electron wrapper + builder config
    ├── BUILD.sh              # Build script
    └── INSTRUCTIONS.txt      # User instructions
```

### Shared vs Platform-Specific

**Shared (Windows + Mac):**
- `app.py` - Main backend
- `templates/index.html` - UI
- `static/` - Assets
- `requirements.txt` - Python dependencies

**Linux-Specific:**
- `linux/app.py` - Linux-specific backend, AppImage paths
- `linux/templates/` - Slightly different UI
- `linux/requirements.txt` - Linux-specific dependencies

> **Why does Linux have its own `app.py` and `templates/`?** The AppImage distribution model requires self-contained runtime bootstrapping (downloading Node.js, Electron, and ffmpeg on first launch) and different path resolution. These constraints make a shared backend impractical, so Linux maintains its own copy with platform-specific adaptations.

**Platform Directories:**
- `windows/electron/` - Windows Electron configuration
- `mac/electron/` - Mac Electron configuration
- `linux/electron/` - Linux Electron configuration

### Key Files

- **version.json** - Master version/build record (NEVER edit manually)
- **patchnotes.txt** - User-facing changelog
- **LICENSE** - AGPL-3.0 License
- **README.md** - Main documentation
- **CONTRIBUTING.md** - This file

---

## ❓ Questions?

- **General questions** - Open a discussion
- **Bug reports** - Open an issue
- **Feature requests** - Open an issue
- **Security concerns** - Please do not file security issues publicly. See [SECURITY.md](SECURITY.md) for responsible disclosure instructions

---

## 🙏 Thank You!

Every contribution helps make EGM Downloader better. Whether it's:
- Reporting bugs
- Suggesting features  
- Improving documentation
- Writing code
- Testing changes

**Your help is appreciated!** 🌟

---

**Happy Contributing!** 🚀

---

## 🔒 CI Policy — SHA-Pinned Actions

All GitHub Actions in this repo are pinned to specific commit SHAs (not version tags) to protect against supply chain attacks. When adding new actions or updating existing ones, pin to the commit SHA and keep the version as a trailing comment:

```yaml
- uses: actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd  # v5
```

Dependabot is configured to open weekly PRs proposing updated SHA pins when actions release new versions. Review the PR, verify the new SHA points to a legitimate release, then merge.
