import { app, BrowserWindow, session, ipcMain, dialog, shell, nativeImage } from 'electron'
import path from 'node:path'
import { spawn, ChildProcess } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { randomBytes } from 'node:crypto'
import { mkdir, readFile, rename, stat, writeFile, copyFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// The built directory structure
//
// ├─┬─┬ dist
// │ │ └── index.html
// │ │
// │ ├─┬ dist-electron
// │ │ ├── main.js
// │ │ └── preload.js
// │
process.env.DIST = path.join(__dirname, '../dist')
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, '../public')

let win: BrowserWindow | null
// 🚧 Use ['ENV_NAME'] avoid vite:define plugin - Vite@2.x
const VITE_DEV_SERVER_URL = process.env['VITE_DEV_SERVER_URL']

let pythonProcess: ChildProcess | null = null
let isQuitting = false
let backendRestartAttempts = 0
const MAX_BACKEND_RESTARTS = 3
const apiToken = randomBytes(32).toString('hex')
const projectRoot = path.join(__dirname, '../../')
let selectedDataDir: string | null = null
const dataDir = () => selectedDataDir || (app.isPackaged ? app.getPath('userData') : path.join(projectRoot, 'archive'))
const preferencesFile = () => path.join(app.getPath('userData'), 'saved-archive-settings.json')

async function loadDataDirectory() {
  try {
    const saved = JSON.parse(await readFile(preferencesFile(), 'utf8'))
    if (typeof saved.dataDir === 'string' && path.isAbsolute(saved.dataDir)) selectedDataDir = path.resolve(saved.dataDir)
  } catch { /* first run or invalid preference */ }
}

async function saveDataDirectory(selected: string) {
  await mkdir(path.dirname(preferencesFile()), { recursive: true })
  const temporary = preferencesFile() + '.tmp'
  await writeFile(temporary, JSON.stringify({ dataDir: selected }), { mode: 0o600 })
  await rename(temporary, preferencesFile())
}

async function backendJson(url: string, init: RequestInit = {}) {
  const response = await fetch(`http://127.0.0.1:8000${url}`, {
    ...init, headers: { 'Content-Type': 'application/json', 'X-App-Token': apiToken, ...init.headers }
  })
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || 'Backend request failed')
  return body
}

