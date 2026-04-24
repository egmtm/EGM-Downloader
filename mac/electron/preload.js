// Preload: expose Electron APIs to the renderer (Flask page) safely
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  pickFolder:      (defaultPath) => ipcRenderer.invoke('pick-folder', defaultPath),
  openFolder:      (folderPath)  => ipcRenderer.invoke('open-folder', folderPath),
  quit:            ()            => ipcRenderer.invoke('quit-app'),
  isElectron: true,
});
