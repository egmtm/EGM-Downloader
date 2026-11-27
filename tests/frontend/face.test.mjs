// The Face of the main window (egm_face): v2 by default, Classic on request. Read before the page is
// drawn, switched with no reload, independent of the theme. jsdom has no layout and no view
// transitions, so how the switch looks is not covered here; what it does to the page and the storage is.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, CURRENT_APP_VERSION } from "./harness.mjs";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Boots the page with egm_face set to `stored` (or absent), collecting uncaught errors.
async function boot(stored, opts = {}) {
  const errors = [];
  const page = await bootPage({
    ...opts,
    prep(w) {
      w.addEventListener("error", (e) => errors.push(e.message));
      if (stored !== undefined) w.localStorage.setItem("egm_face", stored);
      if (opts.prep) opts.prep(w);
    },
  });
  // the names live in one place in the page; the tests read them from there
  const { FACE_KEY: KEY, FACE_CLASS: CLS } = page.w;
  return { ...page, errors, KEY, CLS, isV2: () => page.d.body.classList.contains(CLS) };
}

test("the names are the placeholders, and each is written once in the page's scripts", async () => {
  const { w, d, KEY, CLS } = await boot(undefined);
  assert.equal(KEY, "egm_face");
  assert.equal(CLS, "face-v2");
  const scripts = [...d.querySelectorAll("script")].map((s) => s.textContent).join("\n");
  assert.equal(w.FACE_PROMPT_KEY, "egm_face_prompt");
  for (const name of [KEY, CLS, w.FACE_PROMPT_KEY]) {
    assert.equal(scripts.split(`'${name}'`).length - 1 + scripts.split(`"${name}"`).length - 1, 1, `${name} is a constant in one place`);
  }
  w.close();
});

test("no key gives v2, classic gives Classic, v2 gives v2, and nothing is written at load", async () => {
  for (const [stored, v2] of [[undefined, true], ["classic", false], ["v2", true]]) {
    const { w, d, errors, KEY, isV2 } = await boot(stored);
    assert.equal(isV2(), v2, `stored ${stored}`);
    assert.equal(w.faceNow(), v2 ? "v2" : "classic");
    assert.equal(w.localStorage.getItem(KEY), stored === undefined ? null : stored, "the key is as it was");
    assert.equal(d.getElementById("face-select").value, v2 ? "v2" : "classic", "the dropdown shows it");
    assert.deepEqual(errors, []);
    w.close();
  }
});

// One value per kind of bad input: other case, spaces, the class itself, markup, JSON, the empty string.
const BAD = ["Classic", "CLASSIC", " classic", "classic ", "v1", "face-v2", "classic face-v2", "<img src=x onerror=alert(1)>", '"classic"', "null", "0", ""];

test("a bad stored value gives v2, throws nothing and is left as it was", async () => {
  for (const bad of BAD) {
    const { w, d, errors, KEY, CLS, isV2 } = await boot(bad);
    assert.equal(isV2(), true, JSON.stringify(bad));
    assert.equal(d.body.className.split(/\s+/).filter(Boolean).join(" "), CLS, `only the Face class is on body: ${JSON.stringify(bad)}`);
    assert.equal(w.localStorage.getItem(KEY), bad, "not rewritten at load");
    assert.equal(d.querySelectorAll("img[src=x]").length, 0);
    assert.deepEqual(errors, [], JSON.stringify(bad));
    w.close();
  }
});

test("storage that cannot be read gives v2 and throws nothing", async () => {
  const { w } = await boot("classic");
  const real = w.Storage.prototype.getItem;
  w.Storage.prototype.getItem = () => { throw new Error("storage is off"); };
  try { assert.equal(w.faceStored(), "v2"); } finally { w.Storage.prototype.getItem = real; }
  assert.equal(w.faceStored(), "classic");
  w.close();
});

