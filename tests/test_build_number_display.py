"""Build numbers stay in the machine readable places (feeds, version.json, APP_BUILD,
the validator rule) but are not shown to users in the text the release scripts write.

The scripts are loaded by path (their file names have hyphens) with ROOT pointed at a
temporary folder, so nothing in the real tree is touched."""
import importlib.util
import json
import re
import sys
from pathlib import Path

from conftest import ROOT, read_source


def _load(script, monkeypatch):
    path = Path(ROOT) / "scripts" / script
    monkeypatch.setattr(sys, "argv", [str(path)])
    spec = importlib.util.spec_from_file_location("_t_" + script.replace("-", "_").replace(".py", ""), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_installer_wizard_text_has_no_build_number_in_any_language():
    nsi = read_source("windows/setup.nsi")
    shown = [l for l in nsi.splitlines() if l.startswith("LangString ")]
    assert shown, "no LangString lines found"
    assert [l[:60] for l in shown if "${BUILD}" in l] == [], "a wizard string shows the build number"
    assert 'WriteRegStr HKCU "${REGKEY}" "Build"' in nsi, "the installer still records the build for machines"


def test_portable_instructions_header_has_no_build_number():
    sh = read_source("windows/BUILD.sh")
    header = [l for l in sh.splitlines() if "Portable Edition" in l and l.startswith("EGM Downloader v")]
    assert len(header) == 1, header
    assert "BUILD_NUM" not in header[0] and "Build" not in header[0]


def test_bump_rewrites_the_readme_latest_lines_in_both_forms(tmp_path, monkeypatch):
    bump = _load("bump-version.py", monkeypatch)
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text(
        "**Latest:** v1.4.11 Build 165  \n(text)\n**Latest:** v1.4.11  \n**Latest:** v1.4.11 Build 165  \n",
        encoding="utf-8")
    bump.update_readme("1.5.0", 166, False)
    out = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert out == "**Latest:** v1.5.0  \n(text)\n**Latest:** v1.5.0  \n**Latest:** v1.5.0  \n"


def test_add_patchnote_header_has_no_build_and_is_read_by_the_feed_tools(tmp_path, monkeypatch):
    add = _load("add-patchnote.py", monkeypatch)
    gen = _load("gen-update-json.py", monkeypatch)
    (tmp_path / "version.json").write_text(
        json.dumps({"version": "1.5.0", "build": 166, "date": "10/20/2026", "time": "9:00 PM EST"}), encoding="utf-8")
    monkeypatch.setattr(add, "ROOT", tmp_path)
    monkeypatch.setattr(add, "PATCHNOTES", tmp_path / "patchnotes.txt")
    monkeypatch.setattr(sys, "argv", ["add-patchnote.py", "[WINDOWS] A change"])
    add.main()
    text = (tmp_path / "patchnotes.txt").read_text(encoding="utf-8")
    header = text.splitlines()[0]
    assert "Build" not in header and gen._HEADER.match(header), header
    monkeypatch.setattr(gen, "PATCHNOTES", tmp_path / "patchnotes.txt")
    assert gen.gen_notes("win") == ["A change"]
    assert gen.parse_history("windows")[0]["version"] == "1.5.0"


def test_a_hand_written_header_without_build_is_read_by_the_feed_tools(tmp_path, monkeypatch):
    gen = _load("gen-update-json.py", monkeypatch)
    pn = tmp_path / "patchnotes.txt"
    pn.write_text(
        "v1.5.0 - A NAME (10/20/2026)\n" + "-" * 28 + "\n\n  • [ALL] New: one\n  • [MAC] Only mac\n\n"
        "v1.4.11 - OLD NAME (Build 165) (10/14/2026)\n" + "-" * 40 + "\n\n  • [ALL] Old: two\n",
        encoding="utf-8")
    monkeypatch.setattr(gen, "PATCHNOTES", pn)
    assert gen.gen_notes("win") == ["New: one"]
    hist = gen.parse_history("windows")
    assert [(h["version"], h["date"]) for h in hist] == [("1.5.0", "10/20/2026"), ("1.4.11", "10/14/2026")]
    assert re.match(r"^v\d", pn.read_text(encoding="utf-8")), "the build scripts and the validator find the entry by the leading v and digit"
