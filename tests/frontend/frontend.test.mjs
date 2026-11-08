// EGM frontend regression tests (node --test + jsdom).
// Boots the real rendered page with mocked fetch; each test exercises a flow
// that previously regressed or nearly regressed during development.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en, CURRENT_APP_VERSION } from "./harness.mjs";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

test("i18n boot applies English strings to the live DOM", async () => {
  const { d } = await bootPage();
  const label = d.querySelector('[data-i18n="settings.toggle.upscale"]');
  assert.ok(label, "upscale toggle label present");
  assert.equal(label.textContent.trim(), en.strings["settings.toggle.upscale"]);
});

// The page direction follows the language: right to left for Arabic, left to right for
// every other language, and back again on the next switch. Expected directions come from
// the language files; tests/test_language_direction.py ties those to I18N_RTL.
test("i18nLoad sets dir: rtl for Arabic, ltr for every other language, both ways", async () => {
  const langDir = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "languages");
  const files = Object.fromEntries(readdirSync(langDir).filter((f) => f.endsWith(".json"))
    .map((f) => [f.slice(0, -5), JSON.parse(readFileSync(join(langDir, f), "utf8"))]));
  const { w, d } = await bootPage({
    onFetch: (u) => { const m = /^\/api\/language\/([a-z]{2})$/.exec(u); return m && files[m[1]] ? { ok: true, json: async () => files[m[1]] } : null; },
  });
  const html = d.documentElement;
  assert.equal(html.getAttribute("dir"), "ltr", "English boot is left to right");
  const codes = Object.keys(files);
  assert.equal(codes.length, 10);
  for (const code of ["ar", ...codes.filter((c) => c !== "ar"), "ar", "en"]) {
    await w.i18nLoad(code);
    assert.equal(html.getAttribute("lang"), code);
    assert.equal(html.getAttribute("dir"), code === "ar" ? "rtl" : "ltr", `dir after i18nLoad('${code}')`);
    assert.equal(html.getAttribute("dir"), files[code]._direction, `${code}.json declares the direction the page gets`);
  }
  await w.i18nLoad("ar");
  await w.i18nLoad("xx");   // not allowlisted: English, left to right
  assert.equal(html.getAttribute("lang"), "en");
  assert.equal(html.getAttribute("dir"), "ltr");
});

test("card render: HDR entries appear beneath SDR with tooltip; SDR untouched", async () => {
  const { w, d } = await bootPage();
  const item = {
    id: 1, url: "u", jobId: null, status: "idle", selFmt: "video", selFmtId: "",
    info: {
      title: "T", duration: 60, thumbnail: "", width: 3840, height: 2160,
      formats: [
        { id: "315", label: "2160p", height: 2160, has_audio: false, acodec: "" },
        { id: "701", label: "2160p", height: 2160, hdr: true, has_audio: false, acodec: "" },
        { id: "137", label: "1080p", height: 1080, has_audio: false, acodec: "" },
      ],
      audio_formats: [],
    },
  };
  const el = d.createElement("div"); el.className = "vcard"; d.body.appendChild(el);
  w.renderCard(el, item);
  const opts = [...el.querySelectorAll("select.qsel option")].map(o => ({ v: o.value, t: o.textContent.trim(), tip: o.title || "" }));
  const hdr = opts.find(o => o.v === "701");
  const sdr = opts.find(o => o.v === "315");
  assert.ok(hdr && hdr.t.includes("HDR"), "HDR option labeled");
  assert.ok(hdr.tip.includes("MKV"), "HDR tooltip mentions MKV output");
  assert.ok(sdr && !sdr.t.includes("HDR"), "SDR sibling unlabeled");
  assert.ok(!opts.find(o => o.v === "137").t.includes("HDR"), "plain height untouched");
});

test("naming-modal extension: HDR selection pills .mkv, SDR follows global", async () => {
  const { d } = await bootPage();
  const formats = [
    { id: "315", label: "2160p", height: 2160 },
    { id: "701", label: "2160p", height: 2160, hdr: true },
  ];
  const extFor = (selFmtId) => {
    const selHdr = !!(formats.find(f => f.id === selFmtId) || {}).hdr;
    const vfmt = d.getElementById("output-format-sel")?.value || "mp4";
    return (selHdr || vfmt === "mkv") ? ".mkv" : ".mp4";
  };
  assert.equal(extFor("701"), ".mkv");
  assert.equal(extFor("315"), ".mp4");
});

