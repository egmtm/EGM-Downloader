const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const fs   = require('fs');
const http = require('http');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT    = 8899;
const HOST    = '127.0.0.1';
const APP_URL = `http://${HOST}:${PORT}`;

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
    stdio: 'inherit',  // Show output for debugging
    detached: false,
  });

  flaskProc.on('exit', (code) => {
    if (code !== 0 && code !== null && !app.isQuiting) {
      app.isQuiting = true;
      dialog.showErrorBox('EGM Downloader — Backend crashed',
        `The backend stopped unexpectedly (code ${code}).\n\nPlease restart the app.`);
      app.quit();
    }
  });

  flaskProc.on('error', (err) => {
    if (!app.isQuiting) {
      app.isQuiting = true;
      dialog.showErrorBox('EGM Downloader — Startup error',
        `Failed to start backend:\n${err.message}`);
      app.quit();
    }
  });
  
  updateSplash(30, 'Backend launched, waiting for response...');
}

// ── Fix 4: Single waitForFlask, no double retry ───────────────────────────────
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
  console.log('[EGM] Creating splash window...');
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
  console.log('[EGM] Loading splash from:', splashPath);
  splashWindow.loadFile(splashPath);
  splashWindow.center();
  splashWindow.show();
  console.log('[EGM] Splash window created and shown');
}

// ── Send progress to splash ───────────────────────────────────────────────────
function updateSplash(progress, message) {
  console.log(`[EGM] Splash progress: ${progress}% - ${message}`);
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('splash-progress', { progress, message });
  } else {
    console.log('[EGM] WARNING: Splash window not available for update');
  }
}

function closeSplash() {
  console.log('[EGM] Closing splash window...');
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('splash-complete');
    setTimeout(() => {
      if (splashWindow) {
        splashWindow.close();
        splashWindow = null;
        console.log('[EGM] Splash window closed');
      }
    }, 500);
  }
}

// ── Create window ─────────────────────────────────────────────────────────────
async function createWindow() {
  const winIconPath = path.join(__dirname, '..', 'app', 'static', 'icon-512.png');
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

  // Fix 5: show when the real Flask page is ready — no loading screen
  mainWindow.once('ready-to-show', () => {
    updateSplash(100, 'Ready!');
    closeSplash();
    mainWindow.show();
  });

  // Minimize → normal OS behavior (no intercept)
  // Close (X) → quit the app
  mainWindow.on('close', () => { app.isQuiting = true; });

  // Fix 4: single waitForFlask, single error path
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
  app.isQuiting = true;
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

// ── IPC: open folder in Finder ────────────────────────────────────────────────
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
  app.isQuiting = true;
  if (!flaskProc) return;

  const pid = flaskProc.pid;
  flaskProc = null;

  // Step 1: ask Flask to exit cleanly
  try {
    const http_ = require('http');
    const req = http_.request({ host: HOST, port: PORT, path: '/api/shutdown', method: 'POST' });
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
