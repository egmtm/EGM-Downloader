// compareVersions (footer "Check for updates") handles any number of numbers:
// 1.5.0, 1.5.1.3, 1.5.1.3.1. A missing number counts as 0.
import test from "node:test";
import assert from "node:assert/strict";
import { bootPage } from "./harness.mjs";

test("compareVersions: 3, 4 and 5 numbers", async () => {
  const { w } = await bootPage();
  const cmp = (a, b) => w.eval(`compareVersions(${JSON.stringify(a)}, ${JSON.stringify(b)})`);

  // latest newer = 1, equal = 0, current newer = -1
  assert.equal(cmp("1.4.3", "1.4.4"), 1);                 // three numbers, as before
  assert.equal(cmp("1.4.13", "1.5.1.3"), 1);              // 1.4.x to the mirrored line
  assert.equal(cmp("v1.5.0", "1.5.0"), 0);
  assert.equal(cmp("1.5.1", "1.5.1.1"), 1);               // the fourth number decides
  assert.equal(cmp("1.5.1.1", "1.5.1"), -1);
  assert.equal(cmp("1.5.1", "1.5.1.0"), 0);               // pinned: a missing number is 0
  assert.equal(cmp("1.5.1.0", "1.5.1"), 0);
  assert.equal(cmp("1.5.1.3", "1.5.1.4"), 1);
  assert.equal(cmp("1.5.1.9", "1.5.1.10"), 1);            // numbers, not text
  assert.equal(cmp("1.5.1.3", "1.5.1.3.1"), 1);           // our own patch on the same Electron
  assert.equal(cmp("1.5.1.3.1", "1.5.1.3"), -1);
  assert.equal(cmp("1.5.1.3.2", "1.5.1.3.10"), 1);
  assert.equal(cmp("1.5.1.3.1", "1.5.1.3.1"), 0);
  assert.equal(cmp("1.5.1.3.1", "1.5.2.0"), 1);           // the next Electron minor beats a five number patch
});