test("the boot script is the first thing in body, before anything that is drawn", async () => {
  const { w, d } = await boot(undefined);
  const first = d.body.firstElementChild;
  assert.equal(first.tagName, "SCRIPT");
  assert.match(first.textContent, /faceBoot\(\);/);
  assert.equal(first.nextElementSibling.tagName, "HEADER");
  w.close();
});

test("applyFace changes the class, stores the value and updates the dropdown, with no reload", async () => {
  const { dom, w, d, errors, KEY, isV2 } = await boot(undefined);
  const jsdomErrors = [];
  dom.virtualConsole.on("jsdomError", (e) => jsdomErrors.push(e.message));   // a reload or a navigation is reported here
  const fetched = [];
  const realFetch = w.fetch;
  w.fetch = (u, o) => { fetched.push(u); return realFetch(u, o); };
  const timers = [];
  const realTimeout = w.setTimeout;
  w.setTimeout = (fn, ms) => { timers.push(String(fn)); return realTimeout(fn, ms); };
  w.__kept = { n: 1 };
  const urls = d.getElementById("urls");
  urls.value = "https://example.com/a";
  const href = w.location.href;

  w.applyFace("classic");
  assert.equal(isV2(), false);
  assert.equal(w.localStorage.getItem(KEY), "classic");
  assert.equal(d.getElementById("face-select").value, "classic");
  assert.equal(d.documentElement.classList.contains("face-switching"), false, "the switching mark is gone");

  w.applyFace("v2");
  assert.equal(isV2(), true);
  assert.equal(w.localStorage.getItem(KEY), "v2", "v2 is stored as a value, not as no key");
  assert.equal(d.getElementById("face-select").value, "v2");

  await wait(50);
  assert.deepEqual(w.__kept, { n: 1 }, "the page is the same page");
  assert.equal(d.getElementById("urls"), urls, "the same elements");
  assert.equal(urls.value, "https://example.com/a", "what was typed stays");
  assert.equal(w.location.href, href);
  assert.deepEqual(fetched, [], "the switch asks the backend nothing");
  assert.equal(timers.some((t) => t.includes("reload")), false, "no reload is scheduled");
  assert.deepEqual(jsdomErrors, []);
  assert.deepEqual(errors, []);
  w.close();
});

test("applyFace takes only classic as Classic: anything else is v2, and it never throws", async () => {
  const { w, errors, KEY, CLS, d, isV2 } = await boot("classic");
  for (const bad of [undefined, null, 5, {}, [], ...BAD]) {
    w.applyFace("classic");
    w.applyFace(bad);
    assert.equal(isV2(), true, JSON.stringify(bad));
    assert.equal(w.localStorage.getItem(KEY), "v2", `stored as v2: ${JSON.stringify(bad)}`);
    assert.equal(d.body.className.split(/\s+/).filter(Boolean).join(" "), CLS);
  }
  assert.deepEqual(errors, []);
  w.close();
});

test("the same Face again changes nothing and starts no transition", async () => {
  const { w, d, isV2 } = await boot(undefined);
  let started = 0;
  d.startViewTransition = (fn) => { started++; fn(); return { ready: Promise.resolve(), finished: Promise.resolve() }; };
  w.applyFace("v2");
  assert.equal(started, 0);
  assert.equal(isV2(), true);
  assert.equal(d.documentElement.classList.contains("face-switching"), false);
  w.close();
});

// A stand in for the browser's view transition: it runs the callback later, as the browser does
// (after it has captured the old look), and lets the test end the transition.
function fakeTransitions(d) {
  const made = [];
  d.startViewTransition = (fn) => {
    const t = { fn, ran: false };
    t.ready = new Promise((res, rej) => { t.skip = () => rej(new Error("skipped")); t.go = res; });
    t.finished = new Promise((res) => { t.end = res; });
    t.run = () => { if (!t.ran) { t.ran = true; fn(); } };
    made.push(t);
    return t;
  };
  return made;
}

