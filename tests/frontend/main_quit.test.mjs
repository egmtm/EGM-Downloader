// Main window: the saved "Quit when done" checkbox. After a download or bulk run
// completes it waits for every card to be done and for the Subscriptions window
// to be idle, then shows a 10 second countdown with Cancel before quitting.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const settle = () => new Promise((r) => setTimeout(r, 20));

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
    toastText: () => t.d.querySelector("#toasts .toast span")?.textContent ?? null,
    id: () => t.w.eval("_qodTimer"),
    tick: (id) => timers.get(id)?.(),
    // A download finishes (no card element, so the item leaves the list at once).
    finish: (extra = "") => t.w.eval(`${extra}; const it = {id: 99, status: 'downloading'}; items.push(it); applyJobDone({status:'done', progress:100, filename:'x.mp4'}, it, null, null, null, null);`),
  };
}

test("the saved checkbox is on and every card is done: probe, 10 second countdown, then quit", async () => {
  const t = await boot();
  assert.equal(t.d.getElementById("quit-on-done-chk").checked, true);
  t.finish(); await settle();
  assert.deepEqual(t.calls.quit, [{ whenIdle: true, probe: true }], "no instant quit any more");
  assert.match(t.toastText(), /Quitting in 10s/);
  const id = t.id();
  for (let i = 0; i < 9; i++) await t.tick(id);
  assert.match(t.toastText(), /Quitting in 1s/);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 0);
  await t.tick(id);
  assert.deepEqual(t.calls.quit.filter((o) => !o.probe), [{ whenIdle: true }]);
});

test("checkbox off: nothing happens", async () => {
  const t = await boot({ checked: false });
  t.finish(); await settle();
  assert.equal(t.calls.quit.length, 0);
  assert.equal(t.toastText(), null);
});

for (const bad of ["error", "cancelled"]) {
  test(`a ${bad} card blocks the quit`, async () => {
    const t = await boot();
    t.finish(`items.push({ id: 7, status: '${bad}' })`); await settle();
    assert.equal(t.calls.quit.length, 0);
    assert.equal(t.toastText(), null);
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
  t.d.querySelector("#toasts .toast button").click();
  assert.equal(t.toastText(), null);
  for (let i = 0; i < 12; i++) await t.tick(id);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 0);
  assert.equal(t.d.getElementById("quit-on-done-chk").checked, true);
  assert.equal(t.saved.length, savedBefore, "Cancel saves nothing");
  assert.ok(!t.saved.some((b) => "quit_on_done" in b), "the saved setting is never touched");
});

test("waits while the Subscriptions window is still downloading, then counts down", async () => {
  const t = await boot({ probeBusy: true });
  t.finish(); await settle();
  assert.equal(t.toastText(), null);
  const id = t.id();
  await t.tick(id);
  assert.equal(t.toastText(), null, "still waiting");
  t.ctl.probeBusy = false;
  await t.tick(id);
  assert.match(t.toastText(), /Quitting in 10s/);
});

test("a refused final quit (Subscriptions got busy) drops the countdown and waits again", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  t.ctl.probeBusy = true;
  const realQuit = t.w.electronAPI.quit;
  t.w.electronAPI.quit = async (o) => (o && o.probe ? { busy: true } : (t.calls.quit.push({ ...o }), { busy: true }));
  for (let i = 0; i < 10; i++) await t.tick(id);
  assert.equal(t.toastText(), null);
  assert.ok(t.w.eval("_qodTimer"), "still waiting");
  t.w.electronAPI.quit = realQuit;
});

test("starting another download during the countdown stops it", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  await t.tick(id);
  assert.ok(t.toastText());
  t.w.eval("items.push({ id: 50, status: 'downloading' })");
  await t.tick(id);
  assert.equal(t.toastText(), null);
  assert.equal(t.w.eval("_qodTimer"), null);
  assert.equal(t.calls.quit.filter((o) => !o.probe).length, 0);
});

test("unchecking the box during the countdown stops it", async () => {
  const t = await boot();
  t.finish(); await settle();
  const id = t.id();
  t.d.getElementById("quit-on-done-chk").checked = false;
  await t.tick(id);
  assert.equal(t.toastText(), null);
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
