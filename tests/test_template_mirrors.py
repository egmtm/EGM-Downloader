"""Proposal A: one tree-walk replaces the six hand-listed mirror tests.

templates/ is the source; linux/templates/ is a byte-for-byte copy of it (mac uses the
root tree). Walking the tree means a new template is covered the day it is added and a
file present on only one side is a failure, not a silent skip (today both this suite's
hand-written list and scripts/validate-version-sync.py skip templates/i18n.html and
templates/console.html; the latter is only mirrored by tests in other files).
"""
import os

from conftest import ROOT

ROOT_T = os.path.join(ROOT, "templates")
LINUX_T = os.path.join(ROOT, "linux", "templates")


def _tree(base):
    out = {}
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            full = os.path.join(dirpath, f)
            out[os.path.relpath(full, base).replace(os.sep, "/")] = full
    return out


def test_linux_templates_are_a_byte_identical_copy_of_the_root_tree():
    root, linux = _tree(ROOT_T), _tree(LINUX_T)
    assert len(root) >= 19, f"template tree looks truncated: {sorted(root)}"
    assert set(root) == set(linux), (
        f"only in templates/: {sorted(set(root) - set(linux))}; "
        f"only in linux/templates/: {sorted(set(linux) - set(root))}"
    )
    drifted = [rel for rel in sorted(root)
               if open(root[rel], "rb").read() != open(linux[rel], "rb").read()]
    assert not drifted, f"linux/templates copies differ from templates/ (bytes): {drifted}"