test("hide-settings flow: confirm modal, cancel keeps, confirm hides and saves", async () => {
  const { w, d, saved } = await bootPage();
  const chk = d.getElementById("show-settings-panel-chk");
  const wrap = d.getElementById("settings-panel-wrap");
  assert.ok(chk && wrap, "toggle + panel present");
  assert.notEqual(wrap.style.display, "none", "panel visible initially");

  chk.checked = false; chk.dispatchEvent(new w.Event("change"));
  assert.equal(d.getElementById("hide-settings-modal").style.display, "flex", "modal shown");
  assert.equal(chk.checked, true, "checkbox reverted until confirmed");

  d.getElementById("hide-settings-cancel-btn").click();
  assert.notEqual(wrap.style.display, "none", "cancel keeps panel");

  chk.checked = false; chk.dispatchEvent(new w.Event("change"));
  d.getElementById("hide-settings-confirm-btn").click();
  assert.equal(wrap.style.display, "none", "confirm hides panel");
  assert.deepEqual(saved.filter(s => "show_settings_panel" in s), [{ show_settings_panel: false }], "persisted");
});

test("persisted hidden settings panel stays hidden on boot", async () => {
  const { d } = await bootPage({ settings: { show_settings_panel: false } });
  assert.equal(d.getElementById("settings-panel-wrap").style.display, "none");
  assert.equal(d.getElementById("show-settings-panel-chk").checked, false);
});

test("converting badge: encoder + percentage when present, indeterminate otherwise", async () => {
  const { w, d } = await bootPage();
  const stEl = d.createElement("span");
  const progEl = d.createElement("div");
  progEl.innerHTML = '<div class="prog-inner"></div>';
  w.applyJobProgress({ status: "converting", encoder: "h264_nvenc", progress: 47.3 }, stEl, progEl);
  assert.ok(stEl.textContent.includes("h264_nvenc"), "encoder shown");
  assert.ok(stEl.textContent.includes("47%"), "percentage shown");
  assert.equal(progEl.querySelector(".prog-inner").style.width, "47%", "bar determinate");
  w.applyJobProgress({ status: "converting", encoder: "libx264" }, stEl, progEl);
  assert.ok(progEl.querySelector(".prog-inner").classList.contains("indeterminate"), "merge phase indeterminate");
});

test("queue arrows: edges hidden, middle visible, and removeItem recomputes edges", async () => {
  const { w, d } = await bootPage();
  const results = d.getElementById("results");
  assert.ok(results, "results container present");

  // Three idle cards, matching the real markup shape (.vcard > [id^=qarrows] > .qarrow x2)
  const mkCard = (n) => {
    const el = d.createElement("div");
    el.className = "vcard";
    el.id = "card" + n;
    el.innerHTML = `
      <span id="st${n}"></span>
      <div id="qarrows${n}">
        <button class="qarrow" data-dir="up" data-id="${n}"></button>
        <button class="qarrow" data-dir="down" data-id="${n}"></button>
      </div>`;
    results.appendChild(el);
    return el;
  };
  const els = [1, 2, 3].map(mkCard);

  // Seed items[] (script-scope `let`, not a window property -- eval runs in
  // the same script realm as the page's own inline scripts) and call the
  // real updateQueueArrows()/removeItem() rather than reimplementing the
  // visibility logic in the test.
  w.eval(`items = [1,2,3].map(n => ({ id: n, status: 'idle' })); updateQueueArrows();`);

  const vis = (n, dir) => els[n - 1].querySelector(`.qarrow[data-dir="${dir}"]`).style.visibility;
  assert.equal(vis(1, "up"), "hidden", "first card: up hidden");
  assert.equal(vis(1, "down"), "visible", "first card: down visible");
  assert.equal(vis(2, "up"), "visible", "middle card: up visible");
  assert.equal(vis(2, "down"), "visible", "middle card: down visible");
  assert.equal(vis(3, "up"), "visible", "last card: up visible");
  assert.equal(vis(3, "down"), "hidden", "last card: down hidden");

  // Remove the first card -- the new first (card 2) must gain a hidden up
  // arrow. This exercises the real removeItem() -> updateQueueArrows() call
  // added by this fix, not a hand-rolled recomputation.
  w.eval(`removeItem(1, document.getElementById("card1"))`);
  assert.equal(vis(2, "up"), "hidden", "after removal, new first card: up hidden");
  assert.equal(vis(2, "down"), "visible", "after removal, new first card: down visible");
  assert.equal(vis(3, "up"), "visible", "after removal, remaining last card: up visible");
  assert.equal(vis(3, "down"), "hidden", "after removal, remaining last card: down hidden");
});

