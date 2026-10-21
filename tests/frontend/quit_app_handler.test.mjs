// The 'quit-app' IPC handler in each platform's main.js, run against stubs.
// "Quit when done" in the Subscriptions window calls it with whenIdle, which
// must never close the app while another window still reports downloads.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

function loadHandler(platform) {
  const src = readFileSync(join(repo, platform, "electron", "main.js"), "utf8");
  const m = /ipcMain\.handle\('quit-app'[\s\S]*?\n\}\);/.exec(src);
  assert.ok(m, `${platform}: quit-app handler found`);
  const state = { quits: 0, handler: null, activity: new Map() };
  const app = { isQuitting: false, quit() { state.quits++; }, relaunch() {} };
  const subsWin = { id: "subs" }, mainWin = { id: "main" };
  vm.runInNewContext(m[0], {
    ipcMain: { handle: (name, fn) => { state.handler = fn; } },
    isTrustedSender: (e) => e.trusted !== false,
    BrowserWindow: { fromWebContents: (wc) => (wc === "subs-wc" ? subsWin : mainWin) },
    _activityBySender: state.activity,
    app, path: { join: (...a) => a.join("/") }, fs: { existsSync: () => false }, __dirname: "/x",
  });
  return { state, app, subsWin, mainWin, call: (opts, e = { sender: "subs-wc" }) => state.handler(e, opts) };
}

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: whenIdle quits when no other window is downloading`, () => {
    const h = loadHandler(platform);
    assert.deepEqual({ ...h.call({ whenIdle: true }) }, { success: true });
    assert.equal(h.state.quits, 1);
    assert.equal(h.app.isQuitting, true);
  });

  test(`${platform}: whenIdle refuses (and does not quit) while the main window is downloading`, () => {
    const h = loadHandler(platform);
    h.state.activity.set(h.mainWin, { active: 1, progress: 0.2 });
    assert.deepEqual({ ...h.call({ whenIdle: true }) }, { busy: true });
    assert.equal(h.state.quits, 0);
    assert.equal(h.app.isQuitting, false);
  });

  test(`${platform}: the caller's own activity does not count as busy`, () => {
    const h = loadHandler(platform);
    h.state.activity.set(h.subsWin, { active: 1, progress: 0.2 });
    assert.deepEqual({ ...h.call({ whenIdle: true, probe: true }) }, { busy: false });
  });

  test(`${platform}: probe reports the state without quitting`, () => {
    const h = loadHandler(platform);
    assert.deepEqual({ ...h.call({ whenIdle: true, probe: true }) }, { busy: false });
    h.state.activity.set(h.mainWin, { active: 2, progress: 0.5 });
    assert.deepEqual({ ...h.call({ whenIdle: true, probe: true }) }, { busy: true });
    assert.equal(h.state.quits, 0);
  });

  test(`${platform}: a plain quit (main window, tray flows) is unchanged`, () => {
    const h = loadHandler(platform);
    h.state.activity.set(h.mainWin, { active: 3, progress: 0.5 });
    assert.deepEqual({ ...h.call(undefined) }, { success: true });
    assert.equal(h.state.quits, 1);
  });

  test(`${platform}: an untrusted sender is refused before anything else`, () => {
    const h = loadHandler(platform);
    assert.deepEqual({ ...h.call({ whenIdle: true }, { sender: "x", trusted: false }) }, { error: "Untrusted sender" });
    assert.equal(h.state.quits, 0);
  });
}
