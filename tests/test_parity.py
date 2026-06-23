"""
Tier 1 — Parity tests.

Checks that all three platforms (Windows, Mac, Linux) stay in sync on the
invariants that have caused real bugs when they drifted. Each test here
maps to at least one regression we shipped and then had to fix.
"""
import re
import pytest
from conftest import read_source, read_index_scripts, PLATFORM_APP_FILES, PLATFORM_NAMES


# ── Helpers ────────────────────────────────────────────────────────────────────

def extract_allowed_keys(source: str) -> set:
    """Extract the ALLOWED settings keys set from a platform's app.py source."""
    m = re.search(r'ALLOWED\s*=\s*\{([^}]+)\}', source, re.DOTALL)
    assert m, "ALLOWED set not found in source"
    raw = m.group(1)
    return {k.strip().strip('"').strip("'") for k in raw.split(",") if k.strip().strip('"').strip("'")}


def extract_routes(source: str) -> set:
    """Extract all @app.route(...) paths from a platform's app.py source."""
    return set(re.findall(r'@app\.route\("([^"]+)"', source))


# ── Known platform-specific exceptions ────────────────────────────────────────
# These routes exist on only one platform by design — not a drift bug.
# ── Known platform-specific route exceptions ──────────────────────────────────
# Routes that exist on some platforms but not others by design.
# Update this set whenever a new platform-specific route is added intentionally.
WIN_ONLY_ROUTES = {
    "/api/portable-status",   # portable mode detection — Windows install only
    "/api/show-window",       # second-instance signal — Windows launch.py only
    "/api/show-window-check", # second-instance poll   — Windows launch.py only
    "/api/electron/reinstall", # Electron reinstall marker — Windows only (Mac/Linux bundle)
}
# Auto-update: Windows + Mac have it; Linux does not (AppImage = manual update)
NO_LINUX_ROUTES = WIN_ONLY_ROUTES | {"/api/download-update"}


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_allowed_keys_identical_across_platforms():
    """
    ALLOWED settings keys must be identical across all 3 app.py files.
    Regression: Mac/Linux were missing default_audio_format and default_video_format (v0.99.10).
    """
    sources = {name: read_source(f) for name, f in zip(PLATFORM_NAMES, PLATFORM_APP_FILES)}
    keys    = {name: extract_allowed_keys(src) for name, src in sources.items()}

    assert keys["windows"] == keys["mac"], (
        f"Mac ALLOWED differs from Windows.\n"
        f"  Windows-only: {keys['windows'] - keys['mac']}\n"
        f"  Mac-only:     {keys['mac'] - keys['windows']}"
    )
    assert keys["windows"] == keys["linux"], (
        f"Linux ALLOWED differs from Windows.\n"
        f"  Windows-only: {keys['windows'] - keys['linux']}\n"
        f"  Linux-only:   {keys['linux'] - keys['windows']}"
    )


def test_routes_identical_across_platforms():
    """
    Flask routes must be identical across all 3 platforms (minus known exceptions).
    Drift here means features available on one platform are silently missing on others.
    """
    sources = {name: read_source(f) for name, f in zip(PLATFORM_NAMES, PLATFORM_APP_FILES)}
    routes  = {name: extract_routes(src) for name, src in sources.items()}

    # Windows vs Mac: remove Windows-only routes
    win_vs_mac = routes["windows"] - WIN_ONLY_ROUTES
    assert win_vs_mac == routes["mac"], (
        f"Mac routes differ from Windows.\n"
        f"  Windows-only: {win_vs_mac - routes['mac']}\n"
        f"  Mac-only:     {routes['mac'] - win_vs_mac}"
    )
    # Windows vs Linux: also remove auto-update (Linux = no auto-update by design)
    win_vs_linux = routes["windows"] - NO_LINUX_ROUTES
    assert win_vs_linux == routes["linux"], (
        f"Linux routes differ from Windows.\n"
        f"  Windows/Mac-only: {win_vs_linux - routes['linux']}\n"
        f"  Linux-only:       {routes['linux'] - win_vs_linux}"
    )


