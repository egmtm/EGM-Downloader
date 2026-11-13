"""What the app's own windows send when they load a thumbnail from the site being downloaded.

Thumbnails are shown straight from the site's image server (img-src keeps https:), so the window
makes that request itself. Two things in it were the app's to choose and are now plain:

* the user agent: Electron adds "<app name>/<version>" and "Electron/<version>" to Chrome's, which
  tells the image server which app (and which build) this is. The shells strip both from
  app.userAgentFallback, before any window exists;
* the referrer: every page the backend serves says Referrer-Policy: no-referrer, which covers the
  <img> thumbnails (the download card and one place in Subscriptions). The four Subscriptions
  thumbnails drawn as CSS background-image are not covered by it: Chromium gives CSS image requests
  its default policy, not the page's (found by running Electron 45.2.3, with the header, with a meta
  tag and with both: the image server still got Referer: http://127.0.0.1:8899/). So each shell also
  strips Referer, at the session, from every request that is not to the app itself. The header alone
  passing is not proof, which is why the hook is run here and not just looked for.

A third thing is not a request the app makes but one Chromium makes on its own: it looks up the host
of a link before the link is clicked, when the pointer reaches it or when a link is added to the page
(a Windows capture of the first test build showed DNS lookups for x.com, addons.mozilla.org and
chromewebstore.google.com, the footer link and the links in the cookies dialog, with no connection
after them). Every page the backend serves says X-DNS-Prefetch-Control: off. Checked in Electron
45.2.3 with a page of links: the same page gave lookups for the hovered link and for a link added by
script without the header, and none with it.
"""
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT, read_source
from test_window_requests_cover_every_window import _META_REFERRER

APP_FILES = ("app.py", "mac/app.py", "linux/app.py")
MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")


