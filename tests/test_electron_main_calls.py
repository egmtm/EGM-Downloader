"""The main-process files are not executed by the tests, so a call to a function that does not
exist only shows up at run time (readSettings() in shellStrings() made the Windows tray English
for every language: the try/except hid the ReferenceError)."""
import re

from conftest import read_source

_CALL = re.compile(r"(?<![\w.$])([a-z]\w*Settings)\(")


def test_every_settings_helper_called_in_main_js_is_defined():
    for platform in ("windows", "mac", "linux"):
        src = read_source(f"{platform}/electron/main.js")
        defined = set(re.findall(r"function\s+(\w+)\s*\(", src)) | set(re.findall(r"(?:const|let)\s+(\w+)\s*=", src))
        called = set(_CALL.findall(src))
        assert called <= defined, (platform, sorted(called - defined))