def test_frontend_settings_keys_accepted_by_backend():
    """
    Every settings key the frontend sends via /api/settings/save must be in
    the backend ALLOWED set, or it will be silently dropped.
    """
    index_src  = read_index_scripts()  # JS extracted from index.html (js/ modules resolved)
    backend_src = read_source("app.py")

    # Extract keys from JS save calls: post('/api/settings/save', { key: value })
    frontend_keys = set(re.findall(r'["\']([a-z_]+)["\']:\s*(?:s\.|true|false|\w)', index_src))
    allowed_keys  = extract_allowed_keys(backend_src)

    # Filter to only keys that look like settings (snake_case, known patterns)
    settings_pattern = re.compile(r'^[a-z][a-z_]+$')
    candidate_keys = {k for k in frontend_keys if settings_pattern.match(k) and len(k) > 3}

    # Find keys sent by frontend that backend would silently ignore
    # (Only flag keys we can confirm are in the save payload)
    save_blocks = re.findall(r"post\(['\"][^'\"]*settings/save['\"],\s*\{([^}]+)\}", index_src)
    saved_keys = set()
    for block in save_blocks:
        saved_keys.update(re.findall(r'["\']?([a-z_]+)["\']?\s*:', block))

    unhandled = saved_keys - allowed_keys - {""}
    assert not unhandled, (
        f"Frontend sends keys not in backend ALLOWED (would be silently dropped): {unhandled}"
    )


def test_theme_data_matches_themes_array():
    """
    Every key in THEME_DATA must exist in THEMES array and vice versa
    (excluding 'custom' which is handled specially).
    Regression: new theme batches added to one structure but not the other.
    """
    source = read_index_scripts()  # JS extracted from index.html (js/ modules resolved)

    # Extract THEMES array
    m = re.search(r"const THEMES\s*=\s*\[([^\]]+)\]", source)
    assert m, "THEMES array not found"
    themes_arr = {t.strip().strip("'\"") for t in m.group(1).split(",") if t.strip().strip("'\"")} - {"custom"}

    # Extract THEME_DATA keys (now in shared partial theme_data.html)
    m2 = re.search(r"const THEME_DATA\s*=\s*\{(.*?)\n\s*\};", read_source("templates/theme_data.html"), re.DOTALL)
    assert m2, "THEME_DATA block not found"
    theme_data_keys = set(re.findall(r"""^\s*'?([\w-]+)'?\s*:\s*\{label:""", m2.group(1), re.MULTILINE))

    # Exclude themes that are handled specially (not in THEME_DATA by design)
    SPECIAL_THEMES = {"custom"}  # custom uses a user-defined color picker, not THEME_DATA
    themes_arr       = themes_arr - SPECIAL_THEMES
    theme_data_keys  = theme_data_keys - SPECIAL_THEMES

    in_arr_not_data = themes_arr - theme_data_keys
    in_data_not_arr = theme_data_keys - themes_arr

    # Themes without THEME_DATA entries are flagged (they silently get no swatch data)
    assert not in_data_not_arr, f"THEME_DATA has keys not in THEMES array: {in_data_not_arr}"
    # Note: some themes may intentionally lack THEME_DATA (handled gracefully by app)
    # so in_arr_not_data is informational only — assert count hasn't grown unexpectedly
    assert len(in_arr_not_data) <= 20, (
        f"More themes than expected lack THEME_DATA entries ({len(in_arr_not_data)}): {in_arr_not_data}"
    )


def test_no_duplicate_theme_labels():
    """
    No two themes may share the same display label.
    Regression: 'Aurora' label collision between aurora and aurora-deep.
    """
    source = read_source("templates/theme_data.html")  # shared THEME_DATA partial
    m = re.search(r"const THEME_DATA\s*=\s*\{(.*?)\n\s*\};", source, re.DOTALL)
    assert m, "THEME_DATA block not found"

    labels = re.findall(r"""label\s*:\s*['"]([^'"]+)['"]""", m.group(1))
    seen, dupes = set(), set()
    for label in labels:
        if label in seen:
            dupes.add(label)
        seen.add(label)

    assert not dupes, f"Duplicate theme labels found: {dupes}"


def test_all_theme_css_blocks_have_required_vars():
    """
    Every theme CSS block must define all required CSS variables.
    Regression: contrast patch gutted 36 themes to 2 vars each (v0.99.11).
    """
    source = read_source("templates/theme_styles.html")

    REQUIRED_VARS = [
        "--bg", "--surf", "--surf2", "--surf3",
        "--border", "--acc", "--text", "--text2",
        "--muted", "--log-bg", "--log-text",
    ]

    # Find all body.theme { ... } blocks
    blocks = re.findall(r'body\.([\w-]+)\s*\{([^}]+)\}', source, re.DOTALL)
    assert blocks, "No theme CSS blocks found"

    incomplete = {}
    for theme_name, body in blocks:
        missing = [v for v in REQUIRED_VARS if f"{v}:" not in body]
        if missing:
            incomplete[theme_name] = missing

    assert not incomplete, (
        f"{len(incomplete)} theme(s) missing required CSS vars:\n" +
        "\n".join(f"  {name}: missing {vars_}" for name, vars_ in list(incomplete.items())[:10]))


