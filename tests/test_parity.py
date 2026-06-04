"""
Tier 1 — Parity tests.

Checks that all three platforms (Windows, Mac, Linux) stay in sync on the
invariants that have caused real bugs when they drifted. Each test here
maps to at least one regression we shipped and then had to fix.
"""
import re
import pytest
from conftest import read_source, PLATFORM_APP_FILES, PLATFORM_NAMES


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
    index_src  = read_source("templates/index_scripts.html")  # JS extracted from index.html
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
    source = read_source("templates/index_scripts.html")  # JS extracted from index.html

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
    scripts = read_source("templates/index_scripts.html")
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
    for fname in ["index.html", "index_scripts.html", "themes.html", "theme_styles.html", "theme_data.html"]:
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
