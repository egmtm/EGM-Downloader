"""The app opens only pages that exist: every egerena.com link in the shared scripts is a platform page.

The update dialog and the update toasts fall back to a web page when a feed carries no download link.
Two of those fallbacks, https://egerena.com/mac and https://egerena.com/linux, were never pages
(they answer 404), and the third was the site's front page, not the person's platform. The pages that
exist are the ones each backend's footer link already uses (the platform_url it gives index.html), so
that is the list every other link in the shared scripts has to come from.
"""
import re
from pathlib import Path

from conftest import ROOT

BACKENDS = ("app.py", "mac/app.py", "linux/app.py")
LINK = re.compile(r"https://egerena\.com[^\s'\"`)<>]*")


def _platform_pages():
    pages = set()
    for rel in BACKENDS:
        src = (Path(ROOT) / rel).read_text(encoding="utf-8")
        pages.update(re.findall(r'platform_url="(https://egerena\.com/apps/[a-z]+\.html)"', src))
    return pages


def test_each_backend_names_its_own_platform_page():
    assert _platform_pages() == {
        "https://egerena.com/apps/egm.html",
        "https://egerena.com/apps/egmac.html",
        "https://egerena.com/apps/egml.html",
    }


def test_every_egerena_link_in_the_shared_scripts_is_a_platform_page():
    pages = _platform_pages()
    found = []
    for folder in ("templates", "templates/js"):
        for path in sorted((Path(ROOT) / folder).glob("*.html")):
            for link in LINK.findall(path.read_text(encoding="utf-8")):
                found.append((path.name, link))
    assert found, "no egerena.com link found in the templates, so this checks nothing"
    stray = [(name, link) for name, link in found if link not in pages]
    assert not stray, f"links that are not a platform page: {stray}"
