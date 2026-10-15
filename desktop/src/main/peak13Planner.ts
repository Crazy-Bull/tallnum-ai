import { app } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { createHash } from 'node:crypto'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import type { Peak13Status } from '../shared'

const readJson = async (file: string): Promise<any> => JSON.parse(await readFile(file, 'utf8'))
const sha256 = (bytes: Buffer): string => createHash('sha256').update(bytes).digest('hex')
const validTemplate = (key: unknown): boolean => {
  if (typeof key !== 'string') return false
  const match = /^(\d+):(\d+):(single|match|extend)$/.exec(key)
  if (!match) return false
  const cells = Number(match[1]), target = Number(match[2])
  return cells >= 5 && cells <= 255 && target >= 24 && target <= 65535
}

export class Peak13PlannerManager {
  private child: ChildProcessWithoutNullStreams | null = null
  private state: Peak13Status = { busy: false, directory: '', message: '', error: null, route: null, report: null, validation: null }

  snapshot(): Peak13Status { return this.state }

  async templates(): Promise<string[]> {
    const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../../..')
    const assets = app.isPackaged ? path.join(root, 'peak13-assets') : path.join(root, 'desktop', 'peak13-assets')
    const catalog = await readJson(path.join(assets, 'probability-catalog.json'))
    return [...new Set<string>(catalog.policies.filter((item: any) =>
      (item.cells ?? 5) >= 5 && (item.cells ?? 5) <= 255 && item.target >= 24 && item.target <= 65535 &&
      ['single', 'match', 'extend'].includes(item.exit) && item.pendingValue &&
      item.disableStaticFallback
    ).map((item: any) => `${item.cells ?? 5}:${item.target}:${item.exit}`))].sort((a, b) => {
      const [av, bv] = [Number(a.split(':')[1]), Number(b.split(':')[1])]
      return Number(a.split(':')[0]) - Number(b.split(':')[0]) || av - bv || a.localeCompare(b)
    })
  }

  async start(request: { target: number; cells: number; directory: string; nodeLimit: number; allowedTemplates?: string[] | null }): Promise<void> {
    if (this.child) throw new Error('10240 路线规划正在运行')
    if (!Number.isInteger(request.target) || request.target < 2 || request.target > 65535) throw new Error('目标须为 2–65535 的整数')
    if (!Number.isInteger(request.cells) || request.cells < 1 || request.cells > 255) throw new Error('塔容量须为 1–255 格整数')
    if (!Number.isInteger(request.nodeLimit) || request.nodeLimit < 1 || request.nodeLimit > 1000000) throw new Error('搜索预算须为 1–1000000')
    if (request.allowedTemplates != null && (!Array.isArray(request.allowedTemplates) || request.allowedTemplates.length === 0 ||
      request.allowedTemplates.some(key => !validTemplate(key))))
      throw new Error('请至少选择一种有效定式（至少五格，目标至少 24）')
    const requestedDirectory = request.directory
    if (requestedDirectory && !path.isAbsolute(requestedDirectory)) throw new Error('保存目录须为绝对路径')
    const root = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../../..')
    const assets = app.isPackaged ? path.join(root, 'peak13-assets') : path.join(root, 'desktop', 'peak13-assets')
    const directory = requestedDirectory || path.join(app.getPath('userData'), 'probability-routes', `${request.cells}-${request.target}`)
    await mkdir(directory, { recursive: true })
    this.state = { busy: true, directory, message: '搜索合法的合成路线…', error: null, route: null, report: null, validation: null }
    const certified = false
    const args = ['-u', '-m', 'automation.probability_route_planner', String(request.target),
        '--cells', String(request.cells), '--catalog', path.join(assets, 'probability-catalog.json'),
        '--out', directory, '--node-limit', String(request.nodeLimit),
        ...(request.allowedTemplates || []).flatMap(key => ['--allow-template', key])]
    const child = spawn('python', args, { cwd: root, windowsHide: true, shell: false, env: { ...process.env, PYTHONIOENCODING: 'utf-8' } })
    this.child = child
    let diagnostics = ''
    child.stdout.on('data', () => { /* Drain DP progress; the result is read from its atomic report. */ })
    child.stderr.on('data', bytes => { diagnostics = (diagnostics + String(bytes)).slice(-4000) })
    child.on('error', error => { this.state.error = `无法启动 Python：${error.message}` })
    child.on('close', code => {
      if (this.child !== child) return
      this.child = null
      void this.finish(code, diagnostics, assets, directory, certified)
    })
  }

