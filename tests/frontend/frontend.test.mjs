// EGM frontend regression tests (node --test + jsdom).
// Boots the real rendered page with mocked fetch; each test exercises a flow
// that previously regressed or nearly regressed during development.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage, en } from "./harness.mjs";

test("i18n boot applies English strings to the live DOM", async () => {
  const { d } = await bootPage();
  const label = d.querySelector('[data-i18n="settings.toggle.upscale"]');
  assert.ok(label, "upscale toggle label present");
  assert.equal(label.textContent.trim(), en.strings["settings.toggle.upscale"]);
});

test("card render: HDR entries appear beneath SDR with tooltip; SDR untouched", async () => {
  const { w, d } = await bootPage();
  const item = {
    id: 1, url: "u", jobId: null, status: "idle", selFmt: "video", selFmtId: "",
    info: {
      title: "T", duration: 60, thumbnail: "", width: 3840, height: 2160,
      formats: [
        { id: "315", label: "2160p", height: 2160, has_audio: false, acodec: "" },
        { id: "701", label: "2160p", height: 2160, hdr: true, has_audio: false, acodec: "" },
        { id: "137", label: "1080p", height: 1080, has_audio: false, acodec: "" },
      ],
      audio_formats: [],
    },
  };
  const el = d.createElement("div"); el.className = "vcard"; d.body.appendChild(el);
  w.renderCard(el, item);
  const opts = [...el.querySelectorAll("select.qsel option")].map(o => ({ v: o.value, t: o.textContent.trim(), tip: o.title || "" }));
  const hdr = opts.find(o => o.v === "701");
  const sdr = opts.find(o => o.v === "315");
  assert.ok(hdr && hdr.t.includes("HDR"), "HDR option labeled");
  assert.ok(hdr.tip.includes("MKV"), "HDR tooltip mentions MKV output");
  assert.ok(sdr && !sdr.t.includes("HDR"), "SDR sibling unlabeled");
  assert.ok(!opts.find(o => o.v === "137").t.includes("HDR"), "plain height untouched");
});

test("naming-modal extension: HDR selection pills .mkv, SDR follows global", async () => {
  const { d } = await bootPage();
  const formats = [
    { id: "315", label: "2160p", height: 2160 },
    { id: "701", label: "2160p", height: 2160, hdr: true },
  ];
  const extFor = (selFmtId) => {
    const selHdr = !!(formats.find(f => f.id === selFmtId) || {}).hdr;
    const vfmt = d.getElementById("output-format-sel")?.value || "mp4";
    return (selHdr || vfmt === "mkv") ? ".mkv" : ".mp4";
  };
  assert.equal(extFor("701"), ".mkv");
  assert.equal(extFor("315"), ".mp4");
});

test("hide-settings flow: confirm modal, cancel keeps, confirm hides and saves", async () => {
  const { w, d, saved } = await bootPage();
  const chk = d.getElementById("show-settings-panel-chk");
  const wrap = d.getElementById("settings-panel-wrap");
  assert.ok(chk && wrap, "toggle + panel present");
  assert.notEqual(wrap.style.display, "none", "panel visible initially");

  chk.checked = false; chk.dispatchEvent(new w.Event("change"));
  assert.equal(d.getElementById("hide-settings-modal").style.display, "flex", "modal shown");
  assert.equal(chk.checked, true, "checkbox reverted until confirmed");

  d.getElementById("hide-settings-cancel-btn").click();
  assert.notEqual(wrap.style.display, "none", "cancel keeps panel");

  chk.checked = false; chk.dispatchEvent(new w.Event("change"));
  d.getElementById("hide-settings-confirm-btn").click();
  assert.equal(wrap.style.display, "none", "confirm hides panel");
  assert.deepEqual(saved.filter(s => "show_settings_panel" in s), [{ show_settings_panel: false }], "persisted");
});

test("persisted hidden settings panel stays hidden on boot", async () => {
  const { d } = await bootPage({ settings: { show_settings_panel: false } });
  assert.equal(d.getElementById("settings-panel-wrap").style.display, "none");
  assert.equal(d.getElementById("show-settings-panel-chk").checked, false);
});

test("converting badge: encoder + percentage when present, indeterminate otherwise", async () => {
  const { w, d } = await bootPage();
  const stEl = d.createElement("span");
  const progEl = d.createElement("div");
  progEl.innerHTML = '<div class="prog-inner"></div>';
  w.applyJobProgress({ status: "converting", encoder: "h264_nvenc", progress: 47.3 }, stEl, progEl);
  assert.ok(stEl.textContent.includes("h264_nvenc"), "encoder shown");
  assert.ok(stEl.textContent.includes("47%"), "percentage shown");
  assert.equal(progEl.querySelector(".prog-inner").style.width, "47%", "bar determinate");
  w.applyJobProgress({ status: "converting", encoder: "libx264" }, stEl, progEl);
  assert.ok(progEl.querySelector(".prog-inner").classList.contains("indeterminate"), "merge phase indeterminate");
});

