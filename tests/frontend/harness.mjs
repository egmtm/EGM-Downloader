// Shared jsdom boot scaffold for EGM frontend tests.
// Loads the pre-rendered index (tests/frontend/render_page.py), mocks fetch,
// and resolves once the i18n boot has applied English strings.
import { JSDOM } from "jsdom";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, "..", "..");
export const en = JSON.parse(readFileSync(join(repo, "languages", "en.json"), "utf8"));

// The actual running app version, read from the same rendered HTML bootPage
// loads below -- never hardcode this in a test. A hardcoded version string
// used to "mark the current version as already seen" (to suppress the
// once-per-version auto-show) goes stale the moment the app version bumps,
// silently flipping the auto-show back on and breaking any test that assumed
// the modal starts hidden. Reading it dynamically means this can't recur.
export const CURRENT_APP_VERSION = (() => {
  const html = readFileSync(process.env.EGM_RENDERED_PAGE || "/tmp/egm_rendered_index.html", "utf8");
  const m = html.match(/id="footer-version-pill"[^>]*>v?([\d.]+)</);
  if (!m) throw new Error("could not read the current app version from footer-version-pill in the rendered page");
  return m[1];
})();

export function bootPage({ settings = {}, onFetch } = {}) {
  const html = readFileSync(process.env.EGM_RENDERED_PAGE || "/tmp/egm_rendered_index.html", "utf8");
  const saved = [];
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost/",
    beforeParse(w) {
      w.fetch = async (u, o) => {
        if (onFetch) { const r = onFetch(u, o); if (r) return r; }
        if (u === "/api/settings") return { ok: true, json: async () => ({ language: "en", ...settings }) };
        if (u === "/api/language/en") return { ok: true, json: async () => en };
        if (u === "/api/settings/save" && o) { saved.push(JSON.parse(o.body)); return { ok: true, json: async () => ({ ok: true }) }; }
        return { ok: true, json: async () => ({ ok: true }), text: async () => "" };
      };
      w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
      w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    },
  });
  return new Promise((resolve) => setTimeout(() => resolve({ dom, w: dom.window, d: dom.window.document, saved }), 900));
}
