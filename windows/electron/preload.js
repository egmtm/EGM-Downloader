// Preload: expose Electron APIs to the renderer (Flask page) safely
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  pickFolder:      (defaultPath)    => ipcRenderer.invoke('pick-folder', defaultPath),
  openFolder:      (folderPath)     => ipcRenderer.invoke('open-folder', folderPath),
  createShortcut:  ()               => ipcRenderer.invoke('create-shortcut'),
  quit:            ()               => ipcRenderer.invoke('quit-app'),
  launchInstaller: (installerPath)  => ipcRenderer.invoke('launch-installer', installerPath),
  isElectron: true,
});