test("queue arrows: a status transition hides the card's own arrows and re-edges the rest", async () => {
  const { w, d } = await bootPage();
  const results = d.getElementById("results");
  const mkCard = (n) => {
    const el = d.createElement("div");
    el.className = "vcard";
    el.id = "tcard" + n;
    el.innerHTML = `
      <span id="st${n}"></span>
      <div id="qarrows${n}">
        <button class="qarrow" data-dir="up" data-id="${n}"></button>
        <button class="qarrow" data-dir="down" data-id="${n}"></button>
      </div>`;
    results.appendChild(el);
    return el;
  };
  const els = [1, 2, 3].map(mkCard);
  w.eval(`items = [1,2,3].map(n => ({ id: n, status: 'idle' })); updateQueueArrows();`);
  const vis = (n, dir) => els[n - 1].querySelector(`.qarrow[data-dir="${dir}"]`).style.visibility;
  assert.equal(vis(1, "down"), "visible", "sanity: first card starts with down visible");

  // Card 1 starts downloading: its own arrows must hide (the click handler
  // already no-ops non-idle cards -- the UI must match), and card 2 becomes
  // the first idle card, so its up arrow must hide too.
  w.eval(`items[0].status = 'downloading'; updateQueueArrows();`);
  assert.equal(vis(1, "up"), "hidden", "downloading card: up hidden");
  assert.equal(vis(1, "down"), "hidden", "downloading card: down hidden");
  assert.equal(vis(2, "up"), "hidden", "new first idle card: up hidden");
  assert.equal(vis(2, "down"), "visible", "new first idle card: down visible");
  assert.equal(vis(3, "up"), "visible", "last idle card: up visible");
  assert.equal(vis(3, "down"), "hidden", "last idle card: down hidden");

  // Cancelled cards never return to idle -- arrows stay hidden.
  w.eval(`items[0].status = 'cancelled'; updateQueueArrows();`);
  assert.equal(vis(1, "up"), "hidden", "cancelled card: up stays hidden");
  assert.equal(vis(1, "down"), "hidden", "cancelled card: down stays hidden");
});

test("shell activity: cancel drains the report (bar/badge/sleep blocker released)", async () => {
  const { w } = await bootPage();
  // Inject a capturing electronAPI the way the preload would have -- the
  // reportActivity guard (window.electronAPI?.setActivity) then engages.
  w._activityCalls = [];
  w.eval(`window.electronAPI = { setActivity: (a) => window._activityCalls.push(a) };`);

  // One active download reports active:1 with its progress.
  w.eval(`items = [{ id: 1, status: 'downloading', _lastProgress: 40 }]; _lastActivityKey = ''; reportActivity();`);
  let last = w._activityCalls[w._activityCalls.length - 1];
  assert.equal(last.active, 1, "downloading item reports active:1");
  assert.ok(Math.abs(last.progress - 0.4) < 1e-9, "progress averaged to 0.4");

  // Cancelling the last active job must DRAIN the report -- this exercises
  // the real applyJobDone cancelled branch. Without its reportActivity()
  // call, the taskbar bar/badge freeze at the last state and the
  // powerSaveBlocker stays held until the app quits.
  w.eval(`applyJobDone({ status: 'cancelled' }, items[0], null, null, null, null);`);
  last = w._activityCalls[w._activityCalls.length - 1];
  assert.equal(last.active, 0, "cancelled last job drains active to 0");
  assert.equal(last.progress, -1, "drained report clears the progress bar");
});

