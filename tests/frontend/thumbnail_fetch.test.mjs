// The history thumbnail request each shell's main process makes (History thumbnails in main.js), run
// against stand ins for Electron's net module and session, in all three shells:
//  * the request carries the window's clean Chrome user agent (the shell's own cleanUserAgent line is
//    run first), no cookies (a session of its own, in memory, no session cookies) and no Referer;
//  * only HTTPS, never an internal address, and every redirect hop is checked before it is followed;
//  * reading stops at the 500 KB cap, a length header over it is refused before reading, a request
//    that does not answer is given up after the timeout, a response that is not an image is refused;
//  * the shell fetches only the URL the backend says it is waiting for, hands the bytes back with the
//    per run token, reports a failure with an empty body, and reacts only to the app's own /api/status
//    answers that name an entry.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import http from "node:http";
import vm from "node:vm";
import { EventEmitter } from "node:events";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = (p) => readFileSync(join(repo, p, "electron", "main.js"), "utf8");
const RAW_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) EGM Downloader/1.5.2.3 Chrome/156.0.8078.80 Electron/45.2.3 Safari/537.36";
const CLEAN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36";
const JPEG = Buffer.concat([Buffer.from([0xff, 0xd8, 0xff, 0xe0]), Buffer.alloc(60)]);
const CAP = 512000;

function blockOf(platform) {
  const src = source(platform);
  const block = /\n\/\/ ── History thumbnails[\s\S]*?\nfunction noticeThumbnail\(details\) \{[\s\S]*?\n\}\n/.exec(src);
  assert.ok(block, `${platform}: the History thumbnails block was found`);
  const clean = /\nfunction cleanUserAgent\(ua\) \{[\s\S]*?\n\}\n/.exec(src);
  const line = "app.userAgentFallback = cleanUserAgent(app.userAgentFallback);";
  assert.ok(clean && src.includes(line), `${platform}: cleanUserAgent found`);
  return clean[0] + line + "\n" + block[0];
}

// A stand in for net.request: records the options, the headers and what was done to the request; the
// test then plays the server's side with play(req).
function fakeNet(play) {
  const made = [];
  const net = {
    request(options) {
      const req = new EventEmitter();
      Object.assign(req, { options, headers: {}, follows: 0, aborted: false, ended: false });
      req.setHeader = (k, v) => { req.headers[k] = v; };
      req.followRedirect = () => { req.follows++; setImmediate(() => play(req, "followed")); };
      req.abort = () => { req.aborted = true; };
      req.end = () => { req.ended = true; setImmediate(() => play(req, "sent")); };
      made.push(req);
      return req;
    },
  };
  return { net, made };
}

function response(req, { status = 200, headers = { "content-type": "image/jpeg" }, chunks = [JPEG] } = {}) {
  const res = new EventEmitter();
  res.statusCode = status;
  res.headers = headers;
  req.emit("response", res);
  for (const c of chunks) { if (!req.aborted) res.emit("data", c); }
  if (!req.aborted) res.emit("end");
  return res;
}

// Name resolution as Chromium's resolver would answer it: a table, literal addresses as themselves.
const DNS = { "cdn.example": "93.184.216.34", "img.example": "151.101.1.1", "intranet.example": "10.1.2.3",
              "ipv6only.example": "2606:4700::6810:84e5", "router.example": "192.168.1.1", "meta.example": "169.254.169.254",
              "mixed.example": ["93.184.216.34", "10.0.0.7"], "mixed6.example": ["fd00::7", "2606:4700::6810:84e5"] };