test("with motion allowed the switch runs as a view transition, and the mark stays until it has finished", async () => {
  const { w, d, errors, KEY, isV2 } = await boot(undefined);
  const made = fakeTransitions(d);
  w.applyFace("classic");
  assert.equal(made.length, 1, "one transition is started");
  assert.equal(w.localStorage.getItem(KEY), "classic", "the choice is stored at once");
  assert.equal(isV2(), true, "the class changes inside the transition, after the old look is captured");
  assert.equal(d.documentElement.classList.contains("face-switching"), true);
  made[0].run();
  assert.equal(isV2(), false);
  assert.equal(d.documentElement.classList.contains("face-switching"), true, "still on while it is drawn");
  made[0].go(); made[0].end();
  await wait(0);
  assert.equal(d.documentElement.classList.contains("face-switching"), false);
  assert.deepEqual(errors, []);
  w.close();
});

test("with reduced motion on the switch is instant: no view transition is started", async () => {
  const { w, d, isV2 } = await boot(undefined, {
    prep(w) { w.matchMedia = (q) => ({ matches: /prefers-reduced-motion:\s*reduce/.test(q), addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }); },
  });
  const made = fakeTransitions(d);
  w.applyFace("classic");
  assert.equal(made.length, 0);
  assert.equal(isV2(), false, "changed in the same call");
  assert.equal(d.documentElement.classList.contains("face-switching"), false);
  w.applyFace("v2");
  assert.equal(made.length, 0);
  assert.equal(isV2(), true);
  w.close();
});

test("a second choice before the first one is drawn wins, and the page ends on what is stored", async () => {
  const { w, d, KEY, isV2 } = await boot(undefined);
  const made = fakeTransitions(d);
  w.applyFace("classic");          // started, its callback has not run yet
  w.applyFace("v2");               // the person changes their mind
  assert.equal(w.localStorage.getItem(KEY), "v2");
  made.forEach((t) => t.run());
  assert.equal(isV2(), true, "the page shows the last choice");
  assert.equal(d.getElementById("face-select").value, "v2");
  made.forEach((t) => { t.go(); t.end(); });
  await wait(0);
  assert.equal(d.documentElement.classList.contains("face-switching"), false);

  // and when the first one is already drawn, the second starts its own transition; the first one ending does not take the mark off early
  w.applyFace("classic"); made.at(-1).run();
  const first = made.at(-1);
  w.applyFace("v2");
  assert.notEqual(made.at(-1), first, "a new transition");
  first.go(); first.end();
  await wait(0);
  assert.equal(d.documentElement.classList.contains("face-switching"), true, "the newer switch keeps the mark");
  made.at(-1).run(); made.at(-1).go(); made.at(-1).end();
  await wait(0);
  assert.equal(isV2(), true);
  assert.equal(d.documentElement.classList.contains("face-switching"), false);
  w.close();
});

test("a transition the browser skips still switches, takes the mark off and leaves no unhandled rejection", async () => {
  const { w, d, isV2 } = await boot(undefined);
  const unhandled = [];
  const onUnhandled = (reason) => unhandled.push(String(reason));
  process.on("unhandledRejection", onUnhandled);
  try {
    const made = fakeTransitions(d);
    w.applyFace("classic");
    made[0].run(); made[0].skip(); made[0].end();
    await wait(20);
    assert.equal(isV2(), false);
    assert.equal(d.documentElement.classList.contains("face-switching"), false);
    assert.deepEqual(unhandled, []);
  } finally { process.off("unhandledRejection", onUnhandled); }
  w.close();
});