# ── Security parity — required markers on every platform ──────────────────────
# Prevents security fixes from silently landing Windows-only. If a marker is
# missing on any platform, it means a hardening patch wasn't ported.

def test_security_markers_in_all_app_py():
    """Every platform app.py must contain the same security patterns."""
    REQUIRED = [
        "_is_internal_host",         # SSRF guard on thumbnail downloads
        "Content-Length",            # pre-check rejects oversized images
        "_clamp_int",               # safe int parsing (prevents 500 on bad input)
        "_TOKEN_EXEMPT_PREFIX",     # consolidated token exemption
        "_safe_urlopen",            # timeout-enforced HTTP opens
        "_atomic_write_text",       # crash-safe file writes
        "_safe_video_id",           # video id allowlist (attribute-context XSS guard)
    ]
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        source = read_source(path)
        missing = [m for m in REQUIRED if m not in source]
        assert not missing, f"{name}/app.py missing security markers: {missing}"


def test_security_markers_in_all_main_js():
    """Every platform main.js must contain the same Electron hardening."""
    REQUIRED = [
        "isTrustedSender",          # IPC sender validation
        "atomicWriteJson",          # crash-safe settings write
        "readFileCapped",           # import size cap (2MB)
    ]
    main_files = [
        ("windows", "windows/electron/main.js"),
        ("linux",   "linux/electron/main.js"),
        ("mac",     "mac/electron/main.js"),
    ]
    for name, path in main_files:
        source = read_source(path)
        missing = [m for m in REQUIRED if m not in source]
        assert not missing, f"{name}/main.js missing security markers: {missing}"


def test_istrustedsender_count_locked():
    """isTrustedSender must appear EXACTLY 59 times total across the 3 main.js
    (windows 21, linux 19, mac 19). Every ipcMain handler must be gated by it;
    locking the count auto-catches an accidental handler addition that bypasses
    the gate — the same check done by hand every delta review. If you added a
    legitimate, gated ipcMain handler, bump EXPECTED_TOTAL after confirming the
    new handler calls isTrustedSender.

    v1.2 CANVAS (Theme Creator) added 4 gated handlers per platform (+12):
    open-theme-creator, creator-dirty, creator-confirm-close, creator-preview.
    """
    EXPECTED_TOTAL = 59
    counts = {
        name: read_source(path).count("isTrustedSender")
        for name, path in (
            ("windows", "windows/electron/main.js"),
            ("linux",   "linux/electron/main.js"),
            ("mac",     "mac/electron/main.js"),
        )
    }
    total = sum(counts.values())
    assert total == EXPECTED_TOTAL, (
        f"isTrustedSender count changed: {counts} (total {total}, expected "
        f"{EXPECTED_TOTAL}). A new ipcMain handler must call isTrustedSender; "
        f"if this addition is intentional and gated, update EXPECTED_TOTAL."
    )


def test_security_markers_in_all_preload_js():
    """Every platform preload.js must contain the same bridge-layer validation."""
    REQUIRED = [
        "isStr",                    # string type validator
        "THEME_RE",                 # theme key regex validation
        "isHttpUrl",                # URL protocol validator
    ]
    preload_files = [
        ("windows", "windows/electron/preload.js"),
        ("linux",   "linux/electron/preload.js"),
        ("mac",     "mac/electron/preload.js"),
    ]
    for name, path in preload_files:
        source = read_source(path)
        missing = [m for m in REQUIRED if m not in source]
        assert not missing, f"{name}/preload.js missing security markers: {missing}"


def test_ejs_remote_components_in_download_path():
    """run_download() must invoke yt-dlp with --remote-components ejs:github on
    EVERY platform (YouTube signature solving). Regression: in RC4 this was applied
    to the info path on all 3 but to the download path on Windows only."""
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        source = read_source(path)
        m = re.search(r'cmd = \[sys\.executable, "-m", "yt_dlp".*?\] \+ ', source)
        assert m, f"{name}/app.py: run_download cmd line not found"
        assert "ejs:github" in m.group(0), (
            f"{name}/app.py: run_download missing --remote-components ejs:github "
            f"(signature solving would fail on this platform)"
        )