def _load(path, tmp_path_factory):
    home = str(tmp_path_factory.mktemp("home"))
    mp = pytest.MonkeyPatch()
    for var in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        mp.setenv(var, home)
    try:
        spec = importlib.util.spec_from_file_location("egm_nolabel_" + path.split("/")[0], Path(ROOT) / path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        mp.undo()
    mod.app.template_folder = str(Path(ROOT) / "templates")   # the packaged Mac and Linux apps carry the root templates
    return mod


@pytest.fixture(scope="module", params=APP_FILES)
def backend_module(request, tmp_path_factory):
    if request.param == "app.py":
        return request.getfixturevalue("app_module")
    return _load(request.param, tmp_path_factory)


# ── Referrer ──────────────────────────────────────────────────────────────────────────────────

# The page header: all that reaches an <img>. It does not reach a CSS background image (see below).

PAGES = ("/", "/history-page", "/subscriptions-page", "/console-page", "/themes-page")


@pytest.mark.parametrize("path", PAGES)
def test_every_page_tells_the_browser_to_send_no_referrer(backend_module, path):
    r = backend_module.app.test_client().get(path)
    assert r.status_code == 200, path
    assert r.headers.get("Referrer-Policy") == "no-referrer", f"{path} leaves the referrer policy at the browser default"


def test_api_answers_and_errors_carry_it_too(backend_module):
    c = backend_module.app.test_client()
    ok = c.get("/api/logs", headers={"X-EGM-Token": backend_module._API_TOKEN})
    missing = c.get("/no-such-page")
    assert ok.headers.get("Referrer-Policy") == "no-referrer"
    assert missing.headers.get("Referrer-Policy") == "no-referrer"


def test_no_template_weakens_the_policy():
    """A page or an element could set its own policy and undo the header."""
    templates = sorted(Path(ROOT, "templates").rglob("*.html"))
    assert Path(ROOT, "templates", "index.html") in templates, "the scan found no templates"
    for p in templates:
        assert not _weakens_the_policy(p.read_text(encoding="utf-8")), p.name


def _weakens_the_policy(text):
    """A referrer meta tag (its name attribute with or without quotes) or a referrerpolicy attribute."""
    return bool(_META_REFERRER.search(text)) or "referrerpolicy" in text.lower()


@pytest.mark.parametrize("snippet", ['<meta name=referrer content=unsafe-url>', '<META NAME="Referrer" CONTENT="origin">',
                                     "<meta content=origin name='referrer'>", '<img referrerPolicy=origin src=x>'])
def test_the_policy_scan_sees_each_spelling(snippet):
    assert _weakens_the_policy(snippet), snippet


# ── Link lookups ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PAGES)
def test_every_page_tells_the_window_not_to_look_up_its_links(backend_module, path):
    r = backend_module.app.test_client().get(path)
    assert r.status_code == 200, path
    assert r.headers.get("X-DNS-Prefetch-Control") == "off", f"{path} lets Chromium look up the sites its links point to"


def test_api_answers_and_errors_say_it_too(backend_module):
    c = backend_module.app.test_client()
    ok = c.get("/api/logs", headers={"X-EGM-Token": backend_module._API_TOKEN})
    missing = c.get("/no-such-page")
    assert ok.headers.get("X-DNS-Prefetch-Control") == "off"
    assert missing.headers.get("X-DNS-Prefetch-Control") == "off"


# Every hint that makes Chromium look up, connect to or fetch something before it is used.
HINTS = ("dns-prefetch", "preconnect", "prefetch", "preload", "prerender", "modulepreload")


def _pages():
    """The pages the windows load: the template tree (the Mac and Linux apps carry the same one), the
    static files, and each shell's splash page."""
    files = sorted(Path(ROOT, "templates").rglob("*.html"))
    files += sorted(p for p in Path(ROOT, "static").rglob("*") if p.suffix in (".html", ".js", ".css", ".json", ".svg"))
    files += [Path(ROOT, rel).with_name("splash.html") for rel in MAIN_JS]
    return files


def test_no_template_turns_the_lookups_back_on():
    """A page could set its own control (or ask for a lookup, a connection or a fetch with a hint) and
    undo the header: a <link rel=...> with any of the hints, the same rel set from script, or
    <script type="speculationrules">."""
    pages = _pages()
    assert len(pages) > 10 and all(p.is_file() for p in pages)
    assert Path(ROOT, "templates", "index.html") in pages and Path(ROOT, "templates", "js", "_core.html") in pages
    for p in pages:
        text = p.read_text(encoding="utf-8").lower()
        assert "x-dns-prefetch-control" not in text, p.name
        for m in re.finditer(r"<link\b[^>]*\brel\s*=\s*[\"']?([^\"'>]*)", text):
            assert not set(m.group(1).split()) & set(HINTS), f"{p.name}: {m.group(0)}"
        for hint in HINTS:
            assert not re.search(rf"[\"'`]\s*{hint}\s*[\"'`]", text), f"{p.name} sets rel {hint} from script"
        assert "speculationrules" not in text, f"{p.name} asks for speculative loads"


# ── User agent ────────────────────────────────────────────────────────────────────────────────

CHROME = "Chrome/156.0.8078.100 Safari/537.36"    # what Electron 45.3.2 writes
STOCK_CHROME = "Chrome/156.0.0.0 Safari/537.36"   # what Chrome itself sends (major version only)
WEBKIT = "AppleWebKit/537.36 (KHTML, like Gecko)"
PLATFORMS = {
    "windows/electron/main.js": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "mac/electron/main.js": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "linux/electron/main.js": "Mozilla/5.0 (X11; Linux x86_64)",
}
# the name part as Electron can write it: escaped, with a plain space, the package name, or absent
APP_TOKENS = ("EGM+Downloader/1.5.2.3", "EGM%20Downloader/1.5.2.3", "EGM Downloader/1.5.2.3",
              "egm-downloader/1.5.2.3", "EGMDownloader/1.5.2.3.176", None)


def _function_source(src, name):
    i = src.index(f"function {name}(")
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        depth += src[k] == "{"
        depth -= src[k] == "}"
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced")


def _clean_with_node(rel, uas):
    fn = _function_source(read_source(rel), "cleanUserAgent")
    script = f"{fn}\nconsole.log(JSON.stringify({json.dumps(uas)}.map(cleanUserAgent)));"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_user_agent_keeps_only_what_chrome_itself_sends(rel):
    base = PLATFORMS[rel]
    uas = [" ".join(p for p in (base, WEBKIT, tok, CHROME.split()[0], "Electron/39.2.1", CHROME.split()[1]) if p)
           for tok in APP_TOKENS]
    expected = f"{base} {WEBKIT} {STOCK_CHROME}"
    for got, ua in zip(_clean_with_node(rel, uas), uas):
        assert got == expected, f"{ua!r} became {got!r}"
        assert "egm" not in got.lower() and "electron" not in got.lower()


@pytest.mark.parametrize("rel", MAIN_JS)
def test_a_user_agent_without_either_token_is_left_alone(rel):
    ua = f"{PLATFORMS[rel]} {WEBKIT} {STOCK_CHROME}"
    assert _clean_with_node(rel, [ua]) == [ua]


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_chrome_build_number_is_cut_to_the_major_version_like_chrome_does(rel):
    """Stock Chrome sends Chrome/<major>.0.0.0; Electron's full build (156.0.8078.100) would tell an
    image server that this is not Chrome but an app built on a known Electron release."""
    for full, reduced in (("Chrome/156.0.8078.100", "Chrome/156.0.0.0"), ("Chrome/99.1.22.333", "Chrome/99.0.0.0")):
        ua = f"{PLATFORMS[rel]} {WEBKIT} {full} Safari/537.36"
        assert _clean_with_node(rel, [ua]) == [f"{PLATFORMS[rel]} {WEBKIT} {reduced} Safari/537.36"]


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_shell_cleans_the_fallback_before_any_window_exists(rel):
    src = read_source(rel)
    call = "app.userAgentFallback = cleanUserAgent(app.userAgentFallback)"
    assert call in src, f"{rel} does not clean app.userAgentFallback"
    assert src.index(call) < src.index("app.whenReady()"), f"{rel} cleans it too late"
    assert src.count("new BrowserWindow(") == 6 and src.index(call) < src.index("new BrowserWindow(")


# ── Referrer: the session hook (the only thing that reaches CSS background images) ───────────

def _balanced_call(src, opener):
    """The source of `opener ... )` up to its matching close parenthesis."""
    i = src.index(opener)
    j = src.index("(", i)
    depth = 0
    for k in range(j, len(src)):
        depth += src[k] == "("
        depth -= src[k] == ")"
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced")


HOOK = "session.defaultSession.webRequest.onBeforeSendHeaders("
APP = "http://127.0.0.1:8899"


def _run_hook(rel, requests):
    """Register the shell's own hook on a stand-in session and send each request through it."""
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
def test_the_shell_registers_a_hook_that_strips_the_referer(rel):
    src = read_source(rel)
    assert src.count(HOOK) == 1, f"{rel} has no single onBeforeSendHeaders hook"
    assert src.index(HOOK) > src.index("app.whenReady()"), f"{rel} registers it before the session exists"


@pytest.mark.parametrize("rel", MAIN_JS)
def test_a_request_to_an_image_server_leaves_without_a_referer(rel):
    reqs = [{"url": "https://i.ytimg.com/vi/abc/hqdefault.jpg",
             "headers": {"Referer": APP + "/", "User-Agent": "Chrome", "Accept": "image/*"}},
            {"url": "https://yt3.ggpht.com/a.jpg", "headers": {"Referer": APP + "/subscriptions-page"}},
            {"url": "https://cdn.example/x.jpg", "headers": {}}]
    got = _run_hook(rel, reqs)
    for answers, r in zip(got, reqs):
        assert len(answers) == 1, "the hook must answer exactly once or the request hangs"
        sent = answers[0]["requestHeaders"]
        assert not any(k.lower() == "referer" for k in sent), f"{r['url']} still carries a Referer: {sent}"
        assert {k: v for k, v in sent.items()} == {k: v for k, v in r["headers"].items() if k != "Referer"}, \
            "the hook changed something other than the Referer"
