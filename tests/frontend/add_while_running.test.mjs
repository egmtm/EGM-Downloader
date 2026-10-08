// Main window: adding videos while others are fetched or downloading.
// Fetch only adds (a link already in the list is skipped), Clear never removes a running
// download, and a second Download all hands its new cards to the run that is going.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en } from "./harness.mjs";

const settle = (ms = 80) => new Promise((r) => setTimeout(r, ms));
const windows = [];
after(() => windows.forEach((w) => w.close()));   // stops the page timers, or the test process never exits
const A = "https://e.com/a", B = "https://e.com/b", C = "https://e.com/c", D = "https://e.com/d", E = "https://e.com/e";

async function boot({ quit = false } = {}) {
  const log = { playlist: [], download: [], bodies: [], cancel: [], quit: [], activity: [] };
  const jobs = {};   // jobId -> status served by /api/status/<id>
  const ctl = { fail: new Set(), hang: new Set(), entries: {}, holdInfo: false, held: [], holdDownload: false, heldDl: [], confirms: [], answer: true, maxRunning: 0 };
  let jobSeq = 0;
  const json = (o) => ({ ok: true, json: async () => o });
  const t = await bootPage({
    onFetch: (u, o) => {
      const body = o && o.body ? JSON.parse(o.body) : {};
      if (u === "/api/playlist") {
        log.playlist.push(body.url);
        if (ctl.hang.has(body.url)) return new Promise(() => {});
        if (ctl.fail.has(body.url)) return json({ error: "boom" });
        return json({ is_playlist: true, entries: ctl.entries[body.url] || [{ url: body.url, title: "T " + body.url }] });
      }
      if (u === "/api/info") {
        const info = { title: "T " + body.url, uploader: "U", thumbnail: "", duration: 10, formats: [{ id: "f1", label: "720p", height: 720 }], audio_formats: [] };
        return ctl.holdInfo ? new Promise((res) => ctl.held.push(() => res(json(info)))) : json(info);
      }
      if (u === "/api/download") {
        const id = "j" + ++jobSeq;
        log.download.push(body.url); log.bodies.push(body);
        const start = () => {
          jobs[id] = { status: "downloading", progress: 10 };
          ctl.maxRunning = Math.max(ctl.maxRunning, Object.values(jobs).filter((j) => j.status === "downloading").length);
          return json({ job_id: id });
        };
        return ctl.holdDownload ? new Promise((res) => ctl.heldDl.push(() => res(start()))) : start();
      }
      if (typeof u === "string" && u.startsWith("/api/status/")) return json(jobs[u.slice(12)] || { status: "downloading", progress: 10 });
      if (typeof u === "string" && u.startsWith("/api/cancel/")) { log.cancel.push(u); return json({ success: true }); }
    },
    prep(w) {
      w.confirm = (msg) => { ctl.confirms.push(msg); return ctl.answer; };
      if (quit) {
        w.electronAPI = {
          platform: "win",
          quit: async (opts) => { log.quit.push({ ...opts }); return opts && opts.probe ? { busy: false } : { success: true }; },
          closeSubscriptions: async () => {},
          setActivity: (a) => log.activity.push({ ...a }),
          setLanguage() {}, setTheme() {},
        };
      }
    },
  });
  const { w, d } = t;
  windows.push(w);
  // The pollers the test starts are driven by hand, not by the clock.
  const timers = new Map(); let nextTimer = 9000;
  w.setInterval = (fn) => { const id = nextTimer++; timers.set(id, fn); return id; };
  const realClear = w.clearInterval.bind(w);
  w.clearInterval = (id) => { if (!timers.delete(id)) realClear(id); };
  w.eval("chosenPath = '/tmp/dl'");
  w.eval("document.getElementById('concurrency-sel').value = '2'");
  if (quit) d.getElementById("quit-on-done-chk").checked = true;
  const ev = (code) => JSON.parse(w.eval(`JSON.stringify(${code})`));
  return {
    ...t, log, ctl, jobs, ev,
    fetchLinks: async (text) => { d.getElementById("urls").value = text; d.getElementById("fetch-btn").click(); await settle(); },
    card: (n) => d.getElementById("st" + n)?.closest(".vcard") || null,
    cards: () => d.querySelectorAll("#results .vcard").length,
    toasts: () => [...d.querySelectorAll("#toasts .toast")].map((x) => x.textContent),
    clearToasts: () => { d.getElementById("toasts").innerHTML = ""; },
    all: (fmt = "video", aq = null, vq = null) => w.eval(`downloadAll(${JSON.stringify(fmt)}, ${JSON.stringify(aq)}, ${JSON.stringify(vq)})`),
    finish: (id) => { jobs[id] = { status: "done", progress: 100, filename: id + ".mp4" }; },
    tick: async () => { for (const fn of [...timers.values()]) await fn(); await settle(300); },
    clear: () => d.getElementById("clear-btn").click(),
  };
}

