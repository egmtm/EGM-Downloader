// The shell's side of starting the backend, in each platform's main.js, run against stubs:
//  * waitForFlask only accepts this run's backend (a 200 with the per-run token), never another
//    program on the port or a backend left over from an earlier run (they answer 404 or 403);
//  * the backend's exit handler reports any exit while the app is not quitting (also by a signal,
//    and code 3, the taken port), and forgets the process so before-quit does not stop its PID later.
//    These run the launcher's layout (PACKAGED false); the packaged Windows exit before the backend
//    ever answered has its own box, tested in python_missing_box.test.mjs.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import http from "node:http";
import vm from "node:vm";
import { EventEmitter } from "node:events";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const source = (p) => readFileSync(join(repo, p, "electron", "main.js"), "utf8");
// The shells drop the splash at once before a box (a box blocks the timers closeSplash() waits on).
function dropSplashOf(platform) {
  const d = /\nfunction dropSplash\(\) \{[\s\S]*?\n\}\n/.exec(source(platform));
  assert.ok(d, `${platform}: dropSplash found`);
  return d[0];
}

function waitForFlaskOf(platform, appUrl, token) {
  const m = /function waitForFlask\([\s\S]*?\n\}\n/.exec(source(platform));
  assert.ok(m, `${platform}: waitForFlask found`);
  const ctx = { http, APP_URL: appUrl, EGM_TOKEN: token, setTimeout, Date, Promise, Error };
  vm.runInNewContext(m[0] + "\nthis.waitForFlask = waitForFlask;", ctx);
  return ctx.waitForFlask;
}

function server(handler) {
  return new Promise((res) => {
    const s = http.createServer(handler).listen(0, "127.0.0.1", () => res(s));
  });
}

for (const platform of ["windows", "mac", "linux"]) {
  test(`${platform}: waitForFlask waits for this run's backend, not for any answer on the port`, async (t) => {
    let hits = 0;
    const other = await server((req, res) => { hits++; res.statusCode = req.url === "/" ? 200 : 404; res.end("x"); });
    t.after(() => other.close());
    const url = `http://127.0.0.1:${other.address().port}`;
    await assert.rejects(waitForFlaskOf(platform, url, "tok")(600, 50), /did not start/);
    assert.ok(hits > 1, "it kept asking");
    const ours = await server((req, res) => {
      res.statusCode = req.url === "/api/settings" && req.headers["x-egm-token"] === "tok" ? 200 : 403; res.end("{}");
    });
    t.after(() => ours.close());
    const url2 = `http://127.0.0.1:${ours.address().port}`;
    await assert.rejects(waitForFlaskOf(platform, url2, "old-run-token")(600, 50), /did not start/);
    await waitForFlaskOf(platform, url2, "tok")(3000, 50);
  });

  test(`${platform}: any backend exit while not quitting is reported, and the process is forgotten`, () => {
    const m = /  flaskProc\.on\('exit'[\s\S]*?\n  \}\);\n/.exec(source(platform));
    assert.ok(m, `${platform}: exit handler found`);
    m[0] = dropSplashOf(platform) + m[0];
    for (const [code, signal, expect] of [[null, "SIGKILL", /signal SIGKILL/], [0, null, /code 0/], [3, null, /port 8899/], [1, null, /code 1/]]) {
      const shown = [];
      const ctx = {
        flaskProc: new EventEmitter(), PORT: 8899, PACKAGED: false, splashWindow: null,
        app: { isQuitting: false, quits: 0, quit() { this.quits++; } },
        dialog: { showErrorBox: (t, msg) => shown.push(msg) },
      };
      vm.runInNewContext(m[0], ctx);
      const proc = ctx.flaskProc;
      proc.emit("exit", code, signal);
      assert.equal(shown.length, 1, `exit(${code}, ${signal}) was not reported`);
      assert.match(shown[0], expect);
      assert.equal(ctx.app.quits, 1);
      assert.equal(ctx.flaskProc, null, "the exited process is still kept for before-quit to stop");
    }
    const ctx = { flaskProc: new EventEmitter(), PORT: 8899, PACKAGED: false, splashWindow: null, app: { isQuitting: true, quit() {} },
                  dialog: { showErrorBox: () => assert.fail("a normal quit is not a crash") } };
    vm.runInNewContext(m[0], ctx);
    ctx.flaskProc.emit("exit", 0, null);
  });
}

for (const platform of ["windows", "mac", "linux"]) test(`${platform}: the always on top splash is destroyed before the backend crash box opens`, () => {
  const m = /  flaskProc\.on\('exit'[\s\S]*?\n  \}\);\n/.exec(source(platform));
  assert.ok(m, "exit handler found");
  m[0] = dropSplashOf(platform) + m[0];
  const order = [];
  const ctx = {
    flaskProc: new EventEmitter(), PORT: 8899, PACKAGED: false,
    splashWindow: { isDestroyed: () => false, destroy: () => order.push("splash destroyed") },
    app: { isQuitting: false, quit() {} },
    dialog: { showErrorBox: () => order.push("box shown") },
  };
  vm.runInNewContext(m[0], ctx);
  ctx.flaskProc.emit("exit", 3, null);
  assert.deepEqual(order, ["splash destroyed", "box shown"]);
  assert.equal(ctx.splashWindow, null, "the closed splash is forgotten");
  // a splash that is already gone is left alone
  const gone = { destroyed: false };
  const ctx2 = {
    flaskProc: new EventEmitter(), PORT: 8899, PACKAGED: false,
    splashWindow: { isDestroyed: () => true, destroy: () => { gone.destroyed = true; } },
    app: { isQuitting: false, quit() {} },
    dialog: { showErrorBox() {} },
  };
  vm.runInNewContext(m[0], ctx2);
  ctx2.flaskProc.emit("exit", 3, null);
  assert.equal(gone.destroyed, false, "a destroyed window is not destroyed again");
});
