const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');

// ── Sandbox: AppImages cannot set SUID on chrome-sandbox — disable sandbox ────
// Safe here because we only load a local Flask server (127.0.0.1), never
// arbitrary web content. No remote code execution risk.
app.commandLine.appendSwitch('no-sandbox');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}`;

let mainWindow  = null;
let splashWindow = null;
let flaskProc   = null;
let tray        = null;

// ── Single-instance lock ──────────────────────────────────────────────────────
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
      nodeIntegration: true,
      contextIsolation: false,
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

  mainWindow.once('ready-to-show', () => {
    updateSplash(100, 'Ready!');
    closeSplash();
    mainWindow.show();
  });

  mainWindow.on('close', () => { app.isQuitting = true; });

  try {
    await waitForFlask();
    updateSplash(90, 'Loading interface...');
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
    await shell.openPath(folderPath);
    return { success: true };
  } catch (e) {
    return { error: e.message };
  }
});

// ── App lifecycle ─────────────────────────────────────────────────────────────
app.whenReady().then(async () => {
  createSplash();
  createTray();
  startFlask();
  await createWindow();
});

app.on('window-all-closed', () => {
  app.quit();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (tray) { tray.destroy(); tray = null; }
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
