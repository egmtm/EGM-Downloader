// windows/electron/main.js, startFlask() when no Python can be started, run against stubs.
// The packaged build (installer edition) only uses the Python it ships with, so its box says that
// Python could not start, that antivirus may have blocked or removed it, and to reinstall. Started
// by the launcher, the box is the same as before.
// The same box shows when the packaged backend stops before it ever answered (see below).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { EventEmitter } from "node:events";
import { fileURLToPath } from "node:url";

const repo = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = readFileSync(path.join(repo, "windows", "electron", "main.js"), "utf8");

async function noPython(packaged) {
  const m = /async function startFlask\(\) \{[\s\S]*?\n\}\n/.exec(src);
  assert.ok(m, "startFlask found");
  const shown = [], calls = [];
  const ctx = {
    path, PACKAGED: packaged, APP_DIR: "C:\\EGM", findPython: () => null,
    dropSplash: () => calls.push("dropSplash"),
    closeSplash: () => assert.fail("a box blocks the timers closeSplash() waits on: the splash must go at once"),
    dialog: { showErrorBox: (title, msg) => shown.push({ title, msg }) },
    app: { quit: () => calls.push("quit") },
    spawn: () => assert.fail("nothing is started without a Python"),
  };
  const box = /\nconst BUNDLED_PYTHON_BOX = \[[\s\S]*?\];\n/.exec(src);
  vm.runInNewContext((box ? box[0] : "") + m[0] + "\nthis.startFlask = startFlask;", ctx);
  await ctx.startFlask();
  assert.deepEqual(calls, ["dropSplash", "quit"]);
  assert.equal(shown.length, 1);
  return shown[0];
}

test("packaged: the bundled Python could not start, antivirus may have blocked it, reinstall", async () => {
  const { title, msg } = await noPython(true);
  assert.equal(title, "Python could not start");
  assert.match(msg, /The Python that comes with EGM Downloader could not start/);
  assert.match(msg, /[Aa]ntivirus/);
  assert.match(msg, /blocked or removed/);
  assert.match(msg, /Reinstall EGM Downloader/);
  assert.doesNotMatch(msg, /python\.org|PATH/);
});

test("started by the launcher: the box is unchanged", async () => {
  const { title, msg } = await noPython(false);
  assert.equal(title, "Python not found");
  assert.equal(msg, 'Python 3.11+ is required.\n\nDownload from python.org and check "Add Python to PATH" during install.');
});

// A bundled Python that starts but cannot run the app (part of it quarantined: a module or a DLL
// removed) exits before the backend ever answers. Packaged, that exit shows the same reinstall box,
// after the splash is gone; once the backend has answered, or started by the launcher, an exit is a
// crash as before, and a taken port keeps its own box.
function exitHandler(packaged, answered) {
  const exit = /  flaskProc\.on\('exit'[\s\S]*?\n  \}\);\n/.exec(src);
  const drop = /\nfunction dropSplash\(\) \{[\s\S]*?\n\}\n/.exec(src);
  const box = /\nconst BUNDLED_PYTHON_BOX = \[[\s\S]*?\];\n/.exec(src);
  assert.ok(exit && drop, "exit handler and dropSplash found");
  const order = [];
  const ctx = {
    flaskProc: new EventEmitter(), PORT: 8899, PACKAGED: packaged, backendAnswered: answered,
    splashWindow: { isDestroyed: () => false, destroy: () => order.push("splash destroyed") },
    app: { isQuitting: false, quit: () => order.push("quit") },
    dialog: { showErrorBox: (title, msg) => order.push({ title, msg }) },
  };
  vm.runInNewContext((box ? box[0] : "") + drop[0] + exit[0], ctx);
  return { proc: ctx.flaskProc, order };
}

test("packaged: the backend stopping before it ever answered shows the reinstall box, after the splash", () => {
  for (const [code, signal] of [[1, null], [0, null], [null, "SIGKILL"]]) {
    const { proc, order } = exitHandler(true, false);
    proc.emit("exit", code, signal);
    assert.equal(order.length, 3, JSON.stringify(order));
    assert.equal(order[0], "splash destroyed");
    assert.equal(order[1].title, "Python could not start");
    assert.match(order[1].msg, /The Python that comes with EGM Downloader could not start/);
    assert.match(order[1].msg, /Reinstall EGM Downloader/);
    assert.equal(order[2], "quit");
  }
});

test("packaged: the same box as when the bundled Python does not start at all", async () => {
  const { title, msg } = await noPython(true);
  const { proc, order } = exitHandler(true, false);
  proc.emit("exit", 1, null);
  assert.deepEqual(order[1], { title, msg });
});

test("an exit after the backend answered, started by the launcher, or on a taken port is reported as before", () => {
  for (const [packaged, answered, code, expect] of [[true, true, 1, /stopped unexpectedly \(code 1\)/],
                                                    [false, false, 1, /stopped unexpectedly \(code 1\)/],
                                                    [true, false, 3, /port 8899/]]) {
    const { proc, order } = exitHandler(packaged, answered);
    proc.emit("exit", code, null);
    assert.equal(order[1].title, "EGM Downloader — Backend crashed", JSON.stringify([packaged, answered, code]));
    assert.match(order[1].msg, expect);
  }
});

test("the backend counts as answered once waitForFlask has let the page load", () => {
  const m = /async function createWindow\(\) \{[\s\S]*?\n\}\n/.exec(src);
  assert.ok(m, "createWindow found");
  assert.match(m[0], /await waitForFlask\(\);\n\s*backendAnswered = true;/);
  assert.match(src, /\nlet backendAnswered = false;/);
});
