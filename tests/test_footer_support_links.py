"""The footer asks for support in one place: the PayPal link. There is no Patreon link in the app.

The Patreon link is gone from the footer (the old patchnotes line that announced it is history and
stays). .github/FUNDING.yml is not part of the app and is not looked at here. The PayPal link keeps
its tooltip, so tooltip.support is still used and stays in all ten language files.
"""
import json
from pathlib import Path

from conftest import ROOT, read_source

SHIPPED = (
    [str(p.relative_to(ROOT)) for p in sorted(Path(ROOT, "templates").rglob("*.html"))]
    + [str(p.relative_to(ROOT)) for p in sorted(Path(ROOT, "languages").glob("*.json"))]
    + ["app.py", "mac/app.py", "linux/app.py", "windows/launch.py"]
    + [f"{d}/electron/{f}" for d in ("windows", "mac", "linux") for f in ("main.js", "preload.js", "splash.html")]
)


def test_nothing_the_app_ships_links_to_or_names_patreon():
    assert str(Path("templates", "index.html")) in SHIPPED and str(Path("languages", "en.json")) in SHIPPED, \
        "the scan found no templates or no language files"
    hits = [rel for rel in SHIPPED if "patreon" in read_source(rel).lower()]
    assert hits == [], f"still mentions Patreon: {hits}"


def test_the_paypal_support_link_keeps_its_tooltip():
    html = read_source("templates/index.html")
    link = next(l for l in html.splitlines() if "paypal.me/egerenacom" in l)
    assert 'data-i18n-attr="title:tooltip.support"' in link


def test_tooltip_support_is_still_in_all_ten_language_files():
    files = sorted(Path(ROOT, "languages").glob("*.json"))
    assert len(files) == 10
    for p in files:
        assert "tooltip.support" in json.loads(p.read_text(encoding="utf-8"))["strings"], p.name
