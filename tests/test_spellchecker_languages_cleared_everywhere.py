"""The empty spellchecker language list is set on every platform, unconditionally.

test_no_background_contacts.py runs the setSpellCheckerLanguages([]) line on the test machine. A
condition on the platform (in the line or around it) passed there as long as the test machine was the
platform kept: the dictionary request was seen on Linux, but the shells give the session no language
on every platform, so nothing depends on which one Chromium picks to download for.
"""
import json
import re
import subprocess

import pytest

from conftest import read_source

MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")
SPELL_CALL = "session.defaultSession.setSpellCheckerLanguages([])"
READY = "app.whenReady().then(async () => {"


def _strip(js):
    """Comments and string contents out, so braces in them are not counted."""
    js = re.sub(r"//[^\n]*", "", js)
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", "''", js)


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_call_sits_directly_in_when_ready_not_under_a_condition(rel):
    src = read_source(rel)
    assert src.count(READY) == 1, rel
    start = src.index(READY) + len(READY)
    call = src.rindex("\n", 0, src.index(SPELL_CALL))      # the start of the call's own line
    between = _strip(src[start:call])
    assert between.count("{") - between.count("}") == 0, f"{rel}: the call is inside a block in whenReady"
    line = next(l for l in src.splitlines() if SPELL_CALL in l)
    assert "process.platform" not in line and not re.match(r"\s*if\b", line), f"{rel}: {line.strip()}"


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_line_clears_the_list_whatever_the_platform(rel, platform):
    line = next(l for l in read_source(rel).splitlines() if SPELL_CALL in l).strip()
    script = ("const vm = require('vm');\n"
              "const calls = [];\n"
              "const ctx = { calls, process: { platform: %s },\n"
              "  session: { defaultSession: { setSpellCheckerLanguages: (l) => calls.push(l) } } };\n"
              "vm.runInNewContext(%s, ctx);\n"
              "console.log(JSON.stringify(calls));") % (json.dumps(platform), json.dumps(line))
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-1500:]
    assert json.loads(r.stdout) == [[]], f"{rel} on {platform}"