test("a theme change keeps the Face, and a Face change keeps the theme", async () => {
  const { w, d, errors, CLS } = await boot(undefined);
  const classes = () => [...d.body.classList].sort().join(" ");
  w.applyTheme("eclipse");
  assert.equal(classes(), ["eclipse", CLS].sort().join(" "), "v2 survives a theme change");
  w.applyFace("classic");
  assert.equal(classes(), "eclipse", "the theme survives a Face change");
  w.applyTheme("ghost");
  assert.equal(classes(), "ghost", "Classic survives a theme change");
  w.applyFace("v2");
  assert.equal(classes(), [CLS, "ghost"].sort().join(" "));
  w.applyTheme("void");
  assert.equal(classes(), CLS, "the default theme is no class, the Face stays");
  assert.equal(w.localStorage.getItem("egm-theme"), "void");
  assert.deepEqual(errors, []);
  w.close();
});

test("the Face dropdown is the first control of the Themes tab, above Create theme, and choosing switches", async () => {
  const { w, d, KEY, isV2 } = await boot(undefined);
  const tab = d.getElementById("hpanel-themes");
  const sel = d.getElementById("face-select");
  assert.ok(tab.contains(sel));
  assert.ok(sel.compareDocumentPosition(d.getElementById("theme-create-btn")) & w.Node.DOCUMENT_POSITION_FOLLOWING, "above Create theme");
  assert.equal(tab.querySelector("select, button, input"), sel, "the first control in the tab");
  assert.deepEqual([...sel.options].map((o) => o.value), ["v2", "classic"]);
  sel.value = "classic"; sel.dispatchEvent(new w.Event("change"));
  assert.equal(isV2(), false);
  assert.equal(w.localStorage.getItem(KEY), "classic");
  sel.value = "v2"; sel.dispatchEvent(new w.Event("change"));
  assert.equal(isV2(), true);
  assert.equal(w.localStorage.getItem(KEY), "v2");
  w.close();
});

// ── The one time question after What's New ──────────────────────────────────
const shown = (d, id) => d.getElementById(id).style.display !== "none";
const gotIt = async (d) => { d.getElementById("whats-new-dismiss-btn").click(); await wait(0); };
// What's New shows by itself at load when this version has not been seen yet (the harness default).
const PROMPT = "face-prompt-modal";

test("the question shows once, right after What's New closes, and not before", async () => {
  const { w, d, errors, saved, isV2 } = await boot(undefined);
  const SHOWN = w.FACE_PROMPT_KEY;
  assert.equal(shown(d, "whats-new-modal"), true, "What's New is up on a first launch");
  assert.equal(shown(d, PROMPT), false, "the question waits behind it");
  assert.equal(w.localStorage.getItem(SHOWN), null);
  await gotIt(d);
  assert.equal(shown(d, "whats-new-modal"), false);
  assert.equal(shown(d, PROMPT), true, "Got it brings the question");
  assert.equal(d.getElementById(PROMPT).style.display, "flex");
  assert.equal(w.localStorage.getItem(SHOWN), "1", "remembered as soon as it is shown");
  assert.equal(isV2(), true, "the page stays v2 while it asks");
  assert.equal(w.localStorage.getItem("egm_face"), null, "asking stores no choice");
  assert.ok(saved.some((s) => s.last_seen_version === CURRENT_APP_VERSION), "Got it still marks the version as seen");
  assert.deepEqual(errors, []);
  w.close();
});

test("the question has two choices, v2 and Classic, a close button, and looks like the app's other questions", async () => {
  const { w, d } = await boot(undefined);
  const modal = d.getElementById(PROMPT);
  assert.ok(modal.classList.contains("modal-backdrop"));
  assert.equal(modal.style.display, "none", "hidden at load");
  assert.equal(modal.children.length, 1);
  assert.ok(modal.firstElementChild.classList.contains("modal"));
  const choices = [...modal.querySelectorAll(".modal-actions button")];
  assert.deepEqual(choices.map((b) => b.id), ["face-prompt-classic-btn", "face-prompt-v2-btn"]);
  assert.ok(choices[1].classList.contains("btn-primary"), "v2, the default, is the main button");
  assert.deepEqual([...modal.querySelectorAll("button")].map((b) => b.id).sort(), ["face-prompt-classic-btn", "face-prompt-close-btn", "face-prompt-v2-btn"]);
  assert.equal(modal.querySelectorAll("h3").length, 1);
  assert.equal(modal.querySelectorAll("p").length, 1);
  // a click beside the box is not an answer and does not close it
  await gotIt(d);
  modal.dispatchEvent(new w.MouseEvent("click", { bubbles: true }));
  assert.equal(shown(d, PROMPT), true);
  w.close();
});

