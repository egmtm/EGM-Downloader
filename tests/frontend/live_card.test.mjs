// Livestream cards: LIVE tag, recording progress, Stop and save, localized warning.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en } from "./harness.mjs";

function liveItem(w, isLive = true) {
  // Same shape the page builds after /api/info; renderCard fills the card.
  return w.eval(`(() => {
    const el = makeCardEl(); document.getElementById('results').appendChild(el);
    const item = { id: 301, url: 'https://example.com/live', status: 'idle', selFmt: 'video', selFmtId: '', jobId: 'job1',
      info: { title: 'Stream', uploader: 'Chan', duration: null, thumbnail: '', width: 1280, height: 720,
              formats: [{ id: 'f1', label: '720p', height: 720 }], audio_formats: [], is_live: ${isLive} } };
    items.push(item); renderCard(el, item); return item; })()`);
}

test("a live card shows the LIVE tag, a normal card does not", async () => {
  const { w, d } = await bootPage();
  liveItem(w, true);
  const tag = d.querySelector(".vcard .live-tag");
  assert.ok(tag, "LIVE tag present");
  assert.equal(tag.textContent, en.strings["card.badge.live"]);
  d.querySelector(".vcard").remove();
  liveItem(w, false);
  assert.equal(d.querySelector(".vcard .live-tag"), null);
});

test("recording progress replaces the empty percent: time and size, indeterminate bar", async () => {
  const { w, d } = await bootPage();
  liveItem(w);
  const out = w.eval(`(() => { const st = document.getElementById('st301'), pr = document.getElementById('prog301');
    applyJobProgress({ status: 'downloading', progress: 0, live_time: '00:01:05', live_size: '512kB' }, st, pr);
    return { text: st.textContent.trim(), indet: pr.querySelector('.prog-inner').classList.contains('indeterminate') }; })()`);
  assert.equal(out.text, `${en.strings["card.status.recording"]} · 00:01:05 · 512kB`);
  assert.equal(out.indet, true);
  // a normal download is untouched
  const pct = w.eval(`(() => { const st = document.getElementById('st301');
    applyJobProgress({ status: 'downloading', progress: 42, speed: '1MiB/s', eta: '00:10' }, st, document.getElementById('prog301'));
    return st.textContent.trim(); })()`);
  assert.match(pct, /^42% · 1MiB\/s · ETA 00:10$/);
});

test("Stop and save appears only for live items, next to Cancel, and calls /api/stop", async () => {
  const stops = [];
  const { w, d } = await bootPage({ onFetch: (u, o) => { if (String(u).startsWith("/api/stop/")) { stops.push([u, o && o.method]); return { ok: true, json: async () => ({ success: true }) }; } } });
  const live = liveItem(w, true);
  const cancel = w.eval(`(() => { const b = document.createElement('button'); b.id = 'cancel301'; document.getElementById('dl301').after(b); return b; })()`);
  w.eval("addStopSave(items[0], 301, document.getElementById('cancel301'))");
  const stop = d.getElementById("stop301");
  assert.ok(stop, "button created");
  assert.equal(stop.nextElementSibling.id, "cancel301", "sits right before Cancel");
  assert.match(stop.textContent, new RegExp(en.strings["card.btn.stop_save"]));
  stop.click();
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(stops, [["/api/stop/job1", "POST"]]);
  assert.equal(stop.disabled, true, "no double click");
  // not live: nothing is added
  d.querySelector(".vcard").remove();
  liveItem(w, false);
  w.eval("document.getElementById('stop301')?.remove(); addStopSave(items[items.length-1], 301, document.getElementById('cancel301') || document.body.appendChild(document.createElement('button')))");
  assert.equal(d.getElementById("stop301"), null);
});

test("a refused stop re-enables the button", async () => {
  const { w, d } = await bootPage({ onFetch: (u) => (String(u).startsWith("/api/stop/") ? { ok: false, json: async () => ({ error: "x" }) } : null) });
  liveItem(w);
  w.eval("(() => { const b = document.createElement('button'); b.id = 'cancel301'; document.getElementById('dl301').after(b); addStopSave(items[0], 301, b); })()");
  d.getElementById("stop301").click();
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(d.getElementById("stop301").disabled, false);
});

for (const status of ["done", "error", "cancelled"]) {
  test(`the button goes away when the job ends (${status})`, async () => {
    const { w, d } = await bootPage();
    liveItem(w);
    w.eval("(() => { const b = document.createElement('button'); b.id = 'cancel301'; document.getElementById('dl301').after(b); addStopSave(items[0], 301, b); })()");
    assert.notEqual(d.getElementById("stop301").style.display, "none");
    w.eval(`applyJobDone({ status: '${status}', error: 'e', filename: 'x.mp4', progress: 100 }, items[0], document.getElementById('st301'), document.getElementById('dl301'), document.getElementById('prog301'), document.getElementById('cancel301'))`);
    assert.equal(d.getElementById("stop301").style.display, "none");
  });
}

test("the rescue warning is shown in the app language via its key", async () => {
  const { w, d } = await bootPage();
  liveItem(w);
  w.eval(`applyJobDone({ status: 'done', progress: 100, filename: 'x.mp4', warning: 'English fallback', warning_key: 'download.warning.live_partial' },
    items[0], document.getElementById('st301'), document.getElementById('dl301'), document.getElementById('prog301'), null)`);
  const toasts = [...d.querySelectorAll("#toasts .toast")].map((t) => t.textContent);
  assert.ok(toasts.includes(en.strings["download.warning.live_partial"]), JSON.stringify(toasts));
  // an old style warning with no key still shows its own text
  liveItem(w);
  w.eval(`applyJobDone({ status: 'done', progress: 100, filename: 'y.mp4', warning: 'plain text warning' },
    items[items.length-1], document.getElementById('st301'), document.getElementById('dl301'), document.getElementById('prog301'), null)`);
  assert.ok([...d.querySelectorAll("#toasts .toast")].some((t) => t.textContent === "plain text warning"));
});
