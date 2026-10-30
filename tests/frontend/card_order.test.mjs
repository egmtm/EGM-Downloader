// Order of the links card and the Settings panel (egm_card_order): read at load, stored, exported,
// imported and reset. jsdom has no layout, so the drag itself (pointer capture, the 4 px threshold,
// the swap when the centres cross, the settle) is not covered here; only what does not need layout is.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const KEY = "egm_card_order";
const SWAPPED = '["settings","urls"]';
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Boots the page with egm_card_order set to `stored` (or absent), collecting uncaught errors.
async function boot(stored, opts = {}) {
  const errors = [];
  const page = await bootPage({
    ...opts,
    prep(w) {
      w.addEventListener("error", (e) => errors.push(e.message));
      if (stored !== undefined) w.localStorage.setItem(KEY, stored);
      if (opts.prep) opts.prep(w);
    },
  });
  return { ...page, errors };
}

const order = (d) => {
  const ids = [...d.querySelectorAll("#urls-card, #settings-panel-wrap")].map((e) => e.id);
  return ids.join(",");
};
const DEFAULT = "urls-card,settings-panel-wrap";
const SETTINGS_FIRST = "settings-panel-wrap,urls-card";

test("a stored order is applied at load; with no key the default shows and nothing is written", async () => {
  {
    const { w, d, errors } = await boot(SWAPPED);
    assert.equal(order(d), SETTINGS_FIRST);
    assert.equal(d.documentElement.classList.contains("card-order-pending"), false, "the cards are not left hidden");
    assert.equal(d.querySelectorAll("#urls-card").length + d.querySelectorAll("#settings-panel-wrap").length, 2);
    assert.equal(d.getElementById("settings-panel-wrap").nextElementSibling.id, "urls-card", "the two stay next to each other");
    assert.equal(w.localStorage.getItem(KEY), SWAPPED);
    assert.deepEqual(errors, []);
    w.close();
  }
  {
    const { w, d, errors } = await boot(undefined);
    assert.equal(order(d), DEFAULT);
    assert.equal(w.localStorage.getItem(KEY), null, "the default is not written at load");
    assert.equal(d.documentElement.classList.contains("card-order-pending"), false);
    assert.deepEqual(errors, []);
    w.close();
  }
});

// One value per kind of bad input: not JSON, wrong length, duplicates, unknown names, other types,
// and markup or a selector that must never reach the page as such.
const BAD = [
  "settings,urls",                       // not JSON
  '["settings"]',                        // too short
  '["settings","urls","urls"]',          // too long
  '["settings","settings"]',             // duplicates
  '["settings","foo"]',                  // an unknown name
  '[1,2]',                               // other types
  '{"0":"settings","1":"urls","length":2}',
  '["<img src=x onerror=alert(1)>","urls"]',
  '["#results","urls"]',
];

test("every bad stored value is ignored: the default order shows and the key is left as it was", async () => {
  for (const bad of BAD) {
    const { w, d, errors } = await boot(bad);
    assert.equal(order(d), DEFAULT, bad);
    assert.equal(w.localStorage.getItem(KEY), bad, `not rewritten at load: ${bad}`);
    assert.equal(d.querySelectorAll("img[src=x]").length, 0);
    assert.equal(d.documentElement.classList.contains("card-order-pending"), false, `cards not hidden: ${bad}`);
    assert.deepEqual(errors, [], bad);
    w.close();
  }
});

test("cardOrderParse accepts exactly the two orders and returns its own arrays", async () => {
  const { w } = await boot(undefined);
  const parse = (v) => { const r = w.cardOrderParse(v); return r && [...r]; };
  assert.deepEqual(parse('["settings","urls"]'), ["settings", "urls"]);
  assert.deepEqual(parse('["urls","settings"]'), ["urls", "settings"]);
  assert.deepEqual(parse(' [ "settings" , "urls" ] '), ["settings", "urls"], "whitespace is still JSON");
  for (const v of [...BAD, null, "", "null", "42", "true", '"settings"', "[]", '["urls","urls"]', '["Settings","urls"]', '["settings ","urls"]',
    '[null,null]', '[["settings"],"urls"]', '["__proto__","urls"]', '["urls",{"toString":"settings"}]', "[\"settings\",\"urls\"]x"]) {
    assert.equal(w.cardOrderParse(v), null, String(v));
  }
  w.close();
});

