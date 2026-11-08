"""scripts/validate-version-sync.py: a feed against the zip it describes.

A feed's _checksums.sha256 was checked for its shape only (64 lowercase hex characters), never
against the zip in dist/, and size_bytes only for being a positive integer: a stale or hand edited
hash or size passed. When the zip is in dist/, the feed's hash and size must be the zip's own, for
each pair: EGMd.zip and egm-version.json, EGMd-portable.zip and egm-portable-version.json, and the
Mac and Linux zips with their feeds. With no zip in dist/ (CI, which only puts placeholder feeds
there) nothing is checked.

The validator is loaded as a module with ROOT pointed at a temporary tree."""
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PAIRS = {"egm-version.json": "EGMd.zip", "egm-portable-version.json": "EGMd-portable.zip",
         "egmac-update.json": "EGMdM.zip", "egmlinux-update.json": "EGMdL.zip"}


@pytest.fixture(scope="module")
def val():
    spec = importlib.util.spec_from_file_location("egm_validate_feeds_zips", ROOT / "scripts/validate-version-sync.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def dist(tmp_path, val, monkeypatch):
    monkeypatch.setattr(val, "ROOT", tmp_path)
    d = tmp_path / "dist"
    d.mkdir()
    return d


def _feed(dist, name, sha, size):
    body = {"version": "1.5.2.3", "build": 176, "_version_notes": ["Fixed: a thing."],
            "_checksums": {"sha256": sha, "algorithm": "SHA-256", "file": PAIRS[name]}, "size_bytes": size}
    (dist / name).write_text(json.dumps(body), encoding="utf-8")


def _zip(dist, name, payload=b"zip bytes of a build"):
    (dist / name).write_bytes(payload)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def test_the_pairs_are_the_four_published_ones(val):
    assert val.FEED_ZIP == PAIRS


def test_no_zip_present_means_nothing_is_checked(dist, val):
    for name in PAIRS:
        _feed(dist, name, "0" * 64, 0)      # the placeholder feeds CI writes
    assert val.check_feed_matches_zip() == []


@pytest.mark.parametrize("name", sorted(PAIRS))
def test_a_feed_that_matches_its_zip_passes(dist, val, name):
    sha, size = _zip(dist, PAIRS[name])
    _feed(dist, name, sha, size)
    assert val.check_feed_matches_zip() == []


@pytest.mark.parametrize("name", sorted(PAIRS))
def test_a_wrong_hash_fails(dist, val, name):
    sha, size = _zip(dist, PAIRS[name])
    _feed(dist, name, "f" * 64, size)
    errors = val.check_feed_matches_zip()
    assert any(name in e and "sha256" in e for e in errors), errors


@pytest.mark.parametrize("name", sorted(PAIRS))
def test_a_wrong_size_fails(dist, val, name):
    sha, size = _zip(dist, PAIRS[name])
    _feed(dist, name, sha, size + 1)
    errors = val.check_feed_matches_zip()
    assert any(name in e and "size_bytes" in e for e in errors), errors


@pytest.mark.parametrize("size", [0, None, "20", True])
def test_the_windows_feed_needs_a_positive_integer_size_when_its_zip_is_there(dist, val, size):
    sha, _ = _zip(dist, "EGMd.zip")
    _feed(dist, "egm-version.json", sha, size)
    errors = val.check_feed_matches_zip()
    assert any("egm-version.json" in e and "size_bytes" in e for e in errors), errors


def test_a_zip_whose_feed_is_missing_is_reported(dist, val):
    _zip(dist, "EGMd.zip")
    errors = val.check_feed_matches_zip()
    assert any("EGMd.zip" in e and "egm-version.json" in e for e in errors), errors


def test_the_check_runs_in_main(val):
    assert "check_feed_matches_zip()" in inspect.getsource(val.main)
