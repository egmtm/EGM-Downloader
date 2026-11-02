// The page side of "Keep open" (Windows): when the user keeps the Subscriptions window and its
// downloads, the shell answers { cancelled: true } and the page must not quit the app anyway.
//  * Update Now: the installer was not started, so no quit follows a moment later.
//  * Advanced -> Reinstall Electron -> Restart now: nothing restarts; the page says the reinstall
//    waits for the next launch instead of leaving "Restarting..." as the last word.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const _json = (body) => ({ ok: true, json: async () => body, text: async () => JSON.stringify(body) });

async function updateNow(launchAnswer) {
  const quits = [];
  const { w, d } = await bootPage({
    prep(win) {
      win.electronAPI = {
        platform: "win",
        launchInstaller: async () => launchAnswer,
        quit: async (o) => { quits.push(o); return { success: true }; },
      };
    },
    onFetch(u) {
      if (u === "/api/check-app-update") {
        return _json({ up_to_date: false, current_version: "1.5.2.1", current_build: 174,
                       latest_version: "1.5.2.2", latest_build: 175, zip_url: "https://egerena.com/EGMd.zip",
                       _checksums: { sha256: "ab".repeat(32) } });
      }
      if (u === "/api/download-update") return _json({ installer_path: "C:/Temp/egm-update/egm-setup.exe" });
    },
  });
  d.getElementById("footer-update-btn").click();
  await _sleep(150);
  const btn = [...d.querySelectorAll(".upd-backdrop button")].find((b) => /Update Now/.test(b.textContent));
  assert.ok(btn, "the Update Now button is offered");
  btn.click();
  await _sleep(800 + 1500 + 400);   // the page waits before launching, then before quitting
  w.close();
  return quits;
}

test("Update Now, Keep open: the page does not quit after the installer was refused", async () => {
  assert.deepEqual(await updateNow({ cancelled: true }), []);
});

test("Update Now with the installer started: the page still quits as before", async () => {
  assert.equal((await updateNow({ success: true })).length, 1);
});

test("Restart now to reinstall Electron, Keep open: the page says it applies at the next launch", async () => {
  const quits = [];
  const { w, d } = await bootPage({
    prep(win) {
      win.confirm = () => true;
      win.electronAPI = { platform: "win", quit: async (o) => { quits.push(o); return { cancelled: true }; } };
    },
    onFetch(u) { if (u === "/api/electron/reinstall") return _json({ ok: true }); },
  });
  d.getElementById("adv-electron-btn").click();
  await _sleep(900);
  assert.equal(quits.length, 1);
  assert.equal(quits[0].relaunch, true);
  const toasts = [...d.querySelectorAll(".toast")].map((t) => t.textContent);
  assert.ok(toasts.some((t) => /next time you open the app/.test(t)), JSON.stringify(toasts));
  w.close();
});
