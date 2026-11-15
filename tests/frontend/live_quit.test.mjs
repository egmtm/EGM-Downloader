// Quitting with a live recording running or paused, in each platform's main.js, run against stubs:
// before the backend is told to shut down, the user is asked to save what was recorded (Stop and save
// each, then wait until they are saved, at most 5 minutes), discard it (Cancel each), or keep the app
// open. Asked once per quit; nothing is asked when no live recording exists or the backend is gone.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = (p) => readFileSync(join(repo, p, "electron", "main.js"), "utf8");

function rig(platform, { live = ["job1"], choice = 0, backendDown = false, lang = "en", strings = {}, savesAfter = 1, subsActive = false } = {}) {
  const src = source(platform);
  const block = src.slice(src.indexOf("const LIVE_QUIT_FALLBACK"), src.indexOf("app.on('before-quit'"));
  const subs = /function confirmCloseWithDownloads\([\s\S]*?\n\}\n/.exec(src)[0] + /function subsDownloadsAllowQuit\([\s\S]*?\n\}\n/.exec(src)[0];
  const handler = /app\.on\('before-quit', \(event\) => \{[\s\S]*?\n\}\);\n/.exec(src)[0];
  const log = { posts: [], gets: 0, asked: [], subsAsked: 0, shutdown: 0, quits: 0, prevented: 0, focus: [] };
  let left = [...live], getsAfterPost = 0, posted = false;
  // the shell's own backendCall (it never throws: status 0 when the backend does not answer)
  const backendCall = async (method, path) => {
    if (backendDown) return { status: 0, body: "" };
    if (path === "/api/live-jobs") {
      log.gets++;
      if (posted && ++getsAfterPost >= savesAfter) left = [];
      return { status: 200, body: JSON.stringify({ jobs: left.map((id) => ({ id, status: "paused" })) }) };
    }
    if (method === "POST") { log.posts.push(path); posted = true; }
    return { status: 200, body: "{}" };
  };
  // before-quit tells the backend to shut down with a plain request
  const http = { request(o) { if (o.path === "/api/shutdown") log.shutdown++; return { on() {}, end() {} }; } };
  const handlers = {};
  const mainWindow = { isDestroyed: () => false, isMinimized: () => false, restore() {}, show() { log.focus.push("show"); }, focus() { log.focus.push("focus"); } };
  const ctx = {
    http, backendCall, require: () => http, HOST: "127.0.0.1", PORT: 8899, EGM_TOKEN: "tok",
    LIVE_LANG_DIR: "/app/languages", _shellLang: lang, loadSettings: () => ({ language: "en" }),
    path: { join: (...p) => p.join("/") },
    fs: { readFileSync: () => JSON.stringify({ strings }) },
    dialog: {
      showMessageBox(...a) { const o = a[a.length - 1]; log.asked.push(o); return Promise.resolve({ response: choice }); },
      showMessageBoxSync() { log.subsAsked++; return 0; },      // the Subscriptions question: Close anyway
    },
    mainWindow, flaskProc: { pid: 1 },
    app: { isQuitting: true, on(n, fn) { handlers[n] = fn; }, quit() { log.quits++; } },
    subsWindow: subsActive ? { isDestroyed: () => false, isMinimized: () => false, show() {}, focus() {} } : null,
    subsActiveDownloads: subsActive, subsForceClose: false,
    _psbId: null, powerSaveBlocker: { stop() {} }, tray: null,
    setTimeout: (fn) => { fn(); return 0; }, execSync() {}, process: { kill() {} },
    Date, Promise, JSON, Object, encodeURIComponent,
  };
  vm.runInNewContext(block + subs + handler + "\nthis.__allow = liveRecordingsAllowQuit; this.__answered = () => _liveQuitAnswered;", ctx);
  const quit = () => { const ev = { preventDefault() { log.prevented++; } }; handlers["before-quit"](ev); };
  return { ctx, log, allow: () => ctx.__allow(), answered: () => ctx.__answered(), quit };
}

