"""Error-code mapping: classifier behavior, cross-platform parity, and the
code↔key completeness guard.

The guard exists because of how this feature was born: download.error.region
and download.error.network sat translated in 10 locales for a full cycle with
no pattern ever feeding them (unreachable keys), while _ERROR_MAP carried
long English strings no locale file knew about (keyless text). This test
makes both halves of that failure class structurally impossible.
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLATFORMS = [
    ("windows", REPO / "app.py"),
    ("linux",   REPO / "linux" / "app.py"),
    ("mac",     REPO / "mac" / "app.py"),
]

# Representative raw error strings per expected code — real-world shapes,
# exercised against every platform's _ERROR_MAP source.
SAMPLES = {
    "login":       "ERROR: [youtube] abc: Sign in to confirm you're not a bot.",
    "private":     "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
    "unavailable": "ERROR: [youtube] abc: Video unavailable",
    "format":      "ERROR: [youtube] abc: Requested format is not available",
    "extract":     "ERROR: [generic] abc: Unable to extract video data",
    "403":         "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "404":         "ERROR: [youtube] abc: HTTP Error 404: Not Found",
    "429":         "ERROR: [youtube] abc: HTTP Error 429: Too Many Requests",
    "premiere":    "ERROR: [youtube] abc: This live event will begin in 3 hours",
    "members":     "ERROR: [youtube] abc: Join this channel to get access to members-only content",
    "no_formats":  "ERROR: [youtube] abc: No video formats found!",
    "region":      "ERROR: [youtube] abc: The uploader has not made this video available in your country",
    "network":     "ERROR: Unable to download webpage: <urlopen error [Errno 11001] getaddrinfo failed>",
}
UNCLASSIFIED = "ERROR: something entirely novel the map has never seen"


def _load_module(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"egm_{path.parent.name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _map_codes_from_source(path):
    """Extract the codes _ERROR_MAP emits, from source (no import needed)."""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"_ERROR_MAP = \[(.*?)\n\]", src, re.S)
    assert m, f"{path}: _ERROR_MAP not found"
    return set(re.findall(r'_re\.I\),\s*"([a-z0-9_]+)"\)', m.group(1)))


def test_classifier_codes_all_platforms():
    """Every representative sample resolves to its expected code on every
    platform, and an unknown error resolves to None (raw-text path)."""
    import os
    os.environ.setdefault("EGM_DEV_MODE", "1")
    for name, path in PLATFORMS:
        mod = _load_module(path)
        for code, raw in SAMPLES.items():
            got = mod._classify_error(raw)
            assert got == code, f"{name}: {raw[:50]!r} -> {got!r}, expected {code!r}"
        assert mod._classify_error(UNCLASSIFIED) is None, f"{name}: unclassified must be None"
        assert mod._classify_error("") is None and mod._classify_error(None) is None


def test_every_code_has_a_locale_key_and_vice_versa():
    """code↔key completeness: every code _ERROR_MAP can emit has a
    download.error.* key in en.json, and every download.error.* key is
    reachable from some pattern (no orphans in either direction).
    'generic' is the deliberate exception: it's the UI's final fallback,
    not a classifier output."""
    en = json.loads((REPO / "languages" / "en.json").read_text(encoding="utf-8"))["strings"]
    keyed = {k.split(".", 2)[2] for k in en if k.startswith("download.error.")}
    for name, path in PLATFORMS:
        codes = _map_codes_from_source(path)
        missing_keys = codes - keyed
        assert not missing_keys, f"{name}: codes without locale keys: {missing_keys}"
        orphan_keys = keyed - codes - {"generic"}
        assert not orphan_keys, f"{name}: locale keys no pattern can reach: {orphan_keys}"


def test_error_map_identical_across_platforms():
    """The (pattern, code) map itself must not drift between platforms."""
    blocks = {}
    for name, path in PLATFORMS:
        src = path.read_text(encoding="utf-8")
        m = re.search(r"_ERROR_MAP = \[.*?\n\]", src, re.S)
        blocks[name] = m.group(0)
    assert blocks["windows"] == blocks["linux"] == blocks["mac"], (
        "_ERROR_MAP drifted between platforms"
    )
