const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage, screen } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');
const os   = require('os');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}`;

// ── Settings file (same location as app.py BASE_DIR) ─────────────────────────
const SETTINGS_FILE = path.join(__dirname, '..', 'egm_settings.json');

function loadSettings() {
  try { return JSON.parse(fs.readFileSync(SETTINGS_FILE, 'utf8')); }
  catch { return {}; }
}

function saveSettings(patch) {
  try {
    const s = loadSettings();
    Object.assign(s, patch);
    fs.writeFileSync(SETTINGS_FILE, JSON.stringify(s, null, 2), 'utf8');
  } catch {}
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
let flaskProc   = null;
let tray        = null;

// ── Fix 1: Single-instance lock ───────────────────────────────────────────────
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
  process.exit(0);
}
app.on('second-instance', () => {
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
      execSync(`"${c}" --version`, { stdio: 'ignore', windowsHide: true });
      return c;
    } catch {}
  }
  return null;
}

// ── Start Flask ───────────────────────────────────────────────────────────────
async function startFlask() {
  const python = findPython();
  const appPy  = path.join(__dirname, '..', 'app.py');

  if (!python) {
    dialog.showErrorBox('Python not found',
      'Python 3.10+ is required.\n\nDownload from python.org and check "Add Python to PATH" during install.');
    app.quit();
    return;
  }

  flaskProc = spawn(python, [appPy], {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, PORT: String(PORT), HOST, EGM_ELECTRON: '1' },
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
      dialog.showErrorBox('EGM Downloader — Startup error',
        `Failed to start backend:\n${err.message}`);
      app.quit();
    }
  });
}

// ── Fix 4: Single waitForFlask, no double retry ───────────────────────────────
function waitForFlask(retries = 60, delay = 1000) {
  return new Promise((resolve, reject) => {
    const try_ = (n) => {
      const req = http.get(APP_URL, res => { res.resume(); resolve(); });
      req.on('error', () => {
        if (n <= 0) {
          reject(new Error('The backend did not start within 60 seconds.\n\nTry launching the app again.'));
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
    },
    backgroundColor: '#0b1120',
    show: false,
  });

  // Restore maximized state after window is created
  if (maximized) mainWindow.maximize();

  mainWindow.setMenuBarVisibility(false);

  // Show window only when Flask page is ready — no blank loading screen
  mainWindow.once('ready-to-show', () => mainWindow.show());

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
  } catch (e) {
    dialog.showErrorBox('EGM Downloader — Startup error', e.message);
    app.quit();
  }
}

// ── IPC: launch installer (for auto-update) ──────────────────────────────────
ipcMain.handle('launch-installer', async (event, installerPath) => {
  try {
    if (!installerPath || typeof installerPath !== 'string') return { error: 'Invalid installer path' };
    if (!installerPath.includes('egm-update') && !installerPath.includes('egm-setup')) return { error: 'Unexpected installer name' };
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
ipcMain.handle('quit-app', () => {
  app.isQuitting = true;
  app.quit();
});

// ── IPC: folder picker ────────────────────────────────────────────────────────
ipcMain.handle('pick-folder', async (event, defaultPath) => {
  const result = await dialog.showOpenDialog(mainWindow, {
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

// ── IPC: open file dialog (settings import) ───────────────────────────────────
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

// ── IPC: open cookies file dialog ────────────────────────────────────────────
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
const HISTORY_BOUNDS_FILE = path.join(path.dirname(app.getPath('exe')), 'egm_history_window.json');

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

ipcMain.handle('open-history-window', async () => {
  if (historyWindow && !historyWindow.isDestroyed()) {
    historyWindow.focus();
    return;
  }
  const bounds = loadHistoryBounds();
  historyWindow = new BrowserWindow({
    ...bounds, minWidth: 600, minHeight: 420,
    title: 'Download History',
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
    webPreferences: { nodeIntegration: false, contextIsolation: true },
    autoHideMenuBar: true,
  });
  historyWindow.loadURL(`${APP_URL}/history-page`);
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
const THEMES_BOUNDS_FILE = path.join(path.dirname(app.getPath('exe')), 'egm_themes_window.json');

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
    icon: path.join(__dirname, '..', 'static', 'icon-64.png'),
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

// ── IPC: relay theme change from themes window to main window ─────────────────

// Theme key validation — alphanumeric only, prevents IPC injection while
// supporting any future theme without allowlist maintenance
const VALID_THEME_RE = /^[a-z0-9]+$/;
ipcMain.on('set-theme', (event, theme) => {
  if (!theme || typeof theme !== 'string' || !VALID_THEME_RE.test(theme)) return; // reject malformed theme keys
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('theme-changed', theme);
  }
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

// ── IPC: create desktop shortcut ─────────────────────────────────────────────
ipcMain.handle('create-shortcut', async () => {
  try {
    const lnkTarget = path.join(__dirname, '..', 'EGM Downloader.vbs');
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
    const req = http.get(`${APP_URL}/api/show-window-check`, (res) => {
      let body = '';
      res.on('data', d => body += d);
      res.on('end', () => {
        try {
          if (JSON.parse(body).show) {
            restoreWindowState();
            if (!mainWindow.isVisible()) mainWindow.show();
            mainWindow.focus();
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
  createTray();         // tray first — visible immediately
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
    const req = http.request({ host: HOST, port: PORT, path: '/api/shutdown', method: 'POST' });
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