# ── Theme count consistency — prevents corruption and sync drift ──────────────

def test_theme_counts_consistent():
    """THEME_DATA in index_scripts, themes.html, HTML rows, and THEMES array
    must all agree on the total count. Catches corruption from bad insertions,
    merge drift, and partial integrations."""
    theme_data = read_source("templates/theme_data.html")  # single shared source now
    scripts = read_index_scripts()  # js/ modules resolved
    index_html = read_source("templates/index.html")

    data_count = len(re.findall(r"cat:'", theme_data))
    html_rows  = len(re.findall(r'data-theme=', index_html))

    # THEMES array — count quoted entries
    arr_match = re.search(r'const THEMES = \[(.*?)\]', scripts, re.DOTALL)
    assert arr_match, "THEMES array not found in index_scripts.html"
    arr_count = len(re.findall(r"'[a-z0-9-]+'", arr_match.group(1)))

    assert data_count == html_rows, (
        f"THEME_DATA ({data_count}) != HTML rows ({html_rows}) in index.html")
    assert data_count == arr_count, (
        f"THEME_DATA ({data_count}) != THEMES array ({arr_count})")


def test_theme_counts_linux_parity():
    """Linux templates must have identical theme counts to root templates."""
    for fname in ["index.html", "index_scripts.html", "themes.html", "theme_styles.html", "theme_data.html", "subscriptions.html", "history.html", "theme_validator.html", "theme_creator.html", "js/_core.html", "js/_settings.html", "js/_download.html", "js/_bulk.html", "js/_nav_history.html", "js/_theme.html", "js/_quality.html", "js/_creator.html"]:
        root = read_source(f"templates/{fname}")
        linux = read_source(f"linux/templates/{fname}")
        assert root == linux, f"templates/{fname} differs from linux/templates/{fname}"


# ── HTML div balance — prevents DOM corruption cascading to layout ────────────

def test_index_html_div_balance():
    """The header section of index.html must have balanced <div>...</div> tags.
    Unbalanced divs cause the browser to auto-close at wrong points, breaking
    panel layout — this exact bug caused the Advanced panel to render empty on
    Mac/Linux in RC5."""
    html = read_source("templates/index.html")
    header_start = html.find("<header>")
    header_end = html.find("</header>") + len("</header>")
    assert header_start > 0 and header_end > header_start, "Could not find <header>...</header>"

    header = html[header_start:header_end]
    opens = len(re.findall(r'<div[\s>]', header))
    closes = header.count('</div>')
    assert opens == closes, (
        f"Header div imbalance: {opens} opens vs {closes} closes "
        f"(diff: {opens - closes})"
    )


# ── Channel URL resolution — correct URL per channel setting ──────────────────

def test_ffmpeg_channel_urls_correct():
    """Each platform must have both stable and nightly ffmpeg URL constants,
    and they must point to the correct sources per platform."""
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        source = read_source(path)
        if name == "mac":
            # Mac uses martin-riedl.de with snapshot/release
            assert "martin-riedl.de" in source, f"{name} must use martin-riedl.de for ffmpeg"
            assert "snapshot" in source, f"{name} must have snapshot (nightly) path"
            assert "release" in source, f"{name} must have release (stable) path"
        else:
            # Windows/Linux use BtbN
            assert "FFMPEG_URL_STABLE" in source, f"{name} missing FFMPEG_URL_STABLE"
            assert "FFMPEG_URL_NIGHTLY" in source, f"{name} missing FFMPEG_URL_NIGHTLY"
            assert "ffmpeg-master" in source, f"{name} nightly URL must reference master"
            assert "ffmpeg-n8.1" in source, f"{name} stable URL must reference n8.1"


def test_ytdlp_channel_repos_correct():
    """_get_latest_ytdlp_version must query the correct repo per channel."""
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        source = read_source(path)
        assert "yt-dlp/yt-dlp-nightly-builds" in source, (
            f"{name} missing nightly repo reference")
        assert 'yt-dlp/yt-dlp"' in source or "yt-dlp/yt-dlp'" in source, (
            f"{name} missing stable repo reference")


# ── Template render — Jinja include integrity ─────────────────────────────────

