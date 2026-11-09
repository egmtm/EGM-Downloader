"""Shared fixtures for EGM Downloader test suite."""
import sys
import os
import re
import pytest

# ── Safe app import ────────────────────────────────────────────────────────────
# Set env vars before importing Flask app so it starts in test mode.
os.environ.setdefault("EGM_API_TOKEN", "ci-test-token-not-secret")
# Several tests load windows/launch.py; on Windows its top level would otherwise re-run it under
# pythonw.exe (starting the real launcher) and exit the test process.
os.environ.setdefault("EGM_SILENT", "1")
# EGM_INSTALL_DIR moves app.py's data and tools to another folder. Set in a developer's shell it made the
# modules under test read and write there, so it is cleared before any of them is imported (this file
# loads first). The tests that need it give it to their own child process.
os.environ.pop("EGM_INSTALL_DIR", None)
# EGM_ELECTRON=1 tells app.py it runs under the shell (the shell fetches the history pictures, the backend
# waits 30 seconds for it); set in a developer's shell it made the history tests on app.py wait for a shell
# that is not there. Cleared the same way; the tests that need it set it with monkeypatch.
os.environ.pop("EGM_ELECTRON", None)
sys.argv = ["app.py"]


@pytest.fixture(autouse=True)
def _no_egm_variable_left_changed():
    """A test that leaves an EGM_ variable set, changed or removed after it ran fails, and the variable is
    put back, so no later test runs with it. monkeypatch.setenv and delenv are undone before this check."""
    before = {k: v for k, v in os.environ.items() if k.startswith("EGM_")}
    yield
    after = {k: v for k, v in os.environ.items() if k.startswith("EGM_")}
    if after != before:
        for k in set(after) - set(before):
            del os.environ[k]
        os.environ.update(before)
        changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        pytest.fail(f"the test left {changed} changed; use monkeypatch.setenv or delenv", pytrace=False)


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


# index_scripts.html is an include-shell that pulls in templates/js/_*.html modules.
# Content-analysis tests want the full logical JS regardless of how it's split across
# modules, so resolve the js/ include directives inline (concatenated exactly as Jinja
# would). Non-js includes (e.g. theme_validator.html) are left as literal directives so
# tests can still assert on the include line itself.
import re as _re

def read_index_scripts(platform_dir="templates"):
    shell = read_source(f"{platform_dir}/index_scripts.html")

    def _resolve(m):
        return read_source(f"{platform_dir}/js/{m.group(1)}")

    return _re.sub(r"\{%\s*include\s*'js/([^']+)'\s*%\}", _resolve, shell)

PLATFORM_APP_FILES = ["app.py", "mac/app.py", "linux/app.py"]
PLATFORM_NAMES     = ["windows", "mac", "linux"]
