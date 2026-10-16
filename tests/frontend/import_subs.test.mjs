// Import of subscription settings from an export file (the folder travels with the file).
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en } from "./harness.mjs";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// add(url) answers the add call: default is success; listFails makes the "already subscribed" lookup fail.
async function runImport(entries, { folderOk = true, existing = [], add = null, listFails = false, sel = null, extra = {} } = {}) {
  const updates = [];
  const reloads = [];
  const { w, d } = await bootPage({
    onFetch: (u, o) => {
      if (u === "/api/subscriptions") {
        if (listFails) throw new Error("offline");
        return { ok: true, json: async () => ({ subscriptions: existing.map((url) => ({ url })) }) };
      }
      if (u === "/api/subscriptions/add") {
        const custom = add && add(JSON.parse(o.body).url);   // null means: this one succeeds
        if (custom) return custom;
        return { ok: true, json: async () => ({ subscription: { id: "sub" + (updates.length + 1) } }) };
      }
      if (u === "/api/subscriptions/update") {
        const body = JSON.parse(o.body);
        updates.push(body);
        // the real route refuses the whole update when the folder is not valid on this computer
        if (body.download_folder && !folderOk) return { ok: false, status: 400, json: async () => ({ error: "not valid" }) };
        return { ok: true, json: async () => ({ subscription: {} }) };
      }
    },
  });
  const delays = [];
  w.setTimeout = (fn, ms) => { if (String(fn).includes("location.reload")) { reloads.push(ms); delays.push(ms); } return 0; };   // the page reloads itself after an import; jsdom cannot navigate
  w.electronAPI = { openFile: async () => ({ content: JSON.stringify({ _egm_export_version: 4, subscriptions: entries, ...extra }) }) };
  w._egmSelectorModal = async () => sel || ({ settings: false, history: false, themes: false, subscriptions: true });
  d.getElementById("adv-import-btn").click();
  await wait(400);
  const toastEls = [...d.querySelectorAll("#toasts .toast")];
  return { updates, toasts: toastEls.map((t) => t.textContent), classes: toastEls.map((t) => t.className), reloads: reloads.length, delays, w };
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

// ── What the import tells the user when nothing was added ───────────────────

const refuse = () => ({ ok: false, status: 400, json: async () => ({ error: "Subscription limit reached (500)" }) });
const two = [{ url: "https://example.com/@a" }, { url: "https://example.com/@b" }];
const notAdded = (n) => en.strings["toast.quality.subs_not_added"].replace("{0}", n);

test("every channel already subscribed: a plain notice, no red error, no reload", async () => {
  const { toasts, classes, reloads } = await runImport(two, { existing: two.map((e) => e.url) });
  assert.deepEqual(toasts, [en.strings["toast.already_in_list"]]);
  assert.ok(!classes[0].includes("err"), "this is not an error");
  assert.equal(reloads, 0);
});

test("the server refuses every add: the user is told how many were not added, not that it worked", async () => {
  const { toasts, classes, reloads, updates } = await runImport(two, { add: refuse });
  assert.deepEqual(toasts, [notAdded(2)]);
  assert.ok(classes[0].includes("err"));
  assert.equal(reloads, 0);
  assert.equal(updates.length, 0, "no settings call for a channel that was not added");
});

test("every add call fails to reach the server: same message", async () => {
  const { toasts, classes } = await runImport(two, { add: () => { throw new Error("down"); } });
  assert.deepEqual(toasts, [notAdded(2)]);
  assert.ok(classes[0].includes("err"));
});

test("the list of current subscriptions cannot be read: every channel counts as not added", async () => {
  const { toasts, classes, reloads } = await runImport(two, { listFails: true });
  assert.deepEqual(toasts, [notAdded(2)]);
  assert.ok(classes[0].includes("err"));
  assert.equal(reloads, 0);
});

test("one added and one refused: a warning with the refused count, kept up long enough to read before the reload", async () => {
  const { toasts, classes, reloads, delays, w } = await runImport(two, { add: (url) => url.endsWith("@b") ? refuse() : null });
  assert.equal(toasts.length, 1);
  assert.match(toasts[0], /^1 /, "one subscription was added");
  assert.ok(toasts[0].includes(notAdded(1)), toasts[0]);
  assert.ok(toasts[0].endsWith(en.strings["toast.quality.reloading"]), "the reload word comes from the language file");
  assert.ok(classes[0].includes("warn"), "not a green success");
  assert.equal(reloads, 1);
  assert.deepEqual(delays, [w.eval("TOAST_DURATION")], "the reload waits as long as a notice stays up, not 0.8 s");
});

test("everything added: the quick reload as before", async () => {
  const { classes, delays } = await runImport(two);
  assert.ok(classes[0].includes("ok"));
  assert.deepEqual(delays, [800]);
});

test("the same channel twice in the file is added once and not reported as failed", async () => {
  const seen = new Set();
  const { toasts, classes } = await runImport([two[0], { ...two[0], url: two[0].url + " " }], {
    add: (url) => (seen.has(url) ? { ok: false, status: 409, json: async () => ({ error: "Already subscribed" }) } : (seen.add(url), null)),
  });
  assert.match(toasts[0], /^1 /);
  assert.ok(!toasts[0].includes(en.strings["toast.quality.subs_not_added"].split("{0}")[0]), toasts[0]);
  assert.ok(classes[0].includes("ok"));
});

test("themes only: applied and reloaded, not 'Nothing selected'", async () => {
  const { toasts, reloads, w } = await runImport([], {
    sel: { settings: false, history: false, themes: true, subscriptions: false },
    extra: { localStorage: { "egm-theme": "test-theme" } },
  });
  assert.equal(w.localStorage.getItem("egm-theme"), "test-theme");
  assert.ok(!toasts.includes(en.strings["toast.quality.nothing_selected"]), JSON.stringify(toasts));
  assert.equal(reloads, 1, "the theme shows after the reload");
});

test("one already subscribed and one new: added, nothing reported as failed", async () => {
  const { toasts, reloads } = await runImport(two, { existing: [two[0].url] });
  assert.equal(toasts.length, 1);
  assert.match(toasts[0], /^1 /);
  assert.ok(!toasts[0].includes(en.strings["toast.quality.subs_not_added"].split("{0}")[0]), toasts[0]);
  assert.equal(reloads, 1);
});

test("nothing ticked in the dialog: 'Nothing selected' without claiming a reload", async () => {
  const { toasts, classes, reloads } = await runImport(two, { sel: { settings: false, history: false, themes: false, subscriptions: false } });
  assert.deepEqual(toasts, [en.strings["toast.quality.nothing_selected"]]);
  assert.ok(classes[0].includes("err"));
  assert.equal(reloads, 0);
});
