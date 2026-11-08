// Set the one version string electron-builder cannot set on the packaged exe (it always writes an
// empty OriginalFilename), then check every string against what the app's exe has always shown.
// Runs before the exe is signed. resedit is the library electron-builder itself edits the exe with,
// installed from the staging lock.
//
// usage: node exe_strings.js <stage_electron_dir> <exe> <version> <build>
'use strict';
const fs = require('fs');
const [, , stage, exe, version, build] = process.argv;
const resedit = require(require.resolve('resedit', { paths: [stage] }));

const want = {
  CompanyName: 'egerena.com',
  FileDescription: 'EGM Downloader',
  ProductName: 'EGM Downloader',
  InternalName: 'EGM Downloader',
  OriginalFilename: 'EGM Downloader.exe',
  FileVersion: `${version}.${build}`,
  ProductVersion: version,
};

const pe = resedit.NtExecutable.from(fs.readFileSync(exe));
const res = resedit.NtExecutableResource.from(pe);
const vi = resedit.Resource.VersionInfo.fromEntries(res.entries)[0];
const lang = vi.getAllLanguagesForStringValues()[0];
vi.setStringValues(lang, { OriginalFilename: want.OriginalFilename });
vi.outputToResourceEntries(res.entries);
res.outputResource(pe);
fs.writeFileSync(exe, Buffer.from(pe.generate()));

// Read back from the written file
const check = resedit.Resource.VersionInfo.fromEntries(
  resedit.NtExecutableResource.from(resedit.NtExecutable.from(fs.readFileSync(exe))).entries)[0];
const got = check.getStringValues(lang);
const fixed = (ms, ls) => [ms >>> 16, ms & 0xffff, ls >>> 16, ls & 0xffff].join('.');
const fileFixed = fixed(check.fixedInfo.fileVersionMS, check.fixedInfo.fileVersionLS);
const productFixed = fixed(check.fixedInfo.productVersionMS, check.fixedInfo.productVersionLS);
let bad = 0;
for (const [k, v] of Object.entries(want)) {
  const ok = got[k] === v;
  if (!ok) bad++;
  console.log(`   ${ok ? '✓' : '❌'} ${k}: ${got[k] === undefined ? '(missing)' : got[k]}${ok ? '' : `   (expected ${v})`}`);
}
for (const [k, v] of [['fixed FileVersion', fileFixed], ['fixed ProductVersion', productFixed]]) {
  const ok = v === version;
  if (!ok) bad++;
  console.log(`   ${ok ? '✓' : '❌'} ${k}: ${v}${ok ? '' : `   (expected ${version})`}`);
}
if (bad) { console.error(`❌ ${bad} version field(s) of ${exe} are not as expected`); process.exit(1); }
