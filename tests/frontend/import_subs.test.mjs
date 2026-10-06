// Import of subscription settings from an export file (the folder travels with the file).
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function runImport(entries, { folderOk }) {
  const updates = [];
  const { w, d } = await bootPage({
    onFetch: (u, o) => {
      if (u === "/api/subscriptions") return { ok: true, json: async () => ({ subscriptions: [] }) };
      if (u === "/api/subscriptions/add") return { ok: true, json: async () => ({ subscription: { id: "sub" + (updates.length + 1) } }) };
      if (u === "/api/subscriptions/update") {
        const body = JSON.parse(o.body);
        updates.push(body);
        // the real route refuses the whole update when the folder is not valid on this computer
        if (body.download_folder && !folderOk) return { ok: false, status: 400, json: async () => ({ error: "not valid" }) };
        return { ok: true, json: async () => ({ subscription: {} }) };
      }
    },
  });
  w.setTimeout = () => 0;   // the page reloads itself 0.8 s after an import; jsdom cannot navigate
  w.electronAPI = { openFile: async () => ({ content: JSON.stringify({ _egm_export_version: 4, subscriptions: entries }) }) };
  w._egmSelectorModal = async () => ({ settings: false, history: false, themes: false, subscriptions: true });
  d.getElementById("adv-import-btn").click();
  await wait(400);
  const toasts = [...d.querySelectorAll("#toasts .toast")].map((t) => t.textContent);
  return { updates, toasts };
}

const entry = {
  url: "https://example.com/@chan", name: "Chan", download_folder: "C:\\Users\\alice\\Videos", format: "audio", quality: "mp3_320",
  auto_fetch_on_open: true, sponsorblock_enabled: true, sponsorblock_categories: ["sponsor"],
};

test("a folder this computer rejects no longer drops the channel's other settings, and the user is told", async () => {
  const { updates, toasts } = await runImport([entry], { folderOk: false });
  const settings = updates.find((u) => !("download_folder" in u));
  assert.ok(settings, "format, quality, auto fetch and SponsorBlock are applied in their own call");
  assert.deepEqual([settings.format, settings.quality, settings.auto_fetch_on_open, settings.sponsorblock_enabled, settings.sponsorblock_categories],
    ["audio", "mp3_320", true, true, ["sponsor"]]);
  assert.equal(updates.filter((u) => "download_folder" in u).length, 1, "the folder is tried once, alone");
  assert.ok(toasts.some((t) => /not restored/i.test(t) && /1/.test(t)), JSON.stringify(toasts));
});

test("a folder that is valid here is applied and nothing is reported", async () => {
  const { updates, toasts } = await runImport([entry], { folderOk: true });
  assert.equal(updates.length, 2);
  assert.equal(updates.find((u) => "download_folder" in u).download_folder, entry.download_folder);
  assert.ok(!toasts.some((t) => /not restored/i.test(t)), JSON.stringify(toasts));
});

test("an entry without a folder, and an old export with bare URLs, import without a folder call", async () => {
  const { updates, toasts } = await runImport([{ ...entry, download_folder: null }, "https://example.com/@old"], { folderOk: false });
  assert.equal(updates.filter((u) => "download_folder" in u).length, 0);
  assert.equal(updates.length, 2, "one settings call per channel");
  assert.ok(!toasts.some((t) => /not restored/i.test(t)));
});
