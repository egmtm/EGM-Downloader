"""bump-version.py rewrites the README "Latest:" lines to the bare version whether or not
the line still carries a build number. Before this, a line without "Build N" was skipped
with only a [warn], so a hand edited README stayed stale after a bump."""
import importlib.util
import sys
from pathlib import Path

from conftest import ROOT


def test_bump_rewrites_the_readme_latest_lines_in_both_forms(tmp_path, monkeypatch):
    path = Path(ROOT) / "scripts" / "bump-version.py"
    monkeypatch.setattr(sys, "argv", [str(path)])
    spec = importlib.util.spec_from_file_location("_t_bump_version", path)
    bump = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bump)
    monkeypatch.setattr(bump, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text(
        "**Latest:** v1.4.11 Build 165  \n(text)\n**Latest:** v1.4.11  \n**Latest:** v1.4.11 Build 165  \n",
        encoding="utf-8")
    bump.update_readme("1.4.12", 166, False)
    out = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert out == "**Latest:** v1.4.12  \n(text)\n**Latest:** v1.4.12  \n**Latest:** v1.4.12  \n"