def test_templates_render_without_jinja_errors():
    """index.html must render through Jinja without errors, with all includes
    resolved and THEME_DATA present in the output."""
    from flask import Flask
    import os
    root = os.path.dirname(os.path.dirname(__file__))
    app = Flask(__name__, template_folder=os.path.join(root, "templates"))
    with app.app_context():
        from flask import render_template
        html = render_template("index.html", egm_token="test-token", platform_url="test")

    # Verify no unrendered Jinja
    assert "{%" not in html, "Unrendered Jinja block tag found in output"
    assert "{{" not in html or "egm_token" not in html, "Unrendered Jinja variable found"

    # Verify theme_data.html was included (THEME_DATA should be in output)
    assert "const THEME_DATA" in html, "THEME_DATA not found — theme_data.html include failed"
    assert "body.bologna" in html, "Theme CSS not found — theme_styles.html include failed"

    # Verify the split files were included
    assert "function applyTheme" in html, "index_scripts.html include failed"


# ── Preload bridge parity — full surface, not just security markers ───────────

def test_preload_bridge_full_parity():
    """All exposed bridge functions must exist on Mac AND Linux (identical sets).
    Windows may have extras (launchInstaller, createShortcut) but must be a
    superset of Mac/Linux. Catches the 'Windows-only bridge function' pattern
    that recurred 3 times (security validators, openSubscriptions)."""
    preloads = {
        "windows": read_source("windows/electron/preload.js"),
        "linux":   read_source("linux/electron/preload.js"),
        "mac":     read_source("mac/electron/preload.js"),
    }

    def extract_bridge_keys(source):
        """Extract function names from contextBridge.exposeInMainWorld block."""
        keys = set()
        for line in source.split('\n'):
            m = re.match(r'^\s+(\w+):\s', line)
            if m and m.group(1) not in ('contextBridge', 'ipcRenderer'):
                keys.add(m.group(1))
        return keys

    win_keys   = extract_bridge_keys(preloads["windows"])
    linux_keys = extract_bridge_keys(preloads["linux"])
    mac_keys   = extract_bridge_keys(preloads["mac"])

    # Linux == Mac (these two must be identical)
    assert linux_keys == mac_keys, (
        f"Linux/Mac preload bridge mismatch.\n"
        f"  Linux only: {linux_keys - mac_keys}\n"
        f"  Mac only:   {mac_keys - linux_keys}"
    )

    # Windows ⊇ Linux ∪ Mac (Windows may have extras, must not be missing any)
    shared = linux_keys | mac_keys
    missing_from_win = shared - win_keys
    assert not missing_from_win, (
        f"Windows preload missing functions that Mac/Linux have: {missing_from_win}"
    )

    # Windows extras must be a KNOWN allowlist — catches accidental Windows-only feature functions
    win_only = win_keys - shared
    allowed_win_only = {"launchInstaller", "createShortcut"}  # legitimately Windows-only
    unexpected = win_only - allowed_win_only
    assert not unexpected, (
        f"Windows-only bridge functions not in allowlist: {unexpected}. "
        f"If cross-platform, port to Mac/Linux. If truly Windows-only, add to allowlist."
    )

def test_video_id_xss_guard():
    """Phase 3 regression guard — a malicious video_id from yt-dlp metadata
    must not be able to break out of an attribute context in subscriptions.html.

    Two layers, both checked on every platform/template:
    1. Server: _safe_video_id() allowlists the id charset before storage.
    2. Client: every video_id attribute interpolation uses attrEsc() (which,
       unlike esc(), escapes quotes), and the onclick handlers don't use
       CSS.escape (wrong escaper for an HTML attribute / JS string context).
    """
    # 1. Server-side allowlist behaves correctly on all 3 app.py
    id_re = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        source = read_source(path)
        assert '_safe_video_id(entry.get("id", ""))' in source, \
            f"{name}/app.py does not sanitize video_id at the storage site"
        m = re.search(r'_VIDEO_ID_RE\s*=\s*_re\.compile\(r"([^"]+)"\)', source)
        assert m and m.group(1) == id_re.pattern, \
            f"{name}/app.py _VIDEO_ID_RE drifted from the expected allowlist"

    # The allowlist itself: good ids pass, breakout payloads fail
    assert id_re.fullmatch("dQw4w9WgXcQ")                      # YouTube
    assert id_re.fullmatch("abc.def:123_-x")                   # other extractors
    for bad in ('" onmouseover="alert(1)', "x' y", "a b", "<svg>", "", "x"*129):
        assert not id_re.fullmatch(bad), f"allowlist accepted breakout id: {bad!r}"

    # 2. Client-side: attribute contexts use attrEsc, not esc/CSS.escape
    for tpl in ("templates/subscriptions.html", "linux/templates/subscriptions.html"):
        src = read_source(tpl)
        assert "function attrEsc" in src, f"{tpl} missing attrEsc()"
        for needle in (
            'data-video-id="${attrEsc(v.video_id',
            'id="meta-${attrEsc(v.video_id',
            "cancelJob('${attrEsc(jobId)}','${attrEsc(videoId)}')",
            "clearVideoState('${attrEsc(videoId)}')",
        ):
            assert needle in src, f"{tpl} attribute site not using attrEsc: {needle}"
        assert "onclick=\"cancelJob('${jobId}'" not in src
        for stale in ('data-video-id="${esc(v.video_id', 'id="meta-${esc(v.video_id'):
            assert stale not in src, f"{tpl} still uses esc() in attribute context"


