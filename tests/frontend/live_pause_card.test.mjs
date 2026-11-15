// Live card: Pause shows only while the card reads Recording (not while it reconnects or converts),
// Resume only while paused, with a Paused badge that keeps the time and size. Both post to their route.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en } from "./harness.mjs";

async function liveCard() {
  const posts = [];
  const { w, d } = await bootPage({ onFetch: (u, o) => {
    if (typeof u === "string" && /^\/api\/(pause|resume|stop)\//.test(u) && o && o.method === "POST") {
      posts.push(u); return { ok: true, json: async () => ({ success: true }) };
    }
  } });
  w.eval(`(() => {
    const el = makeCardEl(); document.getElementById('results').appendChild(el);
    const item = { id: 501, url: 'https://example.com/live', status: 'downloading', selFmt: 'video', selFmtId: '', jobId: 'job5',
      info: { title: 'Stream', uploader: 'Chan', duration: null, thumbnail: '', width: 1280, height: 720,
              formats: [{ id: 'f1', label: '720p', height: 720 }], audio_formats: [], is_live: true } };
    items.push(item); renderCard(el, item);
    const b = document.createElement('button'); b.id = 'cancel501'; document.getElementById('dl501').after(b);
    addStopSave(item, 501, b); })()`);
  const show = (job) => w.eval(`applyJobProgress(${JSON.stringify(job)}, document.getElementById('st501'), document.getElementById('prog501'))`);
  const vis = (id) => d.getElementById(id).style.display !== "none";
  return { w, d, posts, show, vis };
}

test("Pause sits before Stop and save and shows only while the card reads Recording", async () => {
  const { d, show, vis } = await liveCard();
  const row = [...d.getElementById("stop501").parentNode.children].map((e) => e.id);
  assert.ok(row.indexOf("pause501") < row.indexOf("stop501") && row.indexOf("resume501") < row.indexOf("stop501"));
  assert.equal(d.getElementById("pause501").textContent, "❚❚ " + en.strings["card.btn.pause"]);
  assert.ok(!vis("pause501") && !vis("resume501"), "hidden until it records");
  show({ status: "downloading", progress: 0 });
  assert.ok(!vis("pause501"), "nothing recorded yet");
  show({ status: "downloading", progress: 0, live_time: "00:06:03", live_size: "117504KiB" });
  assert.ok(vis("pause501") && !vis("resume501"));
  show({ status: "downloading", progress: 0, live_time: "00:06:03", live_reconnecting: 3, live_retries_max: 5 });
  assert.ok(!vis("pause501"), "no Pause while it reconnects (EGM, Nov 14)");
  show({ status: "converting", progress: 0 });
  assert.ok(!vis("pause501") && !vis("resume501"));
});

test("paused: the badge keeps the time and size, Resume replaces Pause, the bar stops moving", async () => {
  const { d, show, vis } = await liveCard();
  show({ status: "paused", progress: 0, live_time: "00:06:03", live_size: "117504KiB" });
  const st = d.getElementById("st501");
  assert.equal(st.textContent.trim(), `${en.strings["card.status.paused"]} · 00:06:03 · 117504KiB`);
  assert.ok(st.classList.contains("b-wait"));
  assert.ok(vis("resume501") && !vis("pause501") && vis("stop501"), "Stop and save stays while paused");
  assert.equal(d.getElementById("resume501").textContent, "▶ " + en.strings["card.btn.resume"]);
  assert.ok(!d.querySelector("#prog501 .prog-inner").classList.contains("indeterminate"));
});

test("Pause and Resume post to their routes once and come back after the next state", async () => {
  const { d, posts, show } = await liveCard();
  show({ status: "downloading", progress: 0, live_time: "00:00:10" });
  d.getElementById("pause501").click();
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(posts, ["/api/pause/job5"]);
  assert.ok(d.getElementById("pause501").disabled, "no second press while it pauses");
  show({ status: "paused", progress: 0, live_time: "00:00:10" });
  d.getElementById("resume501").click();
  await new Promise((r) => setTimeout(r, 20));
  assert.deepEqual(posts, ["/api/pause/job5", "/api/resume/job5"]);
  show({ status: "converting", progress: 0 });
  show({ status: "downloading", progress: 0, live_time: "00:00:12" });
  assert.equal(d.getElementById("pause501").disabled, false, "Pause works again once it records again");
});

test("the end of the job hides Pause and Resume with Stop and save", async () => {
  const { w, d, show, vis } = await liveCard();
  show({ status: "paused", progress: 0, live_time: "00:00:10" });
  w.eval("window.setTimeout = () => 0");
  w.eval(`applyJobDone({ status: 'done', progress: 100, filename: 'x.mp4' }, items[0], document.getElementById('st501'),
    document.getElementById('dl501'), document.getElementById('prog501'), document.getElementById('cancel501'))`);
  assert.ok(!vis("pause501") && !vis("resume501") && !vis("stop501"));
});

test("a paused recording still counts as an active download (EGM, Nov 14)", async () => {
  const { w, show } = await liveCard();
  show({ status: "paused", progress: 0, live_time: "00:00:10" });
  assert.equal(w.eval("items[0].status"), "downloading", "the page's own state stays active while paused");
});
