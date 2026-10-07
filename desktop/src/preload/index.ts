import { contextBridge, ipcRenderer } from 'electron'
import type { DesktopApi } from '../shared'

const api: DesktopApi = {
  automationStatus: () => ipcRenderer.invoke('automation:status'),
  automationStart: request => ipcRenderer.invoke('automation:start', request),
  automationControl: mode => ipcRenderer.invoke('automation:control', mode),
  automationStop: () => ipcRenderer.invoke('automation:stop'),
  list: () => ipcRenderer.invoke('jobs:list'),
  create: spec => ipcRenderer.invoke('jobs:create', spec),
  pause: id => ipcRenderer.invoke('jobs:pause', id),
  resume: id => ipcRenderer.invoke('jobs:resume', id),
  updateBudget: (id, budget) => ipcRenderer.invoke('jobs:updateBudget', id, budget),
  cancel: id => ipcRenderer.invoke('jobs:cancel', id),
  chooseDirectory: () => ipcRenderer.invoke('files:chooseDirectory'),
  openDirectory: id => ipcRenderer.invoke('files:openDirectory', id),
  openReplay: path => ipcRenderer.invoke('files:openReplay', path),
  logs: id => ipcRenderer.invoke('jobs:logs', id),
  exportResult: (id, type) => ipcRenderer.invoke('files:export', id, type),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: settings => ipcRenderer.invoke('settings:set', settings),
  onJobs: callback => {
    const listener = (_event: Electron.IpcRendererEvent, jobs: Parameters<typeof callback>[0]): void => callback(jobs)
    ipcRenderer.on('jobs:changed', listener)
    return () => ipcRenderer.removeListener('jobs:changed', listener)
  }
}

contextBridge.exposeInMainWorld('tallnum', api)