test("cardOrderApply moves the Settings panel and both cards keep their ids and listeners", async () => {
  const { w, d, saved } = await boot(undefined);
  const urls = d.getElementById("urls-card"), panel = d.getElementById("settings-panel-wrap");
  let heard = 0;
  urls.addEventListener("egm-test", () => heard++);
  panel.addEventListener("egm-test", () => heard++);
  w.cardOrderApply(["settings", "urls"]);
  assert.equal(order(d), SETTINGS_FIRST);
  assert.equal(d.getElementById("urls-card"), urls, "the same element, not a copy");
  assert.equal(d.getElementById("settings-panel-wrap"), panel);
  assert.deepEqual([...w.cardOrderNow()], ["settings", "urls"]);
  urls.dispatchEvent(new w.Event("egm-test")); panel.dispatchEvent(new w.Event("egm-test"));
  assert.equal(heard, 2);
  // the page's own listeners still work: the Settings header toggles
  d.getElementById("settings-sec-hdr").click();
  assert.equal(d.getElementById("settings-body").classList.contains("collapsed"), false);
  assert.ok(saved.some((s) => s.settings_open === true));
  w.cardOrderApply(null);
  assert.equal(order(d), DEFAULT);
  assert.equal(w.localStorage.getItem(KEY), null, "applying stores nothing");
  w.close();
});

test("the default order is never stored: moving back removes the key", async () => {
  const { w } = await boot(undefined);
  w.cardOrderSave(["settings", "urls"]);
  assert.equal(w.localStorage.getItem(KEY), SWAPPED);
  w.cardOrderSave(["urls", "settings"]);
  assert.equal(w.localStorage.getItem(KEY), null);
  w.localStorage.setItem(KEY, "junk");
  w.cardOrderSave(w.cardOrderNow());
  assert.equal(w.localStorage.getItem(KEY), null, "saving the page's default order removes even a bad value");
  w.close();
});

test("Export carries egm_card_order with Themes & preferences, and Import writes it back", async () => {
  let content = null;
  const { w, d } = await boot(SWAPPED, {
    prep(w) { w.electronAPI = { saveFile: async (name, c) => { content = c; return { ok: true }; } }; },
  });
  w._egmSelectorModal = async () => ({ settings: false, history: false, themes: true, subscriptions: false });
  d.getElementById("adv-export-btn").click();
  await wait(300);
  assert.ok(content, "export wrote a file");
  assert.equal(JSON.parse(content).localStorage[KEY], SWAPPED);
  // without Themes & preferences it stays out
  w._egmSelectorModal = async () => ({ settings: true, history: false, themes: false, subscriptions: false });
  d.getElementById("adv-export-btn").click();
  await wait(300);
  assert.equal(KEY in JSON.parse(content).localStorage, false);
  w.close();

  const reloads = [];
  const imp = await boot(undefined);
  imp.w.setTimeout = (fn, ms) => { if (String(fn).includes("location.reload")) reloads.push(ms); return 0; };   // jsdom cannot navigate
  imp.w.electronAPI = { openFile: async () => ({ content: JSON.stringify({ _egm_export_version: 4, localStorage: { [KEY]: SWAPPED } }) }) };
  imp.w._egmSelectorModal = async () => ({ settings: false, history: false, themes: true, subscriptions: false });
  imp.d.getElementById("adv-import-btn").click();
  await wait(300);
  assert.equal(imp.w.localStorage.getItem(KEY), SWAPPED);
  assert.equal(reloads.length, 1, "the page reloads to show it");
  imp.w.close();
});

