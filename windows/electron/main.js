const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage, screen, session, powerSaveBlocker } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');
const os   = require('os');
const crypto = require('crypto');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const EGM_TOKEN = crypto.randomBytes(32).toString('hex');
const APP_URL = `http://${HOST}:${PORT}`;

// ── Windows shell identity (taskbar, notifications) ──────────────────────────
if (process.platform === 'win32') {
  app.setAppUserModelId('com.egerena.egm-downloader');
}

// ── Portable mode: redirect Electron userData into the portable folder ─────────
// Must be called BEFORE app ready — Chromium locks userData path on startup.
// Prevents localStorage/theme state leaking to %APPDATA% in portable builds.
// Everything the user owns sits in <root>\data, the folder app.py already uses, so copying
// that one folder when updating carries it all over. Earlier versions kept Electron's data in
// <root>\electron-data: it is moved in on the first start, and used where it is if it cannot be.
const _portableMarker = path.join(installDir(), '.portable');
const _isPortable = fs.existsSync(_portableMarker);
// Anchor to the install folder (parent of electron/), NOT process.cwd().
// cwd depends on how the process was launched and is not guaranteed to be the
// portable root; using __dirname makes this deterministic.
const _dataRoot = _isPortable ? path.join(installDir(), 'data') : installDir();
if (_isPortable) {
  const _oldUserData = path.join(installDir(), 'electron-data');
  let _userData = path.join(_dataRoot, 'electron-data');
  try {
    fs.mkdirSync(_dataRoot, { recursive: true });
    if (fs.existsSync(_oldUserData) && !fs.existsSync(_userData)) fs.renameSync(_oldUserData, _userData);
  } catch {
    if (fs.existsSync(_oldUserData)) _userData = _oldUserData;
  }
  app.setPath('userData', _userData);
}

// ── Settings file (same location as app.py's: BASE_DIR, or the data folder in portable) ──
const SETTINGS_FILE = path.join(_dataRoot, 'egm_settings.json');
// Portable, one time: earlier versions kept the window position in a root egm_settings.json.
if (_isPortable) {
  try {
    const _oldSettings = path.join(installDir(), 'egm_settings.json');
    if (fs.existsSync(_oldSettings)) {
      const _old = JSON.parse(fs.readFileSync(_oldSettings, 'utf8'));
      const _now = loadSettings();
      const _patch = {};
      for (const k of ['window_bounds', 'window_maximized']) {
        if (_old[k] !== undefined && _now[k] === undefined) _patch[k] = _old[k];
      }
      if (Object.keys(_patch).length) saveSettings(_patch);
      fs.unlinkSync(_oldSettings);
    }
  } catch {}
}

// ── Folders ───────────────────────────────────────────────────────────────────
// Started by the launcher, this file is in <install>\electron and the app files are in <install>.
// The packaged build (Electron, Python and the app in one folder) keeps this file inside
// resources\app.asar, the backend, languages and icons in resources\app, and the exe at the top of
// the install folder. Not app.isPackaged: that only looks at the exe's name, and the launcher
// renames electron.exe to "EGM Downloader.exe", so it is already true for the launcher's Electron.
// Function declarations, so the portable set up above can use them before this point.
function packagedLayout() { return path.basename(__dirname).toLowerCase() === 'app.asar'; }
function installDir()     { return packagedLayout() ? path.dirname(process.execPath) : path.join(__dirname, '..'); }
function appFilesDir()    { return packagedLayout() ? path.join(process.resourcesPath, 'app') : path.join(__dirname, '..'); }
const PACKAGED    = packagedLayout();
const INSTALL_DIR = installDir();
const APP_DIR     = appFilesDir();

// ── Window hardening: route external links to default browser, block navigation ─
function hardenWindow(win) {
  // External links → user's default browser. Parse with URL() (not startsWith) and
  // open https only — never hand shell.openExternal an unvalidated string, which
  // could otherwise be coaxed into other URL schemes.
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const u = new URL(url);
      if (u.protocol === 'https:') {
        shell.openExternal(u.toString());
      }
    } catch {}
    return { action: 'deny' };
  });
  // Block in-window navigation away from the exact Flask origin (scheme+host+PORT).
  // Matching only the hostname would allow navigation to any other local service
  // on a different port; origin equality pins it to our own backend.
  win.webContents.on('will-navigate', (event, url) => {
    try {
      const u = new URL(event.url ?? url);   // Electron 45 deprecates the positional url (event.url carries it)
      if (u.origin !== APP_URL) {
        event.preventDefault();
      }
    } catch {
      event.preventDefault();
    }
  });
  // Block webview attachment — we don't use webviews
  win.webContents.on('will-attach-webview', (event) => {
    event.preventDefault();
  });
}

function loadSettings() {
  try { return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')); }
  catch { return {}; }
}

// Atomic JSON write (tmp + rename) — mirrors app.py's atomic settings writes so a
// kill mid-write can't leave a truncated/corrupt egm_settings.json.
function atomicWriteJson(file, data) {
  // Not `${file}.tmp`: the backend writes the same settings file through that name, and two
  // writers sharing one temporary file can rename the other's half written copy into place.
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2), 'utf8');
  fs.renameSync(tmp, file);
}

function saveSettings(patch) {
  try {
    const s = loadSettings();
    Object.assign(s, patch);
    atomicWriteJson(SETTINGS_FILE, s);
  } catch {}
}

// Validate that an IPC message originated from our own Flask-origin pages.
// Every window shares one preload, so without this check any renderer content
// (e.g. a hijacked page) could invoke sensitive IPC. Fail-closed on any error.
function isTrustedSender(event) {
  try {
    const url = (event.senderFrame && event.senderFrame.url) || event.sender.getURL();
    return new URL(url).origin === APP_URL;
  } catch {
    return false;
  }
}

// ── Window state helpers ──────────────────────────────────────────────────────
const DEFAULT_BOUNDS = { width: 920, height: 780 };

function isOnScreen(bounds) {
  return screen.getAllDisplays().some(d => {
    const { x, y, width, height } = d.workArea;
    // Allow 50px tolerance for partially off-screen windows
    return bounds.x >= x - 50 && bounds.y >= y - 50 &&
           bounds.x + bounds.width  <= x + width  + 50 &&
           bounds.y + bounds.height <= y + height + 50;
  });
}

function loadWindowState() {
  const s = loadSettings();
  return {
    bounds:    s.window_bounds    || null,
    maximized: s.window_maximized || false,
  };
}

function saveWindowState() {
  if (!mainWindow) return;
  const maximized = mainWindow.isMaximized();
  // Only save bounds when not maximized — maximized bounds are the full screen
  const bounds = maximized ? loadWindowState().bounds : mainWindow.getBounds();
  saveSettings({ window_bounds: bounds, window_maximized: maximized });
}

function restoreWindowState() {
  if (!mainWindow) return;
  const { bounds, maximized } = loadWindowState();
  if (maximized) {
    mainWindow.maximize();
  } else if (bounds && isOnScreen(bounds)) {
    mainWindow.setBounds(bounds);
  }
}

// ── Debounce ──────────────────────────────────────────────────────────────────
function debounce(fn, delay) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

let mainWindow  = null;
let splashWindow = null;
let flaskProc   = null;
let backendAnswered = false;   // this run's backend has answered once (the page loads)
let tray        = null;

