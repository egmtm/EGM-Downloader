// Preload: expose Electron APIs to the renderer (Flask page) safely
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  pickFolder:      (defaultPath) => ipcRenderer.invoke('pick-folder', defaultPath),
  openFolder:      (folderPath)  => ipcRenderer.invoke('open-folder', folderPath),
  quit:            ()            => ipcRenderer.invoke('quit-app'),
  saveFile:           (name, content) => ipcRenderer.invoke('save-file', name, content),
  openFile:           ()              => ipcRenderer.invoke('open-file'),
  openHistoryWindow:  ()              => ipcRenderer.invoke('open-history-window'),
  isElectron: true,
});
