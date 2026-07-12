"""Dead-element-ID guard.

Every `document.getElementById('literal')` in the frontend must resolve to an
element that actually exists — either statically in the page's HTML or created
dynamically by JS (template-literal `id="..."` / `.id = '...'` assignments).

Mechanizes the manual dead-code sweep from the v1.3 cycle: renamed/removed
markup (version-badge -> footer-version-pill, the removed #deno-log panel, the
Site Cookies redesign, the flask-port row) each left silently-dead JS behind,
found by hand across several review rounds. A dangling getElementById on a
load-bearing element is how the "What's New" modal silently died for two
releases; this test catches the whole class at commit time.

Scopes:
  - templates/js/*.html modules execute inside index.html -> resolve against
    index.html's static ids plus every dynamically-created id in any module.
  - themes/history/subscriptions are standalone windows -> resolve against
    their own static + dynamic ids only.
Cross-window references (`someWindow.document.getElementById`) are skipped —
they resolve in another document by design (the history window's Re-add-to-main
reaches into index.html).
"""
import re
import glob
import os
from conftest import ROOT, read_source

# Ids referenced deliberately even though no element exists (each needs a reason).
ALLOWED_MISSING = {
    # _settings.html installDeno(): the #deno-log panel was removed from the UI;
    # the code treats it as optional (guarded `if (log)`), kept so the log
    # panel can return without re-plumbing.
    "deno-log",
}

_STATIC_ID = re.compile(r'\bid="([a-zA-Z0-9_-]+)"')
_DYN_ID = re.compile(r"""(?:id=\\?["']([a-zA-Z0-9_-]+)\\?["']|\.id\s*=\s*["']([a-zA-Z0-9_-]+)["'])""")
_GET_BY_ID = re.compile(r"document\.getElementById\(\s*'([a-zA-Z0-9_-]+)'\s*\)")


def _defined_ids(source: str) -> set:
    ids = set(_STATIC_ID.findall(source))
    for a, b in _DYN_ID.findall(source):
        ids.add(a or b)
    return ids


def _referenced_ids(source: str):
    """Yield (line_number, id) for same-document getElementById literals."""
    for m in _GET_BY_ID.finditer(source):
        # skip cross-window lookups: `xyzWindow.document.getElementById(...)`
        prefix = source[max(0, m.start() - 40):m.start()]
        if re.search(r"[A-Za-z0-9_$]\.\s*$", prefix):
            continue
        yield source[:m.start()].count("\n") + 1, m.group(1)


def test_index_module_ids_resolve():
    """Every same-document getElementById in templates/js/* must exist in
    index.html or be created dynamically by a module."""
    available = _defined_ids(read_source("templates/index.html"))
    for path in glob.glob(os.path.join(ROOT, "templates", "js", "*.html")):
        available |= _defined_ids(open(path, encoding="utf-8").read())
    dead = []
    for path in sorted(glob.glob(os.path.join(ROOT, "templates", "js", "*.html"))):
        rel = os.path.relpath(path, ROOT)
        src = open(path, encoding="utf-8").read()
        for line, el_id in _referenced_ids(src):
            if el_id not in available and el_id not in ALLOWED_MISSING:
                dead.append(f"{rel}:{line} -> #{el_id}")
    assert not dead, (
        "getElementById targets with no matching element (renamed/removed "
        "markup leaves silently-dead JS — fix the id or add an ALLOWED_MISSING "
        "entry with a reason):\n  " + "\n  ".join(dead)
    )


def test_standalone_window_ids_resolve():
    """Same check for the standalone windows, each against its own document."""
    dead = []
    for page in ("templates/themes.html", "templates/history.html",
                 "templates/subscriptions.html"):
        src = read_source(page)
        available = _defined_ids(src)
        for line, el_id in _referenced_ids(src):
            if el_id not in available and el_id not in ALLOWED_MISSING:
                dead.append(f"{page}:{line} -> #{el_id}")
    assert not dead, (
        "getElementById targets with no matching element in their own window:\n  "
        + "\n  ".join(dead)
    )


def test_guard_has_teeth():
    """Prove-by-mutation: the resolver must actually flag a dead id."""
    fake = "document.getElementById('definitely-not-a-real-id-xyz')"
    refs = list(_referenced_ids(fake))
    assert refs == [(1, "definitely-not-a-real-id-xyz")]
    # and the cross-window skip must skip
    skipped = list(_referenced_ids("win.document.getElementById('urls')"))
    assert skipped == []
