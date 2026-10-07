import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Tray } from 'electron'
import path from 'node:path'
import { JobManager } from './jobs'
import { AutomationManager } from './automation'

// Also permits an isolated profile for packaged-app integration checks.
const profile = app.commandLine.getSwitchValue('user-data-dir')
if (profile && path.isAbsolute(profile)) app.setPath('userData', profile)

const manager = new JobManager()
const automation = new AutomationManager()
let window: BrowserWindow | null = null
let tray: Tray | null = null
let quitting = false

function createWindow(): void {
  window = new BrowserWindow({
    width: 1320, height: 880, minWidth: 1000, minHeight: 680,
    title: 'Tallnum 计算器', show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true, sandbox: true, nodeIntegration: false
    }
  })
  window.once('ready-to-show', () => { if (!app.commandLine.hasSwitch('smoke-test')) window?.show() })
  window.on('close', event => { if (!quitting) { event.preventDefault(); window?.hide() } })
  if (process.env.ELECTRON_RENDERER_URL) window.loadURL(process.env.ELECTRON_RENDERER_URL)
  else window.loadFile(path.join(__dirname, '../renderer/index.html'))
  manager.attach(window)
}

function registerIpc(): void {
  ipcMain.handle('automation:status', () => automation.snapshot())
  ipcMain.handle('automation:start', (_event, request) => automation.start(request))
  ipcMain.handle('automation:control', (_event, mode) => automation.control(mode))
  ipcMain.handle('automation:stop', () => automation.stop())
  ipcMain.handle('jobs:list', () => manager.jobs)
  ipcMain.handle('jobs:create', (_event, spec) => manager.create(spec))
  ipcMain.handle('jobs:pause', (_event, id) => manager.pause(id))
  ipcMain.handle('jobs:resume', (_event, id) => manager.resume(id))
  ipcMain.handle('jobs:updateBudget', (_event, id, budget) => manager.updateBudget(id, budget))
  ipcMain.handle('jobs:cancel', (_event, id) => manager.cancel(id))
  ipcMain.handle('jobs:logs', (_event, id) => manager.logs(id))
  ipcMain.handle('files:chooseDirectory', () => manager.chooseDirectory())
  ipcMain.handle('files:openDirectory', (_event, id) => manager.openDirectory(id))
  ipcMain.handle('files:openReplay', (_event, file) => manager.openReplay(file))
  ipcMain.handle('files:export', (_event, id, type) => manager.exportResult(id, type))
  ipcMain.handle('settings:get', () => manager.settings)
  ipcMain.handle('settings:set', (_event, settings) => manager.setSettings(settings))
}

app.whenReady().then(async () => {
  await manager.load()
  registerIpc()
  createWindow()
  const iconPath = app.isPackaged ? path.join(process.resourcesPath, 'native', 'tray.png') : path.resolve(__dirname, '../../assets/tray.png')
  const icon = nativeImage.createFromPath(iconPath)
  tray = new Tray(icon)
  tray.setToolTip('Tallnum 计算器')
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开 Tallnum', click: () => window?.show() },
    { label: '保存并退出', click: async () => { await automation.stop(); await manager.beforeQuit(); quitting = true; app.quit() } }
  ]))
  tray.on('double-click', () => window?.show())
  app.on('activate', () => { if (!window || window.isDestroyed()) createWindow(); else window.show() })
})

app.on('window-all-closed', () => { /* tray keeps queued computations alive */ })
app.on('before-quit', event => {
  if (quitting) return
  event.preventDefault()
  void dialog.showMessageBox({ type: 'question', message: '保存当前计算并退出？', buttons: ['保存并退出', '继续运行'], defaultId: 0, cancelId: 1 }).then(async answer => {
    if (answer.response === 0) { await automation.stop(); await manager.beforeQuit(); quitting = true; app.quit() }
  })
})
