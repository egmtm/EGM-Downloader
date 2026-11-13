// The page installs Deno silently when it is missing (first launch). Whatever way that install ends, nobody
// clicked anything, so it never starts the plugin update check or the latest Deno lookup. The two tests in
// frontend.test.mjs cover an install that succeeds; these cover the ones that do not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const _json = (body) => ({ ok: true, json: async () => body, text: async () => JSON.stringify(body) });
const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function _firstLaunchDenoInstall(settings, status) {
  const asked = [];
  const { w } = await bootPage({ settings, onFetch(u) {
    asked.push(u);
    if (u === "/api/deno/status") return _json({ installed: false });
    if (u === "/api/deno/install") return _json({ started: true });
    if (u === "/api/deno/install-status") return _json(status);
  } });
  await _sleep(2300);   // the page polls the install every 1.5 s
  w.close();
  return asked;
}

const ENDINGS = [
  ["a failed download", { running: false, done: false, error: "network down" }],
  ["a failed checksum", { running: false, done: true, error: "Checksum mismatch" }],
  ["an install that stopped without an error", { running: false, done: false }],
];

for (const [name, status] of ENDINGS) {
  for (const [panel, settings] of [["closed", {}], ["open", { upd_open: true }]]) {
    test(`first launch Deno install: ${name}, Plugins panel ${panel}: no update check follows`, async () => {
      const asked = await _firstLaunchDenoInstall(settings, status);
      assert.ok(asked.includes("/api/deno/install-status"), `the install never reached its end, so this checks nothing: ${asked}`);
      assert.ok(!asked.includes("/api/check-updates"), asked);
      assert.ok(!asked.includes("/api/deno/status?latest=1"), asked);
    });
  }
}
