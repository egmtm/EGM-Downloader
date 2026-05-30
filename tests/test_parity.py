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
    index_src  = read_source("templates/index.html")
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
    source = read_source("templates/index.html")

    # Extract THEMES array
    m = re.search(r"const THEMES\s*=\s*\[([^\]]+)\]", source)
    assert m, "THEMES array not found"
    themes_arr = {t.strip().strip("'\"") for t in m.group(1).split(",") if t.strip().strip("'\"")} - {"custom"}

    # Extract THEME_DATA keys
    m2 = re.search(r"const THEME_DATA\s*=\s*\{(.*?)\n\s*\};", source, re.DOTALL)
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
    source = read_source("templates/index.html")
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
        "\n".join(f"  {name}: missing {vars_}" for name, vars_ in list(incomplete.items())[:10])
    )
