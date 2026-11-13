// Advanced -> Maintenance on Windows. The installer edition ships Electron inside the app folder and
// nothing reads the Reinstall Electron marker there, so /api/portable-status says bundled: true and
// the page hides the button. The portable edition and the launcher's Electron keep it; Mac and Linux
// never show it (and never ask /api/portable-status).
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

async function boot({ platform, windowsShell, status }) {
  const asked = [];
  const { w, d } = await bootPage({
    prep(win) {
      Object.defineProperty(win.navigator, "platform", { get: () => platform });
      if (windowsShell) win.electronAPI = { platform: "win", createShortcut: async () => ({ success: true }) };
    },
    onFetch(u) {
      if (u === "/api/portable-status") {
        asked.push(u);
        return { ok: true, json: async () => ({ data_dir: "C:\\EGM", ...status }) };
      }
    },
  });
  const btn = d.getElementById("adv-electron-btn");
  const row = d.getElementById("adv-electron-reset-row");
  const out = {
    asked: asked.length,
    bundledClass: d.body.classList.contains("bundled-mode"),
    shown: w.getComputedStyle(btn).display !== "none",
    rowColumns: row.style.gridTemplateColumns,
  };
  w.close();
  return out;
}

test("installer edition (bundled): Reinstall Electron is hidden and Reset settings takes the row", async () => {
  const r = await boot({ platform: "Win32", windowsShell: true, status: { portable: false, bundled: true } });
  assert.deepEqual(r, { asked: 1, bundledClass: true, shown: false, rowColumns: "1fr" });
});

test("portable edition: Reinstall Electron stays", async () => {
  const r = await boot({ platform: "Win32", windowsShell: true, status: { portable: true, bundled: false } });
  assert.deepEqual(r, { asked: 1, bundledClass: false, shown: true, rowColumns: "" });
});

test("launcher edition (no bundled flag, as before): Reinstall Electron stays", async () => {
  const r = await boot({ platform: "Win32", windowsShell: true, status: { portable: false } });
  assert.deepEqual(r, { asked: 1, bundledClass: false, shown: true, rowColumns: "" });
});

test("Mac and Linux: never shown, and the Windows-only endpoint is not asked", async () => {
  for (const platform of ["MacIntel", "Linux x86_64"]) {
    const r = await boot({ platform, windowsShell: false, status: { portable: false, bundled: true } });
    assert.deepEqual(r, { asked: 0, bundledClass: false, shown: false, rowColumns: "1fr" }, platform);
  }
});
