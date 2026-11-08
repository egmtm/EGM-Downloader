"""The window protections hold for every window and every way a page could undo them.

test_window_requests_carry_nothing_identifying.py runs the shells' Referer hook and checks the page
headers. Three ways around them were not covered:

* the hook keeps the Referer for the app's own requests by URL prefix. A prefix that is only the host
  (any port on 127.0.0.1) would also keep it for anything else served on the machine;
* the hook, the empty spellchecker language list and the user agent are set on the default session.
  A window given its own partition (or session) gets a fresh session with none of them;
* a template could set its own referrer policy or ask for a lookup with attributes written without
  quotes (<meta name=referrer ...>, <link rel=preconnect ...>), which the plain text scan missed.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, read_source

MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")
HOOK = "session.defaultSession.webRequest.onBeforeSendHeaders("
APP = "http://127.0.0.1:8899"


def _balanced_call(src, opener):
    i = src.index(opener)
    j = src.index("(", i)
    depth = 0
    for k in range(j, len(src)):
        depth += src[k] == "("
        depth -= src[k] == ")"
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced")


def _run_hook(rel, requests):
    call = _balanced_call(read_source(rel), HOOK)
    script = (f"const APP_URL = {json.dumps(APP)};\nlet hook = null;\n"
              "const session = { defaultSession: { webRequest: { onBeforeSendHeaders: (f) => { hook = f; } } } };\n"
              f"{call};\n"
              "const out = [];\n"
              f"for (const r of {json.dumps(requests)}) {{\n"
              "  const answers = [];\n"
              "  hook({ url: r.url, requestHeaders: Object.assign({}, r.headers) }, (a) => answers.push(a));\n"
              "  out.push(answers);\n"
              "}\n"
              "console.log(JSON.stringify(out));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


@pytest.mark.parametrize("rel", MAIN_JS)
def test_another_server_on_the_same_machine_is_not_the_app(rel):
    reqs = [{"url": "http://127.0.0.1:9000/a.jpg", "headers": {"Referer": APP + "/"}},
            {"url": "http://127.0.0.1/a.jpg", "headers": {"Referer": APP + "/subscriptions-page"}}]
    for answers, r in zip(_run_hook(rel, reqs), reqs):
        assert len(answers) == 1
        assert "Referer" not in answers[0]["requestHeaders"], f"{rel}: {r['url']} still gets the app's address"


def _windows(src):
    out = []
    for m in re.finditer(r"new BrowserWindow\(", src):
        out.append(_balanced_call(src[m.start():], "new BrowserWindow("))
    return out


@pytest.mark.parametrize("rel", MAIN_JS)
def test_every_window_uses_the_default_session(rel):
    """The Referer hook and the empty spellchecker language list are on session.defaultSession only."""
    wins = _windows(read_source(rel))
    assert len(wins) == 6, rel
    for w in wins:
        assert not re.search(r"\b(partition|session)\s*:", w), f"{rel}: a window has its own session:\n{w[:400]}"


# An attribute value with or without quotes.
_META_REFERRER = re.compile(r"<meta\b[^>]*\bname\s*=\s*[\"']?referrer\b", re.I)
_HINT = re.compile(r"<link\b[^>]*\brel\s*=\s*[\"']?[^>]*\b(dns-prefetch|preconnect|prefetch|prerender)\b", re.I)
_HTTP_EQUIV = re.compile(r"\bhttp-equiv\s*=\s*[\"']?(x-dns-prefetch-control|referrer-policy)\b", re.I)


def _templates():
    files = sorted(Path(ROOT, "templates").rglob("*.html"))
    assert files, "the scan found no templates"
    return files


def test_no_template_sets_a_referrer_policy_or_a_lookup_hint_in_any_spelling():
    for p in _templates():
        text = p.read_text(encoding="utf-8")
        for rx in (_META_REFERRER, _HINT, _HTTP_EQUIV):
            m = rx.search(text)
            assert not m, f"{p.name}: {m.group(0)!r}"


@pytest.mark.parametrize("snippet", [
    '<meta name=referrer content=origin>', '<meta content="origin" name="referrer">',
    "<link rel=preconnect href=https://x>", '<link href="https://x" rel="dns-prefetch">',
    '<meta http-equiv=x-dns-prefetch-control content=on>',
])
def test_the_scan_sees_each_spelling(snippet):
    assert any(rx.search(snippet) for rx in (_META_REFERRER, _HINT, _HTTP_EQUIV)), snippet
