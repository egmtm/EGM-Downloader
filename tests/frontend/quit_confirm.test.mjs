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

function rig(platform, { active, force = false, choice = 1, quitting = false, window = true }) {
  const src = source(platform);
  const helper = /function confirmCloseWithDownloads\([\s\S]*?\n\}\n/.exec(src);
  const handler = /app\.on\('before-quit', \(event\) => \{[\s\S]*?\n\}\);\n/.exec(src);
  assert.ok(helper && handler, `${platform}: helper and before-quit handler found`);
  const log = { asked: 0, requests: [], timers: 0, trayDestroyed: false, prevented: 0 };
  const http = { request(o) { log.requests.push(o.path); return { on() {}, end() {} }; } };
  const handlers = {};
  const ctx = {
    app: { isQuitting: quitting, on(name, fn) { handlers[name] = fn; } },
    subsWindow: window ? { isDestroyed: () => false } : null,
    subsActiveDownloads: active, subsForceClose: force,
    dialog: { showMessageBoxSync() { log.asked++; return choice; } },
    _psbId: null, powerSaveBlocker: { stop() {} },
    tray: { destroy() { log.trayDestroyed = true; } },
    flaskProc: { pid: 4242 },
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

  test(`${platform}: the Subscriptions close handler uses the same question, written once`, () => {
    const src = source(platform);
    assert.equal(src.split("Downloads are still in progress.").length - 1, 1, "the dialog text is written more than once");
    assert.match(src, /if \(confirmCloseWithDownloads\(subsWindow\)\) \{ subsForceClose = true; subsWindow\.close\(\); \}/);
  });
}
