# GitHub Actions Workflows - TODO

This document outlines GitHub Actions workflows to implement when the repository goes public.

---

## 🎯 Priority 1 - Essential Workflows

### 1. Version Sync Validation

**Purpose:** Ensure version.json stays in sync with all platform files  
**Trigger:** On every push and pull request  
**File:** `.github/workflows/validate-version.yml`

**What it checks:**
- version.json version matches app.py APP_VERSION
- version.json build matches app.py APP_BUILD
- version.json version matches index.html title
- version.json version matches electron/package.json version

**Exit:** Fail if any mismatch found

**Benefits:**
- Catches manual version edits (which should never happen)
- Ensures bump-version.py was run
- Prevents stale version numbers

**Example workflow:**
```yaml
name: Validate Version Sync

on: [push, pull_request]

jobs:
  check-version-sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Run version validation
        run: python scripts/validate-version-sync.py
```

**Script needed:** Create `scripts/validate-version-sync.py` that:
1. Loads version.json
2. Parses all target files
3. Compares version/build numbers
4. Exits 0 if all match, exits 1 if mismatch

---

### 2. Python Linting

**Purpose:** Enforce code quality standards  
**Trigger:** On pull requests  
**File:** `.github/workflows/lint-python.yml`

**What it checks:**
- PEP 8 compliance (via flake8 or ruff)
- Import order (via isort)
- Type hints coverage (optional, via mypy)

**Benefits:**
- Consistent code style
- Catches common errors early
- Reduces review burden

**Example workflow:**
```yaml
name: Lint Python

on: [pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install linters
        run: pip install flake8 isort
      - name: Run flake8
        run: flake8 app.py linux/app.py scripts/
      - name: Check import order
        run: isort --check-only app.py linux/app.py scripts/
```

---

### 3. JavaScript Linting

**Purpose:** Enforce frontend code quality  
**Trigger:** On pull requests  
**File:** `.github/workflows/lint-javascript.yml`

**What it checks:**
- JavaScript syntax (via eslint)
- Code style consistency
- Potential bugs

**Benefits:**
- Consistent frontend code
- Catches errors before runtime
- Easier to review

**Example workflow:**
```yaml
name: Lint JavaScript

on: [pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - name: Install ESLint
        run: npm install -g eslint
      - name: Lint frontend
        run: eslint templates/index.html linux/templates/index.html --ext .js,.html
```

---

## 🎯 Priority 2 - Testing Workflows

### 4. Python Unit Tests

**Purpose:** Run automated tests  
**Trigger:** On push and pull requests  
**File:** `.github/workflows/test-python.yml`

**What it tests:**
- Backend functionality
- Utility functions
- Helper scripts

**Note:** Requires test suite to be written first

**Example workflow:**
```yaml
name: Python Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: pip install -r requirements.txt pytest
      - name: Run tests
        run: pytest tests/
```

---

### 5. Build Validation (Multi-Platform)

**Purpose:** Ensure builds work on all platforms  
**Trigger:** On pull requests affecting platform code  
**File:** `.github/workflows/validate-builds.yml`

**What it does:**
- Runs build scripts on Windows/Mac/Linux runners
- Checks for build errors
- Validates output structure

**Benefits:**
- Catches platform-specific breakage
- Ensures all platforms still build
- Faster feedback than manual testing

**Example workflow:**
```yaml
name: Validate Builds

on: [pull_request]

jobs:
  build-linux:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - name: Run Linux build
        run: cd linux && chmod +x BUILD.sh && ./BUILD.sh
      - name: Verify outputs
        run: |
          test -f EGMdL.zip || exit 1
          echo "Build successful"
  
  build-mac:
    runs-on: macos-latest
    # Similar steps for Mac
  
  build-windows:
    runs-on: windows-latest
    # Similar steps for Windows
```

---

## 🎯 Priority 3 - Nice-to-Have Workflows

### 6. Dependency Updates

**Purpose:** Keep dependencies current  
**Trigger:** Weekly schedule  
**File:** `.github/workflows/dependency-updates.yml`