// ── Fetch only adds ─────────────────────────────────────────────────────────

test("Fetch adds to the list: earlier cards and a running download stay, only the new link is fetched", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  const cardA = t.card(0);
  assert.ok(cardA);
  t.all(); await settle();
  assert.equal(t.ev("items[0].status"), "downloading");
  await t.fetchLinks(`${A}\n${B}`);
  assert.deepEqual(t.ev("items.map(i => i.url)"), [A, B]);
  assert.equal(t.card(0), cardA, "the first card is the same element, not rebuilt");
  assert.equal(t.ev("items[0].status"), "downloading");
  assert.ok(t.d.getElementById("cancel0"), "its Cancel button is still there");
  assert.deepEqual(t.log.playlist, [A, B], "the link already in the list is not fetched again");
});

test("a link that is already in the list is skipped, and the user is told when nothing new came", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.clearToasts();
  await t.fetchLinks(A);
  assert.equal(t.ev("items.length"), 1);
  assert.equal(t.cards(), 1);
  assert.deepEqual(t.log.playlist, [A]);
  assert.ok(t.toasts().includes(en.strings["toast.already_in_list"]));
});

test("a link that resolves to a video already in the list adds no second card", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.clearToasts();
  t.ctl.entries["https://short.example/x"] = [{ url: A, title: "same video" }];
  await t.fetchLinks("https://short.example/x");
  assert.equal(t.ev("items.length"), 1);
  assert.equal(t.cards(), 1, "the loading card of the typed link is gone too");
  assert.ok(t.toasts().includes(en.strings["toast.already_in_list"]));
});

test("a link that failed gets one error card, replaced when it is tried again", async () => {
  const t = await boot();
  t.ctl.fail.add(C);
  await t.fetchLinks(C);
  assert.equal(t.d.querySelectorAll("#results .vcard.fetch-err").length, 1);
  await t.fetchLinks(C);
  assert.equal(t.d.querySelectorAll("#results .vcard.fetch-err").length, 1, "not two");
  t.ctl.fail.delete(C);
  await t.fetchLinks(C);
  assert.equal(t.d.querySelectorAll("#results .vcard.fetch-err").length, 0);
  assert.deepEqual(t.ev("items.map(i => i.url)"), [C]);
});

test("Cancel fetch counts only what this fetch loaded, not the cards already in the list", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.ctl.hang.add(C);
  await t.fetchLinks(`${A}\n${B}\n${C}`);   // B loads, C never answers
  assert.equal(t.ev("items.length"), 2);
  t.clearToasts();
  t.d.getElementById("cancel-fetch-btn").click();
  assert.deepEqual(t.toasts(), [en.strings["toast.stopped_keeping_one"].replace("{0}", "1")]);
});

// ── Clear ───────────────────────────────────────────────────────────────────

async function threeCards(t) {
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.w.eval("items[0].status = 'downloading'; items[1].status = 'error'");   // C stays idle
  t.ctl.fail.add(D);
  await t.fetchLinks(`${A}\n${B}\n${C}\n${D}`);   // an error card as well
}

