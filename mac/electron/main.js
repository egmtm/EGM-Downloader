const { app, BrowserWindow, ipcMain, dialog, shell, screen, session } = require('electron');
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

// ── Settings file (~/Library/Application Support/EGM Downloader/) ─────────────
const SETTINGS_FILE = path.join(
  os.homedir(), 'Library', 'Application Support', 'EGM Downloader', 'egm_settings.json'
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

// ── Fix 1: Single-instance lock ───────────────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}
app.on('second-instance', () => {
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
    stdio: 'inherit',  // Show output for debugging
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
          reject(new Error('The backend did not start within 3 minutes.\n\nTry launching the app again or check your internet connection.'));
          return;
        }
        setTimeout(() => try_(n - 1), delay);
      });
      req.setTimeout(900, () => { req.destroy(); });
    };
    try_(retries);
  });
}

// ── Create splash window ──────────────────────────────────────────────────────
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

// ── Send progress to splash ───────────────────────────────────────────────────
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

  // Fix 5: show when the real Flask page is ready — no loading screen
  mainWindow.once('ready-to-show', () => {
    closeSplash();
    mainWindow.show();
  });

  // Save window state on resize/move — debounced 500ms
  const debouncedSave = debounce(saveWindowState, 500);
  mainWindow.on('resize', debouncedSave);
  mainWindow.on('move',   debouncedSave);

  // Save state on close
  mainWindow.on('close', () => {
    saveWindowState();
    app.isQuitting = true;
  });

  // Fix 4: single waitForFlask, single error path
  try {
    await waitForFlask();
    try { await mainWindow.webContents.session.clearCache(); } catch {}
    mainWindow.loadURL(APP_URL);
    hardenWindow(mainWindow);
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
    title:       'Select download folder',
    defaultPath: defaultPath,
    properties:  ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths.length) return null;
  return result.filePaths[0];
});

// ── IPC: open folder in Finder ────────────────────────────────────────────────
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
const HISTORY_BOUNDS_FILE = path.join(app.getPath('userData'), 'egm_history_window.json');

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
const THEMES_BOUNDS_FILE = path.join(app.getPath('userData'), 'egm_themes_window.json');

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

// -- IPC: open subscriptions window ----------------------------------------
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

  createSplash();    // show splash immediately
  startFlask();      // spawn backend (non-blocking — createWindow waits for it)
  await createWindow(); // window polls until Flask responds, then loads
});

// Fix 3: window-all-closed only calls quit — cleanup is consolidated in before-quit
app.on('window-all-closed', () => {
  app.quit();
});

// Fix 3: single cleanup point for every quit path (X, crash)
app.on('before-quit', () => {
  app.isQuitting = true;
  if (!flaskProc) return;

  const pid = flaskProc.pid;
  flaskProc = null;

  // Step 1: ask Flask to exit cleanly
  try {
    const http_ = require('http');
    const req = http_.request({ host: HOST, port: PORT, path: '/api/shutdown', method: 'POST', headers: { 'X-EGM-Token': EGM_TOKEN } });
    req.on('error', () => {});
    req.end();
  } catch {}

  // Step 2: after a short grace period, kill the process tree forcefully
  // On macOS/Linux, use kill command instead of taskkill
  setTimeout(() => {
    if (pid) {
      try { 
        // Kill the process group to ensure child processes (yt-dlp, ffmpeg) are also terminated
        process.kill(-pid, 'SIGTERM');
      } catch (e) {
        // If that fails, try regular kill
        try { process.kill(pid, 'SIGTERM'); } catch {}
      }
    }
  }, 400);
});
