# 🚀 Build EGM Downloader for Mac - SIMPLE INSTRUCTIONS

## ✅ Everything is Ready!

I've prepared the complete project with:
- ✅ Cross-platform Python backend (auto-detects macOS/ARM)
- ✅ macOS Electron configuration
- ✅ Your EGM logo converted to .icns format
- ✅ Build script ready to run

---

## 📋 Prerequisites (One-Time Setup)

### 1. Install Python 3.10+
```bash
# Check if you have it:
python3 --version

# If not, install with Homebrew:
brew install python3
```

### 2. Install Node.js 18+
```bash
# Check if you have it:
node --version

# If not, install with Homebrew:
brew install node
```

### 3. Install Homebrew (if you don't have it)
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

---

## 🎯 Build the App (3 Simple Steps)

### Step 1: Open Terminal and Navigate to the Project
```bash
cd /path/to/egm-downloader-mac-ready
```

### Step 2: Run the Build Script
```bash
./BUILD.sh
```

The script will:
- ✅ Install Node.js dependencies
- ✅ Install Python dependencies
- ✅ Build the Electron app
- ✅ Create a signed .dmg installer

**This takes about 2-3 minutes on first run.**

### Step 3: Find Your App
```bash
electron/dist/EGM Downloader-0.67.0-arm64.dmg
```

**Done!** 🎉

---

## 📦 Install the App

1. **Double-click** the .dmg file
2. **Drag** "EGM Downloader" to Applications
3. **Right-click** the app → "Open" (first time only, to bypass Gatekeeper)
4. **Future launches:** Just double-click normally

---

## 🔧 If You Get Errors

### "Python not found"
```bash
brew install python3
```

### "Node.js not found"
```bash
brew install node
```

### "Cannot open app" (Security Warning)
This is normal for unsigned apps:
1. Right-click the app → **Open**
2. Click **Open** in the dialog
3. Works normally after that

### "Build failed"
Make sure you're in the project root directory when running the build script:
```bash
./BUILD.sh
```

---

## 🎯 What You'll Get

- ✅ **Native ARM64 app** for M1/M2/M3/M4/M5
- ✅ **DMG installer** (ready to share)
- ✅ **ZIP archive** (portable version)
- ✅ **Full functionality** (same as Windows version)

---

## 📂 Build Output Location

After building, you'll find:

```
electron/
  dist/
    ├── EGM Downloader-0.67.0-arm64.dmg  ← Main installer
    ├── EGM Downloader-0.67.0-arm64.zip  ← Portable version
    └── mac-arm64/
        └── EGM Downloader.app            ← The actual app
```

---

## 🎨 About the Icon

I converted your EGM logo to macOS format:
- ✅ `static/icon.icns` - Ready to use
- ✅ `static/icon.iconset/` - All sizes (if you need to rebuild)
- ✅ `static/icon-1024.png` - High-res source

---

## ⚡ Quick Commands Cheat Sheet

```bash
# Navigate to project
cd /path/to/egm-downloader-mac-ready

# Build the app
./BUILD.sh

# Open the output folder
open electron/dist
```

---

## ✅ Testing Checklist

After building, verify:

- [ ] App launches
- [ ] Flask backend starts automatically
- [ ] UI loads in the app window
- [ ] Can paste video URLs
- [ ] Download works (try a YouTube video)
- [ ] Audio extraction works
- [ ] Tray icon appears
- [ ] App quits cleanly

---

## 🎉 You're Done!

The build script handles everything. Just run it and get your .dmg!

**Need help?** Check the error messages - they usually tell you exactly what's missing (Python, Node, etc.)

---

**Built with ❤️ for macOS ARM64**