test("Clear with a download running asks first, then removes only the cards that are not downloading", async () => {
  const t = await boot();
  await threeCards(t);
  const running = t.card(0);
  assert.equal(t.cards(), 4);
  t.clear();
  assert.equal(t.ctl.confirms.length, 1);
  assert.equal(t.ctl.confirms[0], en.strings["confirm.clear_keep_active"].replace("{0}", "2").replace("{1}", "1"));
  assert.deepEqual(t.ev("items.map(i => i.url)"), [A]);
  assert.equal(t.cards(), 1);
  assert.equal(t.card(0), running, "the running card is untouched");
  assert.equal(t.d.getElementById("urls").value, "");
});

test("answering No to the Clear question changes nothing", async () => {
  const t = await boot();
  await threeCards(t);
  t.ctl.answer = false;
  t.clear();
  assert.equal(t.ctl.confirms.length, 1);
  assert.equal(t.ev("items.length"), 3);
  assert.equal(t.cards(), 4);
  assert.notEqual(t.d.getElementById("urls").value, "");
});

test("Clear with nothing running works as before: no question, everything goes", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}`);
  t.clear();
  assert.equal(t.ctl.confirms.length, 0);
  assert.equal(t.ev("items.length"), 0);
  assert.equal(t.cards(), 0);
  assert.equal(t.d.getElementById("urls").value, "");
});

test("Clear when every card is running has nothing to remove: no question, the downloads stay", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.all(); await settle();
  t.clear();
  assert.equal(t.ctl.confirms.length, 0);
  assert.equal(t.ev("items.length"), 1);
  assert.equal(t.cards(), 1);
  assert.equal(t.d.getElementById("urls").value, "");
});

test("after Clear a running download still counts: Quit when done stays disarmed and the activity report keeps it", async () => {
  const t = await boot({ quit: true });
  await t.fetchLinks(`${A}\n${B}`);
  t.all("video"); await settle();   // both start
  await t.fetchLinks(`${A}\n${B}\n${C}`);   // C is new and idle
  t.clear();
  assert.equal(t.ev("items.length"), 2);
  assert.equal(t.w.eval("_qodArmed()"), false, "a download is still running");
  t.w.eval("_lastActivityKey = ''; reportActivity()");
  assert.equal(t.log.activity.at(-1).active, 2);
});

// ── Download all joins the run that is going ────────────────────────────────

test("a second Download all feeds the running run: one concurrency limit, each card keeps its own choices", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.all("video"); await settle();
  assert.deepEqual(t.log.download, [A, B], "limit 2: C waits");
  t.clearToasts();
  t.all("video"); await settle();
  assert.deepEqual(t.toasts(), [en.strings["toast.nothing_to_download"]], "C is already queued, nothing new");
  await t.fetchLinks(`${A}\n${B}\n${C}\n${D}\n${E}`);
  t.all("audio", "192", null); await settle();
  assert.deepEqual(t.log.download, [A, B], "joined the run, no extra downloads started");
  for (const [i, id] of ["j1", "j2", "j3", "j4", "j5"].entries()) {
    t.finish(id); await t.tick();
    assert.equal(t.log.download.length, Math.min(i + 3, 5), `one slot freed, one card started (after ${id})`);
  }
  assert.deepEqual(t.log.download, [A, B, C, D, E]);
  assert.equal(t.ctl.maxRunning, 2, "never more than the limit");
  assert.deepEqual(t.log.bodies.map((b) => b.format), ["video", "video", "video", "audio", "audio"]);
  assert.equal(t.log.bodies[3].audio_quality, "192");
  assert.equal(t.toasts().filter((x) => x.startsWith(en.strings["toast.done"])).length, 1, "one run, one Done");
});

test("a second Download all while the run's cards are still loading their info does not start them twice", async () => {
  const t = await boot();
  t.ctl.holdInfo = true;   // stub cards: the run fetches their info before it starts them
  await t.fetchLinks(`${A}\n${B}`);
  t.all(); await settle();   // both are taken by the run and waiting for their info
  t.clearToasts();
  t.all(); await settle();
  assert.deepEqual(t.toasts(), [en.strings["toast.nothing_to_download"]]);
  t.ctl.holdInfo = false;
  t.ctl.held.forEach((release) => release());
  await settle(200);
  assert.deepEqual(t.log.download, [A, B]);
});

test("a second Download all raises the total shown in the bar", async () => {
  const t = await boot();
  const bar = () => t.d.getElementById("bulk-txt").textContent;
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.all("video"); await settle();
  assert.match(bar(), /0 \/ 3 .*\(2 active\)/, "first run: three cards, two running");
  await t.fetchLinks(`${A}\n${B}\n${C}\n${D}\n${E}`);
  t.all("video"); await settle();
  assert.match(bar(), /0 \/ 5 .*\(2 active\)/, "the two added cards join the run, and the total follows");
  t.finish("j1"); await t.tick();
  assert.match(bar(), /1 \/ 5 .*\(2 active\)/, "one done, the next card started");
});

test("Cancel all stops the run but leaves cards that were added after it started idle", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.all(); await settle();   // A, B running, C queued
  await t.fetchLinks(`${A}\n${B}\n${C}\n${D}`);   // D added later
  t.w.eval("cancelBulk()");
  assert.deepEqual(t.ev("items.map(i => i.status)"), ["cancelled", "cancelled", "cancelled", "idle"]);
  assert.equal(t.log.cancel.length, 2);
});

test("a card cleared while its info loads for Download all is not downloaded", async () => {
  const t = await boot();
  t.ctl.holdInfo = true;   // the cards stay stubs: Download all must fetch their info first
  await t.fetchLinks(A);
  t.all(); await settle();
  t.clear();
  assert.equal(t.ev("items.length"), 0);
  t.ctl.holdInfo = false;
  t.ctl.held.forEach((release) => release());
  await settle();
  assert.deepEqual(t.log.download, []);
});

// ── Quit when done ──────────────────────────────────────────────────────────

test("Quit when done waits for a card added mid run, and goes ahead once that one is done too", async () => {
  const t = await boot({ quit: true });
  await t.fetchLinks(A);
  t.all(); await settle();
  await t.fetchLinks(`${A}\n${B}`);
  t.finish("j1"); await t.tick();
  assert.deepEqual(t.log.quit, [], "B is still waiting to be downloaded");
  t.all(); await settle();
  assert.deepEqual(t.log.download, [A, B]);
  t.finish("j2"); await t.tick();
  assert.deepEqual(t.log.quit, [{ whenIdle: true, probe: true }]);
});

// ── One download per card, and nothing left running behind the list ───────

test("a card queued in Download all and started from its own button is downloaded once", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.all(); await settle();                       // limit 2: A and B run, C waits in the run
  t.w.eval("showModal = async () => 'C name'");  // the name dialog answers at once
  t.d.getElementById("dl2").click(); await settle();
  assert.deepEqual(t.log.download, [A, B, C]);
  t.finish("j1"); await t.tick();                // a slot frees: the run must skip C
  assert.deepEqual(t.log.download, [A, B, C]);
});

test("a card the run starts while its own name dialog is open is not started a second time", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.all(); await settle();
  t.w.eval("showModal = () => new Promise((r) => { window._answer = r; })");
  t.d.getElementById("dl2").click(); await settle();   // dialog open for C
  t.finish("j1"); await t.tick();                // meanwhile the run starts C
  assert.deepEqual(t.log.download, [A, B, C]);
  t.w.eval("_answer('C name')"); await settle();
  assert.deepEqual(t.log.download, [A, B, C]);
});

test("Cancel all, then Download all before the old run has wound down, revives nothing and keeps the limit", async () => {
  const t = await boot();
  t.ctl.holdInfo = true;                         // A and B are taken by the run, loading their info
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.all(); await settle();
  t.w.eval("cancelBulk()");
  t.ctl.holdInfo = false;
  await t.fetchLinks(`${A}\n${B}\n${C}\n${D}`);
  t.all(); await settle();                       // a new run, for D only
  t.ctl.held.forEach((release) => release()); await settle(300);
  assert.deepEqual(t.log.download, [D]);
  assert.deepEqual(t.ev("items.map(i => i.status)"), ["cancelled", "cancelled", "cancelled", "downloading"]);
  assert.ok(t.d.getElementById("bulk-bar").classList.contains("show"), "the old run does not hide the new run's bar");
  assert.match(t.d.getElementById("bulk-txt").textContent, /\/ 1 /, "nor does it write its own count over the new run's text");
});

test("Cancel all while a start request is in flight cancels the job once it exists", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.ctl.holdDownload = true;
  t.all(); await settle();                       // POST /api/download sent, no job id yet
  t.w.eval("cancelBulk()");
  t.ctl.heldDl.forEach((release) => release()); await settle();
  assert.deepEqual(t.log.cancel, ["/api/cancel/j1"]);
});

test("a card's own Cancel while its start request is in flight cancels the job once it exists", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.w.eval("showModal = async () => 'A name'");
  t.ctl.holdDownload = true;
  t.d.getElementById("dl0").click(); await settle();
  t.d.getElementById("cancel0").click(); await settle();
  t.ctl.heldDl.forEach((release) => release()); await settle();
  assert.deepEqual(t.log.cancel, ["/api/cancel/j1"]);
  assert.equal(t.ev("items[0].status"), "cancelled");
});

test("removing a running card with its own X asks first, then cancels its download instead of leaving it running unseen", async () => {
  const t = await boot({ quit: true });
  await t.fetchLinks(`${A}\n${B}`);
  t.all(); await settle();
  t.card(0).querySelector(".vcard-remove").click();
  assert.deepEqual(t.ctl.confirms, [en.strings["confirm.remove_running"]]);
  assert.deepEqual(t.log.cancel, ["/api/cancel/j1"]);
  assert.equal(t.cards(), 1);
  assert.equal(t.log.activity.at(-1).active, 1, "only B is still reported, by the removal itself");
});

test("answering No to the question on a running card's X leaves the card and its download alone", async () => {
  const t = await boot({ quit: true });
  await t.fetchLinks(`${A}\n${B}`);
  t.all(); await settle();
  t.ctl.answer = false;
  const reports = t.log.activity.length;
  t.card(0).querySelector(".vcard-remove").click();
  assert.equal(t.ctl.confirms.length, 1);
  assert.deepEqual(t.log.cancel, []);
  assert.equal(t.cards(), 2);
  assert.deepEqual(t.ev("items.map(i => i.status)"), ["downloading", "downloading"]);
  assert.equal(t.log.activity.length, reports, "nothing new is reported");
  assert.equal(t.log.activity.at(-1).active, 2, "both are still reported");
});

test("Cancel on a card that is not downloading and has no job does nothing", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.w.eval("cancelDownload(items[0], 0)"); await settle();
  assert.deepEqual(t.log.cancel, []);
  assert.deepEqual(t.ev("items.map(i => i.status)"), ["idle"]);
});

test("removing a card that is not downloading asks nothing", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}`);
  t.card(0).querySelector(".vcard-remove").click();
  assert.deepEqual(t.ctl.confirms, []);
  assert.deepEqual(t.log.cancel, []);
  assert.deepEqual(t.ev("items.map(i => i.url)"), [B]);
});