test("choosing Classic switches to it, closes the question and it is not asked again", async () => {
  const { w, d, errors, isV2 } = await boot(undefined);
  await gotIt(d);
  d.getElementById("face-prompt-classic-btn").click();
  assert.equal(shown(d, PROMPT), false);
  assert.equal(isV2(), false);
  assert.equal(w.localStorage.getItem("egm_face"), "classic");
  assert.equal(d.getElementById("face-select").value, "classic", "the dropdown in Themes agrees");
  // What's New opened again from the footer, and closed: no second question
  d.getElementById("footer-version-pill").click();
  await wait(20);
  assert.equal(shown(d, "whats-new-modal"), true);
  await gotIt(d);
  assert.equal(shown(d, PROMPT), false);
  assert.equal(isV2(), false);
  assert.deepEqual(errors, []);
  w.close();
});

test("choosing v2 keeps v2, stores it, closes the question and it is not asked again", async () => {
  const { w, d, isV2 } = await boot(undefined);
  await gotIt(d);
  d.getElementById("face-prompt-v2-btn").click();
  assert.equal(shown(d, PROMPT), false);
  assert.equal(isV2(), true);
  assert.equal(w.localStorage.getItem("egm_face"), "v2");
  d.getElementById("footer-version-pill").click();
  await wait(20);
  await gotIt(d);
  assert.equal(shown(d, PROMPT), false);
  w.close();
});

// Boots a second page with the storage the first one left, as the next launch would find it.
async function nextLaunch(prev, opts = {}) {
  const kept = {};
  for (let i = 0; i < prev.localStorage.length; i++) { const k = prev.localStorage.key(i); kept[k] = prev.localStorage.getItem(k); }
  return boot(undefined, { ...opts, prep(w) { for (const [k, v] of Object.entries(kept)) w.localStorage.setItem(k, v); } });
}

test("closing the question without a choice keeps v2, stores no choice, and it is not asked again, not on the next launch either", async () => {
  const first = await boot(undefined);
  await gotIt(first.d);
  first.d.getElementById("face-prompt-close-btn").click();
  assert.equal(shown(first.d, PROMPT), false);
  assert.equal(first.isV2(), true);
  assert.equal(first.w.localStorage.getItem("egm_face"), null, "no choice was made, so none is stored");
  first.d.getElementById("footer-version-pill").click();
  await wait(20);
  await gotIt(first.d);
  assert.equal(shown(first.d, PROMPT), false, "not again in this session");
  // the next launch, with What's New up again (a newer version): still not asked
  const next = await nextLaunch(first.w);
  assert.equal(shown(next.d, "whats-new-modal"), true);
  await gotIt(next.d);
  assert.equal(shown(next.d, PROMPT), false, "not again on the next launch");
  assert.equal(next.isV2(), true);
  first.w.close(); next.w.close();
});

test("with this version already seen there is no What's New at load and no question", async () => {
  const { w, d } = await boot(undefined, { settings: { last_seen_version: CURRENT_APP_VERSION } });
  assert.equal(shown(d, "whats-new-modal"), false);
  assert.equal(shown(d, PROMPT), false);
  assert.equal(w.localStorage.getItem(w.FACE_PROMPT_KEY), null, "not marked as shown: it will be asked after the next What's New");
  w.close();
});

