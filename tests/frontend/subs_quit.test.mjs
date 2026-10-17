// Subscriptions window: "Quit when done" (queue header toggle + 30 s countdown in a
// centered card over a dimmed page that is locked while it shows; Esc works like Cancel).
// Boots the real rendered Subscriptions page; intervals are captured so each
// test drives pollJobs() and the countdown by hand.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootSubsPage, en, trackKeydown } from "./harness.mjs";

const settle = () => new Promise((r) => setTimeout(r, 20));
const COUNTDOWN = 30;
const armed = (t) => t.w.eval("quitWhenDone");
const bar = (t) => t.d.getElementById("quit-card");
const realQuits = (t) => t.calls.quit.filter((o) => !o.probe);

// Queue with one running download and the toggle switched on.
async function armedQueue(opts) {
  const t = await bootSubsPage(opts);
  t.addJob("v1", "j1");
  t.d.querySelector("#detail input.sw").click();
  assert.equal(armed(t), true);
  return t;
}

// Run the whole countdown. "30s" is shown immediately; each 1 s interval tick
// then shows 29s ... 1s, and the 30th tick (30 seconds in) quits.
function runCountdown(t) {
  const id = t.w.eval("_quitTimer");
  for (let i = 0; i < COUNTDOWN; i++) t.tick(id);
}

test("the toggle is in the queue header, reuses the main UI string, and starts off", async () => {
  const t = await bootSubsPage();
  t.addJob("v1", "j1");
  const label = t.d.querySelector("#detail .sw-wrap");
  assert.ok(label, "toggle present while downloads run");
  assert.equal(label.textContent.trim(), en.strings["advanced.toggle.quit_when_done"]);
  assert.equal(label.title, en.strings["tooltip.quit_when_done"]);
  assert.equal(t.d.querySelector("#detail input.sw").checked, false);
});

test("all downloads done: 30 second countdown, then quits (and only then)", async () => {
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  assert.deepEqual(t.calls.quit, [{ whenIdle: true, probe: true }], "probe only, no quit yet");
  assert.match(bar(t).textContent, /Quitting in 30s/);
  const id = t.w.eval("_quitTimer");
  for (let i = 0; i < COUNTDOWN - 1; i++) t.tick(id);
  assert.match(bar(t).textContent, /Quitting in 1s/);
  assert.equal(realQuits(t).length, 0, "still counting");
  t.tick(id);
  assert.deepEqual(realQuits(t), [{ whenIdle: true }]);
  assert.equal(bar(t), null);
});

test("Cancel during the countdown keeps the app open and turns the toggle off", async () => {
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  const id = t.w.eval("_quitTimer");
  t.tick(id); t.tick(id);
  bar(t).querySelector("button").click();
  assert.equal(bar(t), null);
  assert.equal(armed(t), false);
  for (let i = 0; i < COUNTDOWN + 2; i++) t.tick(id);
  assert.equal(realQuits(t).length, 0);
});

for (const failure of ["error", "cancelled"]) {
  test(`a ${failure} download turns the toggle off and the app does not quit`, async () => {
    const t = await armedQueue();
    t.status.j1 = failure;
    await t.poll(); await settle();
    assert.equal(armed(t), false);
    assert.equal(t.calls.quit.length, 0, "no probe, no countdown, no quit");
    assert.equal(bar(t), null);
  });
}

test("an error among several downloads still blocks the quit after the rest finish", async () => {
  const t = await armedQueue();
  t.addJob("v2", "j2");                       // addJob re-renders; the toggle state survives
  assert.equal(t.d.querySelector("#detail input.sw").checked, true);
  t.status.j1 = "error"; t.status.j2 = "done";
  await t.poll(); await settle();
  assert.equal(t.calls.quit.length, 0);
});

