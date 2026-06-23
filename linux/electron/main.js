const { app, BrowserWindow, ipcMain, dialog, shell, screen, session } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');
const os   = require('os');
const crypto = require('crypto');

// ── Sandbox: AppImages cannot set SUID on chrome-sandbox — disable sandbox ────
// Safe here because we only load a local Flask server (127.0.0.1), never
// arbitrary web content. No remote code execution risk.
app.commandLine.appendSwitch('no-sandbox');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const EGM_TOKEN = crypto.randomBytes(32).toString('hex');
const APP_URL = `http://${HOST}:${PORT}`;

// ── Settings file (~/.local/share/egm-downloader/) ───────────────────────────
const SETTINGS_FILE = path.join(
  os.homedir(), '.local', 'share', 'egm-downloader', 'egm_settings.json'
);

// ── Window hardening: route external links to default browser, block navigation ─
function hardenWindow(win) {
  // External links → user's default browser (http/https only, never in-app)
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const u = new URL(url);
      if (u.protocol === 'https:') {
        shell.openExternal(u.toString());
      }
    } catch {}
    return { action: 'deny' };
  });
  // Block in-window navigation away from the exact Flask origin (scheme+host+port).
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

function atomicWriteJson(file, data) {
  const tmp = `${file}.tmp`;
  fs.mkdirSync(path.dirname(file), { recursive: true });
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
// Every window shares one preload, so without this any renderer content could
// invoke sensitive IPC. Fail-closed on any error.
function isTrustedSender(event) {
  try {
    const url = (event.senderFrame && event.senderFrame.url) || event.sender.getURL();
    return new URL(url).origin === APP_URL;
  } catch {
    return false;
  }
}

// Cap user-picked text files so we never read a huge file into memory.
const MAX_IMPORT_BYTES = 2 * 1024 * 1024; // 2 MB
function readFileCapped(filePath) {
  const { size } = fs.statSync(filePath);
  if (size > MAX_IMPORT_BYTES) return { error: 'File too large (max 2 MB)' };
  return { ok: true, content: fs.readFileSync(filePath, 'utf8') };
}

// ── Window state helpers ──────────────────────────────────────────────────────
const DEFAULT_BOUNDS = { width: 920, height: 780 };

function isOnScreen(bounds) {
  return screen.getAllDisplays().some(d => {
    const { x, y, width, height } = d.workArea;
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
  const bounds = maximized ? loadWindowState().bounds : mainWindow.getBounds();
  saveSettings({ window_bounds: bounds, window_maximized: maximized });
}

// ── Debounce ──────────────────────────────────────────────────────────────────
function debounce(fn, delay) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

let mainWindow  = null;
let splashWindow = null;
let flaskProc   = null;

// ── Single-instance lock ──────────────────────────────────────────────────────
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
    const { bounds, maximized } = loadWindowState();
    if (maximized) {
      mainWindow.maximize();
    } else if (bounds && isOnScreen(bounds)) {
      mainWindow.setBounds(bounds);
    }
    if (!mainWindow.isVisible()) mainWindow.show();
    mainWindow.focus();
  }
});

// ── Find Python ───────────────────────────────────────────────────────────────
function findPython() {
  const candidates = [
    // Bundled Python (first priority - in resources/python/bin/)
    path.join(process.resourcesPath, 'python', 'bin', 'python3'),
    path.join(__dirname, '..', 'python', 'bin', 'python3'),
    // System Python (fallback)
    'python3',
    'python',
  ];
  for (const c of candidates) {
    try {
      execFileSync(c, ['--version'], { stdio: 'ignore' });
      return c;
    } catch {}
  }
  return null;
}

// ── Start Flask ───────────────────────────────────────────────────────────────
async function startFlask() {
  const python = findPython();
  const appPy  = path.join(__dirname, '..', 'app', 'app.py');
  if (!python) {
    dialog.showErrorBox('Python not found',
      'Bundled Python not found and no system Python 3.10+ available.\n\nPlease reinstall EGM Downloader or install Python from python.org');
    app.quit();
    return;
  }
  flaskProc = spawn(python, [appPy], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, PORT: String(PORT), HOST, EGM_ELECTRON: '1', EGM_API_TOKEN: EGM_TOKEN },
    stdio: 'inherit',
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
      dialog.showErrorBox('EGM Downloader — Startup error',
        `Failed to start backend:\n${err.message}`);
      app.quit();
    }
  });
}

// ── Wait for Flask ────────────────────────────────────────────────────────────
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

// ── Splash window ─────────────────────────────────────────────────────────────
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 500,
    height: 350,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      sandbox:          true,
    },
  });
  const splashPath = path.join(__dirname, 'splash.html');
  splashWindow.loadFile(splashPath);
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