test("after Reset settings the question is asked again", async () => {
  const first = await boot(undefined, {
    onFetch: (u) => (u === "/api/settings/reset" ? { ok: true, json: async () => ({ ok: true }) } : null),
  });
  await gotIt(first.d);
  first.d.getElementById("face-prompt-classic-btn").click();
  assert.equal(first.w.localStorage.getItem(first.w.FACE_PROMPT_KEY), "1");
  first.w.confirm = () => true;
  first.w.setTimeout = (fn, ms) => 0;   // jsdom cannot reload; the next launch is booted below
  first.d.getElementById("adv-reset-btn").click();
  await wait(300);
  assert.equal(first.w.localStorage.getItem(first.w.FACE_PROMPT_KEY), null, "Reset forgets that it was asked");
  const next = await nextLaunch(first.w);
  assert.equal(shown(next.d, "whats-new-modal"), true, "after a reset What's New shows again");
  assert.equal(shown(next.d, PROMPT), false);
  await gotIt(next.d);
  assert.equal(shown(next.d, PROMPT), true, "and the question follows it");
  first.w.close(); next.w.close();
});

test("when it cannot be remembered the question is not asked, and nothing throws", async () => {
  const { w, d, errors } = await boot(undefined);
  const real = w.Storage.prototype.setItem;
  w.Storage.prototype.setItem = () => { throw new Error("storage is full"); };
  try {
    await gotIt(d);
    assert.equal(shown(d, PROMPT), false);
  } finally { w.Storage.prototype.setItem = real; }
  assert.deepEqual(errors, []);
  w.close();
});

// ── Reset, Export and Import ────────────────────────────────────────────────
const seen = { last_seen_version: CURRENT_APP_VERSION };   // no What's New at load: these tests are not about the question

test("Reset settings leaves v2 on the page at once, with no theme class, and the next launch is v2", async () => {
  for (const stored of ["classic", "v2", undefined]) {
    const first = await boot(stored, {
      settings: seen,
      onFetch: (u) => (u === "/api/settings/reset" ? { ok: true, json: async () => ({ ok: true }) } : null),
    });
    first.w.applyTheme("eclipse");
    const reloads = [];
    first.w.confirm = () => true;
    first.w.setTimeout = (fn, ms) => { if (String(fn).includes("location.reload")) reloads.push(ms); return 0; };   // jsdom cannot reload
    first.d.getElementById("adv-reset-btn").click();
    await wait(300);
    assert.equal(first.d.body.className.trim(), first.CLS, `after Reset the page is v2 and nothing else (was ${stored})`);
    assert.equal(first.w.localStorage.getItem(first.KEY), null, "the stored Face is gone with the other egm_ keys");
    assert.equal(reloads.length, 1, "the reload Reset already did is still scheduled");
    const next = await nextLaunch(first.w);
    assert.equal(next.isV2(), true, "the next launch is v2");
    assert.deepEqual(first.errors, []);
    first.w.close(); next.w.close();
  }
});

// Runs Export with only Themes & preferences ticked (or only Settings) and returns the file's content.
async function exportFile(stored, { themes = true, before } = {}) {
  let content = null;
  const page = await boot(stored, {
    settings: seen,
    prep(w) { w.electronAPI = { saveFile: async (name, c) => { content = c; return { ok: true }; } }; },
  });
  if (before) before(page);
  const keysBefore = page.w.localStorage.getItem(page.KEY);
  page.w._egmSelectorModal = async () => ({ settings: !themes, history: false, themes, subscriptions: false });
  page.d.getElementById("adv-export-btn").click();
  await wait(300);
  assert.ok(content, "export wrote a file");
  assert.equal(page.w.localStorage.getItem(page.KEY), keysBefore, "exporting stores nothing");
  page.w.close();
  return JSON.parse(content);
}

