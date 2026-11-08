"""Every user agent the backends set is the plain name, however the code writes it.

test_update_check_user_agent.py scans for "User-Agent": "<literal>" in double quotes. A header written
with single quotes, in another letter case, from a variable or an f-string built elsewhere, or added
with Request.add_header, was not seen by that scan, and the update check is the only request it drives.
This reads the code instead (Python's own parser), so the spelling does not matter: wherever a backend
names a user agent header, the value is the literal string EGM-Downloader.
"""
import ast

import pytest

from conftest import read_source

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
PLAIN = "EGM-Downloader"


def _is_ua(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.lower() == "user-agent"


def _ua_values(tree):
    """(line, value node) for each user agent header the code sets."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            out += [(v.lineno, v) for k, v in zip(node.keys, node.values) if k is not None and _is_ua(k)]
        elif isinstance(node, ast.Call) and len(node.args) >= 2 and _is_ua(node.args[0]):
            out.append((node.lineno, node.args[1]))           # add_header / putheader / headers.__setitem__-style calls
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Subscript) and _is_ua(t.slice) for t in node.targets):
            out.append((node.lineno, node.value))             # headers["User-Agent"] = ...
    return out


@pytest.mark.parametrize("rel", APP_FILES)
def test_every_user_agent_a_backend_sets_is_the_literal_plain_name(rel):
    found = _ua_values(ast.parse(read_source(rel)))
    assert found, f"{rel}: no user agent found, the scan is looking at the wrong thing"
    bad = [(line, ast.unparse(v)) for line, v in found
           if not (isinstance(v, ast.Constant) and v.value == PLAIN)]
    assert not bad, f"{rel}: {bad}"


@pytest.mark.parametrize("snippet", [
    "r = Request(u, headers={'User-Agent': 'EGM-Downloader/' + v})",
    "r = Request(u, headers={'user-agent': UA})",
    "r.add_header('User-Agent', f'EGM-Downloader {v}')",
    "h['User-Agent'] = 'x'",
])
def test_the_scan_sees_each_spelling(snippet):
    (found,) = _ua_values(ast.parse(snippet))
    assert not (isinstance(found[1], ast.Constant) and found[1].value == PLAIN)
