import { app } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import type { AutomationRequest, AutomationStatus } from '../shared'

export class AutomationManager {
  private plannerVersion: 1 | 2 = 1
  private child: ChildProcessWithoutNullStreams | null = null
  private status: AutomationStatus = { busy: false, command: '', directory: '', events: [], error: null, plan: null, validation: null }

  async snapshot(): Promise<AutomationStatus> {
    for (const key of ['plan', 'validation'] as const) {
      if (!this.status.directory) continue
      try { this.status[key] = JSON.parse(await readFile(path.join(this.status.directory, `${this.plannerVersion === 2 ? 'route-' : ''}${key}.json`), 'utf8')) }
      catch { this.status[key] = null }
    }
    return this.status
  }

  async start(request: AutomationRequest): Promise<void> {
    if (this.child) throw new Error('自动化任务正在运行')
    if (!['plan', 'prepare', 'validate', 'play'].includes(request.command)) throw new Error('未知自动化任务')
    if (!path.isAbsolute(request.directory)) throw new Error('请选择绝对保存目录')
    if (!Number.isInteger(request.target) || request.target < 2 || request.target > 65535) throw new Error('目标必须为 2–65535 的整数')
    for (const n of [request.rounds, request.attempts]) if (!Number.isInteger(n) || n < 1 || n > 1000000) throw new Error('计算预算无效')
    await mkdir(request.directory, { recursive: true })
    this.plannerVersion = request.plannerVersion ?? 1
    if (![1, 2].includes(this.plannerVersion)) throw new Error('未知规划器版本')
    const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../../..')
    const module = path.join(root, 'automation', '__main__.py')
    if (!existsSync(module)) throw new Error('缺少 automation 运行模块')
    this.status = { busy: true, command: request.command, directory: request.directory, events: [], error: null, plan: null, validation: null }
    if (request.command === 'play') await this.control('paused')
    const args = ['-u', '-m', 'automation', ...(this.plannerVersion === 2 ? ['route'] : []), request.command, '--directory', request.directory,
      '--target', String(request.target), '--rounds', String(request.rounds), '--attempts', String(request.attempts)]
    if (this.plannerVersion === 2 && ['plan', 'prepare'].includes(request.command)) {
      const cap = Math.min(128, Math.max(48, 2 * request.target))
      args.push('--cells', '7', '--max-leaf-target', String(cap), '--local-template-bounds', '--node-limit', '10000', '--leaf-targets', ...[...Array.from({ length: Math.floor(cap / 2) }, (_, i) => 2 * (i + 1)), 15].sort((a, b) => a - b).map(String))
    }
    if (this.plannerVersion === 2 && request.command === 'play' && existsSync(path.join(request.directory, 'actions.jsonl'))) args.push('--resume-current-game')
    const child = spawn(process.env.TALLNUM_PYTHON || 'python', args,
    { cwd: root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] })
    this.child = child
    let pending = ''
    child.stdout.on('data', data => {
      pending += data.toString('utf8')
      const lines = pending.split('\n'); pending = lines.pop() || ''
      for (const line of lines) {
        try {
          const item = JSON.parse(line)
          this.status.events.push(item)
          this.status.events = this.status.events.slice(-100)
          if (item.event === 'error') this.status.error = String(item.message)
          if (item.event === 'paused') this.status.error = `已暂停：${String(item.message)}。窗口保持打开，可点击“连续运行”恢复。`
          if (item.event === 'action') this.status.error = null
        } catch { /* native non-JSON diagnostics belong in stderr */ }
      }
    })
    child.stderr.on('data', data => { this.status.error = String(data).slice(-4000) })
    child.on('error', error => { this.status.error = `无法启动 Python 自动化：${error.message}`; this.status.busy = false; this.child = null })
    child.on('exit', code => {
      if (code && !this.status.error) this.status.error = `自动化进程退出码 ${code}`
      this.status.busy = false; this.child = null
    })
  }

  async control(mode: 'run' | 'paused' | 'step' | 'stop'): Promise<void> {
    if (!['run', 'paused', 'step', 'stop'].includes(mode)) throw new Error('未知控制模式')
    if (!this.status.directory) throw new Error('尚无自动化任务')
    const file = path.join(this.status.directory, 'control.json')
    const temp = `${file}.tmp`
    await writeFile(temp, JSON.stringify({ mode, token: Date.now() }), 'utf8')
    await rename(temp, file)
  }

  async stop(): Promise<void> {
    const child = this.child
    if (!child) return
    if (this.status.command === 'play') {
      await this.control('stop')
      const closed = await new Promise<boolean>(resolve => {
        const timer = setTimeout(() => { child.removeListener('exit', done); resolve(false) }, 25000)
        const done = (): void => { clearTimeout(timer); resolve(true) }
        child.once('exit', done)
        if (child.exitCode !== null) done()
      })
      if (closed || this.child !== child) return
    }
    // Kill this owned process tree only, including its native solver child.
    if (process.platform === 'win32' && child.pid) {
      await new Promise<void>((resolve, reject) => {
        const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
        killer.on('error', reject); killer.on('exit', () => resolve())
      })
    } else child.kill('SIGTERM')
  }
}
