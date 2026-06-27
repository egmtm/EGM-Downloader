"""
Tier 1 — JS syntax gate.

Runs `node --check` on every front-end JS module (templates/js/*.html and
linux/templates/js/*.html). Each module is rendered through Jinja first (so
includes/variables resolve) and written to a temp .js file, since node won't
check .html directly.

Regression this guards: a missing closing brace in renderUpdGrid (_settings.html),
introduced with the optlibs card, broke the ENTIRE front-end init at runtime —
every event listener silently failed to attach — yet all 55 parity/security tests
passed. A per-module `node --check` catches that class of error immediately.

If node isn't on PATH the gate skips (rather than failing) — it's a syntax gate,
not a node-availability gate.
"""
import os
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


def _modules():
    """Every js/*.html module across both template dirs, as (label, tdir, relpath)."""
    out = []
    for label, tdir in _TEMPLATE_DIRS:
        for path in sorted(glob.glob(os.path.join(tdir, "js", "*.html"))):
            rel = os.path.relpath(path, tdir).replace(os.sep, "/")
            out.append((label, tdir, rel))
    return out


_MODULES = _modules()


def test_js_modules_discovered():
    """Sanity: we actually found modules to check on both platforms (else the
    parametrized gate below would silently pass with zero cases)."""
    roots = [m for m in _MODULES if m[0] == "root"]
    linux = [m for m in _MODULES if m[0] == "linux"]
    assert roots, "no templates/js/*.html modules found"
    assert linux, "no linux/templates/js/*.html modules found"
    assert len(roots) == len(linux), (
        f"root has {len(roots)} js modules but linux has {len(linux)} — drift"
    )


@pytest.mark.skipif(NODE is None, reason="node not on PATH — JS syntax gate skipped")
@pytest.mark.parametrize(
    "label,tdir,rel",
    _MODULES,
    ids=[f"{label}:{os.path.basename(rel)}" for label, _, rel in _MODULES],
)
def test_js_module_syntax(label, tdir, rel):
    """`node --check` must pass for each rendered JS module — catches missing
    braces/parens and any other syntax error before it ships."""
    app = Flask(__name__, template_folder=tdir)
    with app.app_context():
        js = render_template(rel, egm_token="test-token", platform_url="test")

    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(js)
            tmp = fh.name
        result = subprocess.run(
            [NODE, "--check", tmp], capture_output=True, text=True
        )
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)

    assert result.returncode == 0, (
        f"node --check FAILED for {label}/{rel} — JS syntax error "
        f"(missing brace/paren?):\n{result.stderr.strip()}"
    )
