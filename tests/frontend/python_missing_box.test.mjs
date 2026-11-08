// windows/electron/main.js, startFlask() when no Python can be started, run against stubs.
// The packaged build (installer edition) only uses the Python it ships with, so its box says that
// Python could not start, that antivirus may have blocked or removed it, and to reinstall. Started
// by the launcher, the box is the same as before.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const repo = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = readFileSync(path.join(repo, "windows", "electron", "main.js"), "utf8");

async function noPython(packaged) {
  const m = /async function startFlask\(\) \{[\s\S]*?\n\}\n/.exec(src);
  assert.ok(m, "startFlask found");
  const shown = [], calls = [];
  const ctx = {
    path, PACKAGED: packaged, APP_DIR: "C:\\EGM", findPython: () => null,
    closeSplash: () => calls.push("closeSplash"),
    dialog: { showErrorBox: (title, msg) => shown.push({ title, msg }) },
    app: { quit: () => calls.push("quit") },
    spawn: () => assert.fail("nothing is started without a Python"),
  };
  vm.runInNewContext(m[0] + "\nthis.startFlask = startFlask;", ctx);
  await ctx.startFlask();
  assert.deepEqual(calls, ["closeSplash", "quit"]);
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
