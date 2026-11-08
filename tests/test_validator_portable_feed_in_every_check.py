"""scripts/validate-version-sync.py: the portable feed goes through every feed check.

egm-portable-version.json was missing from FEED_BANNED_TERMS, the list the parse, required keys and
purity checks loop over, so a corrupt portable feed passed where the other three feeds are refused.

The validator is loaded as a module with ROOT pointed at a temporary tree."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def val():
    spec = importlib.util.spec_from_file_location("egm_validate_portable_feed", ROOT / "scripts/validate-version-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dist(tmp_path, val, monkeypatch):
    monkeypatch.setattr(val, "ROOT", tmp_path)
    d = tmp_path / "dist"
    d.mkdir()
    return d


def test_the_portable_feed_is_in_the_feed_list_with_the_windows_terms(val):
    assert "egm-portable-version.json" in val.FEED_BANNED_TERMS
    assert val.FEED_BANNED_TERMS["egm-portable-version.json"] == val.FEED_BANNED_TERMS["egm-version.json"]


def test_a_corrupt_portable_feed_fails_the_parse_check(dist, val):
    (dist / "egm-portable-version.json").write_text("{ not json", encoding="utf-8")
    assert any("egm-portable-version.json" in e for e in val.check_json_feeds_parse())


def test_a_portable_feed_without_the_required_keys_or_with_a_mac_bullet_fails(dist, val):
    body = {"version": "1.5.2.3", "_version_notes": ["Fixed the macOS menu."]}
    (dist / "egm-portable-version.json").write_text(json.dumps(body), encoding="utf-8")
    assert any("egm-portable-version.json" in e and "missing required keys" in e for e in val.check_json_feeds_keys())
    assert any("egm-portable-version.json" in e and "macos" in e for e in val.check_json_feeds_purity())


def test_a_sound_portable_feed_passes_all_three(dist, val):
    body = {k: "x" for k in val.FEED_REQUIRED_KEYS}
    body["_version_notes"] = ["Fixed: the installer keeps your settings."]
    (dist / "egm-portable-version.json").write_text(json.dumps(body), encoding="utf-8")
    assert val.check_json_feeds_parse() == val.check_json_feeds_keys() == val.check_json_feeds_purity() == []
