"""node --check on the JavaScript the Electron shells run (main.js, preload.js, the after-pack
hook). tests/test_js_syntax.py covers the page scripts only; a syntax error in a main.js passed
the whole suite and every workflow (the JavaScript lint workflow does not stop on errors)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted(str(p.relative_to(ROOT)) for p in
               list(ROOT.glob("*/electron/main.js")) + list(ROOT.glob("*/electron/preload.js"))
               + list(ROOT.glob("*/electron/build/*.js")))
NODE = shutil.which("node") or next((p for p in ("/opt/node22/bin/node", "/usr/local/bin/node", "/usr/bin/node")
                                     if Path(p).exists()), None)


def test_every_shell_file_is_found():
    assert len(FILES) >= 6, FILES


@pytest.mark.skipif(NODE is None, reason="node not available")
@pytest.mark.parametrize("rel", FILES)
def test_the_shell_file_parses(rel):
    r = subprocess.run([NODE, "--check", str(ROOT / rel)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
