const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('appBridge', {
  openInstagramLogin: () => ipcRenderer.invoke('open-instagram-login'),
  importSession: () => ipcRenderer.invoke('import-session'),
  importMedia: () => ipcRenderer.invoke('import-media'),
  importFilePath: (filePath) => ipcRenderer.invoke('import-file-path', filePath),
  chooseExportDirectory: () => ipcRenderer.invoke('choose-export-directory'),
  saveDiagnostics: () => ipcRenderer.invoke('save-diagnostics'),
  chooseDataDirectory: () => ipcRenderer.invoke('choose-data-directory'),
  copyArchive: (activate) => ipcRenderer.invoke('copy-archive', activate),
  migrateArchive: (activate) => ipcRenderer.invoke('migrate-archive', activate),
  moveArchive: () => ipcRenderer.invoke('move-archive'),
  restartApp: () => ipcRenderer.invoke('restart-app'),
  startDrag: (filePath) => ipcRenderer.send('start-drag', filePath),
  showInFolder: (filePath) => ipcRenderer.invoke('show-in-folder', filePath),
  saveMediaAs: (filePath, defaultName) => ipcRenderer.invoke('save-media-as', filePath, defaultName),
  bulkExportMedia: (filePaths) => ipcRenderer.invoke('bulk-export-media', filePaths),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  onBackendStatus: (callback) => {
    const handler = (_event, data) => callback(data)
    ipcRenderer.on('backend:status', handler)
    return () => ipcRenderer.removeListener('backend:status', handler)
  },
})
