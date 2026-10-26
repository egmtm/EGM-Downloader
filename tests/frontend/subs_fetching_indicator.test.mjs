// Subscriptions window: "Fetching videos..." stays up for the whole fetch.
// On open the page starts the auto fetch of a channel while the language file is still loading. When the
// language arrives, the language handlers re-render the detail pane; that used to bring the channel's old
// list back in place of the indicator for the rest of the fetch, and a failed fetch wrote its error into
// the list element the re-render had replaced, so nothing was shown at all.
import { test, after } from "node:test";
import assert from "node:assert/strict";
import { bootSubsPage, en } from "./harness.mjs";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
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
  await wait(700);                                      // the first poll answers at 1.2 s
  assert.match(listText(t), /Error: boom/);
  assert.doesNotMatch(listText(t), /Fetching videos|OLD video/);
});

test("a fetch that finishes replaces the indicator with the new list", async () => {
  const t = await boot({ status: "done", subscription: channel("NEW video") });
  await wait(700);
  assert.match(listText(t), /NEW video/);
  assert.doesNotMatch(listText(t), /Fetching videos|OLD video/);
});
