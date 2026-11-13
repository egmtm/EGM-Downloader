"""Nothing a package ships names Patreon, including the texts that come with the app around it.

test_footer_support_links.py scans the templates, the language files, the backends and the shell files.
The packages also carry text the person reads: the instructions next to the app (Windows and Linux), the
installer's own pages (setup.nsi), the portable's instructions written by windows/BUILD.sh, and the
packaging metadata. The app files list of the Windows build is read too, so a text file added to the
build is scanned without this list changing. patchnotes.txt is history (it announced the old link) and
.github/FUNDING.yml is not part of any package.
"""
from pathlib import Path

from conftest import ROOT, read_source

TEXT_SUFFIXES = {".py", ".html", ".json", ".js", ".txt", ".nsi", ".sh", ""}
HISTORY = {"patchnotes.txt"}


def _app_files():
    rels = [l.strip() for l in read_source("windows/app-files.txt").splitlines()
            if l.strip() and not l.lstrip().startswith("#")]
    assert "app.py" in rels, "the app files list was not read"
    return [r for r in rels if Path(r).suffix.lower() in TEXT_SUFFIXES and r not in HISTORY]


AROUND_THE_APP = [
    "windows/instructions.txt", "linux/INSTRUCTIONS.txt", "windows/setup.nsi", "windows/BUILD.sh",
    "windows/electron/package.json", "mac/electron/package.json", "linux/electron/package.json",
]


def test_every_listed_file_exists():
    missing = [r for r in _app_files() + AROUND_THE_APP if not Path(ROOT, r).is_file()]
    assert not missing, missing


def test_no_shipped_text_names_patreon():
    hits = [rel for rel in _app_files() + AROUND_THE_APP if "patreon" in read_source(rel).lower()]
    assert hits == [], f"still mentions Patreon: {hits}"