const tick = () => new Promise((r) => setImmediate(r));

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: no live recording, nothing asked`, async () => {
    const r = rig(platform, { live: [] });
    assert.equal(await r.allow(), true);
    assert.equal(r.log.asked.length, 0);
  });

  test(`${platform}: Save and quit stops and saves each recording, waits until they are saved, then quits`, async () => {
    const r = rig(platform, { live: ["a", "b"], choice: 0, savesAfter: 3 });
    assert.equal(await r.allow(), true);
    assert.deepEqual(r.log.posts, ["/api/stop/a", "/api/stop/b"]);
    assert.ok(r.log.gets >= 4, "it kept checking until the recordings were saved");
    assert.deepEqual(r.log.focus, ["show", "focus"], "the window comes forward for the question");
  });

  test(`${platform}: Discard and quit cancels each recording`, async () => {
    const r = rig(platform, { live: ["a"], choice: 1 });
    assert.equal(await r.allow(), true);
    assert.deepEqual(r.log.posts, ["/api/cancel/a"]);
  });

  test(`${platform}: Keep open changes nothing`, async () => {
    const r = rig(platform, { live: ["a"], choice: 2 });
    assert.equal(await r.allow(), false);
    assert.deepEqual(r.log.posts, []);
  });

  test(`${platform}: a backend that does not answer does not hold the quit`, async () => {
    const r = rig(platform, { backendDown: true });
    assert.equal(await r.allow(), true);
    assert.equal(r.log.asked.length, 0);
  });

  test(`${platform}: the question is in the app language, English for a missing key`, async () => {
    const r = rig(platform, { choice: 2, lang: "es", strings: { "quit.live.title": "Grabación en directo", "quit.live.keep": "Mantener abierta" } });
    await r.allow();
    const o = r.log.asked[0];
    assert.equal(o.title, "Grabación en directo");
    assert.deepEqual(JSON.parse(JSON.stringify(o.buttons)), ["Save and quit", "Discard and quit", "Mantener abierta"]);
    assert.equal(o.defaultId, 0);
    assert.equal(o.cancelId, 2, "Esc keeps the app open");
  });

  test(`${platform}: before-quit holds the quit for the answer, then quits again once, without asking twice`, async () => {
    const r = rig(platform, { live: ["a"], choice: 0 });
    r.quit();
    assert.equal(r.log.prevented, 1, "held while the user answers");
    assert.equal(r.log.shutdown, 0, "the backend still runs while the user answers");
    await tick(); await tick(); await tick();
    assert.equal(r.log.quits, 1, "the quit goes ahead after the save");
    assert.equal(r.answered(), true);
    r.quit();                                   // the quit that app.quit() starts
    assert.equal(r.log.prevented, 1, "not asked a second time");
    assert.equal(r.log.shutdown, 1);
  });

  test(`${platform}: before-quit with Keep open leaves the app running`, async () => {
    const r = rig(platform, { live: ["a"], choice: 2 });
    r.quit();
    await tick(); await tick(); await tick();
    assert.equal(r.log.quits, 0);
    assert.equal(r.ctx.app.isQuitting, false);
    assert.equal(r.answered(), false, "the next quit asks again");
    assert.equal(r.log.shutdown, 0);
  });

  test(`${platform}: Close anyway for Subscriptions, then Keep open for the recording: the next quit asks about Subscriptions again`, async () => {
    const r = rig(platform, { live: ["a"], choice: 2, subsActive: true });
    r.quit();
    await tick(); await tick(); await tick();
    assert.equal(r.log.subsAsked, 1);
    assert.equal(r.log.asked.length, 1);
    assert.equal(r.log.quits, 0);
    assert.equal(r.ctx.subsForceClose, false, "the app stays open, so the Subscriptions window asks again when it is closed");
    r.quit();
    await tick(); await tick(); await tick();
    assert.equal(r.log.subsAsked, 2, "and so does the next quit");
    assert.equal(r.log.shutdown, 0);
  });
}

for (const platform of ["mac", "linux"]) {
  test(`${platform}: closing the main window (which quits the app here) asks first`, () => {
    const src = source(platform);
    const i = src.indexOf("mainWindow.on('close', (e) => {");
    assert.ok(i > 0, "close handler found");
    const body = src.slice(i, src.indexOf("});", i));
    assert.match(body, /if \(!_liveQuitAnswered && flaskProc\) \{\s*e\.preventDefault\(\);/);
    assert.ok(body.indexOf("liveRecordingsAllowQuit()") < body.indexOf("saveWindowState()"));
  });
}

test("windows: the update installer and Restart now ask about live recordings before they act", () => {
  const src = source("windows");
  for (const name of ["launch-installer", "quit-app"]) {
    const h = new RegExp(`ipcMain\\.handle\\('${name}', [\\s\\S]*?\\n\\}\\);\\n`).exec(src)[0];
    assert.match(h, /liveRecordingsAllowQuit\(\)/, name);
  }
});

// Windows: the update installer and Restart now ask the Subscriptions question first, then the live one.
// Keep open on the live one takes the Close anyway back, or nothing would ask about Subscriptions again.
for (const [name, arg] of [["launch-installer", "/tmp/egm-update/egm-setup.exe"], ["quit-app", { relaunch: true }]]) {
  test(`windows: ${name}, Close anyway for Subscriptions then Keep open for the recording, leaves the Subscriptions question armed`, async () => {
    const src = source("windows");
    const subs = /function confirmCloseWithDownloads\([\s\S]*?\n\}\n/.exec(src)[0] + /function subsDownloadsAllowQuit\([\s\S]*?\n\}\n/.exec(src)[0];
    const handler = new RegExp(`ipcMain\\.handle\\('${name}', [\\s\\S]*?\\n\\}\\);\\n`).exec(src)[0];
    const log = { subsAsked: 0, relaunch: 0, quit: 0, spawned: 0 };
    const handlers = {};
    const ctx = {
      ipcMain: { handle(n, fn) { handlers[n] = fn; } }, isTrustedSender: () => true,
      BrowserWindow: { fromWebContents: () => null }, _activityBySender: new Map(),
      app: { isQuitting: false, relaunch() { log.relaunch++; }, quit() { log.quit++; } },
      path: { join: (...p) => p.join("/"), resolve: (p) => p }, fs: { existsSync: () => true },
      EXPECTED_INSTALLER: "/tmp/egm-update/egm-setup.exe", INSTALL_DIR: "/app",
      spawn() { log.spawned++; return { unref() {} }; },
      flaskProc: { pid: 1 },
      subsWindow: { isDestroyed: () => false, isMinimized: () => false, show() {}, focus() {} },
      subsActiveDownloads: true, subsForceClose: false,
      dialog: { showMessageBoxSync() { log.subsAsked++; return 0; } },
      liveRecordingsAllowQuit: async () => false, _liveQuitAnswered: false,
    };
    vm.runInNewContext(subs + handler, ctx);
    const answer = JSON.parse(JSON.stringify(await handlers[name]({ sender: {} }, arg)));
    assert.deepEqual(answer, { cancelled: true });
    assert.equal(log.subsAsked, 1);
    assert.deepEqual([log.spawned, log.relaunch, log.quit], [0, 0, 0]);
    assert.equal(ctx.subsForceClose, false);
    assert.equal(ctx._liveQuitAnswered, false);
  });
}
