import { app } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import type { IntegerPlannerRequest, IntegerPlannerResult, IntegerPlannerStatus } from '../shared'

export class IntegerPlannerManager {
  private child: ChildProcessWithoutNullStreams | null = null
  private state: IntegerPlannerStatus = { busy: false, directory: '', message: '', error: null, result: null }

  async snapshot(): Promise<IntegerPlannerStatus> {
    if (!this.state.busy && this.state.directory && !this.state.error && !this.state.result) {
      try {
        const result: IntegerPlannerResult = JSON.parse(await readFile(path.join(this.state.directory, 'integer-result.json'), 'utf8'))
        if (result.scope?.minimumTemplateTarget !== 24 || result.steps?.some(s => s.kind === 'leaf' && (s.target ?? 0) < 24)) {
          this.state.error = '旧规划结果未按定式目标至少 24 核对，请重新规划'
        } else this.state.result = result
      }
      catch { /* No completed result yet. */ }
    }
    return this.state
  }

  async start(request: IntegerPlannerRequest): Promise<void> {
    if (this.state.busy) throw new Error('路线规划正在运行')
    const integer = (value: number, low: number, high: number): boolean => Number.isInteger(value) && value >= low && value <= high
    if (!integer(request.target, 2, 65535) || (request.target % 2 && request.target !== 15)) throw new Error('目标须为偶数或 15，范围 2–65535')
    if (![7, 10].includes(request.cells)) throw new Error('请选择七格或十格')
    if (!integer(request.maximum, request.target, 65535) || !integer(request.edgeDepth, 0, 8)) throw new Error('搜索范围无效')
    if (!integer(request.nodeLimit, 1, 1000000) || !integer(request.focusNodes, 1, 1000000)) throw new Error('搜索预算无效')
    if (request.ceiling !== null && !integer(request.ceiling, 24, request.maximum)) throw new Error('定式上限须至少为 24')
    if (request.directory && !path.isAbsolute(request.directory)) throw new Error('保存目录须为绝对路径')
    const directory = request.directory || path.join(app.getPath('userData'), 'integer-routes', `${request.target}-${request.cells}`)
    this.state = { busy: true, directory, message: '准备计算', error: null, result: null }
    try {
      await mkdir(directory, { recursive: true })
      const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../../..')
      const args = ['-u', '-m', 'automation.integer_planner', String(request.target), '--cells', String(request.cells),
        '--directory', directory, '--maximum', String(request.maximum), '--edge-depth', String(request.edgeDepth),
        '--node-limit', String(request.nodeLimit), '--focus-nodes', String(request.focusNodes)]
      if (request.ceiling !== null) args.push('--ceiling', String(request.ceiling))
      const child = spawn('python', args, { cwd: root, windowsHide: true, shell: false, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
      this.child = child
      let pending = '', diagnostics = ''
      child.stdout.on('data', data => {
        pending += data.toString('utf8')
        const lines = pending.split('\n'); pending = lines.pop() || ''
        for (const line of lines) {
          try {
            const item = JSON.parse(line)
            if (item.event === 'error') this.state.error = String(item.message)
            if (item.message) this.state.message = String(item.message)
            else if (item.relaxedStates) this.state.message = `核对下界：已计算 ${item.relaxedStates} 个状态`
            else if (item.task && item.after !== undefined) this.state.message = `优化目标 ${item.task[2]}：最高阶调用 ${item.before} → ${item.after}`
          } catch { /* Only structured progress crosses the bridge. */ }
        }
      })
      child.stderr.on('data', data => { diagnostics = (diagnostics + String(data)).slice(-4000) })
      child.on('error', error => { this.state.error = `无法启动 Python：${error.message}` })
      child.on('close', code => {
        if (this.child !== child) return
        this.child = null; this.state.busy = false
        if (code !== 0 && !this.state.error) this.state.error = diagnostics || `规划进程退出：${code}`
      })
    } catch (error) { this.state.busy = false; this.state.error = String(error); throw error }
  }

  async stop(): Promise<void> {
    const child = this.child
    if (!child) return
    this.state.error = '已停止计算，已完成的搜索缓存保留'; this.state.message = '已停止'
    child.kill()
    await new Promise<void>(resolve => { if (child.exitCode !== null) resolve(); else child.once('close', () => resolve()) })
  }
}