test("playlist-path fetch errors render a localized error card, not a stuck stub", async () => {
  const { w, d } = await bootPage({
    onFetch: (u) => {
      if (u === "/api/info") return { ok: true, json: async () => ({
        error: "ERROR: [youtube] abc: Video unavailable",
        error_key: "download.error.unavailable",
      }) };
      return null;
    },
  });
  const results = d.getElementById("results");
  // Drive the real per-entry flow with one stub entry -- the path every real
  // fetch takes (single URLs come back as one-entry playlists). Before the
  // fix, an /api/info error left the stub card spinning forever with no
  // error shown at all.
  w.eval(`fetchAbort = false; items = []; fetchPlaylistEntries([{ url: 'https://example.com/watch?v=1', title: 'T' }], { count: 0 }, () => {});`);
  await new Promise((r) => setTimeout(r, 150));
  const badge = results.querySelector(".b-error");
  assert.ok(badge, "error card rendered on the playlist path");
  assert.ok(
    badge.textContent.includes(en.strings["download.error.unavailable"]),
    `error resolved in the active locale, got: ${badge && badge.textContent}`,
  );
  assert.equal(w.eval("items.length"), 0, "failed entry removed from items[] (error-card convention)");
});

// ── What's New modal: behavioural cover for the two bugs fixed in 5d19073 ─────
// tests/test_whats_new_button.py guards these at the source-text level (that
// split('{0}') is written, that the listener call carries no {once: true}).
// Those assertions are satisfied by the SHAPE of the code, so an edit that
// keeps the shape and breaks the behaviour passes them -- verified by mutation:
// assigning '' to whats-new-title-after, or moving the dismiss listener back
// inside showWhatsNewModal, both leave the Python guards fully green. These two
// drive the real DOM instead, so they fail on the effect rather than the syntax.

test("whats-new heading honours locale word order, not just English's", async () => {
  const ja = JSON.parse(
    readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "languages", "ja.json"), "utf8"),
  );
  const { w, d } = await bootPage({
    settings: { language: "ja", last_seen_version: CURRENT_APP_VERSION },   // suppress the auto-show
    onFetch: (u) => (u === "/api/language/ja" ? { ok: true, json: async () => ja } : null),
  });

  w.eval("showWhatsNewModal('1.4.0')");
  await new Promise((r) => setTimeout(r, 100));

  // Japanese places the version FIRST ("{0}の新機能"), so a fix that only
  // rendered the segment before the placeholder -- or appended the version to
  // a flattened prefix -- drops "の新機能" or emits it in the wrong order.
  const heading = d.getElementById("whats-new-heading").textContent.replace(/\s+/g, " ").trim();
  const expected = ja.strings["whatsnew.title"].replace("{0}", "1.4.0").replace(/\s+/g, " ").trim();
  assert.equal(heading, expected, "heading must match the ja template with {0} substituted in place");
  assert.ok(heading.endsWith("の新機能"), `version must precede the suffix in ja, got: ${heading}`);
});

test("whats-new dismiss stays live across repeated manual opens", async () => {
  const { w, d, saved } = await bootPage({
    // Mark the running version seen so the automatic once-per-version path does
    // not fire -- this test is about the manual footer trigger in isolation.
    settings: { last_seen_version: CURRENT_APP_VERSION },
  });
  const modal = d.getElementById("whats-new-modal");
  const openBtn = d.getElementById("footer-version-pill");
  const dismissBtn = d.getElementById("whats-new-dismiss-btn");
  assert.equal(modal.style.display, "none", "modal starts hidden (version already seen)");

  const savesBefore = saved.length;
  for (const pass of [1, 2, 3]) {
    openBtn.click();
    await new Promise((r) => setTimeout(r, 60));
    assert.equal(modal.style.display, "flex", `manual open #${pass} shows the modal`);
    dismissBtn.click();
    await new Promise((r) => setTimeout(r, 60));
    // A {once: true} listener is consumed by the first dismiss, leaving every
    // later "Got it" dead and the modal stuck open.
    assert.equal(modal.style.display, "none", `dismiss #${pass} still closes the modal`);
  }

  // Exactly one save per dismiss: attaching the listener inside the show
  // function instead of once at load would stack a fresh listener per open,
  // firing 1+2+3 saves instead of 3.
  assert.equal(saved.length - savesBefore, 3, `expected one settings save per dismiss, got ${saved.length - savesBefore}`);
  assert.equal(saved[saved.length - 1].last_seen_version, CURRENT_APP_VERSION, "dismiss records the running version");
});

// ── Update and plugin results: a failed check or install is never shown as success ─────────────
const _json = (body) => ({ ok: true, json: async () => body, text: async () => JSON.stringify(body) });
const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const _toasts = (d) => [...d.querySelectorAll("#toasts .toast")].map((t) => t.textContent);