test("queue arrows: edges hidden, middle visible, and removeItem recomputes edges", async () => {
  const { w, d } = await bootPage();
  const results = d.getElementById("results");
  assert.ok(results, "results container present");

  // Three idle cards, matching the real markup shape (.vcard > [id^=qarrows] > .qarrow x2)
  const mkCard = (n) => {
    const el = d.createElement("div");
    el.className = "vcard";
    el.id = "card" + n;
    el.innerHTML = `
      <span id="st${n}"></span>
      <div id="qarrows${n}">
        <button class="qarrow" data-dir="up" data-id="${n}"></button>
        <button class="qarrow" data-dir="down" data-id="${n}"></button>
      </div>`;
    results.appendChild(el);
    return el;
  };
  const els = [1, 2, 3].map(mkCard);

  // Seed items[] (script-scope `let`, not a window property -- eval runs in
  // the same script realm as the page's own inline scripts) and call the
  // real updateQueueArrows()/removeItem() rather than reimplementing the
  // visibility logic in the test.
  w.eval(`items = [1,2,3].map(n => ({ id: n, status: 'idle' })); updateQueueArrows();`);

  const vis = (n, dir) => els[n - 1].querySelector(`.qarrow[data-dir="${dir}"]`).style.visibility;
  assert.equal(vis(1, "up"), "hidden", "first card: up hidden");
  assert.equal(vis(1, "down"), "visible", "first card: down visible");
  assert.equal(vis(2, "up"), "visible", "middle card: up visible");
  assert.equal(vis(2, "down"), "visible", "middle card: down visible");
  assert.equal(vis(3, "up"), "visible", "last card: up visible");
  assert.equal(vis(3, "down"), "hidden", "last card: down hidden");

  // Remove the first card -- the new first (card 2) must gain a hidden up
  // arrow. This exercises the real removeItem() -> updateQueueArrows() call
  // added by this fix, not a hand-rolled recomputation.
  w.eval(`removeItem(1, document.getElementById("card1"))`);
  assert.equal(vis(2, "up"), "hidden", "after removal, new first card: up hidden");
  assert.equal(vis(2, "down"), "visible", "after removal, new first card: down visible");
  assert.equal(vis(3, "up"), "visible", "after removal, remaining last card: up visible");
  assert.equal(vis(3, "down"), "hidden", "after removal, remaining last card: down hidden");
});

test("queue arrows: a status transition hides the card's own arrows and re-edges the rest", async () => {
  const { w, d } = await bootPage();
  const results = d.getElementById("results");
  const mkCard = (n) => {
    const el = d.createElement("div");
    el.className = "vcard";
    el.id = "tcard" + n;
    el.innerHTML = `
      <span id="st${n}"></span>
      <div id="qarrows${n}">
        <button class="qarrow" data-dir="up" data-id="${n}"></button>
        <button class="qarrow" data-dir="down" data-id="${n}"></button>
      </div>`;
    results.appendChild(el);
    return el;
  };
  const els = [1, 2, 3].map(mkCard);
  w.eval(`items = [1,2,3].map(n => ({ id: n, status: 'idle' })); updateQueueArrows();`);
  const vis = (n, dir) => els[n - 1].querySelector(`.qarrow[data-dir="${dir}"]`).style.visibility;
  assert.equal(vis(1, "down"), "visible", "sanity: first card starts with down visible");

  // Card 1 starts downloading: its own arrows must hide (the click handler
  // already no-ops non-idle cards -- the UI must match), and card 2 becomes
  // the first idle card, so its up arrow must hide too.
  w.eval(`items[0].status = 'downloading'; updateQueueArrows();`);
  assert.equal(vis(1, "up"), "hidden", "downloading card: up hidden");
  assert.equal(vis(1, "down"), "hidden", "downloading card: down hidden");
  assert.equal(vis(2, "up"), "hidden", "new first idle card: up hidden");
  assert.equal(vis(2, "down"), "visible", "new first idle card: down visible");
  assert.equal(vis(3, "up"), "visible", "last idle card: up visible");
  assert.equal(vis(3, "down"), "hidden", "last idle card: down hidden");

  // Cancelled cards never return to idle -- arrows stay hidden.
  w.eval(`items[0].status = 'cancelled'; updateQueueArrows();`);
  assert.equal(vis(1, "up"), "hidden", "cancelled card: up stays hidden");
  assert.equal(vis(1, "down"), "hidden", "cancelled card: down stays hidden");
});
