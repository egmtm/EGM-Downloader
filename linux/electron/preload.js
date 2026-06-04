// Preload: expose Electron APIs to the renderer (Flask page) safely.
// Input is re-validated in main.js too — these checks are defense-in-depth that
// reject obviously-bad values at the bridge before any IPC is sent.
const { contextBridge, ipcRenderer } = require('electron');

const isStr     = (v) => typeof v === 'string' && v.length > 0;
const THEME_RE  = /^[a-z0-9-]+$/;
const isHttpUrl = (v) => {
  try { return ['http:', 'https:'].includes(new URL(v).protocol); }
  catch { return false; }
};

contextBridge.exposeInMainWorld('electronAPI', {
  pickFolder:        (defaultPath) => ipcRenderer.invoke('pick-folder', defaultPath),
  openFolder:        (folderPath)  => isStr(folderPath)
                                        ? ipcRenderer.invoke('open-folder', folderPath)
                                        : Promise.resolve({ error: 'Invalid path' }),
  quit:              ()            => ipcRenderer.invoke('quit-app'),
  saveFile:          (name, content) => ipcRenderer.invoke('save-file', name, content),
  openFile:          (options)       => ipcRenderer.invoke('open-file', options),
  openCookiesFile:   ()              => ipcRenderer.invoke('open-cookies-file'),
  openHistoryWindow: ()              => ipcRenderer.invoke('open-history-window'),
  openThemesWindow:  ()              => ipcRenderer.invoke('open-themes-window'),
  setTheme:          (theme)         => { if (isStr(theme) && THEME_RE.test(theme)) ipcRenderer.send('set-theme', theme); },
  sendUrlToMain:     (url)           => { if (isHttpUrl(url)) ipcRenderer.send('send-url-to-main', url); },
  // Listener registrars return an unsubscribe fn so callers can avoid stacking
  // duplicate handlers across reloads. Existing callers that ignore it still work.
  onThemeChanged:    (cb)            => {
    const handler = (e, theme) => cb(theme);
    ipcRenderer.on('theme-changed', handler);
    return () => ipcRenderer.removeListener('theme-changed', handler);
  },
  onReceiveUrl:      (cb)            => {
    const handler = (e, url) => cb(url);
    ipcRenderer.on('readd-url', handler);
    return () => ipcRenderer.removeListener('readd-url', handler);
  },
  isElectron: true,
  platform: 'linux',
});