test("no countdown while another window is still downloading; starts once it is idle", async () => {
  const t = await armedQueue({ probeBusy: true });
  t.status.j1 = "done";
  await t.poll(); await settle();
  assert.equal(bar(t), null);
  assert.equal(armed(t), true, "stays on, waiting");
  t.ctl.probeBusy = false;
  await t.poll(); await settle();
  assert.match(bar(t).textContent, /Quitting in 30s/);
});

test("a refused final quit (main window got busy) keeps the toggle on and waits again", async () => {
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  t.ctl.probeBusy = true;                     // main window started a download during the countdown
  runCountdown(t);
  assert.equal(bar(t), null);
  assert.equal(armed(t), true);
  await t.poll(); await settle();
  assert.equal(bar(t), null, "no new countdown while busy");
});

test("new downloads during the countdown cancel it but stay armed", async () => {
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  assert.ok(bar(t));
  t.addJob("v2", "j2");
  await t.poll(); await settle();
  assert.equal(bar(t), null);
  assert.equal(armed(t), true);
  t.status.j2 = "done";
  await t.poll(); await settle();
  assert.match(bar(t).textContent, /Quitting in 30s/);
});

test("the choice is never saved", async () => {
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  runCountdown(t);
  assert.equal(t.calls.fetch.filter((u) => /settings\/save/.test(u)).length, 0);
  assert.equal(t.w.localStorage.length, 0);
  assert.equal(t.w.sessionStorage.length, 0);
});

test("a download queued in the last second of the countdown is not cut off", async () => {
  // whenIdle only counts OTHER windows, and pollJobs (every 1.5 s) is what
  // notices a new job here -- so a job added between the last poll and the
  // final tick reached the quit call while it was still running.
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  const id = t.w.eval("_quitTimer");
  for (let i = 0; i < COUNTDOWN - 1; i++) t.tick(id);
  t.addJob("v2", "j2");                 // queued, no poll before the final tick
  t.tick(id);
  assert.equal(realQuits(t).length, 0, "must not quit while this window has a running job");
  assert.equal(armed(t), true, "the toggle stays on so the poll loop re-arms");
});

test("the countdown is a card in the middle of the page", async () => {
  const t = await armedQueue();
  t.status.j1 = "done";
  await t.poll(); await settle();
  const card = bar(t);
  assert.ok(card, "the card is there");
  assert.equal(card.parentElement, t.d.body);
  const st = t.w.getComputedStyle(card);
  assert.equal(st.position, "fixed");
  assert.equal(st.top, "50%");
  assert.equal(st.left, "50%");
  assert.equal(card.querySelector("button").textContent, "Cancel", "the existing Cancel text is reused");
});


// ── The page is locked and dimmed while the card shows ─────────────────────
const lockOf = (t) => t.d.getElementById("quit-lock");
const rest = (t) => [...t.d.body.children].filter((el) => el.id !== "quit-lock" && el.id !== "quit-card");
const escape = (t) => {
  const ev = new t.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
  t.d.body.dispatchEvent(ev);
  return ev;
};
const assertUnlocked = (t, why) => {
  assert.equal(lockOf(t), null, `${why}: the dim layer is gone`);
  assert.equal(bar(t), null, `${why}: the card is gone`);
  assert.equal(t.d.querySelectorAll("[inert]").length, 0, `${why}: nothing is inert any more`);
};
// The countdown is showing (queue empty, other window idle).
async function counting(opts) {
  const t = await armedQueue(opts);
  t.status.j1 = "done";
  await t.poll(); await settle();
  assert.ok(bar(t), "the countdown is showing");
  return t;
}

