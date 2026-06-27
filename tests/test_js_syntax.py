"""
Tier 1 — JS syntax gate.

Runs `node --check` on every front-end JS surface the app ships, rendered through
Jinja first (so includes/variables resolve) and written to a temp .js file, since
node won't check .html directly. Covers BOTH the root and linux template dirs:

  - js/*.html index modules            (whole rendered file is JS)
  - theme_validator.html, theme_data.html   pure-JS partials (whole file is JS)
  - history.html, themes.html, subscriptions.html   standalone windows — their
        inline <script> is extracted before checking

Regression this guards: a missing closing brace in renderUpdGrid (_settings.html),
introduced with the optlibs card, broke the ENTIRE front-end init at runtime — every
event listener silently failed to attach — yet all parity/security tests passed. The
same class of bug in any of the files above (e.g. the security-critical
theme_validator.html gate, or the history/themes/subscriptions window scripts) would
slip through just as silently — so they are all gated here.

If node isn't on PATH the gate skips (rather than failing) — it's a syntax gate, not
a node-availability gate.
"""
import os
import re
import glob
import shutil
import tempfile
import subprocess

import pytest
from flask import Flask, render_template

ROOT = os.path.dirname(os.path.dirname(__file__))


def _find_node():
    node = shutil.which("node")
    if node:
        return node
    for cand in ("/opt/node22/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if os.path.exists(cand):
            return cand
    return None


NODE = _find_node()

# (platform label, absolute template dir)
_TEMPLATE_DIRS = [
    ("root", os.path.join(ROOT, "templates")),
    ("linux", os.path.join(ROOT, "linux", "templates")),
]

# Pure-JS partials: the whole rendered file is JavaScript (checked as-is).
_JS_PARTIALS = ["theme_validator.html", "theme_data.html"]
# Standalone windows: full HTML docs — extract their inline <script> before checking.
_INLINE_SCRIPT_TEMPLATES = ["history.html", "themes.html", "subscriptions.html"]

_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def _units():
    """Every JS-bearing unit across both template dirs.

    Yields (label, tdir, relpath, mode) where mode is:
      'whole'  -> the rendered template IS javascript
      'inline' -> extract inline <script> blocks from the rendered HTML first
    """
    out = []
    for label, tdir in _TEMPLATE_DIRS:
        for path in sorted(glob.glob(os.path.join(tdir, "js", "*.html"))):
            rel = os.path.relpath(path, tdir).replace(os.sep, "/")
            out.append((label, tdir, rel, "whole"))
        for name in _JS_PARTIALS:
            if os.path.exists(os.path.join(tdir, name)):
                out.append((label, tdir, name, "whole"))
        for name in _INLINE_SCRIPT_TEMPLATES:
            if os.path.exists(os.path.join(tdir, name)):
                out.append((label, tdir, name, "inline"))
    return out


_UNITS = _units()


def test_js_units_discovered():
    """Sanity: we found the expected JS surfaces on BOTH platforms and the counts
    match (else the parametrized gate would silently pass with too few cases, or a
    file added on one platform but not the other would go ungated)."""
    root = [u for u in _UNITS if u[0] == "root"]
    linux = [u for u in _UNITS if u[0] == "linux"]
    assert root, "no JS units found under templates/"
    assert linux, "no JS units found under linux/templates/"
    assert len(root) == len(linux), (
        f"root has {len(root)} JS units but linux has {len(linux)} — drift"
    )
    # The non-module surfaces must all be present (they carry large/critical JS).
    root_names = {os.path.basename(u[2]) for u in root}
    for name in _JS_PARTIALS + _INLINE_SCRIPT_TEMPLATES:
        assert name in root_names, f"{name} not picked up by the JS syntax gate"


@pytest.mark.skipif(NODE is None, reason="node not on PATH — JS syntax gate skipped")
@pytest.mark.parametrize(
    "label,tdir,rel,mode",
    _UNITS,
    ids=[f"{label}:{os.path.basename(rel)}" for label, _, rel, _ in _UNITS],
)
def test_js_syntax(label, tdir, rel, mode):
    """`node --check` must pass for each rendered JS surface — catches missing
    braces/parens and any other syntax error before it ships."""
    app = Flask(__name__, template_folder=tdir)
    with app.app_context():
        rendered = render_template(rel, egm_token="test-token", platform_url="test")

    if mode == "inline":
        blocks = _SCRIPT_RE.findall(rendered)
        assert blocks, f"{label}/{rel}: expected inline <script> blocks, found none"
        js = "\n;\n".join(blocks)
    else:
        js = rendered

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(js)
            tmp = fh.name
        result = subprocess.run([NODE, "--check", tmp], capture_output=True, text=True)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)

    assert result.returncode == 0, (
        f"node --check FAILED for {label}/{rel} ({mode}) — JS syntax error "
        f"(missing brace/paren?):\n{result.stderr.strip()}"
    )