function startPythonBackend() {
  // In development, the working directory is the Vite project root.
  // We need to point to the python source root `../src` or run from `../`.
  const rootDir = app.isPackaged ? path.join(process.resourcesPath, 'backend') : projectRoot
  
  console.log("Starting Python API from:", rootDir)
  
  pythonProcess = spawn(app.isPackaged ? path.join(rootDir, 'archive-api.exe') : 'python', app.isPackaged ? [] : ['-m', 'src.api'], {
    cwd: app.isPackaged ? dataDir() : rootDir,
    env: { ...process.env, PYTHONPATH: rootDir, APP_API_TOKEN: apiToken,
      ARCHIVE_DATA_DIR: dataDir(), INSTAGRAM_SESSION_FILE: path.join(dataDir(), 'session.enc') }
  })
  
  pythonProcess.stdout?.on('data', (data) => {
    console.log(`Python: ${data}`)
  })
  
  pythonProcess.stderr?.on('data', (data) => {
    console.error(`Python Error: ${data}`)
  })
  
  pythonProcess.on('close', (code) => {
    console.log(`Python process exited with code ${code}`)
    pythonProcess = null
    if (!isQuitting) {
      win?.webContents.send('backend:status', { status: 'crashed', code })
      if (backendRestartAttempts < MAX_BACKEND_RESTARTS) {
        backendRestartAttempts++
        console.log(`Attempting backend auto-restart (${backendRestartAttempts}/${MAX_BACKEND_RESTARTS})...`)
        setTimeout(async () => {
          if (!isQuitting && !pythonProcess) {
            startPythonBackend()
            await waitForBackend()
            win?.webContents.send('backend:status', { status: 'running' })
          }
        }, 1500)
      } else {
        win?.webContents.send('backend:status', { status: 'failed', code })
      }
    }
  })
  pythonProcess.on('error', (error) => {
    console.error('Python backend failed to start:', error)
    if (!isQuitting) {
      win?.webContents.send('backend:status', { status: 'error', error: String(error) })
    }
  })
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 80; attempt++) {
    if (pythonProcess && pythonProcess.exitCode !== null) return
    try {
      const response = await fetch('http://127.0.0.1:8000/stats', {
        headers: { 'X-App-Token': apiToken }, signal: AbortSignal.timeout(1000)
      })
      if (response.ok) return
    } catch { /* backend is still starting */ }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    webPreferences: {
      preload: path.join(app.getAppPath(), 'electron', 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#1a1a1a',
      symbolColor: '#ffffff',
      height: 30
    }
  })
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  win.webContents.on('will-navigate', (event, url) => {
    const current = win?.webContents.getURL()
    if (current && url.split('#')[0] !== current.split('#')[0]) event.preventDefault()
  })

  // Test active push message to Renderer-process.
  win.webContents.on('did-finish-load', () => {
    win?.webContents.send('main-process-message', (new Date).toLocaleString())
  })

  if (VITE_DEV_SERVER_URL) {
    const url = VITE_DEV_SERVER_URL.replace('localhost', '127.0.0.1');
    const loadWithRetry = (retries = 10, delay = 1000) => {
      win?.loadURL(url).catch((err) => {
        console.log(`Retrying URL load... (${retries} retries left)`);
        if (retries > 0) {
          setTimeout(() => loadWithRetry(retries - 1, delay), delay);
        } else {
          console.error("Failed to load URL:", err);
        }
      });
    };
    loadWithRetry();
  } else {
    win.loadFile(path.join(process.env.DIST, 'index.html'))
  }
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
    win = null
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})

const hasInstanceLock = app.requestSingleInstanceLock()
if (!hasInstanceLock) app.quit()
else app.on('second-instance', () => {
  if (win) { win.show(); win.focus() }
})

