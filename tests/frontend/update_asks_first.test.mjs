// The update check on launch (Windows) asks first: it does not download the update; it shows the
// same toast as on Mac and Linux, whose button opens the update dialog. The dialog shows the
// download size the signed feed gives, and Update Now (the consent) sends it to the backend with
// the address and the checksum, so the download stops there.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const _json = (body) => ({ ok: true, json: async () => body, text: async () => JSON.stringify(body) });

const UPDATE = {
  up_to_date: false, current_version: "1.5.2.3", current_build: 176, latest_version: "1.5.2.4", latest_build: 177,
  zip_url: "https://egerena.com/apps/EGMd.zip", _checksums: { sha256: "ab".repeat(32) },
};

async function launchWith(answer, platform = "win") {
  const calls = [];
  const page = await bootPage({
    settings: { check_updates_on_launch: true },
    prep(win) {
      win.electronAPI = { platform, launchInstaller: async () => ({ cancelled: true }), quit: async () => ({}) };
      win.open = (u) => calls.push({ url: "open:" + u });
    },
    onFetch(u, o) {
      calls.push({ url: u, body: o && o.body ? JSON.parse(o.body) : null });
      if (u === "/api/check-app-update") return _json(answer);
      if (u === "/api/download-update") return _json({ error: "stop here" });
    },
  });
  await _sleep(200);
  return { ...page, calls };
}

const toastButton = (d) => [...d.querySelectorAll("#toasts .toast button")].find((b) => b.textContent === "Download");

test("Windows: the launch check downloads nothing and shows the toast whose button opens the update dialog", async () => {
  const { w, d, calls } = await launchWith({ ...UPDATE, size_bytes: 134217728 });
  assert.ok(calls.some((c) => c.url === "/api/check-app-update"), "the launch check ran");
  assert.deepEqual(calls.filter((c) => c.url === "/api/download-update"), [], "nothing is downloaded before the click");
  const toast = [...d.querySelectorAll("#toasts .toast")].find((t) => /1\.5\.2\.4 is available/.test(t.textContent));
  assert.ok(toast, "the toast says an update is available");
  assert.equal(d.querySelector(".upd-backdrop"), null, "the dialog waits for the click");
  toastButton(d).click();
  const modal = d.querySelector(".upd-backdrop");
  assert.ok(modal, "the toast's button opens the update dialog");
  assert.deepEqual(calls.filter((c) => c.url === "/api/download-update" || c.url.startsWith("open:")), [], "the button only opens the dialog");
  w.close();
});

test("the dialog shows the download size before Update Now, and Update Now sends it", async () => {
  const { w, d, calls } = await launchWith({ ...UPDATE, size_bytes: 134217728 });
  toastButton(d).click();
  const modal = d.querySelector(".upd-backdrop");
  assert.match(modal.textContent, /Download size: 128\.0 MB/);
  const btn = [...modal.querySelectorAll("button")].find((b) => /Update Now/.test(b.textContent));
  assert.ok(btn, "Update Now is offered");
  btn.click();
  await _sleep(50);
  const posts = calls.filter((c) => c.url === "/api/download-update");
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].body, { zip_url: UPDATE.zip_url, expected_checksum: "ab".repeat(32),
                                    expected_size: 134217728, latest_build: 177 });
  w.close();
});

test("a size of zero or less shows no size line", async () => {
  for (const size_bytes of [0, -1]) {
    const { w, d } = await launchWith({ ...UPDATE, size_bytes });
    toastButton(d).click();
    const modal = d.querySelector(".upd-backdrop");
    assert.ok(modal);
    assert.doesNotMatch(modal.textContent, /Download size/, String(size_bytes));
    w.close();
  }
});

test("a feed without a size shows no size line", async () => {
  const { w, d } = await launchWith({ ...UPDATE });
  toastButton(d).click();
  const modal = d.querySelector(".upd-backdrop");
  assert.ok(modal);
  assert.doesNotMatch(modal.textContent, /Download size/);
  w.close();
});

test("Mac and Linux: the launch toast still opens the download page, and nothing is downloaded", async () => {
  for (const platform of ["mac", "linux"]) {
    const { w, d, calls } = await launchWith({ ...UPDATE, size_bytes: 134217728, download_url: "https://egerena.com/x" }, platform);
    toastButton(d).click();
    assert.deepEqual(calls.filter((c) => c.url.startsWith("open:")).map((c) => c.url), ["open:https://egerena.com/x"], platform);
    assert.equal(d.querySelector(".upd-backdrop"), null, platform);
    assert.deepEqual(calls.filter((c) => c.url === "/api/download-update"), [], platform);
    w.close();
  }
});
