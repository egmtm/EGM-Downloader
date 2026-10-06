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

// ── Subscriptions window ────────────────────────────────────────────────────
// Boots the rendered Subscriptions page (render_page.py writes it next to the
// main page as <name>_subs.html). Intervals are captured instead of run so a
// test drives pollJobs() and the "Quit when done" countdown tick by tick, and
// window.electronAPI is a recorder.
export function bootSubsPage({ probeBusy = false } = {}) {
  const main = process.env.EGM_RENDERED_PAGE || "/tmp/egm_rendered_index.html";
  const html = readFileSync(main.replace(/(\.[^./]+)?$/, "_subs$1"), "utf8");
  const calls = { quit: [], fetch: [] };
  const timers = new Map();
  const status = {};          // jobId -> status string served by /api/status/<id>
  const ctl = { probeBusy };
  let nextTimer = 1000;
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost/",
    beforeParse(w) {
      w.setInterval = (fn) => { const id = nextTimer++; timers.set(id, fn); return id; };
      w.clearInterval = (id) => { timers.delete(id); };
      // quit() records a copy of its argument so the Node side compares same-realm objects
      w.electronAPI = {
        quit: async (opts) => { calls.quit.push({ ...opts }); return opts && opts.probe ? { busy: ctl.probeBusy } : { success: true }; },
        setActivity() {}, notifySubsDownloads() {}, closeSubscriptions() {},
      };
      w.fetch = async (u, o) => {
        calls.fetch.push(u);
        let m;
        if ((m = /^\/api\/status\/(.+)$/.exec(u))) return { ok: true, json: async () => ({ status: status[m[1]] || "downloading", progress: 10 }) };
        if (u === "/api/settings") return { ok: true, json: async () => ({ language: "en" }) };
        if (u === "/api/language/en") return { ok: true, json: async () => en };
        return { ok: true, json: async () => ({}), text: async () => "" };
      };
      w.matchMedia = w.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));
      w.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    },
  });
  const w = dom.window;
  return new Promise((resolve) => setTimeout(() => resolve({
    dom, w, d: w.document, calls, status, ctl,
    // Fire the interval the page registered under this id (e.g. w.eval("_quitTimer")).
    tick: (id) => timers.get(id)?.(),
    // Add a download to the queue the way the page does, then open the queue view.
    addJob: (videoId, jobId) => w.eval(`allJobs.set(${JSON.stringify(videoId)}, { jobId: ${JSON.stringify(jobId)}, status: 'downloading', subId: 's1', data: {} }); showQueue = true; renderQueue();`),
    poll: () => w.eval("pollJobs()"),
  }), 900));
}