**What it does:**
- Checks for outdated npm packages
- Checks for outdated pip packages
- Creates PR with updates

**Tool:** Dependabot (built into GitHub)

**Configuration:** `.github/dependabot.yml`
```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/windows/electron"
    schedule:
      interval: "weekly"
  
  - package-ecosystem: "npm"
    directory: "/mac/electron"
    schedule:
      interval: "weekly"
  
  - package-ecosystem: "npm"
    directory: "/linux/electron"
    schedule:
      interval: "weekly"
  
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

---

### 7. Stale Issue Management

**Purpose:** Keep issue tracker clean  
**Trigger:** Daily schedule  
**File:** `.github/workflows/stale.yml`

**What it does:**
- Marks issues inactive for 60 days as "stale"
- Closes issues inactive for 90 days
- Leaves polite comments explaining

**Tool:** actions/stale

**Example workflow:**
```yaml
name: Close Stale Issues

on:
  schedule:
    - cron: '0 0 * * *'  # Daily

jobs:
  stale:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/stale@v8
        with:
          stale-issue-message: 'This issue has been inactive for 60 days and will be closed in 30 days if there is no activity.'
          close-issue-message: 'This issue was closed due to inactivity.'
          days-before-stale: 60
          days-before-close: 30
```

---

### 8. Release Automation

**Purpose:** Automate release creation  
**Trigger:** Manual workflow_dispatch  
**File:** `.github/workflows/create-release.yml`

**What it does:**
- Creates GitHub release
- Attaches build artifacts
- Generates release notes from patchnotes.txt

**Note:** Only useful after repository is public and releases are enabled

**Example workflow:**
```yaml
name: Create Release

on:
  workflow_dispatch:
    inputs:
      version:
        description: 'Version to release (e.g., v0.92)'
        required: true

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Create Release
        uses: actions/create-release@v1
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tag_name: ${{ github.event.inputs.version }}
          release_name: Release ${{ github.event.inputs.version }}
          draft: false
          prerelease: false
```

---

## 📊 Implementation Priority

### Immediate (when going public)
1. ✅ Version sync validation - Prevents version mismatches
2. ✅ Python linting - Code quality
3. ✅ JavaScript linting - Frontend quality

### Short-term (within 1 month)
4. ⏳ Build validation - Catch platform breakage
5. ⏳ Dependency updates - Security

### Long-term (as needed)
6. ⏳ Unit tests - Requires test suite first
7. ⏳ Stale issue management - Only after public
8. ⏳ Release automation - Only after releases enabled

---

## 🛠️ Scripts to Create

Before implementing workflows, create these helper scripts:

### scripts/validate-version-sync.py
```python
"""
Validate that version.json is in sync with all platform files.
Exit 0 if all match, exit 1 if mismatch found.
"""
# Parse version.json
# Parse app.py constants
# Parse index.html tags
# Parse package.json version
# Compare all
# Print mismatches
# Exit accordingly
```

### scripts/lint-check.sh (optional)
```bash
#!/bin/bash
# Run all linters in one command
flake8 app.py linux/app.py scripts/
isort --check-only app.py linux/app.py scripts/
# Add more as needed
```

---

## 📝 Notes

- **Secrets:** Some workflows may need GitHub secrets (API tokens, etc.)
- **Runners:** GitHub provides free runners for public repos
- **Caching:** Add caching for faster runs (pip cache, npm cache)
- **Badges:** Add workflow status badges to README.md

**Example badges:**
```markdown
![Version Sync](https://github.com/egmtm/EGM-Downloader/workflows/validate-version/badge.svg)
![Python Lint](https://github.com/egmtm/EGM-Downloader/workflows/lint-python/badge.svg)
```

---

## 🚀 Next Steps

When ready to implement:

1. Create `.github/workflows/` directory
2. Add priority 1 workflows first
3. Test on a test branch
4. Monitor for false positives
5. Adjust as needed
6. Add status badges to README
7. Document in CONTRIBUTING.md

---

**This TODO list will be updated as requirements evolve.**
