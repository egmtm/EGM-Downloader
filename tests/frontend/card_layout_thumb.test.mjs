// Card thumbnails that fail to load, and the controls row of a card that has started.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

function addCard(w, id, info) {
  return w.eval(`(() => {
    const el = makeCardEl(); document.getElementById('results').appendChild(el);
    const item = { id: ${id}, url: 'https://example.com/v${id}', status: 'idle', selFmt: 'video', selFmtId: '', jobId: 'job${id}',
      info: Object.assign({ title: 'T', uploader: 'U', duration: null, width: 1280, height: 720,
                            formats: [{ id: 'f1', label: '720p', height: 720 }], audio_formats: [] }, ${JSON.stringify(info)}) };
    items.push(item); renderCard(el, item); return el; })()`);
}
const fail = (w, img) => img.dispatchEvent(new w.Event("error"));

test("a thumbnail that fails to load tries the next candidate, then the placeholder", async () => {
  const { w, d } = await bootPage();
  addCard(w, 401, { thumbnail: "https://cdn.example/a.jpg", thumbnails: ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg", "https://cdn.example/c.jpg"] });
  const thumb = d.querySelector(".vcard .thumb");
  assert.equal(thumb.querySelector("img").getAttribute("src"), "https://cdn.example/a.jpg");
  fail(w, thumb.querySelector("img"));
  assert.equal(thumb.querySelector("img").getAttribute("src"), "https://cdn.example/b.jpg");
  fail(w, thumb.querySelector("img"));
  assert.equal(thumb.querySelector("img").getAttribute("src"), "https://cdn.example/c.jpg");
  fail(w, thumb.querySelector("img"));
  assert.equal(thumb.querySelector("img"), null, "no broken image is left on the card");
  assert.ok(thumb.querySelector(".noimg"), "the normal placeholder takes its place");
});

test("older info without a candidate list still works, and no thumbnail shows the placeholder", async () => {
  const { w, d } = await bootPage();
  addCard(w, 402, { thumbnail: "https://cdn.example/only.jpg" });
  const one = d.querySelector(".vcard .thumb img");
  assert.equal(one.getAttribute("src"), "https://cdn.example/only.jpg");
  fail(w, one);
  assert.equal(d.querySelector(".vcard .thumb img"), null);
  assert.ok(d.querySelector(".vcard .thumb .noimg"));
  d.querySelector(".vcard").remove();
  addCard(w, 403, { thumbnail: "" });
  assert.equal(d.querySelector(".vcard .thumb img"), null);
  assert.ok(d.querySelector(".vcard .thumb .noimg"));
});

test("a card that has started gives up the space of its hidden reorder arrows", async () => {
  const { w, d } = await bootPage();
  const idle = addCard(w, 411, {});
  const started = addCard(w, 412, {});
  assert.notEqual(started.querySelector("#qarrows412").style.display, "none", "idle cards keep their arrows");
  w.eval("items.find(i => i.id === 412).status = 'downloading'; updateQueueArrows();");
  assert.equal(started.querySelector("#qarrows412").style.display, "none", "no empty gap before the status badge");
  assert.equal(started.querySelector("#qarrows412 .qarrow").style.visibility, "hidden");
  assert.notEqual(idle.querySelector("#qarrows411").style.display, "none", "the idle card is unaffected");
});

test("Download all hides the dimmed Download button of a card it starts, like a single download", async () => {
  const { w, d } = await bootPage({
    onFetch: (u, o) => {
      if (u === "/api/download") return { ok: true, json: async () => ({ job_id: "job421" }) };
      if (String(u).startsWith("/api/status/")) return { ok: true, json: async () => ({ status: "downloading", progress: 0, live_time: "00:00:05", live_size: "10kB" }) };
    },
  });
  addCard(w, 421, { is_live: true });
  addCard(w, 422, {});
  w.setInterval = () => 0;   // the job pollers would keep this test process alive forever
  w.eval("chosenPath = '/tmp/dl'; downloadAll('video', null, null);");
  await new Promise((r) => setTimeout(r, 150));
  assert.equal(d.getElementById("dl421").style.display, "none");
  assert.equal(d.getElementById("dl421").disabled, true);
  assert.equal(d.getElementById("qarrows421").style.display, "none");
  assert.ok(d.getElementById("cancel421"), "Cancel is there");
});