function shell(platform, play, { appUrl = "http://127.0.0.1:8899", timers = { setTimeout, clearTimeout }, httpModule = http } = {}) {
  const { net, made } = fakeNet(play);
  const partitions = [];
  const partition = {
    async resolveHost(h) {
      const a = DNS[h] || (/^[\d.]+$|:/.test(h) ? h : null);
      if (!a) throw new Error("ERR_NAME_NOT_RESOLVED");
      return { endpoints: [a].flat().map((x) => ({ address: x, family: x.includes(":") ? "ipv6" : "ipv4" })) };
    },
  };
  const ctx = {
    require: (m) => { assert.equal(m, "electron"); return { net }; },
    app: { userAgentFallback: RAW_UA },
    session: { defaultSession: { name: "default" }, fromPartition: (name, opts) => { partitions.push([name, opts]); return partition; } },
    http: httpModule, APP_URL: appUrl, EGM_TOKEN: "tok", URL, Buffer, Promise, Set, Object, String, Number, JSON, Array, parseInt,
    setTimeout: timers.setTimeout, clearTimeout: timers.clearTimeout,
  };
  vm.runInNewContext(blockOf(platform) + "\nthis.api = { fetchThumbnail, deliverThumbnail, noticeThumbnail, isInternalAddress };", ctx);
  return { api: ctx.api, made, partitions, partition, ctx };
}

