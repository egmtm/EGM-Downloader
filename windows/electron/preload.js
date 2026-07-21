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
  pickFolder:      (defaultPath)    => ipcRenderer.invoke('pick-folder', defaultPath),
  openFolder:      (folderPath)     => isStr(folderPath)
                                         ? ipcRenderer.invoke('open-folder', folderPath)
                                         : Promise.resolve({ error: 'Invalid path' }),
  createShortcut:  ()               => ipcRenderer.invoke('create-shortcut'),
  quit:            (opts)           => ipcRenderer.invoke('quit-app', opts),
  launchInstaller: (installerPath)  => isStr(installerPath)
                                         ? ipcRenderer.invoke('launch-installer', installerPath)
                                         : Promise.resolve({ error: 'Invalid installer path' }),
  saveFile:           (name, content)  => ipcRenderer.invoke('save-file', name, content),
  openFile:           (options)         => ipcRenderer.invoke('open-file', options),
  openCookiesFile:    ()               => ipcRenderer.invoke('open-cookies-file'),
  openHistoryWindow:  (from)           => ipcRenderer.invoke('open-history-window', from),
  openThemesWindow:   ()               => ipcRenderer.invoke('open-themes-window'),
  openConsoleWindow:  ()               => ipcRenderer.invoke('open-console-window'),
  openSubscriptions:  ()               => ipcRenderer.invoke('open-subscriptions-window'),
  closeSubscriptions: ()               => ipcRenderer.invoke('close-subscriptions'),
  notifySubsDownloads: (active)        => ipcRenderer.send('subs-active-downloads', !!active),
  onThumbarCommand:  (cb)             => ipcRenderer.on('thumbar-cmd', (_e, cmd) => { if (cmd === 'open-folder' || cmd === 'cancel-all') cb(cmd); }),
  setActivity:        (a)              => ipcRenderer.send('set-activity', a),
  refocusWindow:       ()                 => ipcRenderer.send('refocus-window'),
  setTheme:           (theme)          => { if (isStr(theme) && THEME_RE.test(theme)) ipcRenderer.send('set-theme', theme); },
  sendUrlToMain:      (url)            => { if (isHttpUrl(url)) ipcRenderer.send('send-url-to-main', url); },
  // Tell main the in-page Theme Creator panel opened/closed (it widens the window
  // so the panel never compresses the main UI, and restores it on close).
  notifyCreatorPanel: (open)  => ipcRenderer.send('creator-panel', !!open),
  // Listener registrars return an unsubscribe fn so callers can clean up and avoid
  // stacking duplicate handlers across reloads/navigation. Existing callers that
  // ignore the return value keep working unchanged.
  onThemeChanged:     (cb)             => {
    const handler = (e, theme) => cb(theme);
    ipcRenderer.on('theme-changed', handler);
    return () => ipcRenderer.removeListener('theme-changed', handler);
  },
  onReceiveUrl:       (cb)             => {
    const handler = (e, url) => cb(url);
    ipcRenderer.on('readd-url', handler);
    return () => ipcRenderer.removeListener('readd-url', handler);
  },
  isElectron: true,
  platform: 'win',
});