if (hasInstanceLock) app.whenReady().then(async () => {
  await loadDataDirectory()
  ipcMain.handle('choose-data-directory', async () => {
    const choice = await dialog.showOpenDialog({ defaultPath: dataDir(), properties: ['openDirectory', 'createDirectory'] })
    if (choice.canceled || !choice.filePaths[0]) return null
    const selected = path.resolve(choice.filePaths[0])
    try { await stat(path.join(selected, 'database', 'library.db')) }
    catch { throw new Error('The selected folder does not contain a Saved Archive database') }
    const jobs = await backendJson('/jobs') as { status: string }[]
    if (jobs.some(job => ['QUEUED', 'RUNNING'].includes(job.status))) throw new Error('Finish active jobs before changing storage')
    await saveDataDirectory(selected)
    return selected
  })
  ipcMain.handle('copy-archive', async (_event, activate: boolean) => {
    const choice = await dialog.showOpenDialog({ defaultPath: path.dirname(dataDir()), properties: ['openDirectory', 'createDirectory'] })
    if (choice.canceled || !choice.filePaths[0]) return null
    const job = await backendJson('/storage/copy', { method: 'POST', body: JSON.stringify({
      destination_parent: path.resolve(choice.filePaths[0]), activate: !!activate
    }) }) as { job_id: string }
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      const result = await backendJson(`/jobs/${job.job_id}`) as { status: string; message?: string; details?: string }
      if (result.status === 'COMPLETED') {
        const copied = JSON.parse(result.details || '{}') as { destination: string; files_verified: number }
        if (activate) await saveDataDirectory(copied.destination)
        return copied
      }
      if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(result.status)) throw new Error(result.message || `Archive copy ${result.status}`)
    }
  })
  ipcMain.handle('migrate-archive', async (_event, activate: boolean) => {
    const choice = await dialog.showOpenDialog({
      title: 'Select External Archive to Migrate',
      defaultPath: path.dirname(dataDir()),
      properties: ['openDirectory']
    })
    if (choice.canceled || !choice.filePaths[0]) return null
    const sourceDir = path.resolve(choice.filePaths[0])
    try { await stat(path.join(sourceDir, 'database', 'library.db')) }
    catch { throw new Error('The selected folder does not contain a Saved Archive database (database/library.db)') }

    const job = await backendJson('/storage/migrate', { method: 'POST', body: JSON.stringify({
      source_directory: sourceDir,
      destination_directory: dataDir(),
      activate: !!activate
    }) }) as { job_id: string }
    
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      const result = await backendJson(`/jobs/${job.job_id}`) as { status: string; message?: string; details?: string }
      if (result.status === 'COMPLETED') {
        const migrated = JSON.parse(result.details || '{}') as { destination: string; migrated_files: number; rebased_paths: number }
        return migrated
      }
      if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(result.status)) throw new Error(result.message || `Archive migration ${result.status}`)
    }
  })
  ipcMain.handle('move-archive', async () => {
    const choice = await dialog.showOpenDialog({
      title: 'Select Destination Folder for Archive Migration',
      defaultPath: path.dirname(dataDir()),
      properties: ['openDirectory', 'createDirectory']
    })
    if (choice.canceled || !choice.filePaths[0]) return null
    const destDir = path.resolve(choice.filePaths[0])
    try { await stat(path.join(destDir, 'database', 'library.db')); throw new Error('Destination folder already contains an archive! Choose an empty folder.'); }
    catch (e: any) { if (e.message.includes('already contains')) throw e; }

    const job = await backendJson('/storage/migrate', { method: 'POST', body: JSON.stringify({
      source_directory: dataDir(),
      destination_directory: destDir,
      activate: true
    }) }) as { job_id: string }
    
    for (;;) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      const result = await backendJson(`/jobs/${job.job_id}`) as { status: string; message?: string; details?: string }
      if (result.status === 'COMPLETED') {
        const migrated = JSON.parse(result.details || '{}') as { destination: string; migrated_files: number; rebased_paths: number }
        await saveDataDirectory(migrated.destination)
        return migrated
      }
      if (['FAILED', 'CANCELLED', 'INTERRUPTED'].includes(result.status)) throw new Error(result.message || `Archive migration ${result.status}`)
    }
  })
  ipcMain.handle('restart-app', () => {
    setImmediate(() => { app.relaunch(); app.quit() })
    return true
  })
  ipcMain.handle('open-instagram-login', async () => {
    return new Promise((resolve) => {
      const loginWin = new BrowserWindow({
        width: 520,
        height: 720,
        title: 'ورود رسمی به اینستاگرام | Instagram Official Login',
        parent: win || undefined,
        modal: true,
        autoHideMenuBar: true,
        webPreferences: {
          nodeIntegration: false,
          contextIsolation: true,
        }
      })

      loginWin.webContents.setUserAgent(
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
      )

      loginWin.loadURL('https://www.instagram.com/accounts/login/')

      let sessionCaptured = false

      const checkCookies = async () => {
        if (sessionCaptured || loginWin.isDestroyed()) return
        try {
          const cookies = await loginWin.webContents.session.cookies.get({ domain: '.instagram.com' })
          const sessionidCookie = cookies.find(c => c.name === 'sessionid')
          const dsUserIdCookie = cookies.find(c => c.name === 'ds_user_id')
          const csrfCookie = cookies.find(c => c.name === 'csrftoken')

          if (sessionidCookie && sessionidCookie.value && sessionidCookie.value.length > 5 && dsUserIdCookie && dsUserIdCookie.value) {
            sessionCaptured = true

            try {
              const res = await backendJson('/settings/session/cookie', {
                method: 'POST',
                body: JSON.stringify({
                  sessionid: sessionidCookie.value,
                  ds_user_id: dsUserIdCookie.value,
                  csrftoken: csrfCookie ? csrfCookie.value : ''
                })
              })
              loginWin.close()
              resolve({ success: true, username: res.username || dsUserIdCookie.value })
            } catch (err: any) {
              loginWin.close()
              resolve({ success: false, error: err.message || 'خطا در ثبت نشست' })
            }
          }
        } catch {
          // ignore
        }
      }

      loginWin.webContents.on('did-navigate', checkCookies)
      loginWin.webContents.on('did-finish-load', checkCookies)
      loginWin.webContents.on('did-navigate-in-page', checkCookies)
      const interval = setInterval(checkCookies, 1500)

      loginWin.on('closed', () => {
        clearInterval(interval)
        if (!sessionCaptured) {
          resolve({ success: false, error: 'پنجره ورود توسط کاربر بسته شد' })
        }
      })
    })
  })
  ipcMain.handle('import-session', async () => {
    const choice = await dialog.showOpenDialog({ properties: ['openFile'], filters: [{ name: 'Instagram session', extensions: ['enc', 'json'] }] })
    if (choice.canceled || !choice.filePaths[0]) return false
    if ((await stat(choice.filePaths[0])).size > 2_000_000) throw new Error('Session file is too large')
    const contents = await readFile(choice.filePaths[0])
    const response = await fetch('http://127.0.0.1:8000/settings/session', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-App-Token': apiToken },
      body: JSON.stringify({ contents_b64: contents.toString('base64') })
    })
    if (!response.ok) throw new Error((await response.json()).detail || 'Could not import session')
    return true
  })
  ipcMain.handle('import-media', async () => {
    const choice = await dialog.showOpenDialog({ properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'Images and videos', extensions: ['jpg', 'jpeg', 'png', 'webp', 'mp4', 'mov'] }] })
    if (choice.canceled) return 0
    for (const filePath of choice.filePaths) {
      const response = await fetch('http://127.0.0.1:8000/import/local', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-App-Token': apiToken },
        body: JSON.stringify({ path: filePath })
      })
      if (!response.ok) throw new Error(`Could not import ${path.basename(filePath)}: ${(await response.json()).detail}`)
    }
    return choice.filePaths.length
  })
  ipcMain.handle('choose-export-directory', async () => {
    const choice = await dialog.showOpenDialog({ properties: ['openDirectory'] })
    return choice.canceled ? null : choice.filePaths[0]
  })
  ipcMain.handle('save-diagnostics', async () => {
    const result = await dialog.showSaveDialog({ defaultPath: 'archive-diagnostics.json',
      filters: [{ name: 'JSON', extensions: ['json'] }] })
    if (result.canceled || !result.filePath) return null
    const report = await backendJson('/support/diagnostics')
    await writeFile(result.filePath, JSON.stringify(report, null, 2), { mode: 0o600 })
    return result.filePath
  })
  ipcMain.on('start-drag', (event, filePath: string) => {
    try {
      if (!filePath) return
      const resolvedPath = path.isAbsolute(filePath) ? filePath : path.resolve(filePath)
      if (existsSync(resolvedPath)) {
        let dragIcon: string | Electron.NativeImage | null = null

        // 1. If it's an image, use the file itself
        const ext = path.extname(resolvedPath).toLowerCase()
        if (['.jpg', '.jpeg', '.png', '.webp'].includes(ext)) {
          dragIcon = resolvedPath
        } else if (['.mp4', '.mov'].includes(ext)) {
          // If it's a video, check for an adjacent poster image
          const parsed = path.parse(resolvedPath)
          const possiblePoster = path.join(parsed.dir, parsed.name + '.poster.jpg')
          if (existsSync(possiblePoster)) {
            dragIcon = possiblePoster
          }
        }

        // 2. If no poster/image, try bundled app icon
        if (!dragIcon) {
          const heroIcon = path.join(projectRoot, 'desktop/src/assets/hero.png')
          if (existsSync(heroIcon)) {
            dragIcon = heroIcon
          }
        }

        // 3. Fallback to valid 1x1 transparent NativeImage so Windows Shell drag always succeeds
        if (!dragIcon) {
          const transparentPng = Buffer.from(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
            'base64'
          )
          dragIcon = nativeImage.createFromBuffer(transparentPng)
        }

        event.sender.startDrag({
          file: resolvedPath,
          icon: dragIcon
        })
      }
    } catch (err) {
      console.error('Failed to start native drag:', err)
    }
  })
  ipcMain.handle('import-file-path', async (_event, filePath: string) => {
    try {
      if (!filePath) return false
      const resolved = path.isAbsolute(filePath) ? filePath : path.resolve(filePath)
      if (!existsSync(resolved)) throw new Error('File does not exist on disk')
      const response = await fetch('http://127.0.0.1:8000/import/local', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-App-Token': apiToken },
        body: JSON.stringify({ path: resolved })
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        throw new Error(err.detail || 'Could not import local file')
      }
      return true
    } catch (err: any) {
      console.error('Failed to import file path:', err)
      throw new Error(err.message || 'Import failed')
    }
  })
  ipcMain.handle('show-in-folder', async (_event, filePath: string) => {
    try {
      if (!filePath) return false
      const resolvedPath = path.isAbsolute(filePath) ? filePath : path.resolve(filePath)
      if (existsSync(resolvedPath)) {
        shell.showItemInFolder(resolvedPath)
        return true
      }
      return false
    } catch (err) {
      console.error('Failed to show in folder:', err)
      return false
    }
  })
  ipcMain.handle('save-media-as', async (_event, filePath: string, defaultName?: string) => {
    if (!filePath) throw new Error('No file specified')
    const resolvedPath = path.isAbsolute(filePath) ? filePath : path.resolve(filePath)
    if (!existsSync(resolvedPath)) throw new Error('File not found on disk')
    const ext = path.extname(resolvedPath).replace('.', '')
    const suggested = defaultName || path.basename(resolvedPath)
    const result = await dialog.showSaveDialog({
      defaultPath: suggested,
      filters: [{ name: 'Media file', extensions: [ext || '*'] }]
    })
    if (result.canceled || !result.filePath) return null
    await copyFile(resolvedPath, result.filePath)
    return result.filePath
  })
  ipcMain.handle('bulk-export-media', async (_event, filePaths: string[]) => {
    if (!Array.isArray(filePaths) || filePaths.length === 0) return null
    const choice = await dialog.showOpenDialog({
      title: 'Select Destination Folder for Export',
      properties: ['openDirectory', 'createDirectory']
    })
    if (choice.canceled || !choice.filePaths[0]) return null
    const targetDir = choice.filePaths[0]
    let exported = 0
    for (const fp of filePaths) {
      if (!fp) continue
      const resolved = path.isAbsolute(fp) ? fp : path.resolve(fp)
      if (existsSync(resolved)) {
        const dest = path.join(targetDir, path.basename(resolved))
        await copyFile(resolved, dest)
        exported++
      }
    }
    return { destination: targetDir, count: exported }
  })
  ipcMain.handle('restart-backend', async () => {
    if (pythonProcess) {
      try {
        pythonProcess.kill()
      } catch {}
      pythonProcess = null
    }
    backendRestartAttempts = 0
    startPythonBackend()
    await waitForBackend()
    win?.webContents.send('backend:status', { status: 'running' })
    return true
  })
  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: ['http://127.0.0.1:8000/*'] },
    (details, callback) => callback({ requestHeaders: { ...details.requestHeaders, 'X-App-Token': apiToken } })
  )
  await mkdir(dataDir(), { recursive: true })
  createWindow()
  startPythonBackend()
  waitForBackend().then(() => {
    win?.webContents.send('backend:status', { status: 'running' })
  })
})

app.on('before-quit', () => {
  isQuitting = true
  if (pythonProcess) {
    console.log("Killing python backend...")
    pythonProcess.kill()
  }
})