// ── Reorder arrows ──────────────────────────────────────────────────────────

const domOrder = (t) => [...t.d.querySelectorAll("#results .vcard")].map((c) => c.querySelector('[id^="qarrows"]')?.id || "(error card)");
const arrow = (t, n, dir) => t.card(n).querySelector(`.qarrow[data-dir="${dir}"]`);

test("an arrow trades places with the nearest waiting card, jumping over a running one", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.w.eval("showModal = async () => 'B name'");
  t.d.getElementById("dl1").click(); await settle();          // B runs on its own, between A and C
  assert.equal(arrow(t, 0, "down").style.visibility, "visible", "A can go down: C is waiting");
  assert.equal(arrow(t, 2, "up").style.visibility, "visible", "C can go up: A is waiting");
  arrow(t, 2, "up").click();
  assert.deepEqual(t.ev("items.map(i => i.url)"), [C, B, A], "C and A traded places, B kept its own");
  assert.deepEqual(domOrder(t), ["qarrows2", "qarrows1", "qarrows0"], "the cards in the page follow");
  assert.deepEqual(t.ev("items.map(i => i.status)"), ["idle", "downloading", "idle"]);
  assert.equal(arrow(t, 2, "up").style.visibility, "hidden", "C is the first waiting card now");
  assert.equal(arrow(t, 0, "down").style.visibility, "hidden", "A is the last waiting card now");
  assert.equal(arrow(t, 0, "up").style.visibility, "visible");
  assert.equal(arrow(t, 2, "down").style.visibility, "visible");
  arrow(t, 2, "down").click();
  assert.deepEqual(t.ev("items.map(i => i.url)"), [A, B, C], "and back again");
  assert.deepEqual(domOrder(t), ["qarrows0", "qarrows1", "qarrows2"]);
});