// ── Create window ─────────────────────────────────────────────────────────────
async function createWindow() {
  const winIconPath = path.join(__dirname, '..', 'app', 'static', 'icon-512.png');
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

  // ── Show main window: defensive fallback chain ──────────────────────────────
  // Electron 41 on Ubuntu 24 X11/Mutter does not reliably fire ready-to-show
  // for our BrowserWindow configuration when the app is launched from a file
  // manager or via in-app restart. Backend reaches HTTP 200 normally, but the
  // renderer event never fires, so the splash stays forever and main window
  // never appears.
  //
  // Validated against electron/electron issues #25253 ("ready-to-show event is
  // not fired and app window doesn't show"), #7779 ("ready-to-show never
  // fires", 17 reactions, workaround = use webContents.dom-ready / did-finish-
  // load), and Electron's own docs which acknowledge "ready-to-show could be
  // emitted too late, making the app feel slow."
  //
  // Strategy: try ready-to-show first (fastest, no visual flash). If that
  // doesn't fire, did-finish-load fires when the renderer finishes loading
  // (more reliable). If both fail, a 5s hard timeout forces the window to
  // show anyway. Idempotent via mainWindowShown flag — whichever path fires
  // first wins, others no-op.
  let mainWindowShown = false;
  const showMainWindow = (source) => {
    if (mainWindowShown) return;
    mainWindowShown = true;
    closeSplash();
    mainWindow.show();
    mainWindow.focus();
  };

  // Primary path: ready-to-show (fastest, most semantically correct)
  mainWindow.once('ready-to-show', () => showMainWindow('ready-to-show'));

  // Fallback 1: did-finish-load (more reliable across Linux compositors).
  // Small 100ms delay lets ready-to-show fire first if it's going to,
  // preserving primary path's optimal no-flash behavior.
  mainWindow.webContents.once('did-finish-load', () => {
    setTimeout(() => showMainWindow('did-finish-load'), 100);
  });

  // Fallback 2 (5s hard timeout) is set AFTER loadURL below — not here.
  // Setting it here would fire during ffmpeg/Deno downloads (which block
  // Flask startup), closing the splash before the backend is ready.

  // Save window state on resize/move — debounced 500ms
  const debouncedSave = debounce(saveWindowState, 500);
  mainWindow.on('resize', debouncedSave);
  mainWindow.on('move',   debouncedSave);

  // Save state on close
  mainWindow.on('close', () => {
    saveWindowState();
    app.isQuitting = true;
  });

  try {
    await waitForFlask();
    try { await mainWindow.webContents.session.clearCache(); } catch {}
    mainWindow.loadURL(APP_URL);
    hardenWindow(mainWindow);

    // Fallback 2: hard 5s timeout AFTER loadURL. Defense against both
    // ready-to-show and did-finish-load failing on some Linux compositors.
    // Starts counting only after Flask is confirmed ready and the page is
    // loading — never fires during ffmpeg/Deno downloads.
    setTimeout(() => {
      if (!mainWindowShown) {
        console.warn('[EGM] Window show timeout reached after 5s — forcing show');
        showMainWindow('timeout-fallback');
      }
    }, 5000);
  } catch (e) {
    closeSplash();
    dialog.showErrorBox('EGM Downloader — Startup error', e.message);
    app.quit();
  }
}

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
    title:      'Select download folder',
    defaultPath: defaultPath,
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
});

// ── IPC: open folder in Files ─────────────────────────────────────────────────
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