const answer = (opts) => (req, step) => { if (step === "sent" || step === "followed") response(req, opts); };

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: the thumbnail request carries the clean Chrome user agent, no cookie and no Referer`, async () => {
    const s = shell(platform, answer());
    const bytes = await s.api.fetchThumbnail("https://cdn.example/vi/x/hq.jpg");
    assert.deepEqual(bytes, JPEG);
    const [req] = s.made;
    assert.equal(req.options.url, "https://cdn.example/vi/x/hq.jpg");
    assert.deepEqual(req.headers, { "User-Agent": CLEAN_UA }, "only the user agent is set, and it is the cleaned one");
    assert.equal(s.ctx.app.userAgentFallback, CLEAN_UA, "one source: the value cleanUserAgent gave the windows");
    assert.equal(req.options.session, s.partition, "not the default session and its cookie jar");
    assert.equal(JSON.stringify(s.partitions), JSON.stringify([["egm-thumbnails", { cache: false }]]), "an in memory partition (no persist: prefix), made once");
    assert.equal(req.options.useSessionCookies, false);
    assert.equal(req.options.credentials, "omit");
    assert.equal(req.options.referrerPolicy, "no-referrer");
    assert.ok(!Object.keys(req.headers).some((k) => /^(cookie|referer)$/i.test(k)));
    await s.api.fetchThumbnail("https://img.example/b.jpg");
    assert.equal(s.partitions.length, 1, "the partition is reused");
  });

  test(`${platform}: only HTTPS, and never an internal address`, async () => {
    const s = shell(platform, answer());
    for (const url of ["http://cdn.example/x.jpg", "ftp://cdn.example/x.jpg", "file:///etc/passwd", "javascript:alert(1)",
                       "data:image/jpeg;base64,/9j/", "not a url", "", null,
                       "https://127.0.0.1/x.jpg", "https://[::1]/x.jpg", "https://10.0.0.8/x.jpg", "https://intranet.example/x.jpg",
                       "https://router.example/x.jpg", "https://meta.example/latest", "https://unresolvable.example/x.jpg",
                       "https://[::ffff:127.0.0.1]/x.jpg", "https://[fe80::1]/x.jpg", "https://0.0.0.0/x.jpg"]) {
      assert.equal(await s.api.fetchThumbnail(url), null, String(url));
    }
    assert.equal(s.made.length, 0, "nothing was requested");
    assert.deepEqual(await s.api.fetchThumbnail("https://ipv6only.example/x.jpg"), JPEG, "a global IPv6 address is fine");
  });

  test(`${platform}: a redirect to an internal address or to plain HTTP is not requested`, async () => {
    for (const to of ["https://10.0.0.5/x.jpg", "https://intranet.example/x.jpg", "https://[::1]/x.jpg",
                      "http://img.example/x.jpg", "https://169.254.169.254/latest/meta-data", "https://unresolvable.example/"]) {
      const s = shell(platform, (req, step) => { if (step === "sent") req.emit("redirect", 302, "GET", to, {}); });
      assert.equal(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), null, to);
      assert.equal(s.made.length, 1, `${to} was requested`);
      const [req] = s.made;
      assert.equal(req.options.redirect, "manual", "Chromium must not follow a redirect by itself");
      assert.equal(req.follows, 0);
      assert.ok(req.aborted);
    }
  });

  test(`${platform}: every public hop is checked and requested in turn, the same way`, async () => {
    const chain = { "https://cdn.example/x.jpg": "https://img.example/1.jpg", "https://img.example/1.jpg": "/2.jpg" };
    const s = shell(platform, (req, step) => {
      if (step !== "sent") return;
      const to = chain[req.options.url];
      if (to) req.emit("redirect", 302, "GET", to, {}); else response(req);
    });
    assert.deepEqual(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), JPEG);
    assert.deepEqual(s.made.map((r) => r.options.url), ["https://cdn.example/x.jpg", "https://img.example/1.jpg", "https://img.example/2.jpg"]);
    for (const r of s.made) {
      assert.deepEqual(r.headers, { "User-Agent": CLEAN_UA });
      assert.equal(r.options.session, s.partition);
      assert.equal(r.options.useSessionCookies, false);
      assert.equal(r.follows, 0, "Chromium followed a redirect by itself");
    }
  });

  test(`${platform}: more than 10 redirects are given up`, async () => {
    const s = shell(platform, (req, step) => { if (step === "sent") req.emit("redirect", 302, "GET", `https://img.example/${s.made.length}.jpg`, {}); });
    assert.equal(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), null);
    assert.equal(s.made.length, 11);
  });

  test(`${platform}: reading stops at the cap, and a length over it is refused before reading`, async () => {
    const chunk = Buffer.alloc(200000, 1);
    let res = null, seenAfter = 0;
    const s = shell(platform, (req, step) => {
      if (step !== "sent") return;
      res = new EventEmitter();
      res.statusCode = 200;
      res.headers = { "content-type": "image/jpeg" };              // no length: only counting can stop it
      req.emit("response", res);
      for (let i = 0; i < 6; i++) { res.emit("data", chunk); if (req.aborted) seenAfter++; }
      res.emit("end");
    });
    assert.ok(await s.api.fetchThumbnail("https://cdn.example/big.jpg") === null, "the oversized picture came back");
    assert.ok(s.made[0].aborted, "the request was not stopped");
    assert.equal(seenAfter, 4, "it was stopped by the third chunk (600000 bytes > 512000), not at the end");

    const lying = shell(platform, answer({ headers: { "content-type": "image/jpeg", "content-length": String(CAP + 1) }, chunks: [JPEG] }));
    assert.ok(await lying.api.fetchThumbnail("https://cdn.example/x.jpg") === null, "a length over the cap was read");
    assert.ok(lying.made[0].aborted);

    const exact = shell(platform, answer({ chunks: [Buffer.concat([JPEG, Buffer.alloc(CAP - JPEG.length)])] }));
    assert.equal((await exact.api.fetchThumbnail("https://cdn.example/x.jpg")).length, CAP, "exactly the cap is fine");
  });

  test(`${platform}: a response that is not an image, or not a success, is refused`, async () => {
    for (const opts of [{ headers: { "content-type": "text/html" } }, { headers: { "content-type": "image/svg+xml" } },
                        { headers: {} }, { status: 404 }, { status: 500 }]) {
      const s = shell(platform, answer(opts));
      assert.equal(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), null, JSON.stringify(opts));
    }
    const typed = shell(platform, answer({ headers: { "content-type": "image/webp; charset=binary" } }));
    assert.deepEqual(await typed.api.fetchThumbnail("https://cdn.example/x.webp"), JPEG);
  });

  test(`${platform}: a request that does not answer is given up after the timeout`, async () => {
    const delays = [];
    const timers = { setTimeout: (fn, ms) => { delays.push(ms); return setTimeout(fn, 5); }, clearTimeout };
    const s = shell(platform, () => {}, { timers });
    assert.equal(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), null);
    assert.deepEqual(delays, [15000]);
    assert.ok(s.made[0].aborted);
  });
}

// ── the shell and the backend ─────────────────────────────────────────────────────────────────

