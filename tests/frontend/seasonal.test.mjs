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
  assert.ok(on(2026, 5, 10).includes("velvetrose") && !on(2026, 2, 14).includes("velvetrose") && !on(2026, 7, 1).includes("velvetrose"), "Velvet Rose around Mother's Day (second Sunday of May), no longer around Valentine's");
  assert.ok(on(2026, 10, 18).includes("halloween") && !on(2026, 10, 18).includes("hanami"));
  assert.ok(on(2026, 5, 1).includes("vesak") && on(2026, 4, 5).includes("qingming"), "variable dates still work");
  assert.ok(on(2026, 12, 25).includes("christmas") && on(2027, 1, 10).includes("christmas"), "year wrap");
});

test("variable holidays: Hanukkah keeps its full window past New Year, from the right year", () => {
  assert.ok(on(2028, 1, 23).includes("hanukkah"), "Hanukkah 2027 is Dec 24, so it runs to Jan 23");
  assert.ok(!on(2028, 1, 24).includes("hanukkah"), "and ends there");
  assert.ok(on(2027, 1, 3).includes("hanukkah") && !on(2027, 1, 4).includes("hanukkah"), "Hanukkah 2026 is Dec 4, so it ends Jan 3, not at the next year's end");
  assert.ok(!on(2027, 1, 20).includes("hanukkah"));
});

test("variable holidays: every day 2026 to 2030, any time of day, equals 30 days either side of the real date", () => {
  const DAY = 86400000;
  const dates = new Function(src + "\nreturn SEASONAL_VARIABLE;")();
  const truth = (key, y, m, d) => Object.entries(dates[key]).some(([Y, [hm, hd]]) =>
    Math.abs(Math.round((Date.UTC(y, m, d) - Date.UTC(+Y, hm - 1, hd)) / DAY)) <= 30);
  for (let t = Date.UTC(2026, 0, 1); t < Date.UTC(2031, 0, 1); t += DAY) {
    const u = new Date(t), y = u.getUTCFullYear(), m = u.getUTCMonth(), d = u.getUTCDate();
    for (const hour of [0, 12, 23]) {
      const got = seasonalVisibleKeys(new Date(y, m, d, hour, hour ? 30 : 5));
      for (const key of Object.keys(dates)) {
        assert.equal(got.has(key), truth(key, y, m, d), `${key} on ${y}-${m + 1}-${d} ${hour}h`);
      }
    }
  }
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

// Random theme on launch: boots the rendered page with the clock frozen and Math.random fixed,
// and returns the theme the page ended up with.
const themeSrc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "templates", "js", "_theme.html"), "utf8");
const THEMES = [...themeSrc.match(/const THEMES = \[([\s\S]*?)\];/)[1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
const THEME_DATA = new Function(src + "\nreturn THEME_DATA;")();
const isSeasonal = (k) => !!THEME_DATA[k] && THEME_DATA[k].cat === "seasonal";

async function launchTheme(settings, rnd, [y, m, d]) {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const en = JSON.parse(readFileSync(join(root, "languages", "en.json"), "utf8"));
  const html = readFileSync(process.env.EGM_RENDERED_PAGE || "/tmp/egm_rendered_index.html", "utf8");
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost/",
    beforeParse(w) {
      w.fetch = async (u) => {
        if (u === "/api/settings") return { ok: true, json: async () => ({ language: "en", ...settings }) };
        if (u === "/api/language/en") return { ok: true, json: async () => en };
        return { ok: true, json: async () => ({ ok: true }), text: async () => "" };
      };
      w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
      w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
      w.Math.random = () => rnd;
      const Real = w.Date;
      w.Date = class extends Real {
        constructor(...a) { if (a.length) super(...a); else super(y, m - 1, d, 12); }
        static now() { return new Real(y, m - 1, d, 12).getTime(); }
      };
    },
  });
  await new Promise((r) => setTimeout(r, 700));
  const theme = dom.window.localStorage.getItem("egm-theme");
  dom.window.close();
  return theme;
}

const JULY_20 = [2026, 7, 20];
const closedOnJuly20 = () => {
  const visible = seasonalVisibleKeys(new Date(2026, 6, 20, 12));
  return { visible, out: THEMES.map((k, i) => [k, i]).filter(([k]) => isSeasonal(k) && !visible.has(k)) };
};

test("random theme on launch (all themes): a seasonal theme outside its window is never picked", async () => {
  const { visible, out } = closedOnJuly20();
  assert.ok(out.length > 10, "most seasonal themes are closed on Jul 20");
  // The random value points at a closed seasonal theme's place in the full list: first, middle and last one.
  for (const [key, i] of [out[0], out[Math.floor(out.length / 2)], out[out.length - 1]]) {
    const got = await launchTheme({ random_theme_on_launch: true, random_theme_scope: "all" }, (i + 0.5) / THEMES.length, JULY_20);
    assert.ok(!isSeasonal(got) || visible.has(got), `"${got}" is seasonal and closed on Jul 20 (the random value pointed at ${key})`);
  }
});

test("random theme on launch (all themes): a seasonal theme inside its window can still be picked", async () => {
  const { visible } = closedOnJuly20();
  const pool = THEMES.filter((k) => !isSeasonal(k) || visible.has(k));
  assert.ok(visible.has("fourthofjuly"));
  const got = await launchTheme({ random_theme_on_launch: true, random_theme_scope: "all" }, (pool.indexOf("fourthofjuly") + 0.5) / pool.length, JULY_20);
  assert.equal(got, "fourthofjuly");
});

test("random theme on launch (favorites): a favorite outside its window is skipped too", async () => {
  const got = await launchTheme({ random_theme_on_launch: true, random_theme_scope: "favorites", favorite_themes: ["ogcream", "valentines"] }, 0.99, JULY_20);
  assert.equal(got, "ogcream", "Valentine's Day is closed on Jul 20, so the only candidate left is the other favorite");
});