// ── User agent ────────────────────────────────────────────────────────────────
// Electron writes "<app name>/<version>" and "Electron/<version>" into Chrome's user agent, which
// tells an image server which app (and which build) is asking. Keep only what Chrome itself sends.
// Whatever way the name is written (escaped, with a space, the package name), it sits between
// "(KHTML, like Gecko)" and "Chrome/". Chrome itself sends only its major version (Chrome/156.0.0.0);
// the full build number Electron writes would still single out this app among Chrome users.
function cleanUserAgent(ua) {
  return String(ua)
    .replace(/(\(KHTML, like Gecko\)) .*? (Chrome\/)/, '$1 $2')
    .replace(/ Electron\/\S+/, '')
    .replace(/ Chrome\/(\d+)\.\d+\.\d+\.\d+/, ' Chrome/$1.0.0.0');
}
app.userAgentFallback = cleanUserAgent(app.userAgentFallback);   // before any window exists

// ── History thumbnails ────────────────────────────────────────────────────────
// The picture of a finished download is fetched here, by Chromium, and handed to the backend, which
// checks it again and stores it (until now the backend fetched it with Python). The request carries
// the window's clean Chrome user agent (cleanUserAgent's result, app.userAgentFallback), no cookies
// (a session of its own, in memory, and no session cookies) and no Referer. The backend names the
// entry in an X-EGM-Thumbnail header on the page's own /api/status poll: nothing new is polled, and the
// page is given nothing (no IPC), so no script in a page can ask for a URL. The shell asks the backend
// for the URL it is waiting for (with the per run token), and only that URL is fetched, with the
// backend's guards: HTTPS only, every redirect hop checked against internal addresses before it is
// requested, the 500 KB cap counted while reading, a 15 second timeout, an image content type. When it
// fails, an empty body tells the backend, which then fetches the picture itself.
const { net } = require('electron');
const THUMB_CAP = 512000;
const THUMB_TIMEOUT_MS = 15000;
const THUMB_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
let thumbSession = null;
const thumbsInFlight = new Set();

// The addresses the backend's _is_internal_host refuses (private, loopback, link local, reserved,
// multicast, unspecified), and the shared 100.64.0.0/10 range too. Anything else that is not a public
// IPv4 address or a global IPv6 one (2000::/3 without its special and documentation ranges) counts as internal.
function isInternalAddress(ip) {
  const v4 = /^(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(ip);
  if (v4) {
    const [a, b, c] = v4.slice(1, 4).map(Number);
    return a === 0 || a === 10 || a === 127 || a >= 224 || (a === 100 && b >= 64 && b < 128) ||
      (a === 169 && b === 254) || (a === 172 && b >= 16 && b < 32) || (a === 192 && b === 168) ||
      (a === 192 && b === 0 && (c === 0 || c === 2)) || (a === 198 && (b === 18 || b === 19)) ||
      (a === 198 && b === 51 && c === 100) || (a === 203 && b === 0 && c === 113);
  }
  let s = String(ip).toLowerCase().split('%')[0];
  const tail = /^(.*:)(\d+)\.(\d+)\.(\d+)\.(\d+)$/.exec(s);   // ::ffff:1.2.3.4
  if (tail) {
    const n = tail.slice(2).map(Number);
    s = tail[1] + ((n[0] << 8) | n[1]).toString(16) + ':' + ((n[2] << 8) | n[3]).toString(16);
  }
  const halves = s.split('::');
  if (halves.length > 2) return true;
  const head = halves[0] ? halves[0].split(':') : [];
  const rest = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  const groups = [...head, ...Array(halves.length === 2 ? Math.max(8 - head.length - rest.length, 0) : 0).fill('0'), ...rest];
  if (groups.length !== 8 || groups.some((g) => !/^[0-9a-f]{1,4}$/.test(g))) return true;
  const [g0, g1] = groups.map((g) => parseInt(g, 16));
  return (g0 & 0xe000) !== 0x2000 || (g0 === 0x2001 && g1 < 0x200) || (g0 === 0x2001 && g1 === 0xdb8) || g0 === 0x2002 ||
    (g0 === 0x3fff && g1 < 0x1000);
}

// Resolved by Chromium's own resolver, the one the request then uses. A name that does not resolve
// counts as internal, as in the backend.
async function isInternalHost(host) {
  const h = String(host || '').replace(/^\[(.*)\]$/, '$1');
  if (!h) return true;
  try {
    const { endpoints } = await thumbSession.resolveHost(h);
    return !endpoints.length || endpoints.some((e) => isInternalAddress(e.address));
  } catch {
    return true;
  }
}

// One request, no redirect followed: { bytes }, { redirect: url } or null. Electron cancels a redirect
// that is not followed at once inside its event, and the next address is checked first (that takes a
// name lookup), so each hop is a request of its own.
function requestThumbnail(url) {
  return new Promise((resolve) => {
    let done = false;
    let req = null;
    const finish = (value) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try { req.abort(); } catch {}
      resolve(value);
    };
    const timer = setTimeout(() => finish(null), THUMB_TIMEOUT_MS);
    req = net.request({ url, session: thumbSession, useSessionCookies: false, credentials: 'omit',
                        referrerPolicy: 'no-referrer', redirect: 'manual' });
    req.setHeader('User-Agent', app.userAgentFallback);
    req.on('redirect', (status, method, to) => finish({ redirect: to }));
    req.on('response', (res) => {
      const type = String(res.headers['content-type'] || '').split(';')[0].trim().toLowerCase();
      if (res.statusCode < 200 || res.statusCode > 299 || !THUMB_TYPES.includes(type) ||
          Number(res.headers['content-length'] || 0) > THUMB_CAP) return finish(null);
      const parts = [];
      let size = 0;
      res.on('data', (chunk) => {
        size += chunk.length;
        if (size > THUMB_CAP) return finish(null);     // stop reading at the cap, whatever the length header said
        parts.push(chunk);
      });
      res.on('end', () => finish({ bytes: Buffer.concat(parts) }));
      res.on('error', () => finish(null));
    });
    req.on('error', () => finish(null));
    req.end();
  });
}

// The picture's bytes, or null when anything is refused or fails. Every address, the first and each
// redirect's, is checked before it is requested; at most 10 redirects, as urllib allows.
async function fetchThumbnail(url) {
  if (!thumbSession) thumbSession = session.fromPartition('egm-thumbnails', { cache: false });
  let next = url;
  for (let hop = 0; hop <= 10; hop++) {
    let u = null;
    try { u = new URL(next); } catch {}
    if (!u || u.protocol !== 'https:' || await isInternalHost(u.hostname)) return null;
    const got = await requestThumbnail(u.href);
    if (!got) return null;
    if (got.bytes) return got.bytes;
    try { next = new URL(got.redirect, u).href; } catch { return null; }
  }
  return null;
}

function backendCall(method, pathName, body) {
  return new Promise((resolve) => {
    const headers = { 'X-EGM-Token': EGM_TOKEN };
    if (body) Object.assign(headers, { 'Content-Type': 'application/octet-stream', 'Content-Length': body.length });
    const req = http.request(APP_URL + pathName, { method, headers }, (res) => {
      const parts = [];
      res.on('data', (chunk) => parts.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(parts).toString('utf8') }));
      res.on('error', () => resolve({ status: 0, body: '' }));
    });
    req.on('error', () => resolve({ status: 0, body: '' }));
    req.setTimeout(THUMB_TIMEOUT_MS, () => req.destroy());
    req.end(body);
  });
}

async function deliverThumbnail(entry) {
  if (thumbsInFlight.has(entry)) return;
  thumbsInFlight.add(entry);
  try {
    const asked = await backendCall('GET', `/api/history/${entry}/thumbnail`);
    if (asked.status !== 200) return;              // the backend is not waiting for it (any more): nothing is fetched
    let url = '';
    try { url = JSON.parse(asked.body).url; } catch {}
    const bytes = await fetchThumbnail(url);
    await backendCall('POST', `/api/history/${entry}/thumbnail`, bytes || Buffer.alloc(0));
  } finally {
    thumbsInFlight.delete(entry);
  }
}