  private async finish(code: number | null, diagnostics: string, assets: string, directory: string, certified: boolean): Promise<void> {
    if (code !== 0) {
      this.state.error ||= diagnostics || `路线规划进程退出：${code}`
      this.state.message = '规划未完成'
      this.state.busy = false
      return
    }
    try {
      const report = await readJson(path.join(directory, 'planning-report.json'))
      if (report.status && report.status !== 'candidate') {
        this.state.report = report
        if (report.status === 'missing-probability-tables')
          this.state.route = await readJson(path.join(directory, 'structural-route.json'))
        this.state.message = report.reason || report.status
        this.state.busy = false
        return
      }
      const routeBytes = await readFile(path.join(directory, 'route.json'))
      const route = JSON.parse(routeBytes.toString('utf8'))
      if (certified && (route.target !== 10240 || route.cells !== 10 || report.five64Calls !== 13))
        throw new Error('10240 规划结果没有满足五格 64 主路线 13 次的约束')
      this.state.route = route
      this.state.report = report
      if (certified) {
        const config = await readJson(path.join(assets, 'validation-configuration.json'))
        const summary = await readJson(path.join(assets, 'validation-summary.json'))
        const verified = sha256(routeBytes) === config.routeSha256 && summary.complete === true && summary.acceptancePassed === true
          && config.probabilityOnly === true && config.forcedDraws === false
        this.state.validation = verified ? {
          attempts: summary.attempts, successes: summary.successes, successRate: summary.successRate,
          maximumSuccessfulFive64Calls: summary.successfulGameFive64Calls.maximum,
          originalEngineVerified: summary.originalEngineCheck?.games === 100 && summary.originalEngineCheck?.seededRngParity === true
        } : null
        this.state.message = verified ? '路线已生成；与 100 局概率表实测版本一致' : '路线已生成；此版本尚无匹配的 100 局认证'
      } else {
        this.state.validation = null
        this.state.message = '已生成概率表定式候选路线；尚未进行整局随机验证'
      }
      const registry = await readJson(path.join(assets, 'probability-validations.json')).catch(() => null)
      const measured = registry?.validations?.find((entry: any) => entry.routeSha256 === sha256(routeBytes)
        && entry.target === route.target && entry.cells === route.cells && entry.attempts === 100
        && entry.originalEngineVerified && entry.probabilityOnly && entry.forcedDraws === false)
      if (measured && registry.catalogSha256 === sha256(await readFile(path.join(assets, 'probability-catalog.json')))) {
        let sourcesMatch = true
        for (const name of ['game.py', 'route_runtime.py', 'entry_recovery.py', 'entry_bridge.py', 'library.py', 'no80_full_game.py']) {
          const bytes = await readFile(path.join(rootForRuntime(), 'automation', name)).catch(() => null)
          if (!bytes || sha256(bytes) !== measured.sources?.[name]) sourcesMatch = false
        }
        if (sourcesMatch) {
          this.state.validation = {
            attempts: measured.attempts, successes: measured.successes, successRate: measured.successRate,
            maximumSuccessfulFive64Calls: measured.maximumSuccessfulFive64Calls,
            maximumSuccessfulHighestFiveCellCalls: measured.maximumSuccessfulHighestFiveCellCalls,
            originalEngineVerified: true
          }
          this.state.message = '该路线已有匹配的 100 局概率表实测记录'
        }
      }
    } catch (error) { this.state.error = String(error); this.state.message = '读取规划结果失败' }
    this.state.busy = false
  }

  async stop(): Promise<void> {
    const child = this.child
    if (!child) return
    this.state.message = '已停止'
    this.state.error = '用户停止了路线规划'
    child.kill()
    await new Promise<void>(resolve => { if (child.exitCode !== null) resolve(); else child.once('close', () => resolve()) })
  }
}

const rootForRuntime = (): string => app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '../../..')