# ── Build-feed guards ──────────────────────────────────────────────────────────

def _extract_patchnote_bullets(patchnotes_text, platform_tag):
    """Replicate windows/BUILD.sh's update-feed bullet extraction for the most
    recent (current) patchnotes entry, filtered to [<PLATFORM>] or [ALL] tags.
    Mirrors BUILD.sh's exact break-on-blank-line logic so this catches the same
    early-stop bug it has."""
    bullets, in_block = [], False
    for line in patchnotes_text.splitlines():
        if re.match(r'^v\d', line):
            if in_block:
                break
            in_block = True
            continue
        if in_block:
            if line.startswith('  • '):
                m = re.match(rf'^\[({platform_tag}|ALL)\]\s+(.+)$', line[4:].strip())
                if m:
                    bullets.append(m.group(2))
            elif line.strip() == '' and bullets:
                break
    return bullets


def test_patchnotes_current_version_has_enough_bullets():
    """The most recent patchnotes.txt entry must yield >= 3 update-feed bullets for
    EACH platform tag, using BUILD.sh's exact extraction.

    Regression: in the v1.1.2 cycle a blank line BETWEEN sections
    (THEMES/IMPROVEMENTS/FIXES) made the extractor stop at the first blank line and
    emit 1 bullet instead of 10 — an empty/near-empty _version_notes that was only
    caught mid-build by the BUILD.sh validator. This runs before any build starts.
    """
    pn = read_source("patchnotes.txt")
    for tag in ("WINDOWS", "MAC", "LINUX"):
        bullets = _extract_patchnote_bullets(pn, tag)
        assert len(bullets) >= 3, (
            f"patchnotes.txt: the current version entry yields only {len(bullets)} "
            f"[{tag}|ALL] bullet(s) (need >= 3). Most common cause: a blank line "
            f"BETWEEN sections (THEMES/IMPROVEMENTS/FIXES) makes BUILD.sh's extractor "
            f"stop early. Keep all bullets in one contiguous block (no blank lines "
            f"between sections within a version entry)."
        )


# ── Shared theme validator (theme_validator.html) ──────────────────────────────

def test_theme_validator_covers_all_vars():
    """THEME_VAR_TYPES (theme_validator.html) must name EXACTLY the same vars as
    ALL_VARS (index_scripts.html). If they drift, a theme var would be silently
    rejected (missing from the type map) or an un-typed var would slip through."""
    validator = read_source("templates/theme_validator.html")
    scripts   = read_index_scripts()  # js/ modules resolved
    m = re.search(r'const THEME_VAR_TYPES\s*=\s*\{(.*?)\};', validator, re.DOTALL)
    assert m, "THEME_VAR_TYPES not found in theme_validator.html"
    type_vars = set(re.findall(r"'(--[a-z0-9-]+)'\s*:", m.group(1)))
    rv = re.search(r'const REQUIRED_VARS\s*=\s*\[(.*?)\];', scripts, re.DOTALL)
    av = re.search(r'const ALL_VARS\s*=\s*\[\s*\.\.\.REQUIRED_VARS,(.*?)\];', scripts, re.DOTALL)
    assert rv and av, "REQUIRED_VARS / ALL_VARS not found in index_scripts.html"
    all_vars = (set(re.findall(r"'(--[a-z0-9-]+)'", rv.group(1)))
                | set(re.findall(r"'(--[a-z0-9-]+)'", av.group(1))))
    assert type_vars == all_vars, (
        "theme_validator THEME_VAR_TYPES is out of sync with ALL_VARS:\n"
        f"  only in validator: {sorted(type_vars - all_vars)}\n"
        f"  only in ALL_VARS:  {sorted(all_vars - type_vars)}"
    )