// Every finished request of the windows passes here; only the app's own /api/status answer counts.
function noticeThumbnail(details) {
  let ours = false;
  try {
    const u = new URL(details.url);
    ours = u.origin === APP_URL && u.pathname.startsWith('/api/status/');
  } catch {}
  if (!ours) return;
  const name = Object.keys(details.responseHeaders || {}).find((k) => k.toLowerCase() === 'x-egm-thumbnail');
  const entry = name ? String(details.responseHeaders[name]) : '';
  if (/^[a-f0-9-]{1,64}$/.test(entry)) deliverThumbnail(entry).catch(() => {});
}

// ── Fix 1: Single-instance lock ───────────────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}
app.on('second-instance', () => {
  if (subsWindow && !subsWindow.isDestroyed()) {
    if (subsWindow.isMinimized()) subsWindow.restore();
    subsWindow.show();
    subsWindow.focus();
    return;
  }
  if (mainWindow) {
    restoreWindowState();
    if (!mainWindow.isVisible()) mainWindow.show();
    mainWindow.focus();
  }
});

// ── Icon helper ───────────────────────────────────────────────────────────────
function safeIcon(p, size) {
  if (fs.existsSync(p)) {
    const img = nativeImage.createFromPath(p);
    return size ? img.resize({ width: size, height: size }) : img;
  }
  return nativeImage.createEmpty();
}

// ── Find Python ───────────────────────────────────────────────────────────────
// The packaged build uses only the Python it ships with, and that Python sees only its own packages:
// no user site folder, and no PYTHON variable from the user's environment (the Pythons app.py starts
// inherit this environment; app.py itself also runs with -E -s). Windows names are not case
// sensitive, so any spelling of a name is dropped before the value is set.
function withoutEnv(env, names) {
  const drop = new Set(names);
  return Object.fromEntries(Object.entries(env).filter(([k]) => !drop.has(k.toUpperCase())));
}
function bundledPythonEnv(env) {
  return {
    ...withoutEnv(env, Object.keys(env).map(k => k.toUpperCase()).filter(k => k.startsWith('PYTHON')).concat('EGM_INSTALL_DIR')),
    PYTHONNOUSERSITE: '1',
    EGM_INSTALL_DIR: INSTALL_DIR,   // app.py keeps its data and downloaded tools here
  };
}

function findPython() {
  const candidates = PACKAGED ? [path.join(process.resourcesPath, 'python', 'python.exe')] : [
    path.join(process.resourcesPath, 'python', 'python.exe'),
    path.join(__dirname, '..', 'python', 'python.exe'),
    'python',
    'python3',
  ];
  for (const c of candidates) {
    try {
      // execFileSync passes args as a real argv array — no shell string to quote/escape.
      execFileSync(c, ['--version'], { stdio: 'ignore', windowsHide: true, ...(PACKAGED ? { env: bundledPythonEnv(process.env) } : {}) });
      return c;
    } catch {}
  }
  return null;
}

// Packaged, the box for a bundled Python that cannot run the app: it does not start at all, or the
// backend it starts stops before it ever answered (part of it quarantined or removed).
const BUNDLED_PYTHON_BOX = ['Python could not start',
  'The Python that comes with EGM Downloader could not start. Antivirus software may have blocked or removed it.\n\nReinstall EGM Downloader to restore it.'];

// ── Splash window ────────────────────────────────────────────────────────────
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 500,
    height: 350,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      sandbox:          true,
      spellcheck:       false,
    },
  });
  const _lang = (loadSettings().language || 'en');
  _splashReady = false;
  splashWindow.webContents.once('did-finish-load', () => {
    _splashReady = true;
    if (_splashPending) { const p = _splashPending; _splashPending = null; splashProgress(p[0], p[1]); }
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'), { query: { lang: _lang } });
  splashWindow.center();
  splashWindow.show();
}

// ── Splash progress ──────────────────────────────────────────────────────────
// Real start up steps move the splash bar. Only numbers go into the page. A call made
// before the page has loaded is held (the last one wins) and sent once it is ready.
let _splashReady = false;
let _splashPending = null;
function splashProgress(pct, secs) {
  if (!splashWindow || splashWindow.isDestroyed()) return;
  if (!_splashReady) { _splashPending = [pct, secs]; return; }
  const js = `window.setSplashProgress && window.setSplashProgress(${Number(pct) || 0}, ${Number(secs) || 0})`;
  splashWindow.webContents.executeJavaScript(js).catch(() => {});
}
function splashFadeOut() {
  if (!splashWindow || splashWindow.isDestroyed() || !_splashReady) return;
  splashWindow.webContents.executeJavaScript('window.splashOut && window.splashOut()').catch(() => {});
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashProgress(100, 0.15);          // fill the bar, then fade the card out
    setTimeout(splashFadeOut, 150);
    setTimeout(() => {
      if (splashWindow && !splashWindow.isDestroyed()) {
        splashWindow.close();
        splashWindow = null;
      }
    }, 450);
  }
}

// A box blocks the main process, so the timers closeSplash() waits on never run, and the splash is
// always on top: a box opened while it is up sits under it, out of reach. Drop it at once instead.
function dropSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) { splashWindow.destroy(); splashWindow = null; }
}

// ── Start Flask ───────────────────────────────────────────────────────────────
async function startFlask() {
  const python = findPython();
  const appPy  = path.join(APP_DIR, 'app.py');

  if (!python) {
    dropSplash();
    if (PACKAGED) {
      dialog.showErrorBox(...BUNDLED_PYTHON_BOX);
    } else {
      dialog.showErrorBox('Python not found',
        'Python 3.11+ is required.\n\nDownload from python.org and check "Add Python to PATH" during install.');
    }
    app.quit();
    return;
  }
  const env = { ...process.env, PORT: String(PORT), HOST, EGM_ELECTRON: '1', EGM_API_TOKEN: EGM_TOKEN };
  // -E -s: no PYTHON variable, no user site folder, and (from -E) no PythonPath entries from the
  // registry of a Python 3.11 installed on the machine. The bundled site-packages is not the user's.
  flaskProc = spawn(python, PACKAGED ? ['-E', '-s', appPy] : [appPy], {
    cwd: INSTALL_DIR,
    // EGM_INSTALL_DIR moves app.py's folders, so only the packaged build may set it.
    env: PACKAGED ? bundledPythonEnv(env) : withoutEnv(env, ['EGM_INSTALL_DIR']),
    windowsHide: true,
    stdio: 'ignore',
    detached: false,
  });

  splashProgress(55, 9);   // backend process started

  flaskProc.on('exit', (code, signal) => {
    // It is gone: before-quit must not try to stop this PID later (it may belong to another
    // program by then). Any exit while the app is not quitting is a crash, also one by a
    // signal (code null, e.g. killed for memory) and a clean code 0 nobody asked for.
    flaskProc = null;
    if (!app.isQuitting) {
      app.isQuitting = true;
      dropSplash();
      if (PACKAGED && !backendAnswered && code !== 3) { dialog.showErrorBox(...BUNDLED_PYTHON_BOX); app.quit(); return; }
      dialog.showErrorBox('EGM Downloader — Backend crashed', code === 3
        ? `Another program is using port ${PORT}, so the backend could not start.\n\nClose that program (or wait for an earlier EGM Downloader to finish closing) and start the app again.`
        : `The backend stopped unexpectedly (${signal ? 'signal ' + signal : 'code ' + code}).\n\nPlease restart the app.`);
      app.quit();
    }
  });

  flaskProc.on('error', (err) => {
    if (!app.isQuitting) {
      app.isQuitting = true;
      dropSplash();
      dialog.showErrorBox('EGM Downloader — Startup error',
        `Failed to start backend:\n${err.message}`);
      app.quit();
    }
  });
}

