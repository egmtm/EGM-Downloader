// Main window: the saved "Quit when done" checkbox. After a download or bulk run
// completes it waits for every card to be done and for the Subscriptions window
// to be idle, then shows a 30 second countdown with Cancel in a centered card
// (no dimmed backdrop) before quitting.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const settle = () => new Promise((r) => setTimeout(r, 20));
const COUNTDOWN = 30;

async function boot({ checked = true, probeBusy = false, hidden = false } = {}) {
  const calls = { quit: [], closeSubs: 0 };
  const timers = new Map();
  const ctl = { probeBusy };
  let nextTimer = 5000;
  const t = await bootPage({
    settings: { quit_on_done: checked },
    prep(w) {
      w.setInterval = (fn) => { const id = nextTimer++; timers.set(id, fn); return id; };
      w.clearInterval = (id) => { timers.delete(id); };
      w.electronAPI = {
        platform: "win",
        quit: async (opts) => { calls.quit.push({ ...opts }); return opts && opts.probe ? { busy: ctl.probeBusy } : { success: true }; },
        closeSubscriptions: async () => { calls.closeSubs++; },
        setActivity() {}, setLanguage() {}, setTheme() {},
      };
      Object.defineProperty(w.document, "hidden", { get: () => hidden, configurable: true });
    },
  });
  return {
    ...t, calls, ctl,
    cardText: () => t.d.querySelector("#quit-card span")?.textContent ?? null,
    id: () => t.w.eval("_qodTimer"),
    tick: (id) => timers.get(id)?.(),
    // A download finishes (no card element, so the item leaves the list at once).
    finish: (extra = "") => t.w.eval(`${extra}; const it = {id: 99, status: 'downloading'}; items.push(it); applyJobDone({status:'done', progress:100, filename:'x.mp4'}, it, null, null, null, null);`),
  };
}

test("the saved checkbox is on and every card is done: probe, 30 second countdown, then quit", async () => {
  const t = await boot();
  assert.equal(t.d.getElementById("quit-on-done-chk").checked, true);
  t.finish(); await settle();
  assert.deepEqual(t.calls.quit, [{ whenIdle: true, probe: true }], "no instant quit any more");
  assert.match(t.cardText(), /Quitting in 30s/);
  const id = t.id();
  for (let i = 0; i < COUNTDOWN - 1; i++) await t.tick(id);
  assert.match(t.cardText(), /Quitting in 1s/);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 0);
  await t.tick(id);
  assert.deepEqual(t.calls.quit.filter((o) => !o.probe), [{ whenIdle: true }]);
});

test("checkbox off: nothing happens", async () => {
  const t = await boot({ checked: false });
  t.finish(); await settle();
  assert.equal(t.calls.quit.length, 0);
  assert.equal(t.cardText(), null);
});

for (const bad of ["error", "cancelled"]) {
  test(`a ${bad} card blocks the quit`, async () => {
    const t = await boot();
    t.finish(`items.push({ id: 7, status: '${bad}' })`); await settle();
    assert.equal(t.calls.quit.length, 0);
    assert.equal(t.cardText(), null);
  });
}

test("a card that was never downloaded (idle) still blocks the quit, as before", async () => {
  const t = await boot();
  t.finish("items.push({ id: 8, status: 'idle' })"); await settle();
  assert.equal(t.calls.quit.length, 0);
});

test("Cancel skips this exit only: the saved checkbox stays on and nothing is saved", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  await t.tick(id);
  const savedBefore = t.saved.length;   // the page may save other settings while booting
  t.d.querySelector("#quit-card button").click();
  assert.equal(t.cardText(), null);
  for (let i = 0; i < COUNTDOWN + 2; i++) await t.tick(id);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 0);
  assert.equal(t.d.getElementById("quit-on-done-chk").checked, true);
  assert.equal(t.saved.length, savedBefore, "Cancel saves nothing");
  assert.ok(!t.saved.some((b) => "quit_on_done" in b), "the saved setting is never touched");
});

test("waits while the Subscriptions window is still downloading, then counts down", async () => {
  const t = await boot({ probeBusy: true });
  t.finish(); await settle();
  assert.equal(t.cardText(), null);
  const id = t.id();
  await t.tick(id);
  assert.equal(t.cardText(), null, "still waiting");
  t.ctl.probeBusy = false;
  await t.tick(id);
  assert.match(t.cardText(), /Quitting in 30s/);
});

