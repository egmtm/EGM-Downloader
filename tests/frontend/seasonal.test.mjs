// Seasonal themes: the shared window table (theme_data.html) and the main window picker.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const src = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "templates", "theme_data.html"), "utf8");
const seasonalVisibleKeys = new Function(src + "\nreturn seasonalVisibleKeys;")();
const on = (y, m, d) => [...seasonalVisibleKeys(new Date(y, m - 1, d, 12))];

test("windows: Hanami, Velvet Rose and the newer themes follow their dates", () => {
  assert.ok(on(2026, 3, 19).indexOf("hanami") < 0 && on(2026, 3, 20).includes("hanami"), "Hanami opens Mar 20");
  assert.ok(on(2026, 5, 5).includes("hanami") && !on(2026, 5, 6).includes("hanami"), "Hanami closes after May 5");
  assert.ok(on(2026, 2, 14).includes("velvetrose") && !on(2026, 7, 1).includes("velvetrose"), "Velvet Rose around Valentine's");
  assert.ok(on(2026, 10, 18).includes("halloween") && !on(2026, 10, 18).includes("hanami"));
  assert.ok(on(2026, 5, 1).includes("vesak") && on(2026, 4, 5).includes("qingming"), "variable dates still work");
  assert.ok(on(2026, 12, 25).includes("christmas") && on(2027, 1, 10).includes("christmas"), "year wrap");
});

// Boots the rendered main page with the clock frozen at y-m-d (self-contained, so it runs on any branch's harness).
async function seasonalRowsShownOn(y, m, d) {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const en = JSON.parse(readFileSync(join(root, "languages", "en.json"), "utf8"));
  const html = readFileSync(process.env.EGM_RENDERED_PAGE || "/tmp/egm_rendered_index.html", "utf8");
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost/",
    beforeParse(w) {
      w.fetch = async (u) => {
        if (u === "/api/settings") return { ok: true, json: async () => ({ language: "en" }) };
        if (u === "/api/language/en") return { ok: true, json: async () => en };
        return { ok: true, json: async () => ({ ok: true }), text: async () => "" };
      };
      w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
      w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
      const Real = w.Date;
      w.Date = class extends Real {
        constructor(...a) { if (a.length) super(...a); else super(y, m - 1, d, 12); }
        static now() { return new Real(y, m - 1, d, 12).getTime(); }
      };
    },
  });
  await new Promise((r) => setTimeout(r, 500));
  const shown = [...dom.window.document.querySelectorAll(".theme-row[data-seasonal]")]
    .filter((r) => r.style.display !== "none").map((r) => r.dataset.theme).sort();
  dom.window.close();
  return shown;
}

test("main picker: visible seasonal rows are exactly the shared set", async () => {
  for (const [y, m, d] of [[2026, 4, 10], [2026, 2, 14], [2026, 10, 18], [2026, 7, 20]]) {
    assert.deepEqual(await seasonalRowsShownOn(y, m, d), on(y, m, d).sort(), `picker rows on ${y}-${m}-${d}`);
  }
});