// ── IPC: open file dialog (settings import + cookies browse) ─────────────────
ipcMain.handle('open-file', async (event, options) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
  const isCookies = options && options.type === 'cookies';
  const dialogOpts = {
    title:      isCookies ? 'Select cookies.txt' : 'Import Settings',
    properties: ['openFile'],
  };
  if (!isCookies) dialogOpts.filters = [{ name: 'JSON', extensions: ['json'] }];
  const result = await dialog.showOpenDialog(mainWindow, dialogOpts);
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  try {
    return readFileCapped(result.filePaths[0]);
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: open cookies file dialog (kept for backward compat) ─────────────────
ipcMain.handle('open-cookies-file', async (event) => {
  if (!isTrustedSender(event)) return { error: 'Untrusted sender' };
  const parentWin = BrowserWindow.fromWebContents(event.sender) || mainWindow;
  const result = await dialog.showOpenDialog(parentWin, {
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

// ── IPC: open full history window ─────────────────────────────────────────────
let historyWindow = null;
const HISTORY_BOUNDS_FILE = path.join(os.homedir(), '.local', 'share', 'egm-downloader', 'egm_history_window.json');

function loadHistoryBounds() {
  try {
    const saved = JSON.parse(fs.readFileSync(HISTORY_BOUNDS_FILE, 'utf8'));
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
  try { fs.writeFileSync(HISTORY_BOUNDS_FILE, JSON.stringify(win.getBounds()), 'utf8'); } catch {}
}

ipcMain.handle('open-history-window', async (event, from) => {
  if (!isTrustedSender(event)) return;
  if (historyWindow && !historyWindow.isDestroyed()) { if (from === 'subs') historyWindow.loadURL(`${APP_URL}/history-page?from=subs`); historyWindow.focus(); return; }
  const bounds = loadHistoryBounds();
  historyWindow = new BrowserWindow({
    ...bounds, minWidth: 600, minHeight: 420,
    title: 'Download History',
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  historyWindow.loadURL(`${APP_URL}/history-page${from === 'subs' ? '?from=subs' : ''}`);
  hardenWindow(historyWindow);
  let saveTimer = null;
  const debouncedSave = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveHistoryBounds(historyWindow), 500); };
  historyWindow.on('resize', debouncedSave);
  historyWindow.on('move',   debouncedSave);
  historyWindow.on('closed', () => { historyWindow = null; });
});


// ── IPC: open themes window ───────────────────────────────────────────────────
let themesWindow = null;
const THEMES_BOUNDS_FILE = path.join(os.homedir(), '.local', 'share', 'egm-downloader', 'egm_themes_window.json');

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
    icon: path.join(__dirname, '..', 'app', 'static', 'icon-512.png'),
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
  // Remember how to put main back when the Creator closes: its NORMAL (un-maximized)
  // rectangle, plus whether it was maximized so we re-maximize rather than just resize.
  creatorSavedMainBounds  = liveMain ? { ...mainWindow.getNormalBounds() } : { ...mb };
  creatorMainWasMaximized = wasMaximized;

  let x, y, height;
  if (wasMaximized && liveMain) {
    // Maximized → shifting can't make room (main already spans the display), so
    // un-maximize and tile: main takes the work area minus the Creator column, the
    // Creator fills that column. No overlap; main is re-maximized on close.
    mainWindow.unmaximize();
    await new Promise(r => setTimeout(r, 80));  // Linux WMs process unmaximize async
    mainWindow.setBounds({ x: disp.x, y: disp.y, width: Math.max(360, disp.width - W), height: disp.height });
    x = disp.x + disp.width - W;
    y = disp.y;
    height = disp.height;
  } else {
    // Windowed → shift main left by W and open the Creator flush to its right.
    const newMainX = Math.max(disp.x, mb.x - W);
    if (liveMain) mainWindow.setBounds({ x: newMainX, y: mb.y, width: mb.width, height: mb.height });
    height = Math.max(460, Math.min(mb.height, disp.height));
    x = newMainX + mb.width;
    if (x + W > disp.x + disp.width) x = Math.max(disp.x, mb.x - W);   // no room right → open left
    x = Math.max(disp.x, Math.min(x, disp.x + disp.width - W));
    y = Math.max(disp.y, Math.min(mb.y, disp.y + disp.height - height));
  }

  creatorWindow = new BrowserWindow({
    x, y, width: W, height,
    minWidth: 340, minHeight: 460,
    title: 'Theme Creator — EGM Downloader',
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
    show: false,  // prevent WM centering — we show in ready-to-show after forcing position
  });
  creatorWindow.once('ready-to-show', () => {
    if (!creatorWindow || creatorWindow.isDestroyed()) return;
    creatorWindow.setPosition(Math.round(x), Math.round(y));
    creatorWindow.show();
  });
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

// -- IPC: open subscriptions window ----------------------------------------
let subsWindow = null;
let subsActiveDownloads = false;
let subsForceClose = false;
const WINDOW_STATE_DIR = path.join(os.homedir(), '.local', 'share', 'egm-downloader');
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
  subsWindow = new BrowserWindow({
    ...loadSubsBounds(), minWidth: 600, minHeight: 400,
    title: 'Subscriptions - EGM Downloader',
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  subsWindow.loadURL(APP_URL + '/subscriptions-page');
  hardenWindow(subsWindow);
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
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.show();
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
  try { if (!['http:', 'https:'].includes(new URL(url).protocol)) return; } catch { return; }
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('readd-url', url);
    mainWindow.focus();
  }
});


// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
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

  createSplash();
  startFlask();
  await createWindow();
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (!flaskProc) return;

  const pid = flaskProc.pid;
  flaskProc = null;

  // Ask Flask to shut down cleanly
  try {
    const req = http.request({ host: HOST, port: PORT, path: '/api/shutdown', method: 'POST', headers: { 'X-EGM-Token': EGM_TOKEN } });
    req.on('error', () => {});
    req.end();
  } catch {}

  // Kill the process group after a grace period (takes out yt-dlp + ffmpeg too)
  setTimeout(() => {
    if (pid) {
      try { process.kill(-pid, 'SIGTERM'); } catch {
        try { process.kill(pid, 'SIGTERM'); } catch {}
      }
    }
  }, 400);
});
