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
    # Non-empty guard: if the @app.route regex ever breaks, every set is empty
    # and the equality assertions below pass vacuously. Fail loudly instead.
    for _name, _r in routes.items():
        assert _r, f"{_name}: extract_routes returned no routes — the @app.route regex likely broke"

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

    # Non-empty guard: if either regex breaks, `unhandled` is empty and this
    # passes vacuously. Confirm we actually parsed keys from both sides first.
    assert allowed_keys, "extract_allowed_keys parsed no keys — regex likely broke"
    assert saved_keys, "no settings/save keys parsed from the frontend — regex likely broke"
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
    """isTrustedSender must appear EXACTLY 53 times total across the 3 main.js
    (windows 19, linux 17, mac 17). Every ipcMain handler must be gated by it;
    locking the count auto-catches an accidental handler addition that bypasses
    the gate — the same check done by hand every delta review. If you added a
    legitimate, gated ipcMain handler, bump EXPECTED_TOTAL after confirming the
    new handler calls isTrustedSender.
    (50 → 53 in v1.3.2: the gated open-console-window handler, one per platform.)
    """
    EXPECTED_TOTAL = 59   # +3 set-activity (taskbar/badge/sleep-blocker) +3 set-language (shell i18n), one per platform each
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


def test_every_ipc_handler_is_gated():
    """Structural gate — the one a magic total can't enforce.

    A magic total (test above) does NOT catch adding an *ungated* ipcMain
    handler: an ungated handler adds zero `isTrustedSender` occurrences, so the
    total is unchanged and the total-lock passes. This asserts the invariant the
    total only stands in for: in every main.js the number of `isTrustedSender`
    occurrences equals the number of ipcMain handler registrations PLUS ONE (the
    single `function isTrustedSender` definition) — i.e. every handler calls the
    gate exactly once. Adding a handler without the check breaks the equality.
    """
    handler_re = re.compile(r'ipcMain\.(?:handle|on)\b')
    defn_re    = re.compile(r'function\s+isTrustedSender\b')
    for name, path in (
        ("windows", "windows/electron/main.js"),
        ("linux",   "linux/electron/main.js"),
        ("mac",     "mac/electron/main.js"),
    ):
        src = read_source(path)
        handlers = len(handler_re.findall(src))
        checks   = src.count("isTrustedSender")
        defs     = len(defn_re.findall(src))
        assert defs == 1, f"{name}/main.js: expected exactly one isTrustedSender definition, found {defs}"
        assert checks == handlers + defs, (
            f"{name}/main.js: {handlers} ipcMain handlers but {checks - defs} "
            f"isTrustedSender call sites — every handler must call the gate "
            f"exactly once. An ungated handler is a security bypass."
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
    for fname in ["index.html", "index_styles.html", "index_scripts.html", "themes.html", "theme_styles.html", "theme_data.html", "subscriptions.html", "history.html", "theme_validator.html", "js/_core.html", "js/_settings.html", "js/_download.html", "js/_bulk.html", "js/_nav_history.html", "js/_theme.html", "js/_quality.html", "js/_creator.html"]:
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
                m = _BULLET_TAGS_RE.match(line[4:].strip())
                if m and ({'ALL', platform_tag} & set(_TAG_RE.findall(m.group(1)))):
                    bullets.append(m.group(2).strip())
            elif line.strip() == '' and bullets:
                break
    return bullets


def _extract_patchnote_bullets_naive(patchnotes_text, platform_tag):
    """Same filter as _extract_patchnote_bullets, but scans the WHOLE current
    version entry (bounded only by the next 'v\\d' header) instead of stopping
    at the first blank line. This is the "true" bullet count regardless of
    section spacing -- used as a reference to detect early-stop truncation,
    rather than a fixed minimum count (see test_patchnotes_current_version_
    is_not_truncated for why a fixed minimum stopped being a reliable proxy
    for that once small maintenance releases became a normal, valid shape)."""
    bullets, in_block = [], False
    for line in patchnotes_text.splitlines():
        if re.match(r'^v\d', line):
            if in_block:
                break
            in_block = True
            continue
        if in_block and line.startswith('  • '):
            m = _BULLET_TAGS_RE.match(line[4:].strip())
            if m and ({'ALL', platform_tag} & set(_TAG_RE.findall(m.group(1)))):
                bullets.append(m.group(2).strip())
    return bullets


def test_patchnotes_current_version_is_not_truncated():
    """The most recent patchnotes.txt entry's BUILD.sh-style per-platform
    extraction (which stops at the first blank line, same as BUILD.sh itself)
    must match the naive full-block extraction (which doesn't). A mismatch
    means the blank-line early-stop is actually firing and silently dropping
    real bullets -- BUILD.sh's own bullet count would then be wrong at
    release time.

    Previously this asserted a fixed >= 3 minimum. That was really a proxy
    for "didn't truncate", which worked while every release had far more
    than 3 real bullets -- a truncation from 15 down to 1 was obviously
    wrong under that floor. It stopped being a reliable proxy once
    genuinely small maintenance-only releases (a single dependency bump,
    no user-facing changes) became a normal, valid shape: a real 2-bullet
    release and a truncated 15-into-2 release look identical under any
    fixed minimum. Comparing against the naive count catches truncation
    regardless of how many real bullets there are -- including exactly 1.

    Regression: in the v1.1.2 cycle a blank line BETWEEN sections
    (THEMES/IMPROVEMENTS/FIXES) made the extractor stop at the first blank
    line and emit 1 bullet instead of 10 — an empty/near-empty
    _version_notes that was only caught mid-build by the BUILD.sh
    validator. This runs before any build starts.
    """
    pn = read_source("patchnotes.txt")
    for tag in ("WINDOWS", "MAC", "LINUX"):
        bullets = _extract_patchnote_bullets(pn, tag)
        naive = _extract_patchnote_bullets_naive(pn, tag)
        assert bullets == naive, (
            f"patchnotes.txt: BUILD.sh-style extraction found {len(bullets)} "
            f"[{tag}|ALL] bullet(s) but the full version entry actually has "
            f"{len(naive)} -- a blank line BETWEEN sections (THEMES/"
            f"IMPROVEMENTS/FIXES) is making BUILD.sh's extractor stop early. "
            f"Keep all bullets in one contiguous block (no blank lines "
            f"between sections within a version entry)."
        )
        assert len(bullets) >= 1, (
            f"patchnotes.txt: the current version entry has zero [{tag}|ALL] "
            f"bullets -- every release needs at least one line describing "
            f"what changed, even a small maintenance-only one."
        )


# ── Shared theme validator (theme_validator.html) ──────────────────────────────

def test_all_patchnote_bullet_extractions_agree_with_the_generator():
    """scripts/gen-update-json.py::gen_notes is what actually BUILDS each
    feed's _version_notes, so it is the source of truth for "which bullets
    belong to platform X". Three replicas of that extraction exist -- this
    file's two (_extract_patchnote_bullets and its _naive twin),
    scripts/validate-version-sync.py's, and windows/BUILD.sh's inline copy --
    and validate-version-sync.py now compares the SHIPPED feed's bullet count
    against its replica. If a replica disagrees with the generator, the
    validator rejects a correctly-generated feed and blocks the release cut.

    That is not hypothetical. A bullet may carry more than one leading tag,
    e.g. "• [MAC] [LINUX] Foo" -- a form patchnotes.txt already uses. The
    generator matches the whole run of leading tags and tests set membership;
    the replicas originally matched only a tag in FIRST position, so they
    counted that bullet for MAC and dropped it for LINUX (and left "[LINUX] "
    embedded in MAC's note text). gen-update-json.py's own comment records
    fixing exactly this bug once already.

    The replicas are kept in sync by hand -- the docstrings say "if you
    change one, change all three". This test is what makes that mechanical.
    """
    import importlib.util
    import os
    import pathlib
    import subprocess
    import sys
    import tempfile

    fixture = (
        "v9.9.9 - FIXTURE (Build 999) (1/1/2026)\n"
        "-----------------------------------------\n"
        "\n"
        "  \u2022 [ALL] Shared change\n"
        "  \u2022 [MAC] [LINUX] Multi-tag, second position matters\n"
        "  \u2022 [WINDOWS] [MAC] Another multi-tag\n"
        "  \u2022 [WINDOWS] Windows only\n"
        "\n"
        "v1.0.0 - OLDER (Build 1) (1/1/2025)\n"
        "-----------------------------------------\n"
        "\n"
        "  \u2022 [ALL] Previous release, must not leak into the current one\n"
    )

    root = os.path.dirname(os.path.dirname(__file__))

    spec = importlib.util.spec_from_file_location(
        "egm_gen", os.path.join(root, "scripts", "gen-update-json.py"))
    gen = importlib.util.module_from_spec(spec)
    _argv, sys.argv = sys.argv, ["gen-update-json.py"]
    try:
        spec.loader.exec_module(gen)
    finally:
        sys.argv = _argv

    vspec = importlib.util.spec_from_file_location(
        "egm_validate", os.path.join(root, "scripts", "validate-version-sync.py"))
    val = importlib.util.module_from_spec(vspec)
    _argv, sys.argv = sys.argv, ["validate-version-sync.py"]
    try:
        vspec.loader.exec_module(val)
    finally:
        sys.argv = _argv

    with tempfile.TemporaryDirectory() as td:
        fpath = pathlib.Path(td) / "patchnotes.txt"
        fpath.write_text(fixture, encoding="utf-8")
        gen.PATCHNOTES = fpath

        for plat, tag in (("win", "WINDOWS"), ("mac", "MAC"), ("linux", "LINUX")):
            reference = gen.gen_notes(plat)
            assert reference, f"fixture produced no {tag} bullets -- fixture is broken"

            for name, fn in (
                ("tests/_extract_patchnote_bullets", _extract_patchnote_bullets),
                ("tests/_extract_patchnote_bullets_naive", _extract_patchnote_bullets_naive),
                ("validate-version-sync.py", val._extract_patchnote_bullets),
            ):
                got = fn(fixture, tag)
                assert got == reference, (
                    f"{name} disagrees with gen-update-json.py's gen_notes() "
                    f"for [{tag}]: {got!r} vs {reference!r}. The generator "
                    f"builds the real feed, so a replica that disagrees makes "
                    f"validate-version-sync.py reject a valid feed."
                )

        # windows/BUILD.sh's inline copy (Windows feed only) -- run the real
        # snippet, not a paraphrase of it.
        sh = read_source("windows/BUILD.sh")
        i = sh.index("bullets = []")
        j = sh.index("print('|||'.join(bullets))") + len("print('|||'.join(bullets))")
        snippet = sh[i:j].replace("\\$", "$")
        code = "import re\npn = open(PN, encoding='utf-8').read()\n" + snippet
        with tempfile.TemporaryDirectory() as td2:
            fp2 = pathlib.Path(td2) / "pn.txt"
            fp2.write_text(fixture, encoding="utf-8")
            r = subprocess.run(
                [sys.executable, "-c", f"PN = {str(fp2)!r}\n" + code],
                capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, f"BUILD.sh snippet failed: {r.stderr}"
        build_bullets = [b for b in r.stdout.strip().split("|||") if b]
        assert build_bullets == gen.gen_notes("win"), (
            f"windows/BUILD.sh's inline extraction disagrees with "
            f"gen_notes('win'): {build_bullets!r} vs {gen.gen_notes('win')!r}"
        )


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


# ── Theme Creator — in-page docked panel guards ───────────────────────────────

def test_creator_panel_present_and_uses_shared_validator():
    """The Creator is an in-page docked panel in the main window (no separate window,
    route, or IPC). Its markup must live in index.html; the module must validate every
    value through the shared gate and apply via the CSSOM (setProperty); and the theme
    apply hooks it needs must be exposed by _theme.html."""
    idx = read_source("templates/index.html")
    assert 'id="creator-panel"' in idx, "index.html missing the Creator docked panel"
    assert 'id="theme-create-btn"' in idx, "index.html missing the '+ Create theme' entry button"
    mod = read_source("templates/js/_creator.html")
    assert "validateThemeVar" in mod, "_creator.html does not call validateThemeVar"
    assert "setProperty" in mod, "_creator.html does not apply via setProperty (CSSOM)"
    assert "window.openThemeCreator" in mod, "_creator.html does not define openThemeCreator"
    theme = read_source("templates/js/_theme.html")
    assert "window.applyTheme" in theme and "window._egmApplyCustomTheme" in theme, \
        "_theme.html must expose applyTheme + _egmApplyCustomTheme for the panel's Save"


def test_creator_core_vars_pickers_and_random_in_sync():
    """The picker rows (index.html .cvp-pick), CORE_KEYS, and the Random handler's
    rebuilt `core` object must cover EXACTLY the same 10 vars. Drift — e.g. adding a
    picker but not extending Random — leaves the un-set swatches black and breaks dirty
    tracking (the Random regression). Locking all three equal catches it statically."""
    mod = read_source("templates/js/_creator.html")
    idx = read_source("templates/index.html")

    m = re.search(r"const CORE_KEYS\s*=\s*\[([^\]]+)\]", mod)
    assert m, "CORE_KEYS not found in _creator.html"
    core_keys = set(re.findall(r"'(--[a-z0-9-]+)'", m.group(1)))

    pickers = set(re.findall(r'class="cvp-pick"[^>]*data-var="(--[a-z0-9-]+)"', idx))

    rnd = re.search(r"function randomize\(\).*?\bcore\s*=\s*\{([^}]*)\}", mod, re.DOTALL)
    assert rnd, "Random handler's core object not found in _creator.html"
    random_keys = set(re.findall(r"'(--[a-z0-9-]+)'\s*:", rnd.group(1)))

    assert core_keys == pickers, (
        "CORE_KEYS vs picker rows mismatch:\n"
        f"  only in CORE_KEYS: {sorted(core_keys - pickers)}\n"
        f"  only in pickers:   {sorted(pickers - core_keys)}")
    assert core_keys == random_keys, (
        "Random does not set every core var (black-swatch regression):\n"
        f"  missing from Random: {sorted(core_keys - random_keys)}\n"
        f"  extra in Random:     {sorted(random_keys - core_keys)}")
    assert len(core_keys) == 10, f"expected 10 core vars, got {len(core_keys)}: {sorted(core_keys)}"


def test_creator_panel_resize_wired_on_all_platforms():
    """Opening the panel widens the main window (so it never compresses the main UI) via
    the single gated 'creator-panel' handler — present on all 3 main.js, exposed by all 3
    preloads, and called from the module on open/close. (Gating is locked by the
    isTrustedSender count test.)"""
    for plat in ("windows", "linux", "mac"):
        assert "'creator-panel'" in read_source(f"{plat}/electron/main.js"), \
            f"{plat}/main.js missing the creator-panel resize handler"
        assert "notifyCreatorPanel" in read_source(f"{plat}/electron/preload.js"), \
            f"{plat}/electron/preload.js missing notifyCreatorPanel"
    mod = read_source("templates/js/_creator.html")
    assert "notifyCreatorPanel(true)" in mod and "notifyCreatorPanel(false)" in mod, \
        "_creator.html must notify main on panel open and close"


# ── Universal MP4 (H.264 Max compatibility) parity guard ──────────────────────

def test_universal_mp4_h264_wired():
    """The 'Universal MP4' (Max compatibility) option must be wired identically on all
    3 platforms: the UI offers it, and each app.py prefers an H.264/avc1 stream at
    selection (lossless common case) and carries the conditional transcode fallback that
    guarantees H.264 only when the source isn't already H.264."""
    assert 'value="mp4_h264"' in read_source("templates/index.html"), \
        "UI is missing the 'MP4 · H.264 (Max compatibility)' option"
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        src = read_source(path)
        assert "mp4_h264" in src, f"{name}/app.py does not handle the mp4_h264 output format"
        assert "vcodec^=avc1" in src, f"{name}/app.py does not prefer H.264 (avc1) at selection"
        assert "def _ensure_h264" in src, f"{name}/app.py missing the conditional H.264 transcode"
        assert "libx264" in src, f"{name}/app.py transcode does not target libx264"


def test_saved_themes_multi_storage_wired():
    """Multi-theme 'Save to app' (Imported library): the shared validator partial
    provides the gated storage helpers, the Creator saves into the library, and the
    Themes window includes the validator and renders/applies/deletes Imported themes.
    Every read is re-gated by validateThemeVar (no un-vetted vars reach CSS)."""
    val = read_source("templates/theme_validator.html")
    for fn in ("loadSavedThemes", "saveSavedTheme", "deleteSavedTheme", "migrateLegacyCustom"):
        assert fn in val, f"theme_validator.html missing {fn}"
    assert "egm-saved-themes" in val, "theme_validator.html missing the egm-saved-themes store"
    assert "validateThemeVar" in val, "saved-theme load is not gated by validateThemeVar"

    cre = read_source("templates/js/_creator.html")
    assert "saveSavedTheme(" in cre, "_creator.html Save does not write to the saved-themes library"

    th = read_source("templates/themes.html")
    assert "{% include 'theme_validator.html' %}" in th, "themes.html doesn't include the shared validator"
    for needle in ("loadSavedThemes(", "applySavedTheme(", "deleteSavedTheme(", "data-saved=", "injectCustomCss"):
        assert needle in th, f"themes.html missing saved-theme wiring: {needle!r}"


def test_creator_storage_bridge_defers_until_focused():
    """Linux fix: opening the Creator from the separate Themes window must NOT widen the
    main window while it's still unfocused (the widen setBounds gets dropped on Linux,
    compressing the main UI). The storage-event bridge therefore defers openThemeCreator
    until main has focus — document.hasFocus() fast-path, else a one-shot 'focus' listener
    with a setTimeout fallback. Root and linux must carry this byte-identically."""
    root = read_source("templates/js/_creator.html")
    linux = read_source("linux/templates/js/_creator.html")
    assert root == linux, "templates/js/_creator.html differs from linux/templates/js/_creator.html"

    m = re.search(r"addEventListener\('storage',(.*?)\}\);\s*\}\)\(\);", root, re.DOTALL)
    assert m, "storage-event bridge not found in _creator.html"
    bridge = m.group(1)
    assert "document.hasFocus()" in bridge, "bridge does not fast-path on document.hasFocus()"
    assert "addEventListener('focus'" in bridge, "bridge does not defer the open to a focus event"
    assert "setTimeout(" in bridge, "bridge has no timer fallback if focus never arrives"


def test_creator_save_guards_duplicate_names():
    """Issue 2: saving a theme whose name already exists in the Imported library must
    prompt (Overwrite / Cancel) instead of silently adding a duplicate; Overwrite removes
    the same-name entries first. Locks the dup-name guard + overwrite path in saveTheme."""
    cre = read_source("templates/js/_creator.html")
    m = re.search(r"function saveTheme\(\)\s*\{(.*?)\n  \}", cre, re.DOTALL)
    assert m, "saveTheme() not found in _creator.html"
    body = m.group(1)
    assert "loadSavedThemes(" in body, "saveTheme does not look up existing saved themes"
    assert ".name === theme.name" in body, "saveTheme does not match on the theme name"
    assert "showModal(" in body, "saveTheme does not prompt before overwriting a duplicate"
    assert "Overwrite" in body, "saveTheme overwrite prompt missing"
    assert "deleteSavedTheme(" in body, "saveTheme overwrite path does not remove the old entry"


def test_saved_themes_favoritable():
    """Saved (Imported) themes are favoritable with the SAME mechanism as built-in
    themes: a .fav-heart on each saved card keyed by the theme's id, toggled through the
    shared favoriteThemes set / favorite_themes setting, and surfaced in the Favorites
    section. Saved-theme ids are 'st-...' which match the backend favorite-key regex, so
    no backend change is needed. Root and linux carry it byte-identically."""
    root = read_source("templates/themes.html")
    linux = read_source("linux/templates/themes.html")
    assert root == linux, "templates/themes.html differs from linux/templates/themes.html"

    # The saved-card markup carries a heart bound to the saved theme's id (same class /
    # icon the built-in cards use).
    saved_block = re.search(r"const savedHtml = saved\.map\(t => `(.*?)`\)\.join", root, re.DOTALL)
    assert saved_block, "savedHtml block not found in themes.html"
    sb = saved_block.group(1)
    assert 'class="fav-heart"' in sb, "saved cards have no favorite heart"
    assert 'data-fav="${esc(t.id)}"' in sb, "saved-card heart is not keyed by the theme id"
    assert "favoriteThemes.has(t.id)" in sb, "saved-card heart does not reflect favorite state"

    # Favorites view includes favorited saved themes alongside built-in favorites.
    assert "activeCat === 'favorites'" in root and "favoriteThemes.has(t.id)" in root, \
        "Favorites view does not include favorited saved themes"
    # Deleting a saved theme cleans up a stale favorite (no orphan in the Favorites count).
    assert "favoriteThemes.delete(id)" in root, \
        "deleting a saved theme does not drop its favorite entry"

    # Backend favorite-key sanitizer accepts the 'st-...' id grammar (lowercase/digits/-).
    for app_file in PLATFORM_APP_FILES:
        src = read_source(app_file)
        assert r'fullmatch(r"[a-z0-9-]+"' in src, \
            f"{app_file} favorite_themes sanitizer would reject saved-theme ids"


def test_optlibs_update_panel_cross_platform():
    """The 'Optional libraries' update-panel feature must be coherent on every platform.

    Windows (root app.py) can upgrade them in-app, so it reports full
    current/latest/updates_available. Linux + Mac bundle them with no in-app pip
    upgrade (same model as mutagen), so their check_updates returns optlibs as
    informational-only (current versions, no latest/up_to_date) — the UI then renders
    a neutral badge instead of a dead/actionable toggle. The template that hosts the
    optlibs card must also stay root<->linux byte-identical (Mac serves root templates).
    """
    # All three backends expose the optlibs list + version helper and an optlibs key.
    for app_file in PLATFORM_APP_FILES:
        src = read_source(app_file)
        assert "OPTLIBS" in src and "_get_optlibs_versions" in src, \
            f"{app_file} missing the optlibs helper"
        assert '"optlibs"' in src, f"{app_file} check_updates does not return an optlibs key"

    # Linux/Mac are informational-only: optlibs key carries current but no latest.
    for app_file in ("linux/app.py", "mac/app.py"):
        src = read_source(app_file)
        assert '"optlibs": {"current": _get_optlibs_versions()}' in src, \
            f"{app_file} optlibs is not the informational-only shape (current-only)"

    # Root keeps the actionable shape (updates_available drives the toggle/badge).
    root = read_source("app.py")
    assert "updates_available" in root and "do_optlibs" in root, \
        "root app.py lost the actionable optlibs upgrade path"

    # The optlibs card lives in _settings.html, which must be mirrored to linux byte-identically.
    assert read_source("templates/js/_settings.html") == read_source("linux/templates/js/_settings.html"), \
        "templates/js/_settings.html differs from linux/templates/js/_settings.html"


def test_portable_sentinel_tolerates_module_packages():
    """The Windows portable embedded-Python sentinel checks site-packages on disk. Some
    deps ship as a single top-level MODULE file (e.g. brotli -> brotli.py), not a
    package directory, so a dir-only check would never pass and pip would re-run on
    every launch (and fail an offline warm start). The check must also accept a
    top-level .py / compiled-extension module."""
    src = read_source("windows/launch.py")
    assert "def _present(" in src, "embedded sentinel no longer has a module-tolerant _present() check"
    assert '{pkg}.py' in src, "sentinel does not accept single-file .py modules (brotli regression)"
    assert "all(_present(pkg) for pkg in required)" in src, \
        "embedded sentinel is not using the module-tolerant _present() check"


# Map from an OPTLIBS distribution name to the IMPORT name pip drops in site-packages
# (and that the Windows sentinel imports). Most match after hyphen->underscore; the
# pycryptodomex distribution is the known exception — it installs the `Cryptodome`
# package. Extend this only when a new optional lib's import name differs from its
# normalized dist name.
_OPTLIB_IMPORT_NAME = {"pycryptodomex": "cryptodome"}


def _norm_lib(name):
    return name.strip().strip("\"'").replace("-", "_").lower()


def _optlibs_list(src):
    m = re.search(r"OPTLIBS\s*=\s*\[([^\]]*)\]", src)
    assert m, "OPTLIBS list not found"
    return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]


def test_optional_libs_consistent_across_all_sites():
    """The optional yt-dlp libraries are declared in SIX places that must agree:
    OPTLIBS in each of the 3 app.py, both requirements.txt, and the Windows launch.py
    bootstrap (sentinel imports + both pip-install lists, installer & portable). Adding
    a lib to one and forgetting another — exactly the certifi 6-site change — is the
    drift this guards. Earlier tests checked the optlibs key was *present*; this checks
    the lib SET is consistent everywhere. Names are normalized (hyphen/underscore/case),
    and the dist->import map handles pycryptodomex -> Cryptodome."""
    # 1. OPTLIBS byte-identical across all three app.py (the cross-platform guard).
    lists = {f: _optlibs_list(read_source(f)) for f in PLATFORM_APP_FILES}
    root_list = lists["app.py"]
    for f, lst in lists.items():
        assert lst == root_list, f"{f} OPTLIBS {lst} != root OPTLIBS {root_list}"
    libs = {_norm_lib(x) for x in root_list}
    assert libs, "OPTLIBS is empty"

    # 2. Every optional lib is bundled in BOTH requirements.txt (root + linux).
    for req in ("requirements.txt", "linux/requirements.txt"):
        have = {
            _norm_lib(re.split(r"[><=!~]", line)[0])
            for line in read_source(req).splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
        missing = libs - have
        assert not missing, f"{req} is missing optional libs (added to OPTLIBS but not bundled): {missing}"

    # 3. Every optional lib is in BOTH windows/launch.py pip-install lists
    #    (installer + portable embedded) — so every install path receives them.
    launch = read_source("windows/launch.py")
    pip_blocks = re.findall(r'"pip",\s*"install"(.*?)\]', launch, re.DOTALL)
    assert len(pip_blocks) == 2, f"expected 2 pip-install lists in launch.py, found {len(pip_blocks)}"
    for i, block in enumerate(pip_blocks):
        toks = {_norm_lib(re.split(r"[><=!~]", t)[0]) for t in re.findall(r'"([^"]+)"', block)}
        missing = libs - toks
        assert not missing, f"launch.py pip-install list #{i} missing optional libs: {missing}"

    # 4. Every optional lib is in the sentinel import AND the portable `required` tuple
    #    (by import name) — the sentinels are what trigger a (re)install when a lib is
    #    absent; a lib missing here would never get installed/retrofitted.
    import_names = {_OPTLIB_IMPORT_NAME.get(_norm_lib(x), _norm_lib(x)) for x in root_list}
    imp = re.search(r"import flask,([^;]+);\s*return", launch)
    assert imp, "installer sentinel import line not found in launch.py"
    sentinel = {_norm_lib(x) for x in imp.group(1).split(",")}
    assert not (import_names - sentinel), \
        f"launch.py installer sentinel import missing optional libs: {import_names - sentinel}"
    req = re.search(r"required\s*=\s*\(([^)]*)\)", launch)
    assert req, "portable `required` tuple not found in launch.py"
    required = {_norm_lib(x) for x in req.group(1).split(",") if x.strip()}
    assert not (import_names - required), \
        f"launch.py portable `required` tuple missing optional libs: {import_names - required}"


def test_curl_cffi_stays_within_yt_dlps_supported_version_range():
    """yt-dlp's own networking/_curlcffi.py hard-gates curl_cffi to a specific
    range -- anything outside it raises ImportError at import time, which
    yt-dlp swallows silently and just reports every impersonate target as
    unavailable (no error surfaced to the user or to egm_debug.log). A site
    whose extractor needs impersonation (Kick, at minimum) then gets a
    plain-networking request and a 403, with nothing in the app pointing at
    the real cause.

    History: originally gated to "0.5.10 and 0.10.x through 0.15.x".
    Confirmed directly against real yt-dlp (stable 2026.07.04 AND nightly
    2026.08.04, neither had caught up) before the first fix: curl_cffi>=0.16.0
    breaks Kick this way; downgrading to curl_cffi==0.15.0 immediately
    restored every impersonate target.

    Raised to <0.17.0 (0.16.x now included) after yt-dlp nightly 2026.08.18
    added support -- confirmed the same way: curl_cffi==0.16.0 installed,
    `python3 -m yt_dlp --list-impersonate-targets` against that nightly
    showed real targets, not "(unavailable)". At that point this ceiling
    was ahead of yt-dlp STABLE -- staged deliberately on the testing branch
    per EGM, with release held until stable caught up.

    yt-dlp 2026.08.19 stable shipped the same support (changelog:
    "Request Handler: curl_cffi: Support curl_cffi 0.16.x", #17439) --
    reconfirmed live against that exact stable release, then
    requirements.txt's yt-dlp floor was bumped to it, closing the
    stable-vs-nightly gap. curl_cffi 0.16.x and the pinned yt-dlp floor
    now genuinely work together, not just on nightly.

    Floor (not ceiling) raised 0.10.0 -> 0.16.1 after curl_cffi's own
    0.16.1 patch release (bumps curl-impersonate to 2.1.1, closes
    curl_cffi upstream issue #837) -- confirmed the same way,
    curl_cffi==0.16.1 against yt-dlp 2026.08.19 stable: real
    impersonate targets. Ensures fresh installs and "Update Plugins"
    pull at least this patch rather than an older 0.10.x-0.15.x version
    still technically inside the ceiling.

    Floor raised again 0.16.1 -> 0.16.2 alongside the Electron 44 bump --
    confirmed to the same standard: curl_cffi==0.16.2 with yt-dlp
    2026.08.19 lists 38 real impersonate targets and zero
    "(unavailable)", and live impersonated requests complete against a
    real host on Chrome, Safari and Firefox fingerprints. The only
    packaging change in 0.16.2 is the Android wheel splitting from one
    cp313-abi3 build into per-CPython-minor builds (cp313, cp314); every
    wheel this app actually installs -- macosx arm64, manylinux x86_64,
    win_amd64 -- is still cp310-abi3 and byte-for-byte the same shape as
    0.16.1, so the bundled Python 3.11 resolves exactly as before.

    Separately, NOT covered by this test: Kick.com VOD downloads still
    404 due to an unrelated site-side URL scheme change (yt-dlp issue
    #17284 / PR #17322, both open as of yt-dlp 2026.08.19) -- a Kick
    extractor bug, not a curl_cffi/networking issue.

    This upper bound remains a moving target -- raising it further should
    come with the same live confirmation every bump so far has: real targets
    listed under --list-impersonate-targets against the yt-dlp version(s) in
    question, not just bumping the number because a newer curl_cffi exists."""
    for req in ("requirements.txt", "linux/requirements.txt"):
        line = next(
            (l for l in read_source(req).splitlines() if l.strip().startswith("curl_cffi")),
            None,
        )
        assert line, f"{req}: no curl_cffi line found"
        assert "<0.17.0" in line or re.search(r"==0\.1[0-6]\.\d", line), (
            f"{req}: curl_cffi pin ({line!r}) doesn't exclude 0.17.0+ -- "
            f"confirm yt-dlp actually supports the new range "
            f"(python3 -m yt_dlp --list-impersonate-targets, real targets "
            f"listed rather than '(unavailable)') before raising this bound"
        )


def test_curl_cffi_ceiling_also_enforced_on_every_live_update_path():
    """requirements.txt only governs the INITIAL/bundled install.
    curl-cffi is also in OPTLIBS, so it can be re-upgraded live via the
    in-app "Update Plugins" button (do_optlibs, all 3 platforms) and via
    windows/launch.py's two first-launch bootstrap installers -- both are
    unconstrained `pip install --upgrade curl-cffi` calls, independent of
    requirements.txt. This is exactly how curl_cffi ended up at an
    unsupported 0.16.0+ in the first place: requirements.txt was never
    the problem by itself, an already-running or freshly-installed app
    could self-upgrade straight past the supported range regardless of
    what requirements.txt says. Every one of these must carry the same
    ceiling, and app.py/mac/linux's _CURL_CFFI_CEILING constant (used to
    cap what /api/check-updates reports as "latest", so the Update
    Plugins UI doesn't nag forever for an update that's deliberately
    blocked) must agree with requirements.txt's actual pin.

    Ceiling raised 0.16.0 -> 0.17.0 (0.16.x now included) after yt-dlp
    nightly 2026.08.18 added support -- see the matching caveat in
    test_curl_cffi_stays_within_yt_dlps_supported_version_range and the
    comment above the curl_cffi line in requirements.txt: this ceiling is
    ahead of what yt-dlp STABLE actually supports as of this change, staged
    deliberately on the testing branch with release held until stable
    catches up."""
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        assert "_CURL_CFFI_CEILING = (0, 17, 0)" in src, (
            f"{p}: missing or drifted _CURL_CFFI_CEILING constant"
        )
        i = src.index('if do_optlibs:')
        j = src.index('\n', src.index('curl-cffi', i))
        line = src[i:j]
        assert "curl-cffi<0.17.0" in line, (
            f"{p}: the do_optlibs 'Update Plugins' pip install still "
            f"upgrades curl-cffi below the currently-confirmed ceiling -- "
            f"this is the exact path that put curl_cffi at an unsupported "
            f"version originally"
        )

    launch = read_source("windows/launch.py")
    bootstrap_installs = [
        m.start() for m in re.finditer(r'"-m", "pip", "install"', launch)
    ]
    assert len(bootstrap_installs) == 2, (
        "windows/launch.py: expected exactly 2 pip-install bootstrap call "
        "sites (installer + portable) -- count changed, update this test"
    )
    for pos in bootstrap_installs:
        end = launch.index("\n", launch.index("curl_cffi", pos))
        block = launch[pos:end]
        assert "curl_cffi<0.17.0" in block, (
            "windows/launch.py: a first-launch bootstrap pip-install still "
            "pulls curl_cffi below the currently-confirmed ceiling -- a "
            "brand-new install would hit the same unsupported-version bug "
            "on first run"
        )


def test_no_pip_install_path_can_pull_curl_cffi_past_the_ceiling():
    """Companion to the test above, which checks the ONE currently-known
    install site per app.py (the do_optlibs block) plus windows/launch.py.

    windows/launch.py is additionally protected by a count-lock -- adding a
    third bootstrap install there fails the test until someone updates it.
    The three app.py files had no equivalent: an uncapped
    `pip install --upgrade curl-cffi` added anywhere OUTSIDE the do_optlibs
    block (a future "repair optional libraries" path, say) passed the entire
    suite. That is exactly the shape of the original bug -- an unconstrained
    upgrade path independent of requirements.txt -- so it should not be able
    to reappear silently.

    This scans EVERY pip-install call site in each app.py and requires the
    ceiling on any of them that mentions curl-cffi at all.
    """
    call_re = re.compile(r'"-m",\s*"pip",\s*"install"')
    for p in PLATFORM_APP_FILES:
        src = read_source(p)
        sites = [m.start() for m in call_re.finditer(src)]
        assert sites, f"{p}: no pip-install call sites found -- scan is broken"

        capped = 0
        for pos in sites:
            # The argument list: up to the call's timeout= kwarg or ~500 chars,
            # whichever comes first.
            window = src[pos:pos + 500]
            end = window.find("timeout=")
            args = window[:end] if end != -1 else window
            if "curl-cffi" not in args and "curl_cffi" not in args:
                continue
            capped += 1
            assert "<0.17.0" in args, (
                f"{p}: a pip-install call site pulls curl-cffi without the "
                f"version ceiling:\n    {args.strip()[:200]}\n"
                f"Every install path must carry the cap -- an uncapped upgrade "
                f"is how curl_cffi reached an unsupported version originally."
            )

        assert capped == 1, (
            f"{p}: expected exactly 1 pip-install site mentioning curl-cffi "
            f"(do_optlibs), found {capped}. If you added a legitimate new "
            f"install path, confirm it carries the ceiling and update this "
            f"count -- same discipline as windows/launch.py's bootstrap lock."
        )


def test_mp4_h264_is_the_default_everywhere():
    """Universal MP4 (mp4_h264) must be the DEFAULT output on every platform AND in the UI.
    test_universal_mp4_h264_wired only checks the option/codec/transcode EXIST; this locks
    the DEFAULT VALUE. A regression flipping the default back to plain 'mp4' (or dropping the
    `selected` attribute) silently changes every user's default output and would otherwise
    ship green."""
    idx = read_source("templates/index.html")
    assert re.search(r'value="mp4_h264"[^>]*\bselected\b', idx), \
        "index.html: the mp4_h264 option is not the `selected` default"
    for f in PLATFORM_APP_FILES:
        src = read_source(f)
        assert 'output_format="mp4_h264"' in src, f"{f}: run_download signature default is not mp4_h264"
        assert 'data.get("output_format", "mp4_h264")' in src, f"{f}: download-endpoint fallback is not mp4_h264"
        assert 's.get("output_format", "mp4_h264")' in src, f"{f}: get_settings default is not mp4_h264"
    for f in ("templates/js/_download.html", "templates/js/_bulk.html"):
        assert "'mp4_h264'" in read_source(f), f"{f}: JS dispatcher default is not mp4_h264"


def test_themes_all_count_includes_saved():
    """The Themes window 'All' count must include imported/saved themes, not just built-ins
    (the v1.2.3 fix). Locks countTotal() summing loadSavedThemes() so a regression dropping
    it — silently reverting the feature — fails instead of shipping green."""
    th = read_source("templates/themes.html")
    m = re.search(r"function countTotal\(\)\s*\{(.*?)\n\}", th, re.DOTALL)
    assert m, "countTotal() not found in themes.html"
    assert "loadSavedThemes()" in m.group(1), \
        "countTotal() no longer includes saved/imported themes (All count would exclude them)"


def test_history_fields_escaped_against_xss():
    """History title/filename/url are attacker-controllable — a download's title comes from
    the source site, and /api/history/import accepts arbitrary entries — and they render into
    innerHTML. They MUST be escaped (stored-XSS guard) on BOTH the main-UI panel and the
    standalone window, root + linux."""
    for f in ("templates/js/_nav_history.html", "linux/templates/js/_nav_history.html"):
        assert "_hEsc(item.title" in read_source(f), f"{f}: history title is not escaped before innerHTML"
    for f in ("templates/history.html", "linux/templates/history.html"):
        src = read_source(f)
        assert "escH(item.title" in src and "escH(item.url" in src, \
            f"{f}: history title/url is not escaped before innerHTML"


# ── Feed bullet guard (catches generation-layer drops) ─────────────────────────

def test_generated_feeds_have_enough_bullets():
    """_version_notes in every generated feed must:
      - match patchnotes.txt's own per-platform bullet count exactly (not
        truncated or collapsed during generation)
      - have all [TAG] prefixes stripped (user-facing text only)
      - contain no foreign-platform bullets (no [WINDOWS] text in Mac/Linux feeds)

    Regression guard for two v1.2.3 generation bugs:
      1. Single-pipe separator collapsed 21 bullets into 1 string.
      2. Manual note prep emitted all 21 bullets with [TAG] prefixes intact
         and no per-platform filtering — Mac/Linux feeds carried [WINDOWS] bullets.
    The patchnotes.txt source guard passed green both times because it checks
    the source, not the artifact. This guard checks the artifact.

    Previously this asserted a fixed >= 3 minimum on the feed alone, which
    stopped being a reliable proxy for "not collapsed" once genuinely small
    maintenance-only releases became a normal, valid shape -- a real
    2-bullet release and a 21-into-2 collapse look identical under any fixed
    floor once the floor is low enough to allow real small releases through.
    Cross-referencing the feed's count against patchnotes.txt's own
    extraction (same helper the source-level guard uses) catches a collapse
    regardless of how many real bullets there are, including exactly 1.

    Run after feeds are generated (dist/*.json must exist).
    """
    import json as _json
    from pathlib import Path as _Path

    ROOT = _Path(__file__).parent.parent
    feeds = {
        "dist/egm-version.json":          "WINDOWS",
        "dist/egm-portable-version.json": "WINDOWS",
        "dist/egmac-update.json":         "MAC",
        "dist/egmlinux-update.json":      "LINUX",
    }
    foreign_tags = {
        "WINDOWS": ["[MAC]", "[LINUX]"],
        "MAC":     ["[WINDOWS]", "[LINUX]"],
        "LINUX":   ["[WINDOWS]", "[MAC]"],
    }

    missing = [f for f in feeds if not (ROOT / f).exists()]
    if missing:
        import pytest
        pytest.skip(f"Feed(s) not yet generated: {missing}")

    pn = read_source("patchnotes.txt")

    for feed_path, tag in feeds.items():
        d = _json.loads((ROOT / feed_path).read_text(encoding="utf-8"))
        notes = d.get("_version_notes", [])
        source_bullets = _extract_patchnote_bullets(pn, tag)

        assert len(notes) == len(source_bullets), (
            f"{feed_path}: _version_notes has {len(notes)} bullet(s) but "
            f"patchnotes.txt's current [{tag}|ALL] entry has {len(source_bullets)} "
            f"-- feed generation dropped or collapsed bullets. Regenerate."
        )
        assert len(notes) >= 1, (
            f"{feed_path}: _version_notes is empty -- every release needs at "
            f"least one line describing what changed."
        )
        tag_prefixed = [n for n in notes if n.lstrip().startswith("[")]
        assert not tag_prefixed, (
            f"{feed_path}: {len(tag_prefixed)} bullet(s) still carry [TAG] prefix — "
            f"gen_notes() must strip tags before storing. Example: {tag_prefixed[0]!r}"
        )
        for bad_tag in foreign_tags[tag]:
            leaks = [n for n in notes if bad_tag in n]
            assert not leaks, (
                f"{feed_path} ({tag}): {len(leaks)} bullet(s) contain foreign tag "
                f"{bad_tag!r} — per-platform filtering is broken. Example: {leaks[0]!r}"
            )


def test_audio_bitrate_is_cbr_not_vbr_qa():
    """Audio bitrate selection must produce true CBR at the chosen bitrate, applied
    identically on all 3 platforms.

    The bitrate is passed AS ``--audio-quality`` (a bare number > 10) so yt-dlp's
    FFmpegExtractAudio emits ``-b:a {n}k`` with NO ``-q:a`` -> true CBR. The earlier
    ``--audio-quality 0`` approach emitted ``-q:a 0``, which kept libmp3lame/aac in VBR
    mode and made the encoder IGNORE ``-b:a`` — every bitrate collapsed to ~VBR q0
    (issue #11, confirmed with real ffmpeg). This locks the corrected mechanism and
    guards against a regression back to ``--audio-quality 0`` or a ``-b:a`` postprocessor
    arg in the audio-extraction branch.
    """
    blocks = {}
    for f in PLATFORM_APP_FILES:
        src = read_source(f)
        m = re.search(r'if audio_quality == "flac":(.*?)\n        if format_id: args', src, re.DOTALL)
        assert m, f"{f}: audio-format branch not found"
        blk = m.group(0)
        blocks[f] = blk

        # Corrected mechanism: bitrate passed AS --audio-quality (yt-dlp -> -b:a, no -q:a).
        assert '"--audio-format", "mp3", "--audio-quality", q]' in blk, \
            f"{f}: MP3 does not pass the bitrate as --audio-quality (CBR path)"
        assert '"--audio-format", "m4a", "--audio-quality", bitrate]' in blk, \
            f"{f}: M4A does not pass the bitrate as --audio-quality (CBR path)"
        assert '"--audio-format", "opus", "--audio-quality", bitrate]' in blk, \
            f"{f}: OPUS does not pass the bitrate as --audio-quality (CBR path)"

        # Regressions that reintroduce the -q:a-in-VBR bug must NOT reappear.
        assert '"--audio-quality", "0"' not in blk, \
            f"{f}: `--audio-quality 0` regressed — emits -q:a 0, forcing VBR and ignoring the bitrate"
        assert 'ffmpeg:-b:a {' not in blk, \
            f"{f}: audio branch reintroduced a `-b:a` postprocessor-arg (only meaningful without -q:a)"

        # FLAC is lossless — untouched, no bitrate/quality flags.
        assert 'args += ["-x", "--audio-format", "flac"]' in blk, f"{f}: FLAC branch changed"

    # The whole audio-format branch must be byte-identical across all 3 platforms.
    vals = list(blocks.values())
    assert vals[0] == vals[1] == vals[2], "audio-format branch differs across platform app.py files"

def test_i18n_markers_in_all_app_py():
    """v1.3 POLYGLOT: the locale-code allowlist and its consumers must exist
    identically on all three platforms."""
    REQUIRED = [
        "SUPPORTED_LANGUAGES",        # single allowlist for every locale-code entry point
        '/api/language/<code>',       # allowlist-gated locale file route
        "_detect_os_language",        # OS-locale first-run detection
        "_read_installer_language",   # NSIS hand-off file, allowlist-validated
        "_get_language_setting",      # persisted-language resolution
        '"show_language_selector"',   # footer-selector visibility setting
    ]
    for name, path in zip(PLATFORM_NAMES, PLATFORM_APP_FILES):
        source = read_source(path)
        missing = [m for m in REQUIRED if m not in source]
        assert not missing, f"{name}/app.py missing i18n markers: {missing}"


def test_i18n_supported_languages_consistent():
    """The backend allowlist, the frontend allowlist (templates/i18n.html), and
    the locale files on disk must agree on exactly the same 10 codes."""
    import ast, json, os, re
    root = os.path.dirname(os.path.dirname(__file__))

    src = read_source("app.py")
    m = re.search(r"SUPPORTED_LANGUAGES = (\([^)]*\))", src)
    assert m, "SUPPORTED_LANGUAGES tuple not found in app.py"
    backend = set(ast.literal_eval(m.group(1)))

    js = read_source("templates/i18n.html")
    m = re.search(r"I18N_SUPPORTED = \[([^\]]*)\]", js)
    assert m, "I18N_SUPPORTED not found in templates/i18n.html"
    frontend = set(re.findall(r"'([a-z]{2})'", m.group(1)))

    on_disk = {f[:-5] for f in os.listdir(os.path.join(root, "languages"))
               if f.endswith(".json")}

    assert backend == frontend == on_disk, (
        f"locale-code drift: backend={sorted(backend)} "
        f"frontend={sorted(frontend)} disk={sorted(on_disk)}")
    assert len(backend) == 10


def test_i18n_keys_exist_in_en_locale():
    """Every data-i18n / data-i18n-attr key referenced in any template must
    exist in languages/en.json — catches typos and stale keys at wiring time."""
    import glob, json, os, re
    root = os.path.dirname(os.path.dirname(__file__))
    keys = set(json.load(open(os.path.join(root, "languages", "en.json")))["strings"])
    bad = []
    for pattern in ("templates/**/*.html", "linux/templates/**/*.html"):
        for p in glob.glob(os.path.join(root, pattern), recursive=True):
            if p.endswith("i18n.html"):
                continue  # loader partial documents the attr format with a sample key
            src = open(p, encoding="utf-8").read()
            for k in re.findall(r'data-i18n="([^"]+)"', src):
                if k not in keys: bad.append((os.path.relpath(p, root), k))
            for k in re.findall(r"i18n(?:Get|Fmt|Attr)\('([^']+)'", src):
                if k not in keys: bad.append((os.path.relpath(p, root), k))
            for pair in re.findall(r'data-i18n-attr="([^"]+)"', src):
                for item in pair.split(","):
                    k = item.split(":", 1)[1].strip()
                    if k not in keys: bad.append((os.path.relpath(p, root), k))
    assert not bad, f"templates reference keys missing from en.json: {bad}"


def test_electron_runtime_version_is_identical_across_all_three_platforms():
    """The Electron runtime is declared in SIX hand-edited places -- a
    package.json range and a package-lock.json pin for each of Windows, Mac and
    Linux -- and nothing else in the gate reads any of them.

    Verified by mutation: setting mac/electron/package.json to "^43.3.0" while
    the other two stayed at "^43.4.1" left validate-version-sync.py at rc=0 and
    the suite fully green, so a 2-of-3 bump ships a different Chromium/Node on
    one platform with no signal anywhere. This is the same manual-N-way-sync
    shape as the curl_cffi ceiling, which does have a guard.

    The LOCKFILE is what actually governs what ships (`npm ci` installs the
    pinned version; electron-builder packages whatever landed in node_modules),
    so the pins are checked for equality including the integrity hash -- three
    platforms resolving the same version from different tarballs would mean one
    of them was hand-edited. The range is then checked to actually admit the
    pin, which catches the "bumped package.json, forgot to regenerate the
    lockfile" direction.
    """
    import json as _json
    import os as _os

    root = _os.path.dirname(_os.path.dirname(__file__))
    platforms = ("windows", "mac", "linux")

    ranges, pins = {}, {}
    for plat in platforms:
        pkg_path = _os.path.join(root, plat, "electron", "package.json")
        lock_path = _os.path.join(root, plat, "electron", "package-lock.json")
        pkg = _json.load(open(pkg_path, encoding="utf-8"))
        lock = _json.load(open(lock_path, encoding="utf-8"))

        # Windows declares electron under "dependencies", mac/linux under
        # "devDependencies" -- both are legitimate here, so accept either
        # rather than pinning the section and failing on a valid layout.
        decl = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        assert "electron" in decl, f"{plat}/electron/package.json declares no electron dependency"
        ranges[plat] = decl["electron"]

        entry = lock.get("packages", {}).get("node_modules/electron")
        assert entry, f"{plat}/electron/package-lock.json has no node_modules/electron entry"
        pins[plat] = (entry.get("version"), entry.get("integrity"))
        assert pins[plat][0], f"{plat} lockfile electron entry has no version"
        assert pins[plat][1], f"{plat} lockfile electron entry has no integrity hash"

    assert len(set(ranges.values())) == 1, (
        f"Electron version range differs across platforms: {ranges}. "
        "All three package.json files must request the same runtime."
    )
    assert len(set(pins.values())) == 1, (
        f"Electron lockfile pin differs across platforms: {pins}. "
        "All three package-lock.json files must pin the same version AND the "
        "same integrity hash -- this is what decides the shipped runtime."
    )

    # The range must actually admit the pin. Asserting the range SHAPE first
    # keeps this an invariant rather than a whitelist: a range form this parser
    # cannot reason about fails loudly instead of silently passing.
    rng = next(iter(set(ranges.values())))
    pinned = pins[platforms[0]][0]
    assert re.fullmatch(r'\^\d+\.\d+\.\d+', rng), (
        f"Electron range {rng!r} is not the ^X.Y.Z form this guard understands; "
        "widen the check deliberately rather than leaving the pin unverified."
    )
    floor = tuple(int(n) for n in rng.lstrip("^").split("."))
    got = tuple(int(n) for n in pinned.split("."))
    assert got[0] == floor[0] and got >= floor, (
        f"Electron lockfile pins {pinned} which does not satisfy {rng} -- "
        "package.json was bumped without regenerating package-lock.json, so "
        "`npm ci` would reject the lockfile and the build would fall back to "
        "a non-deterministic `npm install`."
    )


def test_macos_minimum_version_is_stated_consistently_everywhere():
    """The macOS floor is written out in SIX hand-edited places -- three in
    README.md (badge, Mac download section, System Requirements), two inside
    the INSTRUCTIONS.txt heredoc in mac/BUILD.sh (which is SHIPPED to end
    users inside the DMG/zip), and mac/electron/package.json's
    build.mac.minimumSystemVersion -- the one electron-builder actually
    reads to set the app's LSMinimumSystemVersion, previously left as an
    inherited Electron default rather than a declared property of this
    build (v1.3.8 security review, closed by declaring it explicitly).

    The Electron 44 bump raised the floor from Big Sur (11.0) to Ventura
    (13.0) and updated the three README copies; both shipped copies in
    mac/BUILD.sh were missed and still told users Big Sur was supported, on
    a build that macOS refuses to launch below 13.0. The README is the copy
    a reviewer looks at; INSTRUCTIONS.txt is the copy the user actually
    reads after downloading; minimumSystemVersion is the copy that
    determines whether macOS itself gives a clear refusal or the app just
    fails to start with no explanation.

    Rather than pin the literal "13.0", this collects every macOS version
    mentioned as a requirement and asserts they AGREE -- so the next floor
    bump passes as soon as all six move together, and fails the moment one
    lags.
    """
    import json as _json
    import os as _os
    import re as _re

    root = _os.path.dirname(_os.path.dirname(__file__))

    # Version floors stated as "macOS <maj>.<min>" or "MINIMUM MACOS: <maj>.<min>".
    _FLOOR = _re.compile(r'(?:MINIMUM MACOS:|macOS)\s*(\d+\.\d+)', _re.IGNORECASE)
    # Named releases carry the same claim in prose and drift independently.
    _NAMES = {"big sur": "11.0", "monterey": "12.0", "ventura": "13.0",
              "sonoma": "14.0", "sequoia": "15.0"}

    found = {}   # version string -> list of "file:line" citations
    for rel in ("README.md", "mac/BUILD.sh"):
        path = _os.path.join(root, rel)
        for n, line in enumerate(open(path, encoding="utf-8"), 1):
            # shields.io badge URLs spell release names with underscores
            # ("macOS-Big_Sur+"), so normalise separators before matching --
            # the badge is one of the six copies and would otherwise be the
            # one this guard silently skipped.
            low = line.lower().replace("_", " ").replace("-", " ")
            # Only consider lines that are actually stating a requirement --
            # patchnotes-style prose and theme names mention releases too.
            if not any(w in low for w in ("requirement", "minimum macos", "macos-", "macos ")):
                continue
            for v in _FLOOR.findall(line):
                found.setdefault(v, []).append(f"{rel}:{n}")
            for name, v in _NAMES.items():
                if name in low:
                    found.setdefault(v, []).append(f"{rel}:{n}")

    pkg_path = _os.path.join(root, "mac/electron/package.json")
    pkg = _json.load(open(pkg_path, encoding="utf-8"))
    min_sys = pkg.get("build", {}).get("mac", {}).get("minimumSystemVersion")
    assert min_sys, (
        "mac/electron/package.json build.mac.minimumSystemVersion is missing -- "
        "electron-builder would fall back to whatever Electron's own template "
        "declares, an inherited default rather than a property of this build "
        "(v1.3.8 security review §4). Declare it explicitly."
    )
    found.setdefault(min_sys, []).append(
        "mac/electron/package.json:build.mac.minimumSystemVersion"
    )

    assert found, (
        "no macOS version requirement found in README.md or mac/BUILD.sh -- "
        "this guard has lost its anchor and must be updated, not deleted"
    )
    # Vacuity check: the two shipped INSTRUCTIONS.txt copies must be among the
    # citations, otherwise the guard is only ever reading the README.
    cited = [c for cites in found.values() for c in cites]
    assert sum(1 for c in cited if c.startswith("mac/BUILD.sh")) >= 2, (
        f"expected at least 2 macOS floor statements in mac/BUILD.sh's shipped "
        f"INSTRUCTIONS.txt, found {[c for c in cited if c.startswith('mac/BUILD.sh')]}"
    )
    assert len(found) == 1, (
        "macOS minimum version disagrees across README.md, mac/BUILD.sh's "
        "shipped INSTRUCTIONS.txt, and mac/electron/package.json's "
        "minimumSystemVersion: "
        + "; ".join(f"{v} at {', '.join(c)}" for v, c in sorted(found.items()))
        + " -- every copy must state the same floor, including the one that "
          "ships inside the DMG and the one electron-builder actually reads."
    )


def _browser_window_blocks(src):
    """Yield (line_no, webPreferences_source) for every `new BrowserWindow({...})`.

    Brace-matched rather than fixed-width sliced: earlier rounds produced false
    results from windowed slices that cut a config in half, and a window's
    options block is long enough that any fixed window would be a guess.
    """
    import re as _re
    for m in _re.finditer(r'new BrowserWindow\(\s*\{', src):
        line = src[:m.start()].count("\n") + 1
        i = src.index("{", m.start())
        depth = 0
        for j in range(i, len(src)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    break
        block = src[i:j + 1]
        wp = _re.search(r'webPreferences:\s*\{', block)
        if not wp:
            yield line, None
            continue
        k = block.index("{", wp.start())
        d = 0
        for n in range(k, len(block)):
            if block[n] == "{":
                d += 1
            elif block[n] == "}":
                d -= 1
                if d == 0:
                    break
        yield line, block[k:n + 1]


def test_every_browser_window_keeps_the_electron_security_defaults():
    """Every window must be created with nodeIntegration:false,
    contextIsolation:true and sandbox:true, and must never disable
    webSecurity.

    These four flags are the app's entire renderer isolation story -- the Flask
    UI is a local web page with full DOM access, and the only thing standing
    between it and Node is these values on 18 window definitions (6 per
    platform). Every review since this project started has re-verified them by
    hand after each Electron bump, including the 43.4.1 -> 44.0.0 major, and
    nothing in the gate has ever checked them: grepping tests/ for
    contextIsolation, nodeIntegration, sandbox or Content-Security-Policy
    returned zero hits before this test existed.

    The scan is derived from the source, not a list of known windows, so a
    seventh window added later is covered the day it lands rather than the day
    someone remembers to extend a whitelist. A window with no webPreferences at
    all is a failure too -- Electron's own defaults are weaker than these.
    """
    for plat in PLATFORM_NAMES:
        src = read_source(f"{plat}/electron/main.js")
        blocks = list(_browser_window_blocks(src))
        assert len(blocks) >= 6, (
            f"{plat}/electron/main.js: found {len(blocks)} BrowserWindow "
            "definitions, expected at least 6 -- the scan lost its anchor "
            "and would pass vacuously"
        )
        for line, wp in blocks:
            where = f"{plat}/electron/main.js:{line}"
            assert wp is not None, f"{where}: BrowserWindow created with no webPreferences block"
            for flag, want in (("nodeIntegration", "false"),
                               ("contextIsolation", "true"),
                               ("sandbox", "true")):
                assert re.search(rf'\b{flag}:\s*{want}\b', wp), (
                    f"{where}: webPreferences must set {flag}: {want} -- got:\n{wp}"
                )
            # webSecurity defaults to true; the only failure mode is an
            # explicit opt-out, so assert its absence rather than its presence.
            assert not re.search(r'\bwebSecurity:\s*false\b', wp), (
                f"{where}: webSecurity: false disables the same-origin policy"
            )


def test_response_csp_is_locked_and_identical_across_platforms():
    """The CSP injected via onHeadersReceived is the second half of the
    isolation story and is duplicated verbatim in all three main.js files.

    Pinned directive-by-directive rather than as one blob so a genuine
    formatting change doesn't force a test edit, while a weakened directive
    (script-src gaining a remote origin, frame-src or object-src losing 'none',
    connect-src opening up) fails.
    """
    required = {
        "default-src": "'self'",
        "connect-src": "'self'",
        "frame-src":   "'none'",
        "object-src":  "'none'",
        "base-uri":    "'self'",
        "form-action": "'self'",
    }
    seen = {}
    for plat in PLATFORM_NAMES:
        src = read_source(f"{plat}/electron/main.js")
        m = re.search(r"'Content-Security-Policy':\s*\[(.*?)\]", src, re.S)
        assert m, f"{plat}/electron/main.js: no Content-Security-Policy header set"
        policy = " ".join(re.findall(r'"([^"]*)"', m.group(1)))
        assert policy.strip(), f"{plat}: Content-Security-Policy resolved to an empty policy"
        for directive, value in required.items():
            assert re.search(rf'\b{re.escape(directive)}\s+{re.escape(value)}\s*;?', policy), (
                f"{plat}/electron/main.js: CSP directive \"{directive} {value}\" "
                f"missing or weakened -- got: {policy}"
            )
        # script-src may carry 'unsafe-inline' (the templates inline their JS)
        # but must never reach off-origin.
        script_src = re.search(r"script-src([^;]*)", policy)
        assert script_src, f"{plat}: CSP has no script-src directive"
        assert "http://" not in script_src.group(1) and "https://" not in script_src.group(1), (
            f"{plat}/electron/main.js: script-src allows a remote origin: {script_src.group(1)!r}"
        )
        seen[plat] = policy
    assert len(set(seen.values())) == 1, (
        "Content-Security-Policy differs across platforms: "
        + "; ".join(f"{p}={v!r}" for p, v in seen.items())
    )
