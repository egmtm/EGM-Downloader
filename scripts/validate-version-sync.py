#!/usr/bin/env python3
"""
EGM Downloader — Version Sync Validator
========================================
Validates that version.json is in sync with all platform files.

This script is used by GitHub Actions to ensure version numbers stay
consistent across the codebase. It checks that version.json matches:

  Shared / Windows (root):
    - app.py (APP_VERSION, APP_BUILD)
    - templates/index.html (title, version badge, footer)
    - windows/electron/package.json (version field)

  Linux:
    - linux/app.py (APP_VERSION, APP_BUILD)
    - linux/electron/package.json (version == the first three numbers of the app version)
    - linux/INSTRUCTIONS.txt (header)

  Mac:
    - mac/app.py (APP_VERSION, APP_BUILD)
    - mac/electron/package.json (version + build.buildVersion)
    - mac/BUILD.sh (VERSION banner, DMG filename)

Exit codes:
  0 - All versions in sync
  1 - Mismatch found (prints details to stderr)

Usage:
    python scripts/validate-version-sync.py

    # In GitHub Actions:
    - name: Validate version sync
      run: python scripts/validate-version-sync.py
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def load_version():
    """Load version.json as source of truth."""
    with open(ROOT / "version.json") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _read_or_miss(path, label, errors):
    """Read text, or append a missing-file error and return None."""
    if not path.exists():
        errors.append(f"{label} not found")
        return None
    return path.read_text(encoding="utf-8")


def _read_json_or_miss(path, label, errors):
    if not path.exists():
        errors.append(f"{label} not found")
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"{label}: JSON parse error - {e}")
        return None


def _check_app_py(rel_path, expected_version, expected_build):
    """Shared check for root app.py and linux/app.py."""
    errors = []
    path = ROOT / rel_path
    content = _read_or_miss(path, rel_path, errors)
    if content is None:
        return errors

    m = re.search(r'APP_VERSION\s*=\s*"([^"]*)"', content)
    if not m:
        errors.append(f"{rel_path}: APP_VERSION constant not found")
    elif m.group(1) != expected_version:
        errors.append(f"{rel_path}: APP_VERSION is '{m.group(1)}', expected '{expected_version}'")

    m = re.search(r'APP_BUILD\s*=\s*(\d+)', content)
    if not m:
        errors.append(f"{rel_path}: APP_BUILD constant not found")
    elif int(m.group(1)) != expected_build:
        errors.append(f"{rel_path}: APP_BUILD is {m.group(1)}, expected {expected_build}")

    return errors


# --------------------------------------------------------------------------
# Shared / Windows checks
# --------------------------------------------------------------------------

def check_root_app_py(v, b):
    return _check_app_py("app.py", v, b)


def check_root_index_html(v, b, date, time):
    errors = []
    rel = "templates/index.html"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors

    # <title> tag
    m = re.search(r'<title>EGM Downloader v([\d.]+)</title>', content)
    if not m:
        errors.append(f"{rel}: <title> tag not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: <title> is 'v{m.group(1)}', expected 'v{v}'")


    return errors


def semver3(v):
    """Same rule as bump-version.py: Linux and Mac package.json carry the first
    three numbers of the app version (electron-builder needs strict X.Y.Z)."""
    return ".".join(v.split(".")[:3])


def check_windows_package_json(v):
    errors = []
    rel = "windows/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors
    if data.get("version") != v:
        errors.append(f"{rel}: version is '{data.get('version')}', expected '{v}'")
    return errors


def check_windows_launcher_rc(v):
    """The native launcher's embedded PE version resource (Explorer ->
    Properties -> Details). Found stuck at 0.99.11 on a live v1.3.2 build --
    cosmetic only, but this check exists so it can't go stale again."""
    errors = []
    rel = "windows/launcher.rc"
    path = ROOT / rel
    if not path.exists():
        errors.append(f"{rel}: file not found")
        return errors
    text = path.read_text(encoding="utf-8")

    parts = v.split(".")
    while len(parts) < 4:
        parts.append("0")
    comma_form = ",".join(parts[:4])

    if not re.search(rf'FILEVERSION\s+{re.escape(comma_form)}', text):
        errors.append(f"{rel}: FILEVERSION does not match expected {comma_form}")
    if not re.search(rf'PRODUCTVERSION\s+{re.escape(comma_form)}', text):
        errors.append(f"{rel}: PRODUCTVERSION does not match expected {comma_form}")
    if not re.search(rf'VALUE "FileVersion",\s*"{re.escape(v)}"', text):
        errors.append(f"{rel}: FileVersion string does not match expected '{v}'")
    if not re.search(rf'VALUE "ProductVersion",\s*"{re.escape(v)}"', text):
        errors.append(f"{rel}: ProductVersion string does not match expected '{v}'")
    return errors


