"""
Tests for _atomic_write_text — the persistence helper introduced in v0.99.13.

Rule: any new helper that handles persistence gets its own test
the same release it lands. Three cases required:
  (a) normal write succeeds and content lands at the correct path
  (b) chmod is applied to the tmp file BEFORE rename — no race window
  (c) .tmp file is cleaned up on failure — no tmp accumulation

These tests import from Windows app.py (root). The helper is identical across
all 3 platforms — this is covered by test_parity.py's platform-parity tests.
"""
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from conftest import ROOT

# ── Import the helper ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def _write_fn():
    """Import _atomic_write_text from Windows app.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("egm_app_atomic", os.path.join(ROOT, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._atomic_write_text


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_atomic_write_creates_file_with_correct_content(_write_fn, tmp_path):
    """(a) Normal write: file lands at target path with correct content."""
    target = tmp_path / "settings.json"
    _write_fn(target, '{"theme": "void"}')

    assert target.exists(), "Target file was not created"
    assert target.read_text(encoding="utf-8") == '{"theme": "void"}'

    # No .tmp file should remain
    tmp = target.with_suffix(target.suffix + ".tmp")
    assert not tmp.exists(), ".tmp file left behind after successful write"


def test_atomic_write_chmod_applied_before_rename(_write_fn, tmp_path):
    """(b) owner_only=True: chmod is called on the tmp file before os.replace.
    This ensures the final file has correct permissions from the moment it
    exists — no race window where the file is briefly world-readable."""
    target = tmp_path / "cookies.txt"
    chmod_calls = []

    original_chmod = os.chmod

    def tracking_chmod(path, mode):
        chmod_calls.append((str(path), mode))
        original_chmod(path, mode)

    with patch("os.chmod", side_effect=tracking_chmod):
        _write_fn(target, "cookie_data", owner_only=True)

    assert target.exists(), "Target file was not created"

    # chmod must have been called — and on a .tmp path, not the final path
    assert len(chmod_calls) > 0, "os.chmod was never called"

    # The chmod call should be on the .tmp file (i.e., before rename)
    tmp_path_str = str(target.with_suffix(target.suffix + ".tmp"))
    chmod_was_on_tmp = any(tmp_path_str in call[0] for call in chmod_calls)
    assert chmod_was_on_tmp, (
        f"chmod was not called on the .tmp file before rename. "
        f"Calls were: {chmod_calls}"
    )


def test_atomic_write_cleans_up_tmp_on_failure(_write_fn, tmp_path):
    """(c) On write failure the .tmp file is cleaned up — no .tmp accumulation.

    The helper now writes to tmp, fsyncs, then renames. We inject the failure at
    os.fsync — so the .tmp file has actually been created and written by the time
    the error fires, which exercises the cleanup-and-reraise path more directly
    than failing before the file ever exists."""
    target = tmp_path / "history.json"
    tmp = target.with_suffix(target.suffix + ".tmp")

    with patch("os.fsync", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            _write_fn(target, '{"items": []}')

    # Neither target nor .tmp should exist
    assert not target.exists(), "Target file should not exist after failed write"
    assert not tmp.exists(), ".tmp file was not cleaned up after failed write"