test("a refused final quit (Subscriptions got busy) drops the countdown and waits again", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  t.ctl.probeBusy = true;
  const realQuit = t.w.electronAPI.quit;
  t.w.electronAPI.quit = async (o) => (o && o.probe ? { busy: true } : (t.calls.quit.push({ ...o }), { busy: true }));
  for (let i = 0; i < COUNTDOWN; i++) await t.tick(id);
  assert.equal(t.cardText(), null);
  assert.ok(t.w.eval("_qodTimer"), "still waiting");
  t.w.electronAPI.quit = realQuit;
});

test("starting another download during the countdown stops it", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  await t.tick(id);
  assert.ok(t.cardText());
  t.w.eval("items.push({ id: 50, status: 'downloading' })");
  await t.tick(id);
  assert.equal(t.cardText(), null);
  assert.equal(t.w.eval("_qodTimer"), null);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 0);
});

test("unchecking the box during the countdown stops it", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  t.d.getElementById("quit-on-done-chk").checked = false;
  await t.tick(id);
  assert.equal(t.cardText(), null);
});

test("hidden behind the Subscriptions window: the countdown brings the main window back", async () => {
  const t = await boot({ hidden: true });
  t.finish(); await settle();
  assert.equal(t.calls.closeSubs, 1);
});

test("a visible main window is left alone (Subscriptions is not closed)", async () => {
  const t = await boot({ hidden: false });
  t.finish(); await settle();
  assert.equal(t.calls.closeSubs, 0);
});

test("the countdown is a card in the middle of the page, not a corner toast, and nothing dims the page", async () => {
  const t = await boot();
  t.finish(); await settle();
  const card = t.d.getElementById("quit-card");
  assert.ok(card, "the card is there");
  assert.equal(card.parentElement, t.d.body, "on the page itself, not inside the toast corner");
  assert.equal(card.closest(".modal-backdrop"), null, "no dimmed backdrop around it");
  assert.ok([...t.d.querySelectorAll("#toasts .toast")].every((el) => !/Quitting/.test(el.textContent)),
    "the countdown is not a corner toast any more (other toasts, such as Done, are unaffected)");
  const st = t.w.getComputedStyle(card);
  assert.equal(st.position, "fixed");
  assert.equal(st.top, "50%");
  assert.equal(st.left, "50%");
  assert.equal(card.querySelector("button").textContent, "Cancel", "the existing Cancel text is reused");
});

test("the card goes away with the countdown and is never shown twice", async () => {
  const t = await boot();
  t.finish(); await settle();
  await t.tick(t.id());
  assert.equal(t.d.querySelectorAll("#quit-card").length, 1);
  t.w.eval("items.push({ id: 60, status: 'downloading' })");
  await t.tick(t.id());
  assert.equal(t.d.querySelectorAll("#quit-card").length, 0);
});


// ── Round 4 review ──────────────────────────────────────────────────────────
test("Cancel stops the countdown's timer, not only the card", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  t.d.querySelector("#quit-card button").click();
  assert.equal(t.cardText(), null);
  assert.equal(t.w.eval("_qodTimer"), null);
  await t.tick(id);                                  // a leaked interval would probe again
  assert.equal(t.calls.quit.length, 1);
});

test("a link being fetched during the countdown stops it: the user is adding work", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  t.d.getElementById("fetch-btn").disabled = true;   // fetchAll disables it until the link is in the list
  await t.tick(id);
  assert.equal(t.cardText(), null);
  for (let i = 0; i < COUNTDOWN + 1; i++) await t.tick(id);
  assert.deepEqual(t.calls.quit.filter((o) => !o.probe), [], "no quit while the fetch runs");
});

test("after the final quit call the countdown stops, even when the call failed", async () => {
  const t = await boot();
  t.w.electronAPI.quit = async (opts) => { t.calls.quit.push({ ...opts }); return opts && opts.probe ? { busy: false } : { error: "x" }; };
  t.finish(); await settle();
  const id = t.id();
  for (let i = 0; i < COUNTDOWN; i++) await t.tick(id);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 1);
  for (let i = 0; i < 3; i++) await t.tick(id);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 1, "not asked again every second");
  assert.equal(t.cardText(), null, "no frozen 'Quitting in 1s' card");
});

test("the countdown label is set as text, and Cancel is a themed button", async () => {
  const t = await boot();
  t.w.eval("I18N.strings['subscriptions.queue.quitting_in'] = '<b>{0}</b>'");
  t.finish(); await settle();
  assert.equal(t.d.querySelector("#quit-card span").textContent, "<b>30</b>");
  assert.equal(t.d.querySelector("#quit-card b"), null);
  assert.equal(t.d.querySelector("#quit-card").getAttribute("role"), "alert");
  assert.ok(t.d.querySelector("#quit-card button").classList.contains("btn-ghost"));
});
