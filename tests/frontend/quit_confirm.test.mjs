// Quitting while the Subscriptions window has downloads running, in each platform's main.js, run
// against stubs: the "Close anyway / Keep open" question is asked BEFORE the backend is told to shut
// down. It used to be asked afterwards (when the window was closed), so "Keep open" left a window on
// a backend that was already gone, with its downloads killed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = (p) => readFileSync(join(repo, p, "electron", "main.js"), "utf8");

// The question and the check around it, as each main.js has them.
function helpers(src, platform) {
  const ask = /function confirmCloseWithDownloads\([\s\S]*?\n\}\n/.exec(src);
  const allow = /function subsDownloadsAllowQuit\([\s\S]*?\n\}\n/.exec(src);
  assert.ok(ask && allow, `${platform}: confirmCloseWithDownloads and subsDownloadsAllowQuit found`);
  return ask[0] + allow[0];
}

// A Subscriptions window stub that records what was done to it, in order.
function subsWin(seq, minimized = false) {
  return {
    isDestroyed: () => false, isMinimized: () => minimized,
    restore() { seq.push("restore"); }, show() { seq.push("show"); }, focus() { seq.push("focus"); },
  };
}

function rig(platform, { active, force = false, choice = 1, quitting = false, window = true, backend = true, minimized = false }) {
  const src = source(platform);
  const helper = { 0: helpers(src, platform) };
  const handler = /app\.on\('before-quit', \(event\) => \{[\s\S]*?\n\}\);\n/.exec(src);
  assert.ok(handler, `${platform}: before-quit handler found`);
  const log = { asked: 0, requests: [], timers: 0, trayDestroyed: false, prevented: 0, seq: [] };
  const http = { request(o) { log.requests.push(o.path); return { on() {}, end() {} }; } };
  const handlers = {};
  const ctx = {
    app: { isQuitting: quitting, on(name, fn) { handlers[name] = fn; } },
    subsWindow: window ? subsWin(log.seq, minimized) : null,
    subsActiveDownloads: active, subsForceClose: force,
    dialog: { showMessageBoxSync() { log.asked++; log.seq.push("ask"); return choice; } },
    _psbId: null, powerSaveBlocker: { stop() {} },
    tray: { destroy() { log.trayDestroyed = true; } },
    flaskProc: backend ? { pid: 4242 } : null,
    http, require: () => http, HOST: "127.0.0.1", PORT: 8899, EGM_TOKEN: "tok",
    setTimeout() { log.timers++; }, execSync() {}, process: { kill() {} },
  };
  vm.runInNewContext(helper[0] + handler[0], ctx);
  const event = { preventDefault() { log.prevented++; } };
  handlers["before-quit"](event);
  return { ctx, log };
}

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: Keep open refuses the quit and leaves the backend and the app as they were`, () => {
    // The tray Quit and the quit IPC set isQuitting before they call app.quit().
    const { ctx, log } = rig(platform, { active: true, choice: 1, quitting: true });
    assert.equal(log.asked, 1);
    assert.equal(log.prevented, 1, "the quit was not refused");
    assert.deepEqual(log.requests, [], "the backend was told to shut down before the question was answered");
    assert.equal(ctx.app.isQuitting, false, "the window would still be hidden to the tray instead of closing normally");
    assert.notEqual(ctx.flaskProc, null, "the backend process was forgotten");
    assert.equal(log.timers, 0, "the forced kill was scheduled");
    assert.equal(log.trayDestroyed, false, "the tray icon was removed");
    assert.equal(ctx.subsForceClose, false);
  });

  test(`${platform}: Close anyway lets the quit go on and does not ask a second time`, () => {
    const { ctx, log } = rig(platform, { active: true, choice: 0 });
    assert.equal(log.asked, 1);
    assert.equal(log.prevented, 0);
    assert.deepEqual(log.requests, ["/api/shutdown"]);
    assert.equal(ctx.app.isQuitting, true);
    assert.equal(ctx.subsForceClose, true, "the window's own close handler would ask again");
  });

  test(`${platform}: with no downloads in Subscriptions nothing is asked`, () => {
    for (const opts of [{ active: false }, { active: true, force: true }, { active: true, window: false }]) {
      const { ctx, log } = rig(platform, { ...opts, choice: 1 });
      assert.equal(log.asked, 0, JSON.stringify(opts));
      assert.equal(log.prevented, 0);
      assert.deepEqual(log.requests, ["/api/shutdown"]);
      assert.equal(ctx.app.isQuitting, true);
    }
  });

  test(`${platform}: after a backend crash the quit is not questioned`, () => {
    // The crash handler forgets the process and quits: "Keep open" would leave a window on nothing.
    const { ctx, log } = rig(platform, { active: true, choice: 1, quitting: true, backend: false });
    assert.equal(log.asked, 0, "asked to keep a window open on a backend that has already stopped");
    assert.equal(log.prevented, 0);
    assert.equal(ctx.app.isQuitting, true);
  });

  test(`${platform}: a minimized Subscriptions window is brought back before the question`, () => {
    const { log } = rig(platform, { active: true, choice: 1, quitting: true, minimized: true });
    assert.deepEqual(log.seq, ["restore", "show", "focus", "ask"]);
    const shown = rig(platform, { active: true, choice: 1, quitting: true });
    assert.deepEqual(shown.log.seq, ["show", "focus", "ask"], "a window that is not minimized is not restored");
  });

  test(`${platform}: the Subscriptions close handler uses the same question, written once`, () => {
    const src = source(platform);
    assert.equal(src.split("Downloads are still in progress.").length - 1, 1, "the dialog text is written more than once");
    assert.match(src, /if \(confirmCloseWithDownloads\(subsWindow\)\) \{ subsForceClose = true; subsWindow\.close\(\); \}/);
  });
}

// Windows only: the Electron reinstall "Restart now" and the update installer both end the app.
// They ask BEFORE they do something that cannot be taken back (a queued relaunch, a started
// installer), so "Keep open" leaves nothing behind.
function winHandlerRig(name, { active, choice }) {
  const src = source("windows");
  const re = new RegExp(`ipcMain\\.handle\\('${name}', [\\s\\S]*?\\n\\}\\);\\n`);
  const handler = re.exec(src);
  assert.ok(handler, `${name} handler found`);
  const log = { asked: 0, relaunch: 0, quit: 0, spawned: 0 };
  const handlers = {};
  const ctx = {
    ipcMain: { handle(n, fn) { handlers[n] = fn; } },
    isTrustedSender: () => true,
    BrowserWindow: { fromWebContents: () => null }, _activityBySender: new Map(),
    app: { isQuitting: false, relaunch() { log.relaunch++; }, quit() { log.quit++; } },
    path: { join: (...p) => p.join("/"), resolve: (p) => p }, __dirname: "/app/electron",
    fs: { existsSync: () => true },
    EXPECTED_INSTALLER: "/tmp/egm-update/egm-setup.exe",
    spawn() { log.spawned++; return { unref() {} }; },
    flaskProc: { pid: 4242 },
    subsWindow: subsWin([]), subsActiveDownloads: active, subsForceClose: false,
    dialog: { showMessageBoxSync() { log.asked++; return choice; } },
  };
  vm.runInNewContext(helpers(src, "windows") + handler[0], ctx);
  // The handlers answer with objects from the vm context: compare them as plain JSON.
  return { ctx, log, call: async (arg) => JSON.parse(JSON.stringify(await handlers[name]({ sender: {} }, arg) ?? null)) };
}

test("windows: Restart now to reinstall Electron, Keep open: no relaunch is left queued", async () => {
  const { ctx, log, call } = winHandlerRig("quit-app", { active: true, choice: 1 });
  assert.deepEqual(await call({ relaunch: true }), { cancelled: true });
  assert.equal(log.asked, 1);
  assert.equal(log.relaunch, 0, "a relaunch stays queued and fires at the next normal quit");
  assert.equal(log.quit, 0);
  assert.equal(ctx.app.isQuitting, false);
});

test("windows: Restart now to reinstall Electron, Close anyway: relaunch and quit, asked once", async () => {
  const { ctx, log, call } = winHandlerRig("quit-app", { active: true, choice: 0 });
  await call({ relaunch: true });
  assert.equal(log.asked, 1);
  assert.equal(log.relaunch, 1);
  assert.equal(log.quit, 1);
  assert.equal(ctx.subsForceClose, true, "before-quit would ask a second time");
});

test("windows: a plain quit and a relaunch without Subscriptions downloads ask nothing here", async () => {
  for (const [opts, active] of [[undefined, true], [{ relaunch: true }, false]]) {
    const { log, call } = winHandlerRig("quit-app", { active, choice: 1 });
    await call(opts);
    assert.equal(log.asked, 0, JSON.stringify(opts));   // a plain quit is asked in before-quit
    assert.equal(log.quit, 1);
  }
});

test("windows: the update installer is not started when the user keeps Subscriptions open", async () => {
  const keep = winHandlerRig("launch-installer", { active: true, choice: 1 });
  assert.deepEqual(await keep.call("/tmp/egm-update/egm-setup.exe"), { cancelled: true });
  assert.equal(keep.log.spawned, 0, "the installer would start and close the app anyway");
  const close = winHandlerRig("launch-installer", { active: true, choice: 0 });
  assert.deepEqual(await close.call("/tmp/egm-update/egm-setup.exe"), { success: true });
  assert.equal(close.log.spawned, 1);
  assert.equal(close.ctx.subsForceClose, true, "the quit that follows would ask a second time");
  const idle = winHandlerRig("launch-installer", { active: false, choice: 1 });
  assert.deepEqual(await idle.call("/tmp/egm-update/egm-setup.exe"), { success: true });
  assert.equal(idle.log.asked, 0);
});