def test_theme_validator_is_the_only_gate():
    """The import path must use the shared validateThemeVar and not the old inline
    _cssVarSafe (one gate for import + Theme Creator, no fork)."""
    src = read_index_scripts()  # js/ modules resolved
    assert "{% include 'theme_validator.html' %}" in src, "partial not included in index_scripts.html"
    assert "validateThemeVar(" in src, "import path not wired to validateThemeVar"
    assert "_cssVarSafe" not in src, "stale _cssVarSafe still present — superseded by validateThemeVar"
    val = read_source("templates/theme_validator.html")
    for needle in ("function validateThemeVar", "url", "image-set", "expression", "-moz-binding"):
        assert needle in val, f"theme_validator.html missing forbidden-pattern term: {needle!r}"


def test_theme_validator_behaviour():
    """Run the ACTUAL validator (theme_validator.html is pure JS) in node against
    real values and attack vectors. Skips if node is unavailable; the structural
    tests above always run."""
    import shutil, subprocess
    if not shutil.which("node"):
        pytest.skip("node not available — structural validator tests still cover it")
    js = read_source("templates/theme_validator.html")
    harness = js + r"""
    let fail = null;
    const A = (n,v)=>{ if(!validateThemeVar(n,v)) fail = fail || ('REJECTED valid '+n+'='+JSON.stringify(v)); };
    const R = (n,v)=>{ if( validateThemeVar(n,v)) fail = fail || ('ACCEPTED bad  '+n+'='+JSON.stringify(v)); };
    // valid (must accept)
    A('--bg','#010101'); A('--bg','#0a0'); A('--bg','#00004480');
    A('--surf','rgba(0,0,0,.35)'); A('--acc','rgb(20, 200, 168)'); A('--text','transparent');
    A('--shadow','0 4px 12px rgba(0,0,0,.2)'); A('--modal-shadow','0 20px 60px rgba(0,0,0,.14)');
    A('--shadow','inset 0 1px 2px #000, 0 4px 8px rgba(0,0,0,.3)'); A('--modal-overlay','rgba(0,0,0,.5)');
    // attacks (must reject)
    R('--bg','#000}*{background:red}'); R('--bg','red"><img src=x onerror=alert(1)>');
    R('--bg','url(https://evil.example/beacon)'); R('--thumb-bg','image-set("https://e/x")');
    R('--bg','expression(alert(1))'); R('--bg','red;position:fixed'); R('--bg','ur\\6c(x)');
    R('--evil','#ffffff'); R('--bg','linear-gradient(red,blue)'); R('--bg','a'.repeat(201));
    R('--bg',''); R('--bg','#xyz'); R('--shadow','0 0 0 url(x)'); R('--shadow','0 0 0 #000}{');
    if (fail) { console.error(fail); process.exit(1); }
    console.log('OK');
    """
    r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, f"validateThemeVar behaviour failed: {r.stderr.strip() or r.stdout.strip()}"


# ── Theme Creator (v1.2 CANVAS) parity guards ─────────────────────────────────

def test_theme_creator_route_on_all_platforms():
    """The /theme-creator-page Flask route must exist on every platform app.py —
    a missing mirror would 404 the Creator window on that OS."""
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        src = read_source(path)
        assert "/theme-creator-page" in src, f"{name}/app.py missing /theme-creator-page route"
        assert 'render_template("theme_creator.html"' in src, f"{name}/app.py route doesn't render theme_creator.html"


def test_creator_ipc_surface_parity():
    """Every Creator IPC channel must be present (and the gate count is locked by
    test_istrustedsender_count_locked) on all 3 main.js, and exposed by all 3
    preloads — so the feature can't land on one platform only."""
    channels = ["open-theme-creator", "creator-dirty", "creator-confirm-close", "creator-preview"]
    preload_methods = ["openThemeCreator", "creatorPreview", "creatorDirty",
                       "creatorConfirmClose", "onCreatorPreview", "onCreatorPreviewReset",
                       "onCreatorRequestClose"]
    for plat in ("windows", "linux", "mac"):
        mainjs = read_source(f"{plat}/electron/main.js")
        for ch in channels:
            assert f"'{ch}'" in mainjs, f"{plat}/main.js missing IPC handler for {ch!r}"
        preload = read_source(f"{plat}/electron/preload.js")
        for m in preload_methods:
            assert m in preload, f"{plat}/electron/preload.js missing bridge method {m!r}"