test("Export always says which Face the page shows, v2 with no key too", async () => {
  assert.equal((await exportFile(undefined)).localStorage.egm_face, "v2", "the default, stored as no key, is written as v2");
  assert.equal((await exportFile("classic")).localStorage.egm_face, "classic");
  assert.equal((await exportFile("v2")).localStorage.egm_face, "v2");
  assert.equal((await exportFile("junk")).localStorage.egm_face, "v2", "a bad stored value is exported as what the page shows");
  // the page decides, not an old stored value
  assert.equal((await exportFile(undefined, { before: (p) => p.w.applyFace("classic") })).localStorage.egm_face, "classic");
  // without Themes & preferences it stays out
  assert.equal("egm_face" in (await exportFile("classic", { themes: false })).localStorage, false);
});

// Runs Import of `file` on `page` with Themes & preferences ticked; resolves with how many reloads were scheduled.
async function importFile(page, file) {
  const reloads = [];
  page.w.setTimeout = (fn, ms) => { if (String(fn).includes("location.reload")) reloads.push(ms); return 0; };   // jsdom cannot reload
  page.w.electronAPI = { openFile: async () => ({ content: JSON.stringify(file) }) };
  page.w._egmSelectorModal = async () => ({ settings: false, history: false, themes: true, subscriptions: false });
  page.d.getElementById("adv-import-btn").click();
  await wait(300);
  return reloads.length;
}

test("Export then Import on a clean profile carries the Face both ways: Classic to a v2 profile, v2 to a Classic profile", async () => {
  // a Classic machine exports; a clean profile (v2, no key) imports and is Classic at its next launch
  {
    const file = await exportFile("classic");
    const clean = await boot(undefined, { settings: seen });
    assert.equal(clean.isV2(), true, "a clean profile starts as v2");
    assert.equal(await importFile(clean, file), 1, "the page reloads to show it");
    assert.equal(clean.w.localStorage.getItem(clean.KEY), "classic");
    const next = await nextLaunch(clean.w, { settings: seen });
    assert.equal(next.isV2(), false, "Classic after the reload");
    assert.equal(next.d.getElementById("face-select").value, "classic");
    clean.w.close(); next.w.close();
  }
  // a v2 machine that never chose (no key) exports; a profile set to Classic imports and is v2 at its next launch
  {
    const file = await exportFile(undefined);
    const other = await boot("classic", { settings: seen });
    assert.equal(other.isV2(), false);
    assert.equal(await importFile(other, file), 1);
    assert.equal(other.w.localStorage.getItem(other.KEY), "v2", "the file's v2 replaces the stored Classic");
    const next = await nextLaunch(other.w, { settings: seen });
    assert.equal(next.isV2(), true, "v2 after the reload");
    assert.equal(next.d.getElementById("face-select").value, "v2");
    other.w.close(); next.w.close();
  }
});

test("Import of a file without a Face, or with one that is not text, leaves this machine's Face alone", async () => {
  for (const ls of [{ "egm-other": "x" }, { egm_face: 5, "egm-other": "x" }, { egm_face: null, "egm-other": "x" }, { egm_face: ["classic"], "egm-other": "x" }]) {
    const page = await boot("classic", { settings: seen });
    await importFile(page, { _egm_export_version: 4, localStorage: ls });
    assert.equal(page.w.localStorage.getItem(page.KEY), "classic", JSON.stringify(ls));
    assert.equal(page.w.localStorage.getItem("egm-other"), "x", "the other keys still come across");
    page.w.close();
  }
});

test("Import of a Face that is neither value cannot break the page: the next launch is v2 and throws nothing", async () => {
  const page = await boot("classic", { settings: seen });
  await importFile(page, { _egm_export_version: 4, localStorage: { egm_face: "<img src=x onerror=alert(1)>" } });
  const next = await nextLaunch(page.w, { settings: seen });
  assert.equal(next.isV2(), true);
  assert.equal(next.d.body.className.trim(), next.CLS);
  assert.equal(next.d.querySelectorAll("img[src=x]").length, 0);
  assert.deepEqual(next.errors, []);
  page.w.close(); next.w.close();
});
