// A finished card stays a moment reading Done, then fades away (History is the record, the toast is
// unchanged): 5 s for every download, 15 s for a live recording that saved with a note, which the card
// then shows. The timers are caught here instead of waited for.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en } from "./harness.mjs";

function cardItem(w, isLive) {
  return w.eval(`(() => {
    const el = makeCardEl(); document.getElementById('results').appendChild(el);
    const item = { id: 401, url: 'https://example.com/v', status: 'downloading', selFmt: 'video', selFmtId: '', jobId: 'job4',
      info: { title: 'Video', uploader: 'Chan', duration: null, thumbnail: '', width: 1280, height: 720,
              formats: [{ id: 'f1', label: '720p', height: 720 }], audio_formats: [], is_live: ${isLive} } };
    items.push(item); renderCard(el, item); return item; })()`);
}

function finish(w, d, job) {
  // Catch the page's timers: [delay, callback] in the order they were set
  w.eval("window.__timers = []; window.__realSetTimeout = window.setTimeout; window.setTimeout = (fn, ms) => { window.__timers.push([ms, fn]); return 0; };");
  w.eval(`applyJobDone(${JSON.stringify(job)}, items[0], document.getElementById('st401'), document.getElementById('dl401'),
    document.getElementById('prog401'), null)`);
  const card = d.querySelector(".vcard");
  const timers = () => w.eval("window.__timers.map(t => t[0])");
  const run = (ms) => w.eval(`(() => { const i = window.__timers.findIndex(t => t[0] === ${ms}); const [, fn] = window.__timers.splice(i, 1)[0]; fn(); })()`);
  return { card, timers, run };
}

for (const [label, isLive, job, wait] of [
  ["an ordinary download", false, { status: "done", progress: 100, filename: "x.mp4" }, 5000],
  ["a live recording with no note", true, { status: "done", progress: 100, filename: "x.mp4" }, 5000],
  ["a live recording that saved with a note", true,
    { status: "done", progress: 100, filename: "x.mp4", warning: "English fallback", warning_key: "download.warning.live_gap" }, 15000],
]) {
  test(`${label}: the card reads Done, stays ${wait / 1000} s, then fades away and leaves the list`, async () => {
    const { w, d } = await bootPage();
    cardItem(w, isLive);
    const { card, timers, run } = finish(w, d, job);
    assert.equal(d.getElementById("st401").textContent.trim(), en.strings["card.status.done"]);
    assert.ok(d.getElementById("st401").classList.contains("b-done"));
    assert.equal(w.eval("items[0].status"), "done", "a done card is not active: closing the app asks nothing about it");
    assert.ok(card.isConnected && card.style.opacity !== "0", "still there, not fading yet");
    assert.ok(timers().includes(wait), JSON.stringify(timers()));
    run(wait);
    assert.equal(card.style.opacity, "0", "fading");
    assert.match(card.style.transition, /opacity \.8s/);
    assert.ok(card.isConnected, "still in the page while it fades");
    run(800);
    assert.ok(!card.isConnected, "gone after the fade");
    assert.equal(w.eval("items.length"), 0);
  });
}

test("the note of a live recording shows on the card, in the app language, and the toast still shows", async () => {
  const { w, d } = await bootPage();
  cardItem(w, true);
  finish(w, d, { status: "done", progress: 100, filename: "x.mp4", warning: "English fallback", warning_key: "download.warning.live_partial" });
  const note = d.querySelector(".vcard .vnote");
  assert.ok(note, "note on the card");
  assert.equal(note.textContent, en.strings["download.warning.live_partial"]);
  assert.ok([...d.querySelectorAll("#toasts .toast")].some((t) => t.textContent === en.strings["download.warning.live_partial"]));
});

test("an ordinary download never gets a note on its card, even if a warning came with it", async () => {
  const { w, d } = await bootPage();
  cardItem(w, false);
  const { timers } = finish(w, d, { status: "done", progress: 100, filename: "x.mp4", warning: "something" });
  assert.equal(d.querySelector(".vcard .vnote"), null);
  assert.ok(timers().includes(5000) && !timers().includes(15000));
});

test("a card removed by hand while it waits is not touched again when its time is up", async () => {
  const { w, d } = await bootPage();
  cardItem(w, false);
  const { card, timers, run } = finish(w, d, { status: "done", progress: 100, filename: "x.mp4" });
  card.remove();
  w.eval("items = []");
  run(5000);
  assert.ok(!timers().includes(800), "no fade for a card that is already gone");
  assert.equal(w.eval("items.length"), 0);
});
