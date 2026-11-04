"""Linux ships the root templates/ tree, like Mac.

linux/electron/package.json packages templates/ from the repo root into app/templates, next to
app/app.py, where Flask looks for them. A linux/templates/ folder would be a second copy that the
build ignores and no test reads, so it must not come back, and the packaging config must keep
pulling the root tree.
"""
import json
import os

import pytest

from conftest import ROOT


def _template_sources(platform):
    """[(source dir, packaged dir)] for every extraResources entry that brings in templates."""
    base = os.path.join(ROOT, platform, "electron")
    with open(os.path.join(base, "package.json"), encoding="utf-8") as fh:
        entries = json.load(fh)["build"]["extraResources"]
    out = []
    for e in entries:
        src = os.path.normpath(os.path.join(base, e["from"]))
        filters = e.get("filter", [])
        if any(f == "templates" or f.startswith("templates/") for f in filters):
            out.append((os.path.join(src, "templates"), f"{e['to']}/templates"))
        elif os.path.basename(src) == "templates":
            out.append((src, e["to"]))
    return out, entries


def test_linux_has_no_template_copy():
    path = os.path.join(ROOT, "linux", "templates")
    assert not os.path.exists(path), (
        "linux/templates/ is back; Linux packages templates/ from the repo root "
        "(linux/electron/package.json), so this copy would never ship. Edit templates/ instead."
    )


@pytest.mark.parametrize("platform", ["linux", "mac"])
def test_packaging_pulls_the_root_templates_next_to_app_py(platform):
    sources, entries = _template_sources(platform)
    assert sources == [(os.path.join(ROOT, "templates"), "app/templates")], (
        f"{platform}/electron/package.json must package the root templates/ (and nothing else) "
        f"as app/templates; found {sources}"
    )
    app_py = [e["to"] for e in entries if "app.py" in e.get("filter", [])]
    assert app_py == ["app"], f"{platform}: app.py must be packaged as app/app.py, beside app/templates; found {app_py}"
