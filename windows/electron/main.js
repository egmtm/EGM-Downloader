const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage, screen, session } = require('electron');
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
const _portableMarker = path.join(__dirname, '..', '.portable');
if (fs.existsSync(_portableMarker)) {
  // Anchor to the install folder (parent of electron/), NOT process.cwd().
  // cwd depends on how the process was launched and is not guaranteed to be the
  // portable root; using __dirname makes this deterministic and keeps the path
  // in sync with launch.py's portable hide-list (which hides <root>/electron-data).
  app.setPath('userData', path.join(__dirname, '..', 'electron-data'));
}

// ── Settings file (same location as app.py BASE_DIR) ─────────────────────────
const SETTINGS_FILE = path.join(__dirname, '..', 'egm_settings.json');

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
      const u = new URL(url);
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
  const tmp = `${file}.tmp`;
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
let tray        = null;

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
function findPython() {
  const candidates = [
    path.join(process.resourcesPath, 'python', 'python.exe'),
    path.join(__dirname, '..', 'python', 'python.exe'),
    'python',
    'python3',
  ];
  for (const c of candidates) {
    try {
      // execFileSync passes args as a real argv array — no shell string to quote/escape.
      execFileSync(c, ['--version'], { stdio: 'ignore', windowsHide: true });
      return c;
    } catch {}
  }
  return null;
}

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
    },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  splashWindow.center();
  splashWindow.show();
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    setTimeout(() => {
      if (splashWindow) {
        splashWindow.close();
        splashWindow = null;
      }
    }, 300);
  }
}

// ── Start Flask ───────────────────────────────────────────────────────────────
async function startFlask() {
  const python = findPython();
  const appPy  = path.join(__dirname, '..', 'app.py');

  if (!python) {
    closeSplash();
    dialog.showErrorBox('Python not found',
      'Python 3.10+ is required.\n\nDownload from python.org and check "Add Python to PATH" during install.');
    app.quit();
    return;
  }
  flaskProc = spawn(python, [appPy], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, PORT: String(PORT), HOST, EGM_ELECTRON: '1', EGM_API_TOKEN: EGM_TOKEN },
    windowsHide: true,
    stdio: 'ignore',
    detached: false,
  });

  flaskProc.on('exit', (code) => {
    if (code !== 0 && code !== null && !app.isQuitting) {
      app.isQuitting = true;
      dialog.showErrorBox('EGM Downloader — Backend crashed',
        `The backend stopped unexpectedly (code ${code}).\n\nPlease restart the app.`);
      app.quit();
    }
  });

  flaskProc.on('error', (err) => {
    if (!app.isQuitting) {
      app.isQuitting = true;
      closeSplash();
      dialog.showErrorBox('EGM Downloader — Startup error',
        `Failed to start backend:\n${err.message}`);
      app.quit();
    }
  });
}

// ── Fix 4: Single waitForFlask, no double retry ───────────────────────────────
function waitForFlask(retries = 180, delay = 1000) {
  return new Promise((resolve, reject) => {
    let attemptCount = 0;
    const try_ = (n) => {
      attemptCount++;
      // Exponential curve: visible movement early, slows as it approaches 90%
      const req = http.get(APP_URL, res => { res.resume(); resolve(); });
      req.on('error', () => {
        if (n <= 0) {
          reject(new Error('The backend did not start within 3 minutes.\n\nTry launching the app again.'));
          return;
        }
        setTimeout(() => try_(n - 1), delay);
      });
      req.setTimeout(900, () => { req.destroy(); });
    };
    try_(retries);
  });
}