# --------------------------------------------------------------------------
# Mac checks
# --------------------------------------------------------------------------

def check_mac_app_py(v, b):
    return _check_app_py("mac/app.py", v, b)


# --------------------------------------------------------------------------
# Linux checks
# --------------------------------------------------------------------------

def check_linux_app_py(v, b):
    return _check_app_py("linux/app.py", v, b)


def check_linux_package_json(v):
    errors = []
    rel = "linux/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors
    expected = semver3(v)
    if data.get("version") != expected:
        errors.append(f"{rel}: version is '{data.get('version')}', expected '{expected}'")
    return errors


def check_linux_instructions(v):
    errors = []
    rel = "linux/INSTRUCTIONS.txt"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors
    m = re.search(r'EGM Downloader v([\d.]+)\s+\u2014\s+Linux', content)
    if not m:
        errors.append(f"{rel}: header line 'EGM Downloader v0.xx -- Linux' not found")
    elif m.group(1) != v:
        errors.append(f"{rel}: header version is 'v{m.group(1)}', expected 'v{v}'")
    return errors


# --------------------------------------------------------------------------
# Mac checks
# --------------------------------------------------------------------------

def check_mac_package_json(v):
    errors = []
    rel = "mac/electron/package.json"
    data = _read_json_or_miss(ROOT / rel, rel, errors)
    if data is None:
        return errors

    expected = semver3(v)
    if data.get("version") != expected:
        errors.append(f"{rel}: version is '{data.get('version')}', expected '{expected}'")

    build_cfg = data.get("build", {})
    bv = build_cfg.get("buildVersion") if isinstance(build_cfg, dict) else None
    if bv is None:
        # buildVersion is optional; only error if present and wrong.
        pass
    elif bv != expected:
        errors.append(f"{rel}: build.buildVersion is '{bv}', expected '{expected}'")

    return errors


def check_mac_build_sh(v):
    errors = []
    rel = "mac/BUILD.sh"
    path = ROOT / rel
    content = _read_or_miss(path, rel, errors)
    if content is None:
        return errors

    m = re.search(r'VERSION: v([\d.]+)', content)
    if m and m.group(1) != v:
        errors.append(f"{rel}: VERSION banner is 'v{m.group(1)}', expected 'v{v}'")

    m = re.search(r'EGM Downloader-([\d.]+)-arm64\.dmg', content)
    expected_dmg = v
    if m and m.group(1) != expected_dmg:
        errors.append(f"{rel}: DMG filename has '{m.group(1)}', expected '{expected_dmg}'")

    return errors


# --------------------------------------------------------------------------
# Item 5 — Portable file list drift check
# --------------------------------------------------------------------------