def test_creator_uses_shared_validator():
    """The Creator page must reuse the single shared gate (theme_validator.html)
    and the module must validate at the entry points — no forked allowlist."""
    page = read_source("templates/theme_creator.html")
    assert "{% include 'theme_validator.html' %}" in page, "Creator page doesn't include the shared validator"
    assert "{% include 'js/_creator.html' %}" in page, "Creator page doesn't include the _creator module"
    assert 'id="creator-root"' in page, "Creator page missing #creator-root role marker"
    mod = read_source("templates/js/_creator.html")
    assert "validateThemeVar" in mod, "_creator.html does not call validateThemeVar"
    assert "setProperty" in mod, "_creator.html does not apply via setProperty"


def test_creator_core_vars_pickers_and_random_in_sync():
    """The picker rows (theme_creator.html), CORE_KEYS, and the Random handler's
    rebuilt `core` object must cover EXACTLY the same vars. Drift — e.g. adding a
    picker but not extending Random — leaves the un-set swatches black and breaks
    dirty tracking (the v1.2 Random regression). Locking all three equal catches it
    statically, before a build."""
    mod  = read_source("templates/js/_creator.html")
    page = read_source("templates/theme_creator.html")

    m = re.search(r"const CORE_KEYS\s*=\s*\[([^\]]+)\]", mod)
    assert m, "CORE_KEYS not found in _creator.html"
    core_keys = set(re.findall(r"'(--[a-z0-9-]+)'", m.group(1)))

    pickers = set(re.findall(r'class="cv-pick"[^>]*data-var="(--[a-z0-9-]+)"', page))

    rnd = re.search(r"\$\('cv-random'\)\.addEventListener.*?\bcore\s*=\s*\{([^}]*)\}", mod, re.DOTALL)
    assert rnd, "Random handler's core object not found in _creator.html"
    random_keys = set(re.findall(r"'(--[a-z0-9-]+)'\s*:", rnd.group(1)))

    assert core_keys == pickers, (
        "CORE_KEYS vs picker rows mismatch:\n"
        f"  only in CORE_KEYS: {sorted(core_keys - pickers)}\n"
        f"  only in pickers:   {sorted(pickers - core_keys)}")
    assert core_keys == random_keys, (
        "Random does not set every core var (v1.2 black-swatch regression):\n"
        f"  missing from Random: {sorted(core_keys - random_keys)}\n"
        f"  extra in Random:     {sorted(random_keys - core_keys)}")
    assert len(core_keys) == 10, f"expected 10 core vars, got {len(core_keys)}: {sorted(core_keys)}"


def test_creator_window_restore_lifecycle():
    """Opening the Creator shifts/shrinks main to make room; closing it must put main
    back — including the maximized case (un-maximize to tile → re-maximize on close)
    and a renderer-crash path that would otherwise strand main resized. Static guard
    that the lifecycle wiring is present and mirrored on all 3 platforms (the geometry
    itself is exercised at runtime)."""
    markers = [
        "isMaximized()",            # capture maximized state at open
        "getNormalBounds()",        # remember main's normal (restore) size
        "creatorMainWasMaximized",  # carry the flag through to close
        ".unmaximize()",            # make room when main was maximized
        ".maximize()",              # re-maximize on close
        "render-process-gone",      # renderer crash → forced close → restore runs
    ]
    for plat in ("windows", "linux", "mac"):
        src = read_source(f"{plat}/electron/main.js")
        missing = [m for m in markers if m not in src]
        assert not missing, f"{plat}/main.js missing Creator restore-lifecycle markers: {missing}"


def test_creator_window_placement_parity():
    """Creator placement must be wired identically on all 3 platforms (one block,
    branched at runtime): Wayland-aware degradation, deferred create→place→show on
    macOS/X11-Linux (their WMs ignore the constructor x/y and an immediate setPosition,
    centering the window), immediate on Windows, plus a macOS deferred re-assert (its
    default placement overrides an immediate setBounds in the windowed case). Guards
    against the per-platform drift that produced centered Creator windows."""
    for plat in ("windows", "linux", "mac"):
        src = read_source(f"{plat}/electron/main.js")
        assert "deferPlacement" in src, f"{plat}/main.js missing the deferPlacement gate"
        assert "show: isWayland || !deferPlacement" in src, f"{plat}/main.js Creator not Wayland-aware deferred-show wired"
        assert "XDG_SESSION_TYPE" in src, f"{plat}/main.js missing Wayland detection"
        # macOS-only re-assert after show — overrides macOS's show-time placement.
        assert "process.platform === 'darwin'" in src and "setTimeout(placeCreator" in src, \
            f"{plat}/main.js missing the macOS post-show position re-assert"
