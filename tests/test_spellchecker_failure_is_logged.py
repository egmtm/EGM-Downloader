"""When the session refuses setSpellCheckerLanguages([]), the shell says so and the start goes on.

The call used to sit in an empty catch: had it failed (a Chromium change, say), the dictionary download
it exists to stop would have come back with nothing anywhere to show why. The shells write their start
up warnings with console.warn and an "[EGM]" prefix (the window show timeout in the Linux shell); the
catch now writes one such line. The shell's own line is run under node with a stand in session."""
import json
import subprocess

import pytest

from conftest import read_source

MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")
SPELL_CALL = "session.defaultSession.setSpellCheckerLanguages([])"


def _run(rel, throws):
    lines = [l.strip() for l in read_source(rel).splitlines() if SPELL_CALL in l]
    assert len(lines) == 1, f"{rel}: expected the call on one line"
    body = "throw new Error('spellchecker unavailable')" if throws else "calls.push(langs)"
    script = ("const calls = [];\n"
              f"const session = {{ defaultSession: {{ setSpellCheckerLanguages: (langs) => {{ {body}; }} }} }};\n"
              f"{lines[0]}\n"
              "console.log('START GOES ON ' + JSON.stringify(calls));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-1500:]
    return r.stdout, r.stderr


@pytest.mark.parametrize("rel", MAIN_JS)
def test_a_refused_call_writes_one_warning_line_and_the_start_goes_on(rel):
    out, err = _run(rel, throws=True)
    assert "START GOES ON []" in out
    warn = [l for l in err.splitlines() if l.strip()]
    assert len(warn) == 1, err
    assert warn[0].startswith("[EGM] ") and "spellchecker" in warn[0].lower(), warn[0]
    assert "spellchecker unavailable" in warn[0], "the line says why"


@pytest.mark.parametrize("rel", MAIN_JS)
def test_a_call_that_works_writes_nothing(rel):
    out, err = _run(rel, throws=False)
    assert "START GOES ON [[]]" in out and err.strip() == ""