def check_linux_drift_from_root():
    """Verify linux/requirements.txt matches root requirements.txt.

    Bug class this catches:
      - linux/requirements.txt drifting from root → mutagen (or other deps)
        added to root never get installed in Linux Python bundle, so
        importlib.metadata.version() returns "not installed" forever.

    Linux ships the root templates/ tree (linux/electron/package.json), so
    there is no template copy to compare.

    Returns errors list. Opportunistic — skips if either side doesn't exist.
    """
    errors = []
    root = ROOT

    # requirements.txt
    root_req  = root / 'requirements.txt'
    linux_req = root / 'linux' / 'requirements.txt'
    if root_req.exists() and linux_req.exists():
        # Compare ignoring blank lines and comments — what matters is the deps
        def normalize(p):
            return sorted(
                line.strip() for line in p.read_text().splitlines()
                if line.strip() and not line.strip().startswith('#')
            )
        if normalize(root_req) != normalize(linux_req):
            errors.append(
                "linux/requirements.txt has drifted from requirements.txt — "
                "deps differ (e.g. mutagen missing on linux means the plugin "
                "won't install, causing 'checking…' UI hang). Sync both."
            )

    return errors


# ── Windows file lists: one list of app files, both editions checked against it ──
# windows/app-files.txt lists the app files once, as repository-relative paths. The portable stage
# (windows/BUILD.sh) copies them next to its launcher, the installer folder build
# (windows/installer/build-folder.sh) into resources/app. Each edition adds only its own files:
#   portable:  the launcher exe, launch.py, instructions.txt, electron/package*.json, .portable
#              (plus the shell files main.js, preload.js and splash.html in electron/)
#   installer: the Electron runtime at the top of the folder, resources/app.asar (holding the shell
#              files) and resources/python (the bundled Python)
APP_FILES_LIST = ROOT / 'windows' / 'app-files.txt'
PORTABLE_ONLY = {'EGM Downloader.exe', 'launch.py', 'instructions.txt',
                 'electron/package.json', 'electron/package-lock.json', '.portable'}
SHELL_FILES = {'main.js', 'preload.js', 'splash.html'}
INSTALLER_RESOURCES = {'app', 'app.asar', 'python'}


def read_app_files():
    """The relative paths in windows/app-files.txt, in order (comments and blank lines skipped)."""
    lines = APP_FILES_LIST.read_text(encoding='utf-8').splitlines()
    return [l.strip() for l in lines if l.strip() and not l.lstrip().startswith('#')]


def check_app_files_list():
    """windows/app-files.txt: every entry a plain relative path to a file in the repo, no duplicate,
    and nothing the app needs left out (every template, every language file)."""
    if not APP_FILES_LIST.exists():
        return [f"{APP_FILES_LIST.relative_to(ROOT)} is missing"]
    errors = []
    files = read_app_files()
    dupes = sorted({f for f in files if files.count(f) > 1})
    if dupes:
        errors.append(f"windows/app-files.txt lists files twice: {dupes}")
    for f in files:
        if f.startswith(('/', '\\')) or '..' in f.split('/') or '\\' in f:
            errors.append(f"windows/app-files.txt: not a plain relative path: {f}")
        elif not (ROOT / f).is_file():
            errors.append(f"windows/app-files.txt lists a file that does not exist: {f}")
    # Completeness: a file missing from the list is missing from both editions, which no sync
    # check can see (that exact gap once shipped TemplateNotFound: i18n.html in a test build).
    needed = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'templates').glob('*.html')}
    needed |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'templates' / 'js').glob('*.html')}
    needed |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'languages').glob('*.json')}
    needed |= {'app.py', 'patchnotes.txt', 'LICENSE'}
    unlisted = sorted(needed - set(files))
    if unlisted:
        errors.append(f"In the repo but missing from windows/app-files.txt: {unlisted}")
    return errors


def portable_stage_files(sh_text):
    """The relative paths the portable stage of windows/BUILD.sh produces, read from its cp lines,
    its loop over windows/app-files.txt and the files it writes itself."""
    start = sh_text.find('# ── Build portable variant')
    end = sh_text.find('# ── Push to GitHub', start)
    if start == -1 or end == -1:
        return None
    section = sh_text[start:end]
    out = set()
    for src, dest in re.findall(r'^cp "\$REPO_ROOT/([^"]+)"\s+"\$PORTABLE_STAGE/([^"]*)"', section, re.M):
        out.add(dest + src.rsplit('/', 1)[-1] if dest == '' or dest.endswith('/') else dest)
    if re.search(r'^done < "\$REPO_ROOT/windows/app-files\.txt"', section, re.M):
        out |= set(read_app_files())
    out |= set(re.findall(r'> "\$PORTABLE_STAGE/([^"]+)"', section))
    return out