// ── Fix 4: Single waitForFlask, no double retry ───────────────────────────────
// Polls the backend every 250 ms for up to 3 minutes. The budget is a time, not a count: a refused
// connection takes about 2 s to fail on Windows (each probe is also cut off after 900 ms), so a
// count of attempts would not add up to 3 minutes there.
function waitForFlask(budgetMs = 180000, delay = 250) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + budgetMs;
    const try_ = () => {
      const retry = () => {
        if (Date.now() >= deadline) {
          reject(new Error('The backend did not start within 3 minutes.\n\nTry launching the app again.'));
          return;
        }
        setTimeout(try_, delay);
      };
      // Only this run's backend answers 200 here: it knows the per-run token. Another program on
      // the port, or a backend left over from an earlier run, must not be loaded into this window
      // (with the preload, its page would pass the sender check, which compares the origin only).
      const req = http.get(APP_URL + '/api/settings', { headers: { 'X-EGM-Token': EGM_TOKEN } }, res => {
        res.resume();
        if (res.statusCode === 200) resolve(); else retry();
      });
      req.on('error', retry);
      req.setTimeout(900, () => { req.destroy(); });
    };
    try_();
  });
}

// ── Create tray ───────────────────────────────────────────────────────────────

// ── Shell i18n: tray strings ──────────────────────────────────────────────────
// The main process has no access to the renderer's i18n, so the tray menu
// reads the locale file directly. Falls back to English on any failure;
// refreshed live via the set-language channel.
let _shellLang = null;
const SHELL_FALLBACK = {
  trayOpen: 'Open EGM Downloader', trayQuit: 'Quit',
};
function shellStrings() {
  const KEYS = { trayOpen: 'tray.open', trayQuit: 'tray.quit' };
  try {
    const lang = _shellLang || (loadSettings().language || 'en');   // this used to call a helper that does not exist, so the tray was always English
    if (!/^[a-z]{2}$/.test(lang)) return { ...SHELL_FALLBACK };
    const raw = JSON.parse(fs.readFileSync(
      path.join(APP_DIR, 'languages', `${lang}.json`), 'utf8')).strings || {};
    const out = {};
    for (const k of Object.keys(KEYS)) out[k] = raw[KEYS[k]] || SHELL_FALLBACK[k];
    return out;
  } catch { return { ...SHELL_FALLBACK }; }
}
function refreshShellText() {
  try {
    if (tray) tray.setContextMenu(buildTrayMenu());
  } catch {}
}

function buildTrayMenu() {
  const t = shellStrings();
  return Menu.buildFromTemplate([
    {
      label: t.trayOpen,
      click: () => {
        if (!mainWindow) return;
        restoreWindowState();
        mainWindow.show();
        mainWindow.focus();
      },
    },
    { type: 'separator' },
    {
      label: t.trayQuit,
      click: () => { app.isQuitting = true; app.quit(); },
    },
  ]);
}

function createTray() {
  const iconPath = path.join(APP_DIR, 'static', 'icon-64.png');
  tray = new Tray(safeIcon(iconPath, 16));
  tray.setToolTip('EGM Downloader');
  tray.setContextMenu(buildTrayMenu());

  // Left-click tray icon → restore and show
  tray.on('click', () => {
    if (!mainWindow) return;
    restoreWindowState();
    mainWindow.show();
    mainWindow.focus();
  });
}

// ── Create window ─────────────────────────────────────────────────────────────
async function createWindow() {
  const winIconPath = path.join(APP_DIR, 'static', 'icon.ico');
  const winIconOpts = fs.existsSync(winIconPath) ? { icon: winIconPath } : {};

  // Load saved window state — use saved dimensions or defaults
  const { bounds, maximized } = loadWindowState();
  const initBounds = (bounds && isOnScreen(bounds))
    ? { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height }
    : DEFAULT_BOUNDS;

  mainWindow = new BrowserWindow({
    ...initBounds,
    minWidth:  700,
    minHeight: 560,
    title: 'EGM Downloader',
    ...winIconOpts,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      sandbox:          true,
      spellcheck:       false,
    },
    backgroundColor: '#0b1120',
    show: false,
  });

  // Restore maximized state after window is created
  if (maximized) mainWindow.maximize();

  mainWindow.setMenuBarVisibility(false);

  // Show window only when Flask page is ready — close splash, show main window
  mainWindow.once('ready-to-show', () => {
    closeSplash();
    mainWindow.show();
  });

  // Save window state on resize/move — debounced 500ms to avoid hammering disk
  const debouncedSave = debounce(saveWindowState, 500);
  mainWindow.on('resize', debouncedSave);
  mainWindow.on('move',   debouncedSave);

  // X button → hide to tray (downloads continue in background)
  // Tray Quit → app.isQuitting = true → this interceptor does not fire
  mainWindow.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault();
      saveWindowState(); // save immediately before hiding
      // Close secondary windows — they shouldn't outlive main
      if (themesWindow && !themesWindow.isDestroyed()) themesWindow.close();
      if (historyWindow && !historyWindow.isDestroyed()) historyWindow.close();
      mainWindow.hide();
    }
  });

  // Wait for Flask to be ready, then load the page
  try {
    await waitForFlask();
    backendAnswered = true;
    splashProgress(85, 6);   // backend answers
    // Clear Chromium's HTTP cache before loading — guarantees fresh templates
    // after an app update. Without this, stale index.html may persist across
    // upgrades. Cheap on every launch (templates re-fetch from local Flask).
    try { await mainWindow.webContents.session.clearCache(); } catch {}
    mainWindow.loadURL(APP_URL);
    hardenWindow(mainWindow);
  } catch (e) {
    dropSplash();
    dialog.showErrorBox('EGM Downloader — Startup error', e.message);
    app.quit();
  }
}