function backend(handler) {
  const calls = [];
  return new Promise((res) => {
    const srv = http.createServer((req, resp) => {
      const parts = [];
      req.on("data", (c) => parts.push(c));
      req.on("end", () => {
        calls.push({ method: req.method, url: req.url, headers: req.headers, body: Buffer.concat(parts) });
        handler(req, resp, calls);
      });
    }).listen(0, "127.0.0.1", () => res({ srv, calls, url: `http://127.0.0.1:${srv.address().port}` }));
  });
}

const ENTRY = "3f2c1a9e-0b4d-4c6e-9a7f-1234567890ab";

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: the shell fetches only the URL the backend waits for and hands the bytes back`, async (t) => {
    const b = await backend((req, resp) => {
      if (req.method === "GET") { resp.setHeader("Content-Type", "application/json"); resp.end(JSON.stringify({ url: "https://cdn.example/x.jpg" })); }
      else resp.end('{"ok": true}');
    });
    t.after(() => b.srv.close());
    const s = shell(platform, answer(), { appUrl: b.url });
    await s.api.deliverThumbnail(ENTRY);
    assert.deepEqual(b.calls.map((c) => `${c.method} ${c.url}`), [`GET /api/history/${ENTRY}/thumbnail`, `POST /api/history/${ENTRY}/thumbnail`]);
    assert.ok(b.calls.every((c) => c.headers["x-egm-token"] === "tok"), "the per run token on both");
    assert.equal(b.calls[1].headers["content-type"], "application/octet-stream");
    assert.deepEqual(b.calls[1].body, JPEG);
    assert.equal(s.made[0].options.url, "https://cdn.example/x.jpg");
  });

  test(`${platform}: a failed fetch is reported with an empty body, and nothing is fetched when the backend is not waiting`, async (t) => {
    let waiting = true;
    const b = await backend((req, resp) => {
      if (req.method === "GET" && !waiting) { resp.statusCode = 404; resp.end("{}"); return; }
      resp.end(req.method === "GET" ? JSON.stringify({ url: "https://10.0.0.1/x.jpg" }) : "{}");
    });
    t.after(() => b.srv.close());
    const s = shell(platform, answer(), { appUrl: b.url });
    await s.api.deliverThumbnail(ENTRY);
    assert.equal(b.calls[1].method, "POST");
    assert.equal(b.calls[1].body.length, 0, "the refused fetch was reported as an empty body");
    assert.equal(b.calls[1].headers["content-length"], "0");
    waiting = false;
    await s.api.deliverThumbnail(ENTRY);
    assert.equal(b.calls.length, 3, "only the GET: no fetch and no POST");
    assert.equal(s.made.length, 0);
  });

  test(`${platform}: only the app's own /api/status answer that names an entry starts it, once at a time`, async (t) => {
    const b = await backend((req, resp) => { resp.statusCode = 404; resp.end("{}"); });
    t.after(() => b.srv.close());
    const s = shell(platform, answer(), { appUrl: b.url });
    const notice = (url, headers) => s.api.noticeThumbnail({ url, responseHeaders: headers });
    notice(`${b.url}/api/status/abc`, {});
    notice(`${b.url}/api/settings`, { "X-EGM-Thumbnail": [ENTRY] });
    notice(`https://evil.example/api/status/abc`, { "X-EGM-Thumbnail": [ENTRY] });
    notice(`${b.url}.evil.example/api/status/abc`, { "X-EGM-Thumbnail": [ENTRY] });
    for (const bad of ["../../x", "ABC", "a b", "x".repeat(65), ""]) notice(`${b.url}/api/status/abc`, { "X-EGM-Thumbnail": [bad] });
    await new Promise((r) => setTimeout(r, 100));
    assert.equal(b.calls.length, 0, "something else started a thumbnail request");
    notice(`${b.url}/api/status/abc`, { "x-egm-thumbnail": [ENTRY] });
    notice(`${b.url}/api/status/abc`, { "X-EGM-Thumbnail": [ENTRY] });     // the next poll, while the first is on its way
    await new Promise((r) => setTimeout(r, 200));
    assert.deepEqual(b.calls.map((c) => c.url), [`/api/history/${ENTRY}/thumbnail`]);
  });

  test(`${platform}: the shell registers the notice on the default session, and polls nothing for it`, () => {
    const src = source(platform);
    assert.equal(src.split("session.defaultSession.webRequest.onCompleted(noticeThumbnail);").length, 2);
    assert.ok(src.indexOf("session.defaultSession.webRequest.onCompleted(noticeThumbnail);") > src.indexOf("app.whenReady()"));
    const block = blockOf(platform);
    assert.ok(!/setInterval|ipcMain|contextBridge/.test(block), "no polling, and nothing handed to the pages");
  });
}