def check_portable_stage():
    """The portable zip holds exactly the app files plus its own files (relative paths)."""
    sh_path = ROOT / 'windows' / 'BUILD.sh'
    if not sh_path.exists() or not APP_FILES_LIST.exists():
        return []
    have = portable_stage_files(sh_path.read_text(encoding='utf-8', errors='replace'))
    if have is None:
        return ["windows/BUILD.sh: the portable stage section was not found"]
    want = set(read_app_files()) | PORTABLE_ONLY | {f'electron/{n}' for n in SHELL_FILES}
    errors = []
    if want - have:
        errors.append(f"Portable stage is missing: {sorted(want - have)}")
    if have - want:
        errors.append(f"Portable stage has files that are neither app files nor portable-only: {sorted(have - want)}")
    return errors


def _asar_files(path):
    """File names in an asar archive's header (top level only: the shell keeps no folders there)."""
    import struct
    with open(path, 'rb') as f:
        head = f.read(16)
        size = struct.unpack('<I', head[12:16])[0]
        header = json.loads(f.read(size).decode('utf-8'))
    return set(header.get('files', {}))


def check_installer_folder(folder=None):
    """The built installer folder (dist/win-unpacked), when there is one: resources/app holds exactly
    the app files, app.asar the shell files, resources holds nothing else but the bundled Python,
    and the exe is at the top. File sets only: a folder built before a later edit is not an error."""
    folder = Path(folder) if folder else ROOT / 'dist' / 'win-unpacked'
    if not folder.is_dir():
        return []
    errors = []
    res = folder / 'resources'
    if not (folder / 'EGM Downloader.exe').is_file():
        errors.append(f"{folder.name}: EGM Downloader.exe is not at the top of the folder")
    if not res.is_dir():
        return errors + [f"{folder.name}: no resources folder"]
    extra = sorted(p.name for p in res.iterdir())
    if set(extra) != INSTALLER_RESOURCES:
        errors.append(f"{folder.name}/resources holds {extra}, expected {sorted(INSTALLER_RESOURCES)}")
    app = res / 'app'
    if app.is_dir():
        have = {p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        want = set(read_app_files())
        if have != want:
            errors.append(f"{folder.name}/resources/app differs from windows/app-files.txt: "
                          f"missing {sorted(want - have)}, extra {sorted(have - want)}")
    if (res / 'app.asar').is_file():
        inside = _asar_files(res / 'app.asar')
        if inside != SHELL_FILES | {'package.json'}:
            errors.append(f"{folder.name}/resources/app.asar holds {sorted(inside)}, expected the shell files and package.json")
    if not (res / 'python' / 'python.exe').is_file():
        errors.append(f"{folder.name}/resources/python has no python.exe")
    return errors


# --------------------------------------------------------------------------
# Item 2 — Merge conflict marker scanner
# --------------------------------------------------------------------------

def check_merge_conflict_markers():
    """Fail if any tracked source file contains unresolved Git merge conflict markers.

    Uses git ls-files so gitignored directories (node_modules/, dist/, python/,
    linux/python/, mac/python/) are automatically excluded — no false positives
    from Chromium's LICENSES.chromium.html or pydoc_data/topics.py.
    """
    import subprocess
    errors = []
    EXTS = {'.py', '.js', '.json', '.sh', '.md', '.txt', '.html', '.nsi', '.yml', '.yaml'}
    # Split marker strings so this file doesn't trigger its own scan
    MARKERS = ('<' * 7 + ' ', '>' * 7 + ' ')

    try:
        result = subprocess.run(
            ['git', 'ls-files'],
            cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        tracked = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    except Exception:
        # git not available or not a repo — fall back to rglob with exclusions
        tracked = [
            str(p.relative_to(ROOT))
            for p in ROOT.rglob('*')
            if p.is_file()
            and p.suffix in EXTS
            and not any(part in ('node_modules', 'dist', 'python', '__pycache__') for part in p.parts)
        ]

    for rel in tracked:
        path = ROOT / rel
        if path.suffix not in EXTS:
            continue
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
            for marker in MARKERS:
                if marker in content:
                    errors.append(f"{rel}: contains merge conflict marker '{marker.strip()}'")
                    break  # one error per file is enough
        except (OSError, PermissionError):
            continue

    return errors


# --------------------------------------------------------------------------
# Item 4 — JSON feed validation (parse + required keys + cross-platform purity)
# --------------------------------------------------------------------------

FEED_REQUIRED_KEYS = [
    '_comment', '_version_notes', '_history', '_last_updated',
    'version', 'build', 'label', 'downloadUrl', 'zip',
]

FEED_BANNED_TERMS = {
    'egm-version.json':     ['mac update', 'macos', 'darwin', 'appimage', '.dmg', '.deb', '.rpm', 'snap install'],
    'egmac-update.json':    ['windows', 'win32', 'nsis', '.msi', 'appimage', 'apt-get', 'yum', 'snap install'],
    'egmlinux-update.json': ['windows', 'win32', '.exe', 'mac update', 'macos', 'darwin', '.dmg'],
}


def check_json_feeds_parse():
    """Fail loudly if any dist/ feed contains invalid JSON.

    Opportunistic: skips missing feeds (dist/ not present after non-build CI run).
    """
    errors = []
    dist = ROOT / 'dist'
    for feed in FEED_BANNED_TERMS:
        path = dist / feed
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            errors.append(f"dist/{feed}: invalid JSON — {e}")
    return errors


def check_json_feeds_keys():
    """Fail if any dist/ feed is missing a required top-level key."""
    errors = []
    dist = ROOT / 'dist'
    for feed in FEED_BANNED_TERMS:
        path = dist / feed
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue  # caught by check_json_feeds_parse
        missing = [k for k in FEED_REQUIRED_KEYS if k not in d]
        if missing:
            errors.append(f"dist/{feed}: missing required keys: {missing}")
    return errors


def check_json_feeds_purity():
    """Fail if a platform's _version_notes bullets contain language from other platforms.

    Terms are matched case-insensitively. Conservative list — only clear OS-specific
    language. Avoids terms that could legitimately appear in cross-platform bullets
    (e.g. 'Windows' is banned from Linux/Mac feeds, but 'window' is not).
    """
    errors = []
    dist = ROOT / 'dist'
    for feed, banned in FEED_BANNED_TERMS.items():
        path = dist / feed
        if not path.exists():
            continue
        try:
            d = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        for note in d.get('_version_notes', []):
            note_lower = note.lower()
            for term in banned:
                if term.startswith('.'):
                    # File extension — substring match is appropriate (.dmg, .exe, etc.)
                    hit = term in note_lower
                else:
                    # Word — use word boundary to avoid false positives
                    # (e.g. "nsis" inside "consistent", "win" inside "window")
                    hit = bool(re.search(r'\b' + re.escape(term) + r'\b', note_lower))
                if hit:
                    errors.append(
                        f"dist/{feed}: cross-platform leak — bullet contains '{term}': "
                        f"'{note[:80]}{'...' if len(note) > 80 else ''}'"
                    )
                    break  # one error per bullet is enough
    return errors


# --------------------------------------------------------------------------
# Pre-handoff feed checks (build monotonicity, notes/headline, checksums,
# size, cross-feed consistency, stale-feed) — all OPPORTUNISTIC: they run only
# when dist/ feeds are present (i.e. a release build), never on a plain CI run.
# --------------------------------------------------------------------------

# All four published feeds. The portable feed is optional (only emitted when a
# release ships the portable variant), so every check tolerates it being absent.
ALL_FEED_FILES = [
    'egm-version.json',           # Windows installer (auto-update)
    'egm-portable-version.json',  # Windows portable (optional)
    'egmac-update.json',          # Mac (informational)
    'egmlinux-update.json',       # Linux (informational)
]

FEED_PLATFORM_TAG = {
    'egm-version.json':          'WINDOWS',
    'egm-portable-version.json': 'WINDOWS',
    'egmac-update.json':         'MAC',
    'egmlinux-update.json':      'LINUX',
}

_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


# A bullet may carry MORE THAN ONE leading tag, e.g. "• [MAC] [LINUX] Foo"
# (patchnotes.txt already uses this form). scripts/gen-update-json.py -- which
# actually BUILDS the feeds -- matches the whole run of leading tags and tests
# set membership. Any replica of that extraction must do the same, or it
# disagrees with the shipped feed: a single-tag `^\[(TAG|ALL)\]` pattern counts
# "[MAC] [LINUX] Foo" for MAC but drops it for LINUX, and leaves "[LINUX] "
# embedded in the note text for MAC.
_BULLET_TAGS_RE = re.compile(r'^((?:\[[A-Z]+\]\s*)+)(.+)$')
_TAG_RE = re.compile(r'\[([A-Z]+)\]')


def _extract_patchnote_bullets(patchnotes_text, platform_tag):
    """Extracts the current (most recent) patchnotes.txt entry's [<PLATFORM>]/
    [ALL] bullets. Kept in sync with the identical extraction in
    tests/test_parity.py (_extract_patchnote_bullets) and windows/BUILD.sh's
    own inline version — all three must agree on what "the current entry's
    bullets" means. If you change one, change all three."""
    bullets, in_block = [], False
    for line in patchnotes_text.splitlines():
        if re.match(r'^v\d', line):
            if in_block:
                break
            in_block = True
            continue
        if in_block:
            if line.startswith('  \u2022 '):
                m = _BULLET_TAGS_RE.match(line[4:].strip())
                if m and ({'ALL', platform_tag} & set(_TAG_RE.findall(m.group(1)))):
                    bullets.append(m.group(2).strip())
            elif line.strip() == '' and bullets:
                break
    return bullets


def _load_feed(name):
    """Load a dist/ feed as JSON, or None if absent/unparseable (parse errors are
    reported by check_json_feeds_parse, so we stay silent here)."""
    path = ROOT / 'dist' / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None


def check_feed_build_monotonic():
    """Every feed's build must be strictly greater than the last released build
    (scripts/last-released-build.txt). Catches publishing a feed without bumping
    the build — the most common feed mistake. Skips if no baseline is configured."""
    errors = []
    baseline_path = ROOT / 'scripts' / 'last-released-build.txt'
    if not baseline_path.exists():
        return errors
    raw = baseline_path.read_text(encoding='utf-8').strip()
    try:
        baseline = int(raw.split()[0])
    except (ValueError, IndexError):
        errors.append(f"scripts/last-released-build.txt: not a valid integer ({raw!r})")
        return errors
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        b = d.get('build')
        if not isinstance(b, int):
            errors.append(f"dist/{name}: 'build' missing or not an integer ({b!r})")
        elif b <= baseline:
            errors.append(
                f"dist/{name}: build {b} must be > last released build {baseline} "
                f"— bump version.json build before generating feeds (and update "
                f"scripts/last-released-build.txt to {b} after this release ships)."
            )
    return errors


def check_feed_notes_and_headline():
    """Every feed's _version_notes must match patchnotes.txt's own per-platform
    bullet count exactly (not truncated/collapsed during generation), and —
    when a keyword list is configured (scripts/release-keywords.txt) — at
    least one bullet must mention a headline keyword. Catches thin/collapsed
    notes and the v1.1 incident where feeds shipped with only maintenance
    bullets and never mentioned Subscriptions. An EMPTY keyword file
    intentionally skips the headline requirement (a pure maintenance release).

    Previously this asserted a fixed >= 3 minimum on the feed alone. That
    stopped being a reliable proxy for "not truncated" once genuinely small
    maintenance-only releases (a single dependency bump, no user-facing
    changes) became a normal, valid shape -- a real 2-bullet release and a
    21-into-2 collapse look identical under any fixed floor low enough to
    let real small releases through. Cross-referencing against patchnotes.txt's
    own extraction catches a collapse regardless of how many real bullets
    there are, including exactly 1."""
    errors = []
    kw_path = ROOT / 'scripts' / 'release-keywords.txt'
    keywords = []
    if kw_path.exists():
        keywords = [ln.strip().lower()
                    for ln in kw_path.read_text(encoding='utf-8').splitlines()
                    if ln.strip() and not ln.strip().startswith('#')]
    pn_path = ROOT / 'patchnotes.txt'
    pn_text = pn_path.read_text(encoding='utf-8') if pn_path.exists() else ''
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        notes = d.get('_version_notes', [])
        n = len(notes) if isinstance(notes, list) else 0
        tag = FEED_PLATFORM_TAG[name]
        source_n = len(_extract_patchnote_bullets(pn_text, tag))
        if not isinstance(notes, list) or n != source_n:
            errors.append(
                f"dist/{name}: _version_notes has {n} bullet(s) but "
                f"patchnotes.txt's current [{tag}|ALL] entry has {source_n} "
                f"-- feed generation dropped or collapsed bullets."
            )
            continue
        if n < 1:
            errors.append(f"dist/{name}: _version_notes is empty")
            continue
        if keywords:
            joined = " ".join(str(x) for x in notes).lower()
            if not any(kw in joined for kw in keywords):
                errors.append(
                    f"dist/{name}: no _version_notes bullet mentions a headline keyword "
                    f"{keywords} — add the release's headline feature to the notes, or empty "
                    f"scripts/release-keywords.txt for a pure maintenance release."
                )
    return errors


def check_feed_checksums():
    """Every feed must carry _checksums.sha256 as lowercase 64-char hex. Catches the
    PowerShell uppercase-SHA256 issue, truncated hashes, and missing checksums."""
    errors = []
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        cs = d.get('_checksums')
        if not isinstance(cs, dict) or 'sha256' not in cs:
            errors.append(f"dist/{name}: missing _checksums.sha256")
            continue
        sha = cs.get('sha256', '')
        if not isinstance(sha, str) or not _SHA256_RE.match(sha):
            if isinstance(sha, str) and sha.lower() != sha and _SHA256_RE.match(sha.lower()):
                reason = "uppercase — must be lowercase hex"
            elif isinstance(sha, str):
                reason = f"not 64 lowercase-hex chars (len={len(sha)})"
            else:
                reason = "not a string"
            errors.append(f"dist/{name}: _checksums.sha256 invalid ({reason}): {sha!r}")
    return errors


def check_feed_size_bytes():
    """Every feed must carry a top-level integer size_bytes > 0. (Currently the
    BUILD.sh gen-update-json calls do NOT pass --size-bytes, so this fails until the
    build is updated to pass it — that gap is exactly what this gate surfaces.)"""
    errors = []
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        sz = d.get('size_bytes')
        if not isinstance(sz, int) or isinstance(sz, bool) or sz <= 0:
            errors.append(
                f"dist/{name}: size_bytes must be an integer > 0 ({sz!r}) — pass "
                f"--size-bytes to gen-update-json.py in the build."
            )
    return errors


def check_feed_cross_consistency(v, b):
    """Every present feed must agree with version.json on BOTH version and build.
    This makes all four feeds consistent with each other (covers the case where the
    Mac feed was left stale at an old version while the others advanced)."""
    errors = []
    for name in ALL_FEED_FILES:
        d = _load_feed(name)
        if d is None:
            continue
        fv = d.get('version')
        fb = d.get('build')
        if fv != v:
            errors.append(
                f"dist/{name}: version '{fv}' != source-of-truth '{v}' "
                f"(stale/forgotten feed — regenerate it)."
            )
        if fb != b:
            errors.append(
                f"dist/{name}: build {fb!r} != source-of-truth {b} (regenerate this feed)."
            )
    return errors


def main():
    print("Validating version sync...")
    print()

    try:
        data = load_version()
    except Exception as e:
        print(f"ERROR: Failed to load version.json: {e}", file=sys.stderr)
        return 1

    v = data.get("version")
    b = data.get("build")
    date = data.get("date")
    time = data.get("time")

    if not all([v, b, date, time]):
        print("ERROR: version.json missing required fields", file=sys.stderr)
        return 1

    print(f"   Source of truth: v{v} Build {b} @ {date} {time}")
    print()

    all_errors = []

    checks = [
        ("app.py",                              lambda: check_root_app_py(v, b)),
        ("templates/index.html",                lambda: check_root_index_html(v, b, date, time)),
        ("windows/electron/package.json",       lambda: check_windows_package_json(v)),
        ("windows/launcher.rc",                 lambda: check_windows_launcher_rc(v)),
        ("linux/app.py",                        lambda: check_linux_app_py(v, b)),
        ("linux/electron/package.json",         lambda: check_linux_package_json(v)),
        ("linux/INSTRUCTIONS.txt",              lambda: check_linux_instructions(v)),
        ("mac/app.py",                          lambda: check_mac_app_py(v, b)),
        ("mac/electron/package.json",           lambda: check_mac_package_json(v)),
        ("mac/BUILD.sh",                        lambda: check_mac_build_sh(v)),
    ]

    for label, fn in checks:
        print(f"   Checking {label}...")
        all_errors.extend(fn())

    # ── Item 5: Windows file lists (portable stage, installer folder) ──────────
    print("   Checking windows/app-files.txt...")
    all_errors.extend(check_app_files_list())
    print("   Checking the portable stage against the app files...")
    all_errors.extend(check_portable_stage())
    print("   Checking the installer folder (dist/win-unpacked, if built)...")
    all_errors.extend(check_installer_folder())

    # ── Item 6: Linux/Mac copies drift check ──────────────────────────────────
    # linux/requirements.txt should track root/requirements.txt. Mac uses root
    # requirements, and both Mac and Linux ship the root templates/ tree, so the
    # Linux requirements file is the only copy that needs drift detection.
    print("   Checking linux/requirements for drift vs root...")
    all_errors.extend(check_linux_drift_from_root())

    # ── Item 2: Merge conflict markers ────────────────────────────────────────
    print("   Scanning for merge conflict markers...")
    all_errors.extend(check_merge_conflict_markers())

    # ── Item 4: JSON feed validation (opportunistic — skipped if dist/ absent) ─
    dist = ROOT / "dist"
    feeds_present = any((dist / f).exists() for f in ALL_FEED_FILES)
    if feeds_present:
        print("   Validating JSON feeds (parse validity)...")
        all_errors.extend(check_json_feeds_parse())
        print("   Validating JSON feeds (required keys)...")
        all_errors.extend(check_json_feeds_keys())
        print("   Validating JSON feeds (cross-platform purity)...")
        all_errors.extend(check_json_feeds_purity())
        print("   Validating JSON feeds (build > last released)...")
        all_errors.extend(check_feed_build_monotonic())
        print("   Validating JSON feeds (notes depth + headline keyword)...")
        all_errors.extend(check_feed_notes_and_headline())
        print("   Validating JSON feeds (sha256 lowercase hex)...")
        all_errors.extend(check_feed_checksums())
        print("   Validating JSON feeds (size_bytes present)...")
        all_errors.extend(check_feed_size_bytes())
        print("   Validating JSON feeds (cross-feed version/build agreement)...")
        all_errors.extend(check_feed_cross_consistency(v, b))
    else:
        print("   JSON feeds: dist/ not present — skipping feed validation")

    print()

    if all_errors:
        print("VERSION SYNC FAILED", file=sys.stderr)
        print(file=sys.stderr)
        print("Mismatches found:", file=sys.stderr)
        for error in all_errors:
            print(f"  * {error}", file=sys.stderr)
        print(file=sys.stderr)
        print("Fix by running: python scripts/bump-version.py", file=sys.stderr)
        print(file=sys.stderr)
        return 1
    else:
        print("All version strings are in sync across every platform.")
        print()
        return 0


if __name__ == "__main__":
    sys.exit(main())