// Runs Import with `lsPart` as the file's localStorage part; resolves with how many reloads were scheduled.
async function importLocalStorage(page, lsPart) {
  const reloads = [];
  page.w.setTimeout = (fn, ms) => { if (String(fn).includes("location.reload")) reloads.push(ms); return 0; };   // jsdom cannot navigate
  page.w.electronAPI = { openFile: async () => ({ content: JSON.stringify({ _egm_export_version: 4, localStorage: lsPart }) }) };
  page.w._egmSelectorModal = async () => ({ settings: false, history: false, themes: true, subscriptions: false });
  page.d.getElementById("adv-import-btn").click();
  await wait(300);
  return reloads.length;
}

test("Export always says which order the page has, the default one too, and writes nothing itself", async () => {
  let content = null;
  const { w, d } = await boot(undefined, {
    prep(w) { w.electronAPI = { saveFile: async (name, c) => { content = c; return { ok: true }; } }; },
  });
  w._egmSelectorModal = async () => ({ settings: false, history: false, themes: true, subscriptions: false });
  d.getElementById("adv-export-btn").click();
  await wait(300);
  assert.equal(JSON.parse(content).localStorage[KEY], '["urls","settings"]', "the default order is in the file");
  assert.equal(w.localStorage.getItem(KEY), null, "exporting stores nothing");
  // after a swap on the page it says so (the page decides, not an old stored value)
  w.cardOrderApply(["settings", "urls"]);
  d.getElementById("adv-export-btn").click();
  await wait(300);
  assert.equal(JSON.parse(content).localStorage[KEY], SWAPPED);
  w.close();
});

test("Import takes the file's order, the default one too, and ignores a value that is not one of the two", async () => {
  // a file with the default order puts a default order back on a machine whose cards are swapped
  {
    const page = await boot(SWAPPED);
    assert.equal(order(page.d), SETTINGS_FIRST);
    assert.equal(await importLocalStorage(page, { [KEY]: '["urls","settings"]' }), 1, "the page reloads to show it");
    assert.equal(page.w.localStorage.getItem(KEY), null, "the default order is stored as no key");
    page.w.close();
  }
  // the other way round, and a spaced but valid value is stored in its plain form
  {
    const page = await boot(undefined);
    assert.equal(await importLocalStorage(page, { [KEY]: '[ "settings" , "urls" ]' }), 1);
    assert.equal(page.w.localStorage.getItem(KEY), SWAPPED);
    page.w.close();
  }
  // anything else is left out: the machine keeps its order and nothing odd is written
  for (const bad of ["junk", "[]", '["settings"]', '["urls","urls"]', '["settings","urls","x"]', "null", 5, null, ["settings", "urls"]]) {
    const page = await boot(SWAPPED);
    await importLocalStorage(page, { [KEY]: bad, "egm-other": "kept" });
    assert.equal(page.w.localStorage.getItem(KEY), SWAPPED, `a bad value is ignored: ${JSON.stringify(bad)}`);
    assert.equal(page.w.localStorage.getItem("egm-other"), "kept", "the other keys still come across");
    page.w.close();
  }
  // a file from before this feature has no such key: the order on this machine stays
  {
    const page = await boot(SWAPPED);
    await importLocalStorage(page, { "egm-other": "x" });
    assert.equal(page.w.localStorage.getItem(KEY), SWAPPED);
    page.w.close();
  }
});

test("Reset removes egm_card_order with the other egm_ keys", async () => {
  const reloads = [];
  const { w, d } = await boot(SWAPPED, {
    onFetch: (u) => (u === "/api/settings/reset" ? { ok: true, json: async () => ({ ok: true }) } : null),
  });
  w.confirm = () => true;
  w.setTimeout = (fn, ms) => { if (String(fn).includes("location.reload")) reloads.push(ms); return 0; };
  d.getElementById("adv-reset-btn").click();
  await wait(300);
  assert.equal(w.localStorage.getItem(KEY), null);
  assert.equal(reloads.length, 1);
  w.close();
});