// ── gaps found by mutation (session 4's thumbnail code) ──────────────────────────────────────────

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: a name that resolves to a public and an internal address is not fetched`, async () => {
    const s = shell(platform, answer());
    for (const url of ["https://mixed.example/x.jpg", "https://mixed6.example/x.jpg"]) {
      assert.equal(await s.api.fetchThumbnail(url), null, url);
    }
    assert.equal(s.made.length, 0, "a name with any internal address was requested");
  });

  test(`${platform}: the shared address range 100.64.0.0/10 is refused, its neighbours are not`, async () => {
    const s = shell(platform, answer());
    for (const ip of ["100.64.0.1", "100.100.100.100", "100.127.255.254"]) {
      assert.equal(await s.api.fetchThumbnail(`https://${ip}/x.jpg`), null, ip);
    }
    assert.equal(s.made.length, 0);
    for (const ip of ["100.63.255.255", "100.128.0.1"]) {
      assert.deepEqual(await s.api.fetchThumbnail(`https://${ip}/x.jpg`), JPEG, ip);
    }
  });

  test(`${platform}: one byte over the cap, with no length header, is refused`, async () => {
    const s = shell(platform, answer({ chunks: [Buffer.concat([JPEG, Buffer.alloc(CAP + 1 - JPEG.length)])] }));
    assert.equal(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), null);
    assert.ok(s.made[0].aborted);
  });

  // A dropped error handler leaves the request open for ever: the limit makes that a failure, not a hang.
  test(`${platform}: a network error on the picture request gives null and the backend an empty body`, { timeout: 5000 }, async (t) => {
    const b = await backend((req, resp) => resp.end(req.method === "GET" ? JSON.stringify({ url: "https://cdn.example/x.jpg" }) : "{}"));
    t.after(() => { b.srv.closeAllConnections(); b.srv.close(); });
    const failing = (req, step) => { if (step === "sent") req.emit("error", new Error("net::ERR_CONNECTION_RESET")); };
    const s = shell(platform, failing);
    assert.equal(await s.api.fetchThumbnail("https://cdn.example/x.jpg"), null);
    const s2 = shell(platform, failing, { appUrl: b.url });
    await s2.api.deliverThumbnail(ENTRY);
    assert.deepEqual(b.calls.map((c) => `${c.method} ${c.body.length}`), ["GET 0", "POST 0"]);
  });

  test(`${platform}: the shell's call to the backend gives up after the timeout`, async (t) => {
    const b = await backend(() => {});                       // never answers
    t.after(() => { b.srv.closeAllConnections(); b.srv.close(); });
    const asked = [];
    const httpModule = { ...http, request: (...a) => {
      const req = http.request(...a);
      const set = req.setTimeout.bind(req);
      req.setTimeout = (ms, cb) => { asked.push(ms); return set(50, cb); };
      return req;
    } };
    const s = shell(platform, answer(), { appUrl: b.url, httpModule });
    const done = await Promise.race([s.api.deliverThumbnail(ENTRY).then(() => "done"),
                                     new Promise((r) => setTimeout(() => r("still waiting"), 3000))]);
    assert.equal(done, "done", "the call to a backend that does not answer was never given up");
    assert.deepEqual(asked, [15000]);
    assert.equal(s.made.length, 0, "nothing is fetched without the backend's answer");
  });
}

test("the three shells carry the same thumbnail block", () => {
  const [w, m, l] = ["windows", "mac", "linux"].map((p) => /\n\/\/ ── History thumbnails[\s\S]*?\nfunction noticeThumbnail\(details\) \{[\s\S]*?\n\}\n/.exec(source(p))[0]);
  assert.equal(m, w);
  assert.equal(l, w);
});
