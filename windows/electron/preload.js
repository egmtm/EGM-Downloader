// Preload: expose Electron APIs to the renderer (Flask page) safely
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  pickFolder:      (defaultPath)    => ipcRenderer.invoke('pick-folder', defaultPath),
  openFolder:      (folderPath)     => ipcRenderer.invoke('open-folder', folderPath),
  createShortcut:  ()               => ipcRenderer.invoke('create-shortcut'),
  quit:            ()               => ipcRenderer.invoke('quit-app'),
  launchInstaller: (installerPath)  => ipcRenderer.invoke('launch-installer', installerPath),
  saveFile:           (name, content)  => ipcRenderer.invoke('save-file', name, content),
  openFile:           ()               => ipcRenderer.invoke('open-file'),
  openHistoryWindow:  ()               => ipcRenderer.invoke('open-history-window'),
  openThemesWindow:   ()               => ipcRenderer.invoke('open-themes-window'),
  setTheme:           (theme)          => ipcRenderer.send('set-theme', theme),
  onThemeChanged:     (cb)             => ipcRenderer.on('theme-changed', (e, theme) => cb(theme)),
  isElectron: true,
  platform: 'win',
});
