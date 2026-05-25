"""Shared fixtures for EGM Downloader test suite."""
import sys
import os
import re
import pytest

# ── Safe app import ────────────────────────────────────────────────────────────
# Set env vars before importing Flask app so it starts in test mode.
os.environ.setdefault("EGM_API_TOKEN", "ci-test-token-not-secret")
sys.argv = ["app.py"]


@pytest.fixture(scope="session")
def app_module():
    """Import Windows app.py once per session."""
    import importlib.util
    root = os.path.dirname(os.path.dirname(__file__))
    spec = importlib.util.spec_from_file_location("app", os.path.join(root, "app.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Source file helpers ────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(__file__))

def read_source(rel_path):
    return open(os.path.join(ROOT, rel_path), encoding="utf-8").read()

PLATFORM_APP_FILES = ["app.py", "mac/app.py", "linux/app.py"]
PLATFORM_NAMES     = ["windows", "mac", "linux"]
