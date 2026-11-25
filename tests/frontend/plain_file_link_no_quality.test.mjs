// A plain file link: the backend answers /api/info with no video and no audio formats (yt-dlp reports one
// format with no height and no codecs). The card is not left loading, Download does not ask for the info
// again and again, and the link is downloaded as it is served (no quality choice).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const settle = (ms = 80) => new Promise((r) => setTimeout(r, ms));
const windows = [];
after(() => windows.forEach((w) => w.close()));
const URL = "https://files.example/clip.mp4";
const PLAIN = { title: "clip", uploader: "", thumbnail: "", duration: 2, formats: [], audio_formats: [], is_live: false };
const WITH_FORMATS = { ...PLAIN, formats: [{ id: "f1", label: "720p", height: 720 }] };

async function boot(answer = PLAIN, single = false) {
  const log = { info: 0, download: [] };
  const json = (o) => ({ ok: true, json: async () => o });
  const t = await bootPage({
    onFetch: (u, o) => {
      const body = o && o.body ? JSON.parse(o.body) : {};
      if (u === "/api/playlist") return json(single ? { is_playlist: false } : { is_playlist: true, entries: [{ url: body.url, title: "clip" }] });
      if (u === "/api/info") {
        log.info++;
        if (log.info > 50) return new Promise(() => {});   // stops a runaway loop so the test can report it
        return json(answer);
      }
      if (u === "/api/download") { log.download.push(body); return json({ job_id: "j" + log.download.length }); }
      if (typeof u === "string" && u.startsWith("/api/status/")) return json({ status: "downloading", progress: 10 });
    },
  });
  windows.push(t.w);
  t.w.eval("chosenPath = '/tmp/dl'");
  const timers = new Map(); let next = 9000;
  t.w.setInterval = (fn) => { const id = next++; timers.set(id, fn); return id; };   // pollers stay still
  return { ...t, log };
}

async function pressDownload(t, n = 0) {
  t.d.getElementById("dl" + n).click();
  await settle(300);
  if (t.d.getElementById("name-modal").style.display === "flex") t.w.eval("confirmModal()");
  await settle(300);
}

// Both fetch paths: a link the backend lists as a one entry playlist, and one it answers as a single link
for (const single of [false, true]) test(`a plain file link (${single ? "single" : "one entry list"}): the card is not left loading, and Download starts it as it is served`, async () => {
  const t = await boot(PLAIN, single);
  t.d.getElementById("urls").value = URL;
  t.d.getElementById("fetch-btn").click();
  await settle(300);
  assert.equal(t.log.info, 1, "the fetch asks the backend once");
  assert.equal(t.d.getElementById("lqg0"), null, "no loading spinner on a card whose info has come back");
  const btn = t.d.getElementById("dl0");
  assert.ok(btn && !btn.disabled, "the card has a Download button the person can press");
  await pressDownload(t);
  assert.equal(t.log.info, 1, `Download asked for the info ${t.log.info - 1} more times`);
  assert.equal(t.log.download.length, 1, "the download starts");
  assert.equal(t.log.download[0].url, URL);
  assert.equal(t.log.download[0].format_id, null, "no quality choice: the link is downloaded as it is served");
  assert.equal(t.w.eval("items[0].status"), "downloading");
});

test("a stub card whose info has not come yet still asks once, then downloads", async () => {
  for (const answer of [PLAIN, WITH_FORMATS]) {
    const t = await boot(answer);
    t.w.eval(`(() => { const el = makeCardEl(); document.getElementById('results').appendChild(el);
      const it = addItem(${JSON.stringify(URL)}, { title: 'stub', formats: [], audio_formats: [] }); renderCard(el, it); })()`);
    assert.ok(t.d.getElementById("lqg0"), "a stub shows the loading spinner");
    await pressDownload(t);
    assert.equal(t.log.info, 1, `asked for the info ${t.log.info} times`);
    assert.equal(t.log.download.length, 1, "then the download starts");
  }
});

test("Download all on a plain file link does not ask for the info again", async () => {
  const t = await boot();
  t.d.getElementById("urls").value = URL;
  t.d.getElementById("fetch-btn").click();
  await settle(300);
  t.w.eval("downloadAll('video', null, null)");
  await settle(400);
  assert.equal(t.log.info, 1, `Download all asked for the info ${t.log.info - 1} more times`);
  assert.equal(t.log.download.length, 1);
  assert.equal(t.log.download[0].format_id, null);
});