test("the links card shows no grip while the Settings panel is hidden, and gets it back when it is shown", async () => {
  const { w, d, errors } = await boot(SWAPPED, { settings: { show_settings_panel: false } });
  const grip = d.querySelector("#urls-card > .card-grip");
  assert.equal(d.getElementById("settings-panel-wrap").style.display, "none");
  assert.equal(order(d), SETTINGS_FIRST, "the order applies to a hidden panel too");
  assert.equal(grip.hidden, true);
  const chk = d.getElementById("show-settings-panel-chk");
  chk.checked = true; chk.dispatchEvent(new w.Event("change"));
  await wait(0);
  assert.equal(grip.hidden, false);
  // hidden again through the confirmation
  chk.checked = false; chk.dispatchEvent(new w.Event("change"));
  d.getElementById("hide-settings-confirm-btn").click();
  await wait(0);
  assert.equal(grip.hidden, true);
  assert.deepEqual(errors, []);
  w.close();
});

test("the pill is marked near only while the pointer is in the top 24px of the card and within 90px of its middle", async () => {
  const { w, d, errors } = await boot(undefined);
  for (const id of ["urls-card", "settings-panel-wrap"]) {
    const card = d.getElementById(id);
    card.getBoundingClientRect = () => ({ top: 100, left: 50, width: 760, height: 212, right: 810, bottom: 312 });   // middle at x = 430
    const at = (x, y) => { card.dispatchEvent(new w.MouseEvent("pointermove", { bubbles: true, clientX: x, clientY: y })); return card.classList.contains("card-grip-near"); };
    assert.equal(at(430, 108), true, `${id}: on the handle`);
    assert.equal(at(430 + 89, 123), true, `${id}: edge of the area`);
    assert.equal(at(430 - 89, 100), true, `${id}: edge of the area, the other side`);
    assert.equal(at(430 + 90, 108), false, `${id}: 90px aside`);
    assert.equal(at(430, 124), false, `${id}: 24px down`);
    assert.equal(at(80, 108), false, `${id}: top corner`);
    assert.equal(at(430, 200), false, `${id}: middle of the card`);
    assert.equal(at(430, 108), true);
    card.dispatchEvent(new w.MouseEvent("pointerleave"));
    assert.equal(card.classList.contains("card-grip-near"), false, `${id}: leaving the card clears it`);
  }
  assert.deepEqual(errors, []);
  w.close();
});

test("the grip is decorative, sits in the card and not in its header, and a click on it does not toggle Settings", async () => {
  const { w, d, saved } = await boot(undefined);
  for (const id of ["urls-card", "settings-panel-wrap"]) {
    const card = d.getElementById(id);
    const grips = card.querySelectorAll(".card-grip");
    assert.equal(grips.length, 1, id);
    const g = grips[0];
    assert.equal(g.parentElement, card, `${id}: a child of the card itself`);
    assert.equal(card.lastElementChild, g, `${id}: the last child (the Settings header stays the first)`);
    assert.equal(g.getAttribute("aria-hidden"), "true");
    assert.equal(g.textContent, "");
    for (const a of ["title", "aria-label", "tabindex", "role", "data-i18n", "data-i18n-attr"]) assert.equal(g.hasAttribute(a), false, `${id}: ${a}`);
  }
  assert.equal(d.querySelector("#settings-panel-wrap > :first-child").id, "settings-sec-hdr");
  d.querySelector("#settings-panel-wrap > .card-grip").click();
  assert.equal(d.getElementById("settings-body").classList.contains("collapsed"), true);
  assert.equal(saved.some((s) => "settings_open" in s), false);
  w.close();
});