test("plugins update: a run that stopped on a failed checksum shows the error, not 'Update complete'", async () => {
  const { d } = await bootPage({ onFetch(u) {
    if (u === "/api/run-update") return _json({ started: true });
    if (u === "/api/update-status") return _json({ running: false, done: true, error: "Checksum mismatch — update aborted", log: [] });
  } });
  d.getElementById("run-update-btn").click();
  await _sleep(1300);
  const t = _toasts(d);
  assert.ok(t.some((x) => x.includes("Checksum mismatch")), t);
  assert.ok(!t.some((x) => x.includes(en.strings["toast.plugins.update_complete"])), t);
});

test("plugins update: a Deno reinstall that failed is reported, not folded into 'Update complete'", async () => {
  const { d } = await bootPage({ onFetch(u) {
    if (u === "/api/deno/reinstall") return _json({ started: true });
    if (u === "/api/deno/install-status") return _json({ running: false, done: false, error: "network down", log: ["Error: network down"] });
  } });
  d.getElementById("update-grid").innerHTML =
    '<input type="checkbox" id="sw-ytdlp"><input type="checkbox" id="sw-deno" checked>';
  d.getElementById("run-update-btn").click();
  await _sleep(1300);
  const t = _toasts(d);
  assert.ok(t.some((x) => x.includes(en.strings["toast.settings.deno_install_failed"]) && x.includes("network down")), t);
  assert.ok(!t.some((x) => x.includes(en.strings["toast.plugins.update_complete"])), t);
});

test("Deno install: a failed checksum shows the failure, not 'Deno installed'", async () => {
  const { w, d } = await bootPage({ onFetch(u) {
    if (u === "/api/deno/install") return _json({ started: true });
    if (u === "/api/deno/install-status") return _json({ running: false, done: true, error: "Checksum mismatch — install aborted", log: [] });
  } });
  const btn = d.createElement("button");
  btn.id = "install-deno-btn";
  d.body.appendChild(btn);
  await w.installDeno();
  await _sleep(1000);
  const t = _toasts(d);
  assert.ok(t.some((x) => x.includes(en.strings["toast.settings.deno_install_failed"])), t);
  assert.ok(!t.some((x) => x.includes(en.strings["toast.settings.deno_installed_signature"])), t);
});

// The page installs Deno silently when it is missing. When that finishes it used to run the full plugin update
// check (GitHub for yt-dlp and ffmpeg, PyPI for the libraries) and the latest Deno lookup with nobody having
// clicked anything. Only a Plugins panel that is open is refreshed.
async function _firstLaunchDenoInstall(settings) {
  const asked = [];
  const { w } = await bootPage({ settings, onFetch(u) {
    asked.push(u);
    if (u === "/api/deno/status") return _json({ installed: false });
    if (u === "/api/deno/install") return _json({ started: true });
    if (u === "/api/deno/install-status") return _json({ running: false, done: true });
  } });
  await _sleep(2300);   // the page polls the install every 1.5 s
  w.close();
  return asked;
}

test("first launch Deno install: with the Plugins panel closed, no update check follows", async () => {
  const asked = await _firstLaunchDenoInstall({});
  assert.ok(asked.includes("/api/deno/install-status"), `the install never reached its end, so this checks nothing: ${asked}`);
  assert.ok(!asked.includes("/api/check-updates"), asked);
  assert.ok(!asked.includes("/api/deno/status?latest=1"), asked);
});

test("first launch Deno install: with the Plugins panel open, the grid is refreshed", async () => {
  const asked = await _firstLaunchDenoInstall({ upd_open: true });
  assert.ok(asked.includes("/api/deno/install-status"), `the install never reached its end, so this checks nothing: ${asked}`);
  assert.ok(asked.includes("/api/check-updates"), asked);
  assert.ok(asked.includes("/api/deno/status?latest=1"), asked);
});

