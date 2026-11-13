"""The session hook that strips the Referer decides "the app itself" by the request's origin.

It used to test details.url.startsWith(APP_URL), a prefix: http://127.0.0.1:8899@tracker.example/x.png
(userinfo, the host is tracker.example) and http://127.0.0.1:88990/x (another port) both start with
"http://127.0.0.1:8899", so they kept the Referer. Now the hook compares new URL(url).origin with
APP_URL, treats a URL it cannot parse as foreign (its Referer goes), and answers the request exactly
once on every path: a request it never answers would hang.

The shell's own hook is registered on a stand in session and run under node."""
import json
import re
import subprocess

import pytest

from conftest import read_source

MAIN_JS = ("windows/electron/main.js", "mac/electron/main.js", "linux/electron/main.js")
HOOK = "session.defaultSession.webRequest.onBeforeSendHeaders("


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


def _config(src):
    """The shell's own PORT, HOST and APP_URL lines."""
    lines = [l for l in src.splitlines() if re.match(r"const (PORT|HOST|APP_URL)\s*=", l)]
    assert len(lines) == 3, lines
    return "\n".join(lines)


def _run(rel, requests, throwing_headers=False):
    """Each request through the shell's hook: the answers it gave, and whether it threw."""
    src = read_source(rel)
    headers = ("new Proxy(Object.assign({}, r.headers), { deleteProperty() { throw new Error('locked'); } })"
               if throwing_headers else "Object.assign({}, r.headers)")
    script = (f"{_config(src)}\nlet hook = null;\n"
              "const session = { defaultSession: { webRequest: { onBeforeSendHeaders: (f) => { hook = f; } } } };\n"
              f"{_balanced_call(src, HOOK)};\n"
              "const out = [];\n"
              f"for (const r of {json.dumps(requests)}) {{\n"
              "  const answers = []; let threw = false;\n"
              f"  try {{ hook({{ url: r.url, requestHeaders: {headers} }}, (a) => answers.push(JSON.parse(JSON.stringify(a)))); }}\n"
              "  catch (e) { threw = true; }\n"
              "  out.push({ answers, threw });\n"
              "}\n"
              "console.log(JSON.stringify({ app: APP_URL, origin: new URL(APP_URL).origin, out }));")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout)


def _sent(result):
    assert len(result["answers"]) == 1, f"answered {len(result['answers'])} times"
    return result["answers"][0]["requestHeaders"]


@pytest.mark.parametrize("rel", MAIN_JS)
def test_app_url_is_exactly_an_origin(rel):
    got = _run(rel, [])
    assert got["app"] == got["origin"] == "http://127.0.0.1:8899"


FOREIGN = [
    "http://127.0.0.1:8899@tracker.example/x.png",      # userinfo: the host is tracker.example
    "http://127.0.0.1:88990/x.png",                     # another port that starts with the app's
    "http://127.0.0.1:8899.tracker.example/x.png",      # a host that starts with the app's
    "https://127.0.0.1:8899/x.png",                     # another scheme
    "https://i.ytimg.com/vi/abc/hqdefault.jpg",
]


@pytest.mark.parametrize("rel", MAIN_JS)
@pytest.mark.parametrize("url", FOREIGN)
def test_a_request_to_any_other_origin_loses_its_referer(rel, url):
    headers = {"Referer": "http://127.0.0.1:8899/", "Accept": "image/*"}
    sent = _sent(_run(rel, [{"url": url, "headers": headers}])["out"][0])
    assert sent == {"Accept": "image/*"}, f"{url} kept {sent}"


@pytest.mark.parametrize("rel", MAIN_JS)
@pytest.mark.parametrize("url", ["not a url", "http://[::1", ""])
def test_a_url_that_cannot_be_parsed_counts_as_foreign(rel, url):
    sent = _sent(_run(rel, [{"url": url, "headers": {"Referer": "http://127.0.0.1:8899/"}}])["out"][0])
    assert sent == {}


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_apps_own_requests_keep_every_header(rel):
    reqs = [{"url": u, "headers": {"Referer": "http://127.0.0.1:8899/x", "X-EGM-Token": "t"}}
            for u in ("http://127.0.0.1:8899/", "http://127.0.0.1:8899/api/settings", "http://127.0.0.1:8899?x=1")]
    for res, r in zip(_run(rel, reqs)["out"], reqs):
        assert _sent(res) == r["headers"], r["url"]


@pytest.mark.parametrize("rel", MAIN_JS)
def test_the_request_is_answered_once_even_when_the_hook_fails(rel):
    """A header object that refuses the delete makes the hook throw; the request is still answered."""
    got = _run(rel, [{"url": "https://cdn.example/a.jpg", "headers": {"Referer": "http://127.0.0.1:8899/"}}],
               throwing_headers=True)
    assert len(got["out"][0]["answers"]) == 1, got
