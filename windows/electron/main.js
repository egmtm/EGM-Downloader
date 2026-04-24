const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage } = require('electron');
const { spawn, execSync, execFileSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');
const os   = require('os');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}`;

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

  // Left-click tray icon → show and focus (tray is secondary access point)
  tray.on('click', () => {
    if (!mainWindow) return;
    mainWindow.show();
    mainWindow.focus();
  });
}

// ── Create window ─────────────────────────────────────────────────────────────
async function createWindow() {
  const winIconPath = path.join(__dirname, '..', 'static', 'icon-512.png');
  const winIconOpts = fs.existsSync(winIconPath) ? { icon: winIconPath } : {};

  mainWindow = new BrowserWindow({
    width:  920,
    height: 780,
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

  mainWindow.setMenuBarVisibility(false);

  // Show window only when Flask page is ready — no blank loading screen
  mainWindow.once('ready-to-show', () => mainWindow.show());

  // Minimize → normal OS behavior (no intercept)
  // Close (X) → quit the app
  mainWindow.on('close', () => { app.isQuitting = true; });

  // Wait for Flask to be ready, then load the page
  try {
    await waitForFlask();
    mainWindow.loadURL(APP_URL);
  } catch (e) {
    dialog.showErrorBox('EGM Downloader — Startup error', e.message);
    app.quit();
  }
}

// ── IPC: launch installer (for auto-update) ──────────────────────────────────
ipcMain.handle('launch-installer', async (event, installerPath) => {
  try {
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
    await shell.openPath(folderPath);
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

// ── IPC: create desktop shortcut ─────────────────────────────────────────────
ipcMain.handle('create-shortcut', async () => {
  try {
    const lnkTarget = path.join(__dirname, '..', 'EGM Downloader.vbs');
    const workDir   = path.join(__dirname, '..');
    const iconPath  = path.join(__dirname, '..', 'static', 'icon.ico');
    const tmpVbs    = path.join(os.tmpdir(), `egm_sc_${Date.now()}.vbs`);

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

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  createTray();      // tray first — visible immediately
  startFlask();      // spawn backend (non-blocking — createWindow waits for it)
  await createWindow(); // window polls until Flask responds, then loads
});

// All cleanup consolidated in before-quit — window-all-closed just triggers quit
app.on('window-all-closed', () => {
  app.quit();
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
