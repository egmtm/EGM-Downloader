// Quality popups: a description that would wrap is made a little smaller until it fits on one line, never
// below 10px; one that still does not fit wraps at its normal size (EGM, Nov 15). jsdom has no layout, so
// each description gets a width model: its one line width at 12px scales with its font size.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

const BOX = 200;   // the width a description has inside its row

// widths: one line width at 12px for each description of the popup, in order
function model(w, modalId, widths) {
  const els = [...w.document.querySelectorAll(`#${modalId} .quality-desc`)];
  els.forEach((el, i) => {
    const at12 = widths[i] ?? 100;
    Object.defineProperty(el, "clientWidth", { configurable: true, get: () => BOX });
    Object.defineProperty(el, "scrollWidth", { configurable: true, get: () => {
      const size = parseFloat(el.style.fontSize || "12");
      const line = Math.ceil(at12 * size / 12);
      return el.style.whiteSpace === "nowrap" ? line : Math.min(line, BOX);
    } });
  });
  const real = w.getComputedStyle.bind(w);
  w.getComputedStyle = (el, ...rest) => el.classList?.contains("quality-desc")
    ? { fontSize: el.style.fontSize || "12px" } : real(el, ...rest);
  return els;
}

test("opening the audio popup: a line that fits is untouched, one that wraps shrinks just enough, one that would go below 10px wraps at its normal size", async () => {
  const { w, d } = await bootPage();
  const els = model(w, "audio-quality-modal", [190, 220, 260]);   // fits, needs about 10.9px, needs about 9.2px
  d.getElementById("dl-all-audio-btn").click();
  assert.equal(d.getElementById("audio-quality-modal").style.display, "flex");
  assert.equal(els[0].style.fontSize, "", "a line that fits keeps its size");
  const s = parseFloat(els[1].style.fontSize);
  assert.ok(s < 12 && s >= 10, `shrunk to ${s}px`);
  assert.ok(els[1].scrollWidth <= els[1].clientWidth, "it fits on one line");
  assert.ok(Math.ceil(220 * (s + 0.25) / 12) > BOX, "not smaller than it needs to be");
  assert.equal(els[1].style.whiteSpace, "nowrap");
  assert.equal(els[2].style.fontSize, "", "below the floor it keeps its normal size");
  assert.equal(els[2].style.whiteSpace, "", "and wraps as before");
});

test("the video popup is fitted the same way when it opens", async () => {
  const { w, d } = await bootPage();
  const els = model(w, "video-quality-modal", [100, 230]);
  w.showVideoQualityModal();
  assert.equal(els[0].style.fontSize, "");
  assert.ok(parseFloat(els[1].style.fontSize) < 12 && els[1].scrollWidth <= els[1].clientWidth);
});

test("opening again starts from the normal size: a line that no longer needs it is not left small (a shorter text after a language change)", async () => {
  const { w, d } = await bootPage();
  let at12 = 230;
  const [el] = model(w, "audio-quality-modal", [0]);
  Object.defineProperty(el, "scrollWidth", { configurable: true, get: () => {
    const line = Math.ceil(at12 * parseFloat(el.style.fontSize || "12") / 12);
    return el.style.whiteSpace === "nowrap" ? line : Math.min(line, BOX);
  } });
  d.getElementById("dl-all-audio-btn").click();
  assert.ok(parseFloat(el.style.fontSize) < 12, "shrunk the first time");
  d.getElementById("audio-quality-modal").style.display = "none";
  at12 = 150;
  d.getElementById("dl-all-audio-btn").click();
  assert.equal(el.style.fontSize, "", "back to its normal size");
});

test("a resize while a popup is open fits it again; a closed popup is left alone", async () => {
  const { w, d } = await bootPage();
  const a = model(w, "audio-quality-modal", [150]);
  const v = model(w, "video-quality-modal", [230]);
  d.getElementById("dl-all-audio-btn").click();
  assert.equal(a[0].style.fontSize, "");
  Object.defineProperty(a[0], "clientWidth", { configurable: true, get: () => 140 });   // the window got narrower
  w.dispatchEvent(new w.Event("resize"));
  assert.ok(parseFloat(a[0].style.fontSize) < 12 && a[0].scrollWidth <= a[0].clientWidth);
  assert.equal(v[0].style.fontSize, "", "the closed video popup was not touched");
});