// ── IPC: launch installer (for auto-update) ──────────────────────────────────
const EXPECTED_INSTALLER = path.join(os.tmpdir(), 'egm-update', 'egm-setup.exe');
ipcMain.handle('launch-installer', async (event, installerPath) => {
  try {
    if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
    if (!installerPath || typeof installerPath !== 'string') return { error: 'Invalid installer path' };
    // Exact path match — only the path our own download-update endpoint writes is
    // allowed. Resolve BOTH sides so normalization can't cause a false mismatch.
    if (path.resolve(installerPath) !== path.resolve(EXPECTED_INSTALLER)) return { error: 'Unexpected installer path' };
    if (!fs.existsSync(installerPath)) return { error: 'Installer not found: ' + installerPath };
    // The installer closes the app: ask about Subscriptions downloads before it starts, not after.
    if (!subsDownloadsAllowQuit()) return { cancelled: true };
    // Spawn installer detached so it outlives Electron
    // spawn is already imported at the top of this file
    const child = spawn(installerPath, [], {
      detached:    true,
      stdio:       'ignore',
      windowsHide: false,
    });
    child.unref();
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: quit app ─────────────────────────────────────────────────────────────
ipcMain.handle('quit-app', (event, opts) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
  // opts.whenIdle: Subscriptions "Quit when done". Refuse while any OTHER
  // window (the main window) still reports active downloads, so this can
  // never cut off a download that is running elsewhere. opts.probe reports
  // that state without quitting.
  if (opts && opts.whenIdle) {
    const self = BrowserWindow.fromWebContents(event.sender);
    const busy = [..._activityBySender.keys()].some(w => w !== self);
    if (busy || opts.probe) return { busy };
  }
  // opts.relaunch: reopen the app after it exits (Advanced -> Reinstall Electron
  // -> "Restart now"). Relaunch the TOP-LEVEL launcher (which runs launch.py and
  // processes the .electron-update marker), NOT Electron directly — a plain
  // relaunch would bypass launch.py and skip the reinstall. Falls back to a plain
  // relaunch if the launcher isn't found: the app still reopens and the marker
  // persists, so the reinstall applies on the next manual launch.
  if (opts && opts.relaunch) {
    // A queued relaunch cannot be taken back: ask about Subscriptions downloads before queueing it,
    // not only in before-quit, where "Keep open" would leave it waiting to fire at the next quit.
    if (!subsDownloadsAllowQuit()) return { cancelled: true };
    try {
      const launcher = path.join(INSTALL_DIR, 'EGM Downloader.exe');
      if (fs.existsSync(launcher)) app.relaunch({ execPath: launcher });
      else app.relaunch();
    } catch { try { app.relaunch(); } catch {} }
  }
  app.isQuitting = true;
  app.quit();
  return { success: true };
});

// ── IPC: folder picker ────────────────────────────────────────────────────────
ipcMain.handle('pick-folder', async (event, defaultPath) => {
  if (!isTrustedSender(event)) return null;
  const parentWin = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  const result = await dialog.showOpenDialog(parentWin, {
    title:       'Select download folder',
    defaultPath: defaultPath,
    properties:  ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
});

// ── IPC: open folder in Explorer ──────────────────────────────────────────────
ipcMain.handle('open-folder', async (event, folderPath) => {
  try {
    if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
    if (!folderPath || typeof folderPath !== 'string') return { error: 'Invalid path' };
    if (folderPath.startsWith('http') || folderPath.startsWith('javascript')) return { error: 'Invalid path' };
    // Must be an existing directory — prevents shell.openPath from launching arbitrary files
    const resolved = path.resolve(folderPath);
    let stat;
    try { stat = fs.statSync(resolved); } catch { return { error: 'Path not found' }; }
    if (!stat.isDirectory()) return { error: 'Not a directory' };
    await shell.openPath(resolved);
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: save file dialog (settings export) ───────────────────────────────────
ipcMain.handle('save-file', async (event, defaultName, content) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
  // Extension-aware: .txt exports (the Diagnostics window) get a text filter/title;
  // everything else keeps the original JSON behavior (settings/theme export).
  const isTxt = /\.txt$/i.test(defaultName || '');
  const parent = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  const result = await dialog.showSaveDialog(parent, {
    title:       isTxt ? 'Export Log' : 'Export Settings',
    defaultPath: defaultName || 'egm-settings.json',
    filters:     isTxt ? [{ name: 'Text', extensions: ['txt'] }]
                       : [{ name: 'JSON', extensions: ['json'] }],
  });
  if (result.canceled || !result.filePath) return { canceled: true };
  try {
    require('fs').writeFileSync(result.filePath, content, 'utf8');
    return { ok: true, path: result.filePath };
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: open file dialog (settings import) ───────────────────────────────────
// Read a user-picked text file, rejecting oversized selections client-side so we
// never pull a huge file into memory (Flask also caps cookies at 1 MB on submit).
const MAX_IMPORT_BYTES = 2 * 1024 * 1024; // 2 MB
function readFileCapped(filePath) {
  const { size } = fs.statSync(filePath);
  if (size > MAX_IMPORT_BYTES) return { error: 'File too large (max 2 MB)' };
  return { ok: true, content: fs.readFileSync(filePath, 'utf8') };
}

ipcMain.handle('open-file', async (event, options) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
  const isCookies = options && options.type === 'cookies';
  const dialogOpts = {
    title:      isCookies ? 'Select cookies.txt' : 'Import Settings',
    properties: ['openFile'],
  };
  if (isCookies)  dialogOpts.filters = [{ name: 'Text files', extensions: ['txt'] }, { name: 'All files', extensions: ['*'] }];
  else            dialogOpts.filters = [{ name: 'JSON', extensions: ['json'] }];
  const result = await dialog.showOpenDialog(mainWindow, dialogOpts);
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  try {
    return readFileCapped(result.filePaths[0]);
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: open cookies file dialog ────────────────────────────────────────────
ipcMain.handle('open-cookies-file', async (event) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
  const result = await dialog.showOpenDialog(mainWindow, {
    title:      'Select cookies.txt',
    filters:    [{ name: 'Text files', extensions: ['txt'] }, { name: 'All files', extensions: ['*'] }],
    properties: ['openFile'],
  });
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  try {
    return readFileCapped(result.filePaths[0]);
  } catch (e) {
    return { error: e.message };
  }
});

// Window-bounds files live in userData (which is redirected to the portable folder
// in portable mode). Storing them next to the exe leaked install-location state and
// wrote them deep inside node_modules/electron/dist, where they're wiped on every
// Electron reinstall. userData keeps them with the rest of per-user state.
const WINDOW_STATE_DIR = app.getPath('userData');

// ── IPC: open full history window ─────────────────────────────────────────────
let historyWindow = null;
const HISTORY_BOUNDS_FILE = path.join(WINDOW_STATE_DIR, 'egm_history_window.json');

function loadHistoryBounds() {
  try {
    const saved = JSON.parse(fs.readFileSync(HISTORY_BOUNDS_FILE, 'utf8'));
    // Off-screen safety: ensure bounds intersect a display
    const displays = require('electron').screen.getAllDisplays();
    const onScreen = displays.some(d => {
      const b = d.bounds;
      return saved.x < b.x + b.width && saved.x + saved.width > b.x &&
             saved.y < b.y + b.height && saved.y + saved.height > b.y;
    });
    return onScreen ? saved : { width: saved.width || 780, height: saved.height || 560 };
  } catch { return { width: 780, height: 560 }; }
}

function saveHistoryBounds(win) {
  try {
    const b = win.getBounds();
    fs.writeFileSync(HISTORY_BOUNDS_FILE, JSON.stringify(b), 'utf8');
  } catch {}
}

ipcMain.handle('open-history-window', async (event, from) => {
  if (!isTrustedSender(event)) return;
  if (historyWindow && !historyWindow.isDestroyed()) {
    if (from === 'subs') historyWindow.loadURL(`${APP_URL}/history-page?from=subs`);
    historyWindow.focus();
    return;
  }
  const bounds = loadHistoryBounds();
  historyWindow = new BrowserWindow({
    ...bounds, minWidth: 600, minHeight: 420,
    title: 'Download History',
    icon: path.join(APP_DIR, 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, spellcheck: false, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  historyWindow.loadURL(`${APP_URL}/history-page${from === 'subs' ? '?from=subs' : ''}`);
  hardenWindow(historyWindow);
  let saveTimer = null;
  const debouncedSave = () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveHistoryBounds(historyWindow), 500);
  };
  historyWindow.on('resize', debouncedSave);
  historyWindow.on('move',   debouncedSave);
  historyWindow.on('closed', () => { historyWindow = null; });
});


// ── IPC: open themes window ───────────────────────────────────────────────────
let themesWindow = null;
const THEMES_BOUNDS_FILE = path.join(WINDOW_STATE_DIR, 'egm_themes_window.json');

function loadThemesBounds() {
  try {
    const saved = JSON.parse(fs.readFileSync(THEMES_BOUNDS_FILE, 'utf8'));
    const displays = require('electron').screen.getAllDisplays();
    const onScreen = displays.some(d => {
      const b = d.bounds;
      return saved.x < b.x + b.width && saved.x + saved.width > b.x &&
             saved.y < b.y + b.height && saved.y + saved.height > b.y;
    });
    return onScreen ? saved : { width: saved.width || 720, height: saved.height || 560 };
  } catch { return { width: 720, height: 560 }; }
}

function saveThemesBounds(win) {
  try { fs.writeFileSync(THEMES_BOUNDS_FILE, JSON.stringify(win.getBounds()), 'utf8'); } catch {}
}

ipcMain.handle('open-themes-window', async (event) => {
  if (!isTrustedSender(event)) return;
  if (themesWindow && !themesWindow.isDestroyed()) { themesWindow.focus(); return; }
  const bounds = loadThemesBounds();
  themesWindow = new BrowserWindow({
    ...bounds, minWidth: 480, minHeight: 400,
    title: 'All Themes — EGM Downloader',
    icon: path.join(APP_DIR, 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, spellcheck: false, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  themesWindow.loadURL(`${APP_URL}/themes-page`);
  hardenWindow(themesWindow);
  let saveTimer = null;
  const debouncedSave = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveThemesBounds(themesWindow), 500); };
  themesWindow.on('resize', debouncedSave);
  themesWindow.on('move',   debouncedSave);
  themesWindow.on('closed', () => { themesWindow = null; });
});


// ── IPC: open log-console window ──────────────────────────────────────────────
// Opened via IPC like every other child window — a plain window.open() from the
// renderer is denied by hardenWindow's setWindowOpenHandler (it only routes
// https: links to the external browser), so the IPC path is the only one that
// works in the packaged app.
let consoleWindow = null;
const CONSOLE_BOUNDS_FILE = path.join(WINDOW_STATE_DIR, 'egm_console_window.json');

function loadConsoleBounds() {
  try {
    const saved = JSON.parse(fs.readFileSync(CONSOLE_BOUNDS_FILE, 'utf8'));
    const displays = require('electron').screen.getAllDisplays();
    const onScreen = displays.some(d => {
      const b = d.bounds;
      return saved.x < b.x + b.width && saved.x + saved.width > b.x &&
             saved.y < b.y + b.height && saved.y + saved.height > b.y;
    });
    return onScreen ? saved : { width: saved.width || 760, height: saved.height || 520 };
  } catch { return { width: 760, height: 520 }; }
}

function saveConsoleBounds(win) {
  try { fs.writeFileSync(CONSOLE_BOUNDS_FILE, JSON.stringify(win.getBounds()), 'utf8'); } catch {}
}

ipcMain.handle('open-console-window', async (event) => {
  if (!isTrustedSender(event)) return;
  if (consoleWindow && !consoleWindow.isDestroyed()) { consoleWindow.focus(); return; }
  const bounds = loadConsoleBounds();
  consoleWindow = new BrowserWindow({
    ...bounds, minWidth: 480, minHeight: 320,
    title: 'Diagnostics — EGM Downloader',
    icon: path.join(APP_DIR, 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, spellcheck: false, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  consoleWindow.loadURL(`${APP_URL}/console-page`);
  hardenWindow(consoleWindow);
  let saveTimer = null;
  const debouncedSave = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveConsoleBounds(consoleWindow), 500); };
  consoleWindow.on('resize', debouncedSave);
  consoleWindow.on('move',   debouncedSave);
  consoleWindow.on('closed', () => { consoleWindow = null; });
});


// ── IPC: open subscriptions window ────────────────────────────────────────────
let subsWindow = null;
let subsActiveDownloads = false;
let subsForceClose = false;
const SUBS_BOUNDS_FILE = path.join(WINDOW_STATE_DIR, 'egm_subs_window.json');

function loadSubsBounds() {
  try {
    const saved = JSON.parse(fs.readFileSync(SUBS_BOUNDS_FILE, 'utf8'));
    const displays = require('electron').screen.getAllDisplays();
    const onScreen = displays.some(d => {
      const b = d.bounds;
      return saved.x < b.x + b.width && saved.x + saved.width > b.x &&
             saved.y < b.y + b.height && saved.y + saved.height > b.y;
    });
    return onScreen ? saved : { width: 1100, height: 700 };
  } catch { return { width: 1100, height: 700 }; }
}

function saveSubsBounds(win) {
  try { fs.writeFileSync(SUBS_BOUNDS_FILE, JSON.stringify(win.getBounds()), 'utf8'); } catch {}
}

// Asked when the Subscriptions window is closed, and before a quit shuts the backend down: a quit
// the user then refuses ("Keep open") must find the backend and its downloads still running.
function confirmCloseWithDownloads(parent) {
  return dialog.showMessageBoxSync(parent, {
    type: 'warning',
    buttons: ['Close anyway', 'Keep open'],
    defaultId: 1,
    cancelId: 1,
    noLink: true,
    title: 'Downloads in progress',
    message: 'Downloads are still in progress.',
    detail: 'If you close this window, downloads will continue in the background as long as the app stays open.\n\nIf you close the entire app, active downloads will be cancelled.\n\nClose anyway?'
  }) === 0;
}

// Asked once per quit, while the backend still runs: true when the quit may go on. Nothing is asked
// when the backend is already gone (a crash quits the app, and "Keep open" would only leave a window
// on nothing).
function subsDownloadsAllowQuit() {
  if (!flaskProc || !subsWindow || subsWindow.isDestroyed() || !subsActiveDownloads || subsForceClose) return true;
  // A modal question on a minimized window can stay out of sight while it holds up the whole app.
  if (subsWindow.isMinimized()) subsWindow.restore();
  subsWindow.show();
  subsWindow.focus();
  if (!confirmCloseWithDownloads(subsWindow)) return false;
  subsForceClose = true;       // the window's own close handler must not ask a second time
  return true;
}

ipcMain.handle('open-subscriptions-window', async (event) => {
  if (!isTrustedSender(event)) return;
  if (subsWindow && !subsWindow.isDestroyed()) { subsWindow.focus(); return; }
  const bounds = loadSubsBounds();
  subsWindow = new BrowserWindow({
    ...bounds, minWidth: 600, minHeight: 400,
    title: 'Subscriptions — EGM Downloader',
    icon: path.join(APP_DIR, 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, spellcheck: false, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  subsWindow.loadURL(`${APP_URL}/subscriptions-page`);
  hardenWindow(subsWindow);
  // Sub-app mode: hide main window when subscriptions opens
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.hide();
  subsActiveDownloads = false; subsForceClose = false;
  let saveTimer = null;
  const debouncedSave = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveSubsBounds(subsWindow), 500); };
  subsWindow.on('resize', debouncedSave);
  subsWindow.on('move', debouncedSave);
  subsWindow.on('close', (e) => {
    // Item 1: if downloads are active, intercept the close (X button or the
    // renderer's "Back to app" → close-subscriptions) and confirm natively.
    if (subsForceClose || !subsActiveDownloads) return;
    e.preventDefault();
    if (confirmCloseWithDownloads(subsWindow)) { subsForceClose = true; subsWindow.close(); }
  });
  // Teardown order matters: the activity slot is dropped and the reference
  // cleared BEFORE re-aggregating, so the per-window shell loop never
  // iterates the window being torn down. The re-aggregate is wrapped
  // because a throw there would skip the window restore below -- and the
  // main window is hidden in sub-app mode, so that would leave no visible
  // window at all.
  subsWindow.on('closed', () => {
    _activityBySender.delete(subsWindow);
    subsWindow = null;
    try { _applyAggregateActivity(); } catch {}
    subsActiveDownloads = false; subsForceClose = false;
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
});

ipcMain.handle('close-subscriptions', async (event) => {
  if (!isTrustedSender(event)) return;
  if (subsWindow && !subsWindow.isDestroyed()) subsWindow.close();
});

// Item 1: renderer keeps main.js informed whether subscriptions has active
// downloads, so subsWindow.on('close') above can decide whether to confirm.

// ── Activity reporting: taskbar progress, badge, sleep blocker ───────────────
// Each window (main, subscriptions) sends { progress: 0..1 | -1, active: n }
// on every poll tick where its own state changed. Main and subscriptions can
// both have genuinely concurrent activity -- subscriptions hides the main
// window visually ("sub-app mode") but doesn't pause it, so a download
// started in the main window keeps running (and keeps being reportable)
// while subscriptions is the visible window. Tracked per-sender and
// aggregated into what the shell actually shows, so neither window's report
// can silently clobber the other's.
let _psbId = null;
const _activityBySender = new Map();   // BrowserWindow -> {active, progress}

function _badgeIconForCount(n) {
  if (n <= 0) return null;
  const name = n > 9 ? '9plus' : String(n);
  return safeIcon(path.join(APP_DIR, 'static', `badge-${name}.png`), 32);
}

function _applyAggregateActivity() {
  let active = 0, weighted = 0, counted = 0;
  for (const st of _activityBySender.values()) {
    active += st.active;
    if (st.progress >= 0) { weighted += st.progress; counted++; }
  }
  const prog = counted > 0 ? weighted / counted : -1;

  // Applied to every existing top-level window, not just mainWindow --
  // subsWindow has its own independent taskbar button (no skipTaskbar,
  // no parent), and main.js hides mainWindow while subscriptions is open
  // ("sub-app mode"). Targeting mainWindow alone meant the progress
  // bar/badge were written to a window with no taskbar presence at that
  // moment, while the window the user was actually looking at never
  // received them. A hidden/destroyed window's update is a harmless
  // no-op; whichever window currently has a taskbar button gets the
  // real one.
  const icon = _badgeIconForCount(active);
  for (const win of [mainWindow, subsWindow]) {
    if (!win || win.isDestroyed()) continue;
    win.setProgressBar(active > 0 ? prog : -1);
    if (icon) { try { win.setOverlayIcon(icon, `${active} active`); } catch {} }
    else { win.setOverlayIcon(null, ''); }
  }
  if (active > 0 && _psbId === null) {
    _psbId = powerSaveBlocker.start('prevent-app-suspension');
  } else if (active === 0 && _psbId !== null) {
    try { powerSaveBlocker.stop(_psbId); } catch {}
    _psbId = null;
  }
}

ipcMain.on('set-activity', (event, a) => {
  try {
    if (!isTrustedSender(event)) return;
    if (!a || typeof a !== 'object') return;
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win || win.isDestroyed()) return;
    const active = Number.isInteger(a.active) && a.active > 0 ? a.active : 0;
    const prog = (typeof a.progress === 'number' && a.progress >= 0 && a.progress <= 1) ? a.progress : -1;
    if (active === 0) _activityBySender.delete(win);
    else _activityBySender.set(win, { active, progress: prog });
    _applyAggregateActivity();
  } catch {}
});

ipcMain.on('subs-active-downloads', (event, active) => {
  if (!isTrustedSender(event)) return;
  subsActiveDownloads = !!active;
});

// Restore OS-level window focus after a native dialog. A sandboxed +
// contextIsolated renderer can't reliably re-focus its own BrowserWindow with
// window.focus(); the main process must call .focus() on the sender's window.
ipcMain.on('refocus-window', (event) => {
  if (!isTrustedSender(event)) return;
  const win = BrowserWindow.fromWebContents(event.sender);
  if (!win || win.isDestroyed()) return;
  // win.focus() restores the OS window but NOT the web page's INPUT focus, so
  // document.hasFocus() stays false and clipboard/keyboard stay dead after a
  // native dialog. webContents.focus() is what actually restores it — it's what
  // opening DevTools does under the hood. Retry once after the dialog finishes
  // tearing down, to win the focus race.
  const refocus = () => {
    if (win.isDestroyed()) return;
    try { win.focus(); } catch (e) {}
    try {
      const wc = win.webContents;
      if (wc && !wc.isDestroyed()) wc.focus();
    } catch (e) {}
  };
  refocus();
  setTimeout(refocus, 60);
});

// ── IPC: relay theme change from themes window to main window ─────────────────

// Theme key validation — alphanumeric only, prevents IPC injection while
// supporting any future theme without allowlist maintenance
const VALID_THEME_RE = /^[a-z0-9-]+$/;
ipcMain.on('set-language', (event, lang) => {
  if (!isTrustedSender(event)) return;
  if (typeof lang !== 'string' || !/^[a-z]{2}$/.test(lang)) return;
  _shellLang = lang;
  refreshShellText();
});

ipcMain.on('set-theme', (event, theme) => {
  if (!isTrustedSender(event)) return;
  if (!theme || typeof theme !== 'string' || !VALID_THEME_RE.test(theme)) return;
  // Item 3: broadcast to every open window except the sender, so all child
  // windows (main, history, themes, subscriptions) update live on theme change.
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed() || win.webContents.id === event.sender.id) continue;
    win.webContents.send('theme-changed', theme);
  }
});

// ── IPC: widen the main window while the in-page Theme Creator panel is open, so the
// panel never compresses the main UI; restore the exact prior bounds on close. Window
// *size* changes work on every platform incl. Wayland (only window *position* doesn't,
// and we're not positioning anything — just widening a too-narrow window).
let _creatorPanelPrevBounds = null;
ipcMain.on('creator-panel', (event, open) => {
  if (!isTrustedSender(event) || !mainWindow || mainWindow.isDestroyed()) return;
  if (mainWindow.isMaximized() || mainWindow.isFullScreen()) return;   // centered content already has room
  const b = mainWindow.getBounds();
  const TARGET = 1160;                                                  // 760 content + 340 panel + padding
  if (open) {
    if (_creatorPanelPrevBounds || b.width >= TARGET) return;           // already widened / already wide enough
    _creatorPanelPrevBounds = { ...b };
    const disp = require('electron').screen.getDisplayMatching(b).workArea;
    let x = b.x;
    if (x + TARGET > disp.x + disp.width) x = Math.max(disp.x, disp.x + disp.width - TARGET);
    mainWindow.setBounds({ x, y: b.y, width: TARGET, height: b.height });
  } else if (_creatorPanelPrevBounds) {
    mainWindow.setBounds(_creatorPanelPrevBounds);
    _creatorPanelPrevBounds = null;
  }
});

// ── IPC: forward URL from history window to main window's URL textarea ────────
// History window is a separate BrowserWindow with no opener relationship,
// so cross-window readd uses this IPC bridge.
ipcMain.on('send-url-to-main', (event, url) => {
  if (!isTrustedSender(event)) return;
  if (typeof url !== 'string' || !url.trim()) return;
  // Only forward http(s) URLs — this value lands in the main window's URL box.
  try {
    if (!['http:', 'https:'].includes(new URL(url).protocol)) return;
  } catch {
    return;
  }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('readd-url', url);
    mainWindow.focus();
  }
});

// ── IPC: create desktop shortcut ─────────────────────────────────────────────
ipcMain.handle('create-shortcut', async (event) => {
  try {
    if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
    const lnkTarget = path.join(INSTALL_DIR, 'EGM Downloader.exe');
    const workDir   = INSTALL_DIR;
    const iconPath  = path.join(APP_DIR, 'static', 'icon.ico');
    const tmpVbs    = path.join(os.tmpdir(), `egm_sc_${Date.now()}.vbs`);

    // Check if shortcut already exists on Desktop
    let desktopPath;
    try {
      const { execSync } = require('child_process');
      desktopPath = execSync(
        'powershell -command "[Environment]::GetFolderPath(\'Desktop\')"',
        { windowsHide: true, timeout: 5000 }
      ).toString().trim();
    } catch {
      desktopPath = path.join(os.homedir(), 'Desktop');
    }
    const lnkPath = path.join(desktopPath, 'EGM Downloader.lnk');
    if (fs.existsSync(lnkPath)) {
      return { exists: true };
    }

    const vbs = [
      'Set ws   = CreateObject("WScript.Shell")',
      'desktop  = ws.SpecialFolders("Desktop")',
      'Set lnk  = ws.CreateShortcut(desktop & "\\EGM Downloader.lnk")',
      'lnk.TargetPath       = "' + lnkTarget + '"',
      'lnk.WorkingDirectory = "' + workDir + '"',
      'lnk.IconLocation     = "' + iconPath + '"',
      'lnk.Description      = "EGM Downloader"',
      'lnk.Save',
    ].join('\r\n');

    fs.writeFileSync(tmpVbs, vbs, 'utf8');
    execFileSync('wscript.exe', ['/nologo', tmpVbs], { windowsHide: true, timeout: 15000 });
    try { fs.unlinkSync(tmpVbs); } catch {}
    // WScript cannot set AppUserModelID — stamp it so the taskbar names us correctly
    try {
      shell.writeShortcutLink(lnkPath, 'update', {
        target: lnkTarget, cwd: workDir, icon: iconPath, iconIndex: 0,
        appUserModelId: 'com.egerena.egm-downloader',
      });
    } catch {}
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

// ── Show-window poller — receives signals from launch.py via Flask ────────────
// launch.py POSTs /api/show-window if the app is already running.
// Flask sets a flag; we poll /api/show-window-check every 500ms and show
// the window when the flag fires. Replaces the second-instance spawn entirely.
function startShowWindowPoller() {
  setInterval(() => {
    if (!mainWindow) return;
    const req = http.get(`${APP_URL}/api/show-window-check`, { headers: { 'X-EGM-Token': EGM_TOKEN } }, (res) => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        try {
          if (JSON.parse(body).show) {
            if (subsWindow && !subsWindow.isDestroyed()) {
              if (subsWindow.isMinimized()) subsWindow.restore();
              subsWindow.show();
              subsWindow.focus();
            } else {
              restoreWindowState();
              if (!mainWindow.isVisible()) mainWindow.show();
              mainWindow.focus();
            }
          }
        } catch {}
      });
    });
    req.on('error', () => {}); // Flask not ready yet — ignore silently
    req.setTimeout(400, () => req.destroy());
  }, 500);
}

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  // Set display name AFTER ready so userData path is already locked to 'egm-downloader'
  app.setName('EGM Downloader');

  // Stamp our AppUserModelID onto the installer-created shortcuts ('update'
  // never creates, so portable installs are untouched). The taskbar context
  // menu resolves the app name through a Start Menu shortcut whose AUMID
  // matches the window's — without the stamp it falls back to the Electron
  // runtime's internal FileDescription and shows "Electron".
  try {
    const lnkOpts = {
      target: path.join(INSTALL_DIR, 'EGM Downloader.exe'),
      cwd: INSTALL_DIR,
      icon: path.join(APP_DIR, 'static', 'icon.ico'),
      iconIndex: 0,
      appUserModelId: 'com.egerena.egm-downloader',
    };
    // Packaged: 'update' would also point the shortcuts at this exe. Only stamp the ones that already
    // open it, so a copy run from another folder never takes over an installed app's shortcuts.
    const opensThisExe = (lnk) => {
      try { return path.resolve(shell.readShortcutLink(lnk).target).toLowerCase() === path.resolve(lnkOpts.target).toLowerCase(); }
      catch { return false; }
    };
    const smLnk = path.join(app.getPath('appData'),
      'Microsoft', 'Windows', 'Start Menu', 'Programs', 'EGM Downloader', 'EGM Downloader.lnk');
    if (!PACKAGED || opensThisExe(smLnk)) shell.writeShortcutLink(smLnk, 'update', lnkOpts);
    const deskLnk = path.join(app.getPath('desktop'), 'EGM Downloader.lnk');
    if (!PACKAGED || opensThisExe(deskLnk)) shell.writeShortcutLink(deskLnk, 'update', lnkOpts);
  } catch {}
  // No spellchecker language, so Chromium never downloads a dictionary. Turning spellcheck off on the windows
  // does not stop that download (Electron 45.2.3 on Linux asked Google's CDN for one at the first start with
  // it off); an empty language list does. Nothing is lost: every BrowserWindow turns spellcheck off in
  // its webPreferences, so no window checks spelling anyway; the two inputs in index.html that also set
  // spellcheck="false" are extra. On macOS the call changes nothing: it uses the system spellchecker.
  try { session.defaultSession.setSpellCheckerLanguages([]); } catch (e) { console.warn('[EGM] Could not clear the spellchecker languages:', e && e.message); }
  // No Referer to anyone but the app itself. The Referrer-Policy header the backend sends covers <img>,
  // but Chromium gives CSS background images the default policy, not the page's, so the four
  // Subscriptions thumbnails drawn that way would still send http://127.0.0.1:<port>/ to the image server.
  // The app is the origin APP_URL exactly (a prefix would also match http://127.0.0.1:8899@host/ and
  // another port); a URL that cannot be parsed counts as foreign. Every request is answered once.
  session.defaultSession.webRequest.onBeforeSendHeaders((details, callback) => {
    try {
      let own = false;
      try { own = new URL(details.url).origin === APP_URL; } catch {}
      if (!own) delete details.requestHeaders['Referer'];
    } finally {
      callback({ requestHeaders: details.requestHeaders });
    }
  });
  // A finished download's picture (see History thumbnails above): the page's /api/status answers name it.
  session.defaultSession.webRequest.onCompleted(noticeThumbnail);
  // Content-Security-Policy: applied to all responses from Flask
  // 'unsafe-inline' for scripts/styles required because templates use inline JS/CSS.
  // External scripts, frames, objects, plugins, non-self connections all blocked.
  session.defaultSession.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [
          "default-src 'self'; " +
          "script-src 'self' 'unsafe-inline'; " +
          "style-src 'self' 'unsafe-inline'; " +
          "img-src 'self' data: blob: https:; " +
          "font-src 'self' data:; " +
          "connect-src 'self'; " +
          "frame-src 'none'; " +
          "object-src 'none'; " +
          "base-uri 'self'; " +
          "form-action 'self'"
        ]
      }
    });
  });

  createTray();
  createSplash();       // show splash — visible during Flask/ffmpeg startup
  startFlask();         // spawn backend (non-blocking — createWindow waits for it)
  await createWindow(); // window polls until Flask responds, then loads
  startShowWindowPoller(); // start after window is ready — listens for show signals
});

// Window is hidden to tray when X is pressed — window-all-closed should NOT
// trigger app quit. Only tray Quit sets app.isQuitting and calls app.quit().
app.on('window-all-closed', () => {
  if (app.isQuitting) app.quit();
});

// Single cleanup point for every quit path (X button, tray Quit, crash)
app.on('before-quit', (event) => {
  // Ask first, while the backend still runs: "Keep open" has to leave the app and its downloads as
  // they were. (Asking after the shutdown request left a window on a dead backend.)
  if (!subsDownloadsAllowQuit()) {
    event.preventDefault();
    app.isQuitting = false;    // the tray Quit and the quit IPC set it before calling app.quit()
    return;
  }
  app.isQuitting = true;
  // OS-level power save blockers are released on process death regardless,
  // but stop it explicitly here too -- same "single cleanup point" spirit
  // as the tray teardown right below, not left to rely on implicit cleanup.
  if (_psbId !== null) { try { powerSaveBlocker.stop(_psbId); } catch {} _psbId = null; }
  if (tray) { tray.destroy(); tray = null; }
  if (!flaskProc) return;

  const pid = flaskProc.pid;
  flaskProc = null;

  // Step 1: ask Flask to exit cleanly
  try {
    const req = http.request({ host: HOST, port: PORT, path: '/api/shutdown', method: 'POST', headers: { 'X-EGM-Token': EGM_TOKEN } });
    req.on('error', () => {});
    req.end();
  } catch {}

  // Step 2: after a short grace period, kill the process tree forcefully
  // taskkill /F /T kills the parent and all child processes (yt-dlp, ffmpeg, etc.)
  setTimeout(() => {
    if (pid) {
      try { execSync(`taskkill /PID ${pid} /F /T`, { windowsHide: true, stdio: 'ignore' }); } catch {}
    }
  }, 400);
});
