const { app, BrowserWindow, ipcMain, dialog, shell, screen } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');
const os   = require('os');

// ── Sandbox: AppImages cannot set SUID on chrome-sandbox — disable sandbox ────
// Safe here because we only load a local Flask server (127.0.0.1), never
// arbitrary web content. No remote code execution risk.
app.commandLine.appendSwitch('no-sandbox');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}`;

// ── Settings file (~/.local/share/egm-downloader/) ───────────────────────────
const SETTINGS_FILE = path.join(
  os.homedir(), '.local', 'share', 'egm-downloader', 'egm_settings.json'
);

function loadSettings() {
  try { return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')); }
  catch { return {}; }
}

function saveSettings(patch) {
  try {
    const s = loadSettings();
    Object.assign(s, patch);
    fs.mkdirSync(path.dirname(SETTINGS_FILE), { recursive: true });
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(s, null, 2), 'utf8');
  } catch {}
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
      execSync(`"${c}" --version`, { stdio: 'ignore' });
      console.log(`[EGM] Using Python: ${c}`);
      return c;
    } catch {}
  }
  return null;
}

// ── Start Flask ───────────────────────────────────────────────────────────────
async function startFlask() {
  updateSplash(10, 'Starting backend...');

  const python = findPython();
  const appPy  = path.join(__dirname, '..', 'app', 'app.py');
  if (!python) {
    dialog.showErrorBox('Python not found',
      'Bundled Python not found and no system Python 3.10+ available.\n\nPlease reinstall EGM Downloader or install Python from python.org');
    app.quit();
    return;
  }

  updateSplash(20, 'Launching Python backend...');

  flaskProc = spawn(python, [appPy], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, PORT: String(PORT), HOST, EGM_ELECTRON: '1' },
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

  updateSplash(30, 'Backend launched, waiting for response...');
}

// ── Wait for Flask ────────────────────────────────────────────────────────────
function waitForFlask(retries = 180, delay = 1000) {
  return new Promise((resolve, reject) => {
    let attemptCount = 0;
    const try_ = (n) => {
      attemptCount++;
      const progress = 30 + Math.min(60, (attemptCount / retries) * 60);
      updateSplash(progress, `Waiting for backend... (${attemptCount}/${retries})`);

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
    },
  });
  const splashPath = path.join(__dirname, 'splash.html');
  splashWindow.loadFile(splashPath);
  splashWindow.center();
  splashWindow.show();
}

function updateSplash(progress, message) {
  console.log(`[EGM] ${progress}% - ${message}`);
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('splash-progress', { progress, message });
  }
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('splash-complete');
    setTimeout(() => {
      if (splashWindow) {
        splashWindow.close();
        splashWindow = null;
      }
    }, 500);
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
    console.log(`[EGM] Main window shown via: ${source}`);
    updateSplash(100, 'Ready!');
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

  // Fallback 2: hard 5s timeout. Defense against both events failing.
  // Flask backend reaches 100% Ready well before 5s under normal conditions
  // (typical: ~1-2s). Only triggers if the event chain is genuinely broken.
  setTimeout(() => {
    if (!mainWindowShown) {
      console.warn('[EGM] Window show timeout reached after 5s — forcing show');
      showMainWindow('timeout-fallback');
    }
  }, 5000);

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
    updateSplash(90, 'Loading interface...');
    try { await mainWindow.webContents.session.clearCache(); } catch {}
    mainWindow.loadURL(APP_URL);
  } catch (e) {
    closeSplash();
    dialog.showErrorBox('EGM Downloader — Startup error', e.message);
    app.quit();
  }
}

// ── IPC: quit app ─────────────────────────────────────────────────────────────
ipcMain.handle('quit-app', () => {
  app.isQuitting = true;
  app.quit();
});

// ── IPC: folder picker ────────────────────────────────────────────────────────
ipcMain.handle('pick-folder', async (event, defaultPath) => {
  const result = await dialog.showOpenDialog(mainWindow, {
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
    if (!folderPath || typeof folderPath !== 'string') return { error: 'Invalid path' };
    if (folderPath.startsWith('http') || folderPath.startsWith('javascript')) return { error: 'Invalid path' };
    await shell.openPath(folderPath);
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: save file dialog (settings export) ───────────────────────────────────
ipcMain.handle('save-file', async (event, defaultName, content) => {
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
  const isCookies = options && options.type === 'cookies';
  const dialogOpts = {
    title:      isCookies ? 'Select cookies.txt' : 'Import Settings',
    properties: ['openFile'],
  };
  if (!isCookies) dialogOpts.filters = [{ name: 'JSON', extensions: ['json'] }];
  const result = await dialog.showOpenDialog(mainWindow, dialogOpts);
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  try {
    const content = require('fs').readFileSync(result.filePaths[0], 'utf8');
    return { ok: true, content };
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: open cookies file dialog (kept for backward compat) ─────────────────
ipcMain.handle('open-cookies-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title:      'Select cookies.txt',
    filters:    [{ name: 'Text files', extensions: ['txt'] }, { name: 'All files', extensions: ['*'] }],
    properties: ['openFile'],
  });
  if (result.canceled || !result.filePaths.length) return { canceled: true };
  try {
    const content = require('fs').readFileSync(result.filePaths[0], 'utf8');
    return { ok: true, content };
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

ipcMain.handle('open-history-window', async () => {
  if (historyWindow && !historyWindow.isDestroyed()) { historyWindow.focus(); return; }
  const bounds = loadHistoryBounds();
  historyWindow = new BrowserWindow({
    ...bounds, minWidth: 600, minHeight: 420,
    title: 'Download History',
    webPreferences: { nodeIntegration: false, contextIsolation: true, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  historyWindow.loadURL(`${APP_URL}/history-page`);
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
ipcMain.handle('open-themes-window', async () => {
  if (themesWindow && !themesWindow.isDestroyed()) { themesWindow.focus(); return; }
  const bounds = loadThemesBounds();
  themesWindow = new BrowserWindow({
    ...bounds, minWidth: 480, minHeight: 400,
    title: 'All Themes — EGM Downloader',
    icon: path.join(__dirname, '..', 'app', 'static', 'icon-512.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true, preload: path.join(__dirname, 'preload.js') },
    autoHideMenuBar: true,
  });
  themesWindow.loadURL(`${APP_URL}/themes-page`);
  let saveTimer = null;
  const debouncedSave = () => { clearTimeout(saveTimer); saveTimer = setTimeout(() => saveThemesBounds(themesWindow), 500); };
  themesWindow.on('resize', debouncedSave);
  themesWindow.on('move',   debouncedSave);
  themesWindow.on('closed', () => { themesWindow = null; });
});

// Theme key validation — alphanumeric only, prevents IPC injection while
// supporting any future theme without allowlist maintenance
const VALID_THEME_RE = /^[a-z0-9]+$/;
ipcMain.on('set-theme', (event, theme) => {
  if (!theme || typeof theme !== 'string' || !VALID_THEME_RE.test(theme)) return;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('theme-changed', theme);
});

// ── IPC: forward URL from history window to main window's URL textarea ────────
// History window is a separate BrowserWindow with no opener relationship,
// so cross-window readd uses this IPC bridge.
ipcMain.on('send-url-to-main', (event, url) => {
  if (typeof url !== 'string' || !url.trim()) return;
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('readd-url', url);
    mainWindow.focus();
  }
});


// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
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
    const req = http.request({ host: HOST, port: PORT, path: '/api/shutdown', method: 'POST' });
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