test("footer update check follows the backend's build decision, not the version text", async () => {
  const cases = [
    // [feed answer, expect the update dialog]
    [{ up_to_date: true, current_version: "1.5.2.1", current_build: 175, latest_version: "1.5.3", latest_build: 170 }, false],
    [{ up_to_date: false, current_version: "1.5.3", current_build: 175, latest_version: "1.5.2.9", latest_build: 176 }, true],
    [{ up_to_date: false, current_version: "1.5.2.1", current_build: 175, latest_version: "1.5.2.1", latest_build: 176 }, true],
    [{ up_to_date: true, current_version: "1.5.2.1", current_build: 175, latest_version: "1.5.2.1", latest_build: 175 }, false],
  ];
  for (const [answer, offered] of cases) {
    const { w, d } = await bootPage({ onFetch(u) { if (u === "/api/check-app-update") return _json(answer); } });
    d.getElementById("footer-update-btn").click();
    await _sleep(100);
    assert.equal(!!d.querySelector(".upd-backdrop"), offered, JSON.stringify(answer));
    w.close();
  }
});

// ── History entries and stored theme names come from imported files: shown as text, never run ──
import { JSDOM as _JSDOM } from "jsdom";
const _hjson = (body) => ({ ok: true, json: async () => body, text: async () => JSON.stringify(body) });
const _HOSTILE = {
  id: "h1", title: "ok", url: "https://example.invalid/v", completed_at: new Date().toISOString(),
  thumbnail: 'x"><img id="pwn-thumb" src="y" onerror="window.__pwn=1">',
  format: '<img id="pwn-fmt" src="y" onerror="window.__pwn=1">',
  size_bytes: '<b id="pwn-size">x</b>',
};
function _bootHistory({ items, theme } = {}) {
  const main = process.env.EGM_RENDERED_PAGE || "/tmp/egm_rendered_index.html";
  const html = readFileSync(main.replace(/(\.[^./]+)?$/, "_history$1"), "utf8");
  const dom = new _JSDOM(html, { runScripts: "dangerously", url: "http://localhost/history-page",
    beforeParse(w) {
      if (theme) w.localStorage.setItem("egm-theme", theme);
      w.fetch = async (u) => {
        if (u === "/api/settings") return _hjson({ language: "en" });
        if (u === "/api/language/en") return _hjson(en);
        if (u.startsWith("/api/history")) return _hjson({ items, total: items.length, page: 1, pages: 1, per_page: 500 });
        return _hjson({});
      };
    } });
  return new Promise((r) => setTimeout(() => r(dom), 600));
}

test("history panel: an imported thumbnail, format and size are shown as text, never as markup", async () => {
  const { w, d } = await bootPage({ onFetch(u) {
    if (u.startsWith("/api/history?")) return _hjson({ items: [_HOSTILE, { id: "n", title: "t", format: 5, size_bytes: "x" }], total: 2, page: 1, pages: 1, per_page: 5 });
  } });
  await w.loadHistoryPanel();
  for (const id of ["pwn-thumb", "pwn-fmt", "PWN-FMT", "pwn-size"]) assert.equal(d.getElementById(id), null, id);
  const img = d.querySelector("img.hthumb");
  if (img) img.dispatchEvent(new w.Event("error"));
  assert.equal(w.__pwn, undefined);
  assert.equal(d.querySelectorAll(".hentry").length, 2, "both entries render, the one with a number as its format too");
  w.close();
});

test("History window: an imported thumbnail, format and size are shown as text, never as markup", async () => {
  const dom = await _bootHistory({ items: [_HOSTILE, { id: "n", title: "t", format: 5, size_bytes: "x" }] });
  const d = dom.window.document;
  for (const id of ["pwn-thumb", "pwn-fmt", "PWN-FMT", "pwn-size"]) assert.equal(d.getElementById(id), null, id);
  assert.equal(d.querySelectorAll(".row").length >= 2, true, "both entries render");
  assert.equal(dom.window.__pwn, undefined);
  dom.window.close();
});

test("a stored theme name that is not a theme key does not stop the main window or the History window", async () => {
  const { w, d } = await bootPage({ prep(w) { w.localStorage.setItem("egm-theme", "bad theme"); } });
  assert.equal(typeof w.openThemeCreator, "function", "the scripts after the theme module still ran");
  assert.ok(d.querySelectorAll("#theme-list .theme-row").length > 0, "the theme picker was drawn");
  let asked = false;
  w.confirm = () => { asked = true; return false; };
  d.getElementById("adv-reset-btn").click();
  assert.equal(asked, true, "Reset settings still works");
  w.close();
  const dom = await _bootHistory({ items: [{ id: "a", title: "kept", format: "mp4" }], theme: "bad theme" });
  assert.equal(dom.window.document.querySelectorAll(".row").length, 1);
  dom.window.close();
});
