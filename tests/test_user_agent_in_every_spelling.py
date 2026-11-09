"""Every user agent the backends set is the plain name, however the code writes it.

test_update_check_user_agent.py scans for "User-Agent": "<literal>" in double quotes. A header written
with single quotes, in another letter case, from a variable or an f-string built elsewhere, or added
with Request.add_header, was not seen by that scan, and the update check is the only request it drives.
This reads the code instead (Python's own parser), so the spelling does not matter: wherever a backend
names a user agent header, the value is the literal string EGM-Downloader.

One value is not: the history thumbnail fetch the backend makes when the shell cannot fetch the
picture sends the agent yt-dlp used for that download (decided, so the image server sees what it saw
for the download). It is allowed by name, the user_agent argument of _fetch_thumbnail, and nowhere
else; test_thumbnail_fallback_user_agent.py checks its value.
"""
import ast

import pytest

from conftest import read_source

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
PLAIN = "EGM-Downloader"
YT_DLP_AGENT = ("_fetch_thumbnail", "user_agent")


def _yt_dlp_agent_nodes(tree):
    """The user_agent name inside _fetch_thumbnail, the one value allowed to differ."""
    return {id(n) for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == YT_DLP_AGENT[0]
            for n in ast.walk(f) if isinstance(n, ast.Name) and n.id == YT_DLP_AGENT[1]}


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
    tree = ast.parse(read_source(rel))
    found = _ua_values(tree)
    assert found, f"{rel}: no user agent found, the scan is looking at the wrong thing"
    allowed = _yt_dlp_agent_nodes(tree)
    bad = [(line, ast.unparse(v)) for line, v in found
           if not (isinstance(v, ast.Constant) and v.value == PLAIN) and id(v) not in allowed]
    assert not bad, f"{rel}: {bad}"


def test_the_allowance_is_for_that_one_argument_only():
    other_name = "def _fetch_thumbnail(url, ua):\n    r = Request(url, headers={'User-Agent': ua})"
    other_function = "def _fetch(url, user_agent):\n    r = Request(url, headers={'User-Agent': user_agent})"
    for snippet in (other_name, other_function):
        tree = ast.parse(snippet)
        (found,) = _ua_values(tree)
        assert id(found[1]) not in _yt_dlp_agent_nodes(tree), snippet


@pytest.mark.parametrize("snippet", [
    "r = Request(u, headers={'User-Agent': 'EGM-Downloader/' + v})",
    "r = Request(u, headers={'user-agent': UA})",
    "r.add_header('User-Agent', f'EGM-Downloader {v}')",
    "h['User-Agent'] = 'x'",
])
def test_the_scan_sees_each_spelling(snippet):
    (found,) = _ua_values(ast.parse(snippet))
    assert not (isinstance(found[1], ast.Constant) and found[1].value == PLAIN)