test("a cancelled card between two waiting ones is jumped over too", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.w.eval("showModal = async () => 'B name'");
  t.d.getElementById("dl1").click(); await settle();
  t.d.getElementById("cancel1").click(); await settle();
  assert.equal(t.ev("items[1].status"), "cancelled");
  arrow(t, 2, "up").click();
  assert.deepEqual(t.ev("items.map(i => i.url)"), [C, B, A]);
  assert.deepEqual(domOrder(t), ["qarrows2", "qarrows1", "qarrows0"]);
});

test("neighbouring waiting cards still swap as before", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  arrow(t, 1, "up").click();
  assert.deepEqual(t.ev("items.map(i => i.url)"), [B, A, C]);
  assert.deepEqual(domOrder(t), ["qarrows1", "qarrows0", "qarrows2"]);
});

test("an arrow with no waiting card in its direction does nothing", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}\n${C}`);
  t.w.eval("showModal = async () => 'a name'");
  t.d.getElementById("dl1").click(); await settle();
  t.d.getElementById("dl2").click(); await settle();          // B and C run, only A waits
  arrow(t, 0, "down").click();
  assert.deepEqual(t.ev("items.map(i => i.url)"), [A, B, C]);
  assert.deepEqual(domOrder(t), ["qarrows0", "qarrows1", "qarrows2"]);
});

test("a card that failed to fetch keeps its place when the cards around it trade", async () => {
  const t = await boot();
  t.ctl.fail.add(D);
  await t.fetchLinks(`${A}\n${D}\n${C}`);
  assert.deepEqual(domOrder(t), ["qarrows0", "(error card)", "qarrows1"]);
  arrow(t, 1, "up").click();                                  // C is item 1 (the failed link has no item)
  assert.deepEqual(t.ev("items.map(i => i.url)"), [C, A]);
  assert.deepEqual(domOrder(t), ["qarrows1", "(error card)", "qarrows0"]);
});

test("Download all with a free slot starts the new card at once", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.all(); await settle();                       // A runs, one slot of two free
  await t.fetchLinks(`${A}\n${B}`);
  t.all(); await settle();
  assert.deepEqual(t.log.download, [A, B]);
});

test("Download all after a run ended starts a new run with its own bar and Done", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.all(); await settle();
  t.finish("j1"); await t.tick();
  assert.ok(!t.d.getElementById("bulk-bar").classList.contains("show"));
  await t.fetchLinks(B);                         // A's card went away when it was done
  t.clearToasts();
  t.all(); await settle();
  assert.ok(t.d.getElementById("bulk-bar").classList.contains("show"));
  t.finish("j2"); await t.tick();
  assert.equal(t.toasts().filter((x) => x.startsWith(en.strings["toast.done"])).length, 1, "the second run says Done too");
});

test("Clear keeps a card that is converting", async () => {
  const t = await boot();
  await t.fetchLinks(`${A}\n${B}`);
  t.w.eval("showModal = async () => 'A name'");
  t.d.getElementById("dl0").click(); await settle();
  t.w.eval("items[0].status = 'converting'");
  t.clear();
  assert.deepEqual(t.ev("items.map(i => i.url)"), [A]);
});

test("a card cleared while its name dialog is open is not downloaded", async () => {
  const t = await boot();
  await t.fetchLinks(A);
  t.w.eval("showModal = () => new Promise((r) => { window._answer = r; })");
  t.d.getElementById("dl0").click(); await settle();
  t.clear();
  const errors = [];
  t.w.addEventListener("error", (e) => errors.push(e.message));
  t.w.eval("_answer('A name')"); await settle();
  assert.deepEqual(t.log.download, []);
  assert.deepEqual(errors, []);
});