// ── Create tray ───────────────────────────────────────────────────────────────
function createTray() {
  const iconPath = path.join(__dirname, '..', 'static', 'icon-64.png');
  tray = new Tray(safeIcon(iconPath, 16));
  tray.setToolTip('EGM Downloader');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Open EGM Downloader',
      click: () => {
        if (!mainWindow) return;
        restoreWindowState();
        mainWindow.show();
        mainWindow.focus();
      },
    },
    { type: 'separator' },
    {
      label: 'Quit',
      click: () => { app.isQuitting = true; app.quit(); },
    },
  ]);

  tray.setContextMenu(contextMenu);

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
  const winIconPath = path.join(__dirname, '..', 'static', 'icon.ico');
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
      mainWindow.hide();
    }
  });

  // Wait for Flask to be ready, then load the page
  try {
    await waitForFlask();
    // Clear Chromium's HTTP cache before loading — guarantees fresh templates
    // after an app update. Without this, stale index.html may persist across
    // upgrades. Cheap on every launch (templates re-fetch from local Flask).
    try { await mainWindow.webContents.session.clearCache(); } catch {}
    mainWindow.loadURL(APP_URL);
    hardenWindow(mainWindow);
  } catch (e) {
    closeSplash();
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
ipcMain.handle('quit-app', (event) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
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
  const result = await dialog.showSaveDialog(mainWindow, {
    title:       'Export Settings',
    defaultPath: defaultName || 'egm-settings.json',
    filters:     [{ name: 'JSON', extensions: ['json'] }],
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
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
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
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
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

// ── IPC: Theme Creator window (v1.2 CANVAS) ───────────────────────────────────
// Standalone top-level window (NOT parent:) positioned right of main, clamped to
// main's display — mirrors themesWindow/subsWindow. The dirty-state + close guard
// mirror the subsWindow pattern (main owns the flag; the renderer shows the in-app
// modal). Live preview fans a var map to the main window, re-validated there.
let creatorWindow           = null;
let creatorDirty          = false;
let creatorForceClose     = false;
let creatorSavedMainBounds = null;
let creatorMainWasMaximized = false;

ipcMain.handle('open-theme-creator', async (event, opts) => {
  if (!isTrustedSender(event)) return;
  if (creatorWindow && !creatorWindow.isDestroyed()) { creatorWindow.focus(); return; }
  const fromThemes = !!(opts && opts.fromThemes);

  const W = 360;
  const liveMain = mainWindow && !mainWindow.isDestroyed();
  const wasMaximized = !!(liveMain && mainWindow.isMaximized());
  const mb = liveMain ? mainWindow.getBounds() : { x: 80, y: 80, width: 920, height: 780 };
  const disp = screen.getDisplayMatching(mb).workArea;
  // Native Wayland's compositor owns window placement — we can't force position there.
  // But a Wayland *session* (XDG_SESSION_TYPE=wayland) still runs us under XWayland,
  // where placement DOES work — so don't disable on session type alone (that is why an
  // x11 flag appeared to have "no effect": this gate skipped placement before the flag
  // could matter). An explicit x11 ozone hint/switch forces the X11 path and re-enables
  // positioning: ELECTRON_OZONE_PLATFORM_HINT=x11 or --ozone-platform=x11.
  const _ozone = ((process.env.ELECTRON_OZONE_PLATFORM_HINT || '') + ' ' +
                  (app.commandLine.getSwitchValue('ozone-platform') || '')).toLowerCase();
  const _forcedX11 = _ozone.includes('x11');
  const isWayland = process.platform === 'linux' &&
                    process.env.XDG_SESSION_TYPE === 'wayland' && !_forcedX11;

  let x, y, height;
  if (!isWayland) {
    // Remember how to put main back when the Creator closes.
    creatorSavedMainBounds  = liveMain ? { ...mainWindow.getNormalBounds() } : { ...mb };
    creatorMainWasMaximized = wasMaximized;
    if (wasMaximized && liveMain) {
      mainWindow.unmaximize();
      mainWindow.setBounds({ x: disp.x, y: disp.y, width: Math.max(360, disp.width - W), height: disp.height });
      x = disp.x + disp.width - W;
      y = disp.y;
      height = disp.height;
    } else {
      const newMainX = Math.max(disp.x, mb.x - W);
      if (liveMain) mainWindow.setBounds({ x: newMainX, y: mb.y, width: mb.width, height: mb.height });
      height = Math.max(460, Math.min(mb.height, disp.height));
      x = newMainX + mb.width;
      if (x + W > disp.x + disp.width) x = Math.max(disp.x, mb.x - W);
      x = Math.max(disp.x, Math.min(x, disp.x + disp.width - W));
      y = Math.max(disp.y, Math.min(mb.y, disp.y + disp.height - height));
    }
  } else {
    // Wayland: let compositor place the window; just set a sensible height.
    height = Math.max(460, Math.min(mb.height, disp.height));
  }

  // Windows honors the constructor x/y. macOS and X11 Linux WMs frequently ignore it
  // (and an immediate setPosition) and center the window instead, so on those platforms
  // create it hidden, place it once it's realized, show it, then re-assert after it's
  // mapped — some Linux WMs only honor a move request at that point.
  const deferPlacement = !isWayland && process.platform !== 'win32';
  creatorWindow = new BrowserWindow({
    ...(isWayland ? {} : { x, y }),
    width: W, height,
    show: isWayland || !deferPlacement,
    minWidth: 340, minHeight: 460,
    title: 'Theme Creator — EGM Downloader',
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  if (deferPlacement) {
    // No await/timer here: the main-window resize above stays synchronous, and these
    // run on window events after the handler returns, so window state can't be raced
    // (that race is what crashed the earlier setTimeout attempt). Local ref + the
    // isDestroyed guard keep it safe if the window closes before it paints.
    const cw = creatorWindow;
    const placeCreator = () => { if (cw && !cw.isDestroyed()) cw.setBounds({ x, y, width: W, height }); };
    cw.once('ready-to-show', () => {
      if (cw.isDestroyed()) return;
      placeCreator();   // position before reveal (honored on macOS + cooperative WMs)
      cw.show();
    });
    cw.once('show', () => {
      placeCreator();
      setImmediate(placeCreator);   // re-assert after map (X11 Linux WMs)
      // macOS applies its default window placement on a LATER runloop turn after
      // show, overriding the immediate setBounds — the maximized path escapes this
      // only because the preceding unmaximize() flushes AppKit first. Re-assert on
      // later turns so our explicit frame is the last word. Non-awaited timers run
      // after the handler returns, so they can't interleave with the main resize.
      if (process.platform === 'darwin') { setTimeout(placeCreator, 0); setTimeout(placeCreator, 60); }
    });
  }
  creatorWindow.loadURL(`${APP_URL}/theme-creator-page`);
  hardenWindow(creatorWindow);
  creatorDirty = false; creatorForceClose = false;

  // Opened from Themes → close Themes AFTER Creator exists so focus lands right.
  if (fromThemes && themesWindow && !themesWindow.isDestroyed()) {
    themesWindow.close();
    // Windows foreground-lock: closing the opener can swallow focus (the bug that
    // bit the subs overlay). Same shipped nudge — Windows only, harmless elsewhere.
    if (process.platform === 'win32') {
      creatorWindow.setAlwaysOnTop(true);
      creatorWindow.focus();
      setTimeout(() => { if (creatorWindow && !creatorWindow.isDestroyed()) creatorWindow.setAlwaysOnTop(false); }, 80);
    }
  }

  // Dirty close guard — same shape as subsWindow: clean → close; dirty → intercept
  // and ask the renderer to show its in-app "Close without saving?" modal.
  creatorWindow.on('close', (e) => {
    if (creatorForceClose || !creatorDirty) return;
    e.preventDefault();
    if (!creatorWindow.isDestroyed()) creatorWindow.webContents.send('creator-request-close');
  });
  creatorWindow.on('closed', () => {
    creatorWindow = null; creatorDirty = false; creatorForceClose = false;
    // Wipe any lingering live-preview overrides on main (covers save, cancel, and
    // crash paths alike) so it shows its real (or freshly-saved) theme, then put main
    // back where it was: restore its normal bounds, and re-maximize if it had been.
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('creator-preview-reset');
      if (creatorSavedMainBounds) mainWindow.setBounds(creatorSavedMainBounds);
      if (creatorMainWasMaximized) mainWindow.maximize();
    }
    creatorSavedMainBounds = null;
    creatorMainWasMaximized = false;
  });

  // A renderer crash never fires 'closed', which would strand main shrunk/un-maximized.
  // Route it through a forced close so the restore logic above still runs.
  creatorWindow.webContents.on('render-process-gone', () => {
    if (creatorWindow && !creatorWindow.isDestroyed()) { creatorForceClose = true; creatorWindow.close(); }
  });
});

// Renderer keeps main informed of unsaved edits (mirrors subs-active-downloads).
ipcMain.on('creator-dirty', (event, dirty) => {
  if (!isTrustedSender(event)) return;
  creatorDirty = !!dirty;
});

// Confirmed "Close anyway" from the in-app modal → force the close through.
ipcMain.handle('creator-confirm-close', (event) => {
  if (!isTrustedSender(event)) return;
  if (creatorWindow && !creatorWindow.isDestroyed()) { creatorForceClose = true; creatorWindow.close(); }
});

// Live preview — forward the renderer-validated var map to main, which re-validates
// with validateThemeVar before applying via setProperty (CSSOM = breakout-immune).
ipcMain.on('creator-preview', (event, vars) => {
  if (!isTrustedSender(event) || !vars || typeof vars !== 'object') return;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('creator-preview', vars);
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

ipcMain.handle('open-subscriptions-window', async (event) => {
  if (!isTrustedSender(event)) return;
  if (subsWindow && !subsWindow.isDestroyed()) { subsWindow.focus(); return; }
  const bounds = loadSubsBounds();
  subsWindow = new BrowserWindow({
    ...bounds, minWidth: 600, minHeight: 400,
    title: 'Subscriptions — EGM Downloader',
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
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
    const choice = dialog.showMessageBoxSync(subsWindow, {
      type: 'warning',
      buttons: ['Close anyway', 'Keep open'],
      defaultId: 1,
      cancelId: 1,
      noLink: true,
      title: 'Downloads in progress',
      message: 'Downloads are still in progress.',
      detail: 'If you close this window, downloads will continue in the background as long as the app stays open.\n\nIf you close the entire app, active downloads will be cancelled.\n\nClose anyway?'
    });
    if (choice === 0) { subsForceClose = true; subsWindow.close(); }
  });
  subsWindow.on('closed', () => {
    subsWindow = null;
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
    const lnkTarget = path.join(__dirname, '..', 'EGM Downloader.exe');
    const workDir   = path.join(__dirname, '..');
    const iconPath  = path.join(__dirname, '..', 'static', 'icon.ico');
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

  createTray();         // tray first — visible immediately
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
app.on('before-quit', () => {
  app.isQuitting = true;
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
