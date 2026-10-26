// Subscriptions window: "Fetching videos..." stays up for the whole fetch.
// On open the page starts the auto fetch of a channel while the language file is still loading. When the
// language arrives, the language handlers re-render the detail pane; that used to bring the channel's old
// list back in place of the indicator for the rest of the fetch, and a failed fetch wrote its error into
// the list element the re-render had replaced, so nothing was shown at all.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { bootSubsPage, en } from "./harness.mjs";

// Waits for the list to show `re` (checked every 50 ms, up to 10 s) instead of sleeping a fixed time: the first
// poll answers 1.2 s after the fetch starts, and a slow runner must not turn that into a failure.
const until = (t, re) => new Promise((resolve, reject) => {
  const t0 = Date.now();
  (function look() { if (re.test(listText(t))) return resolve(); if (Date.now() - t0 > 10000) return reject(new Error(`video-list never matched ${re}: ${listText(t)}`)); setTimeout(look, 50); })();
});
const windows = [];
after(() => windows.forEach((w) => w.close()));   // stops the page timers (the fetch keeps polling), or the test process never exits
const json = (body) => ({ ok: true, json: async () => body });
const late = (ms, res) => new Promise((r) => setTimeout(() => r(res), ms));

const channel = (title) => ({
  id: "s1", url: "https://example.com/@chan", name: "Chan", auto_fetch_on_open: true, format: "video",
  videos: [{ video_id: "v1", title, upload_date: "20261001" }],
});

// The channel opens with OLD video and has an auto fetch; the fetch ends with `status` at its first poll (1.2 s in).
// The language file answers after 300 ms, well after the fetch started.
async function boot(status) {
  const t = await bootSubsPage({
    onFetch: (u) => {
      if (u === "/api/subscriptions") return json({ subscriptions: [channel("OLD video")] });
      if (u === "/api/language/en") return late(300, json(en));
      if (u === "/api/subscriptions/fetch") return json({ fetch_id: "f1" });
      if (u === "/api/subscriptions/fetch-status") return json(status);
    },
  });
  windows.push(t.w);
  return t;
}
const listText = (t) => t.d.getElementById("video-list").textContent;

test("the indicator is still up after the language arrives mid fetch, and the old list is not shown", async () => {
  const t = await boot({ status: "running" });          // booted: language is in, the first poll is not due yet
  assert.match(listText(t), /Fetching videos/);
  assert.doesNotMatch(listText(t), /OLD video/);
});

test("a fetch that fails shows its error, not an indicator or the old list", async () => {
  const t = await boot({ status: "error", error: "boom" });
  await until(t, /Error: boom/);                        // the first poll answers 1.2 s after the fetch started
  assert.match(listText(t), /Error: boom/);
  assert.doesNotMatch(listText(t), /Fetching videos|OLD video/);
});

// A fetch whose request throws must not leave the channel marked as fetching, or every later render of it
// would show the line for good. The request fails 500 ms in, after the language has arrived, so no re-render
// follows the error text; a render afterwards shows the stored list without the line.
test("a fetch whose request throws shows the error and leaves no indicator behind", async () => {
  const t = await bootSubsPage({
    onFetch: (u) => {
      if (u === "/api/subscriptions") return json({ subscriptions: [channel("OLD video")] });
      if (u === "/api/language/en") return late(300, json(en));
      if (u === "/api/subscriptions/fetch") return new Promise((_, reject) => setTimeout(() => reject(new Error("network down")), 500));
    },
  });
  windows.push(t.w);
  await until(t, /Fetch failed/);
  t.w.eval("renderDetail()");
  assert.match(listText(t), /OLD video/);
  assert.doesNotMatch(listText(t), /Fetching videos/);
});

test("a fetch that finishes replaces the indicator with the new list", async () => {
  const t = await boot({ status: "done", subscription: channel("NEW video") });
  await until(t, /NEW video/);
  assert.match(listText(t), /NEW video/);
  assert.doesNotMatch(listText(t), /Fetching videos|OLD video/);
});