test("the page is dimmed and locked while the card shows: a dim layer under the card, the rest inert", async () => {
  const t = await counting();
  const lock = lockOf(t), card = bar(t);
  assert.ok(lock, "the dim layer is there");
  assert.equal(lock.parentElement, t.d.body);
  const others = rest(t);
  assert.ok(others.length >= 2, "the page has several top level parts");
  assert.ok(others.every((el) => el.hasAttribute("inert")), "everything else is inert: no clicks, no Tab, hidden from screen readers");
  assert.ok(!lock.hasAttribute("inert") && !card.hasAttribute("inert"), "the card and its layer stay live");
  const ls = t.w.getComputedStyle(lock), cs = t.w.getComputedStyle(card);
  assert.equal(ls.position, "fixed");
  assert.ok(Number(ls.zIndex) > 10000, "above the other dialogs");
  assert.ok(Number(cs.zIndex) > Number(ls.zIndex), "the card sits above its own dim layer");
});

test("clicking the dim layer does nothing: the countdown and the card stay", async () => {
  const t = await counting();
  lockOf(t).click();
  assert.ok(bar(t));
  assert.ok(t.w.eval("_quitTimer"));
  assert.equal(armed(t), true);
  assert.equal(realQuits(t).length, 0);
});

test("Cancel has the focus when the card opens", async () => {
  const t = await counting();
  assert.equal(t.d.activeElement, bar(t).querySelector("button"));
});

test("Cancel unlocks the page", async () => {
  const t = await counting();
  bar(t).querySelector("button").click();
  assertUnlocked(t, "Cancel");
});

test("the page is unlocked again when new downloads arrive during the countdown", async () => {
  const t = await counting();
  t.addJob("v2", "j2");
  await t.poll(); await settle();
  assertUnlocked(t, "new download");
  assert.equal(armed(t), true, "still armed, as before");
});

test("the page is unlocked again when the countdown ends and the app quits", async () => {
  const t = await counting();
  runCountdown(t);
  assert.equal(realQuits(t).length, 1);
  assertUnlocked(t, "quit");
});

test("the page is unlocked again when the final quit is refused (main window got busy)", async () => {
  const t = await counting();
  t.ctl.probeBusy = true;
  runCountdown(t);
  assertUnlocked(t, "refused");
});

test("Esc works like Cancel: unlocks, turns the toggle off and does not quit", async () => {
  const t = await counting();
  const ev = escape(t);
  assert.equal(ev.defaultPrevented, true);
  assertUnlocked(t, "Esc");
  assert.equal(armed(t), false);
  assert.equal(t.w.eval("_quitTimer"), null);
  for (let i = 0; i < COUNTDOWN + 2; i++) t.tick(1000);
  assert.equal(realQuits(t).length, 0);
});

test("other keys leave the countdown running", async () => {
  const t = await counting();
  for (const key of ["Enter", "Tab", " ", "a"]) t.d.body.dispatchEvent(new t.w.KeyboardEvent("keydown", { key, bubbles: true }));
  assert.ok(bar(t));
  assert.ok(lockOf(t));
  assert.equal(armed(t), true);
});

test("Esc is taken by the card: nothing behind it also reacts, and it is free again afterwards", async () => {
  const t = await armedQueue();
  let seen = 0;
  t.w.addEventListener("keydown", (e) => { if (e.key === "Escape") seen++; });
  t.status.j1 = "done";
  await t.poll(); await settle();
  escape(t);
  assert.equal(seen, 0, "the page's own Esc handlers do not see the key that cancelled the countdown");
  escape(t);
  assert.equal(seen, 1, "with the card gone, Esc reaches the page as before");
});

test("the Esc listener is added with the card and removed with it, whichever way it ends", async () => {
  const endings = [
    (t) => bar(t).querySelector("button").click(),                       // Cancel
    (t) => escape(t),                                                    // Esc
    async (t) => { t.addJob("v2", "j2"); await t.poll(); await settle(); },   // new downloads
    (t) => runCountdown(t),                                              // the quit
  ];
  for (const end of endings) {
    const t = await armedQueue();
    const keys = trackKeydown(t.d);
    const base = keys.live;
    t.status.j1 = "done";
    await t.poll(); await settle();
    assert.equal(keys.live, base + 1, "one listener while the card shows");
    await end(t);
    assert.equal(keys.live, base, "none left behind");
  }
});
