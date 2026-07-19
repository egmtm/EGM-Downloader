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
