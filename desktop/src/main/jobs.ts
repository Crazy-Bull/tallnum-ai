import { app, BrowserWindow, dialog, shell } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID, createHash } from 'node:crypto'
import { createReadStream, existsSync } from 'node:fs'
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import type { Job, JobSpec, Stage, StageResult } from '../shared'
import { normalizeRules, validateExitRules, generatorRuleArgs, assertModelRules } from '../calculator-rules'
import { readPendingProbabilities } from './pendingProbabilities'

const LEGACY_CORE_VERSION = 'tallnum-v4-desktop-1'
const CORE_VERSION = 'tallnum-v4-desktop-5-pending-probabilities'
const indexPath = (): string => path.join(app.getPath('userData'), 'jobs.json')
const settingsPath = (): string => path.join(app.getPath('userData'), 'settings.json')
const nativeDir = (): string => app.isPackaged ? path.join(process.resourcesPath, 'native') : path.resolve(__dirname, '../../native')
const executable = (name: string): string => path.join(nativeDir(), `${name}.exe`)
// Native C++ uses narrow file APIs; keep command arguments ASCII and let the
// Unicode-aware Windows process cwd select the task directory.
const nativePath = (file: string): string => path.basename(file)
const iso = (): string => new Date().toISOString()

async function atomicJson(file: string, data: unknown): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true })
  const temp = `${file}.${process.pid}.tmp`
  await writeFile(temp, JSON.stringify(data, null, 2), 'utf8')
  await rename(temp, file)
}

async function fingerprint(file: string): Promise<string> {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  return hash.digest('hex')
}

function finite(value: number, min: number, max: number, name: string): void {
  if (!Number.isFinite(value) || value < min || value > max) throw new Error(`${name} 超出范围`)
}

function validate(spec: JobSpec): void {
  if (!spec || typeof spec.name !== 'string' || spec.name.trim().length < 1 || spec.name.length > 100) throw new Error('任务名称无效')
  if (!path.isAbsolute(spec.directory)) throw new Error('请选择绝对保存路径')
  const r = spec.rules
  validateExitRules(r)
  for (const [value, min, max, label] of [
    [r.maxValue ?? r.target, r.target, 65535, '最大出现数字'], [r.cells, 5, 255, '空格数'], [r.target, 24, 65535, '目标数字'], [r.maxGoalCells, 1, 5, '最终占格上限']
  ] as const) { finite(value, min, max, label); if (!Number.isInteger(value)) throw new Error(`${label} 必须为整数`) }
  finite(r.aggressiveness, 0, r.target / 7.5, '激进度（0 至目标数字 / 7.5）')
  if (r.successSide !== 'above' && r.successSide !== 'both') throw new Error('成功位置无效')
  if (!Array.isArray(r.bases) || r.bases.length === 0 || new Set(r.bases).size !== r.bases.length || r.bases.some(x => !Number.isInteger(x) || x < 1 || x > 65535 || x % 2 !== 1)) throw new Error('基必须是不重复的正奇数')
  finite(spec.repeats, 1, 100, '流程重复次数')
  if (!Number.isInteger(spec.repeats) || !Array.isArray(spec.stages) || spec.stages.length < 1 || spec.stages.length > 100) throw new Error('流程配置无效')
  for (const stage of spec.stages) {
    finite(stage.rounds, 1, 1000000, '阶段轮数')
    if (!Number.isInteger(stage.rounds)) throw new Error('阶段轮数必须为整数')
    if (stage.kind === 'vi') finite(stage.tolerance, Number.MIN_VALUE, 0.999999, 'VI 阈值')
    else throw new Error('新任务只支持基于概率表的值迭代阶段')
  }
}

type Settings = { checkpointSeconds: number; defaultDirectory: string }

export class JobManager {
  jobs: Job[] = []
  private child: ChildProcessWithoutNullStreams | null = null
  private activeId: string | null = null
  private activeDone: Promise<void> | null = null
  private saveChain: Promise<void> = Promise.resolve()
  private stopping = false
  private window: BrowserWindow | null = null
  settings: Settings = { checkpointSeconds: 120, defaultDirectory: '' }

  async load(): Promise<void> {
    this.settings.defaultDirectory = path.join(app.getPath('documents'), 'Tallnum')
    try { this.settings = { ...this.settings, ...JSON.parse(await readFile(settingsPath(), 'utf8')) } } catch { /* first run */ }
    try { this.jobs = JSON.parse(await readFile(indexPath(), 'utf8')) as Job[] } catch { this.jobs = [] }
    for (const job of this.jobs) {
      job.coreVersion ??= LEGACY_CORE_VERSION
      job.spec.rules.aggressiveness ??= 0
      if (job.coreVersion !== CORE_VERSION && ['queued', 'running', 'pausing'].includes(job.status)) {
        job.status = 'paused'; job.phase = '规则已更新，请按原参数新建任务'
      }
      if (job.status === 'running' || job.status === 'pausing') {
        job.status = 'paused'
        job.phase = '上次退出后等待从检查点恢复'
        job.segmentStartedAt = undefined
      }
    }
    await this.save()
    this.pump()
  }

  attach(window: BrowserWindow): void { this.window = window; this.broadcast() }
  private broadcast(): void { if (this.window && !this.window.isDestroyed()) this.window.webContents.send('jobs:changed', this.jobs) }
  private async save(): Promise<void> {
    this.saveChain = this.saveChain.then(() => atomicJson(indexPath(), this.jobs)).then(() => this.broadcast())
    await this.saveChain
  }
  private location(job: Job): string { return path.join(job.spec.directory, job.id) }
  private async event(job: Job, data: Record<string, unknown>): Promise<void> {
    const file = path.join(this.location(job), 'events.jsonl')
    await writeFile(file, JSON.stringify({ time: iso(), ...data }) + '\n', { flag: 'a' })
  }

  async create(spec: JobSpec): Promise<Job> {
    spec = { ...spec, rules: normalizeRules(spec.rules) }
    validate(spec)
    const job: Job = { coreVersion: CORE_VERSION, id: randomUUID(), spec: structuredClone(spec), status: 'queued', phase: '排队中', stageIndex: 0, round: 0, kspIteration: null, states: null, probability: null, residual: null, createdAt: iso(), elapsedMs: 0, results: [], history: [] }
    await mkdir(this.location(job), { recursive: true })
    await atomicJson(path.join(this.location(job), 'spec.json'), { coreVersion: job.coreVersion, spec: job.spec })
    this.jobs.unshift(job)
    await this.save()
    this.pump()
    return job
  }

  private get(id: string): Job { const job = this.jobs.find(x => x.id === id); if (!job) throw new Error('任务不存在'); return job }
  async pause(id: string): Promise<void> {
    const job = this.get(id)
    if (job.status === 'queued') { job.status = 'paused'; job.phase = '已暂停'; await this.save(); return }
    if (job.status !== 'running') return
    job.status = 'pausing'; job.phase = '正在保存检查点'
    await writeFile(path.join(this.location(job), 'control.txt'), 'pause')
    await this.save()
  }
  async resume(id: string): Promise<void> {
    const job = this.get(id)
    if (job.coreVersion !== CORE_VERSION) throw new Error('旧任务使用策略表或旧规则，请新建概率表任务重新计算')
    if (job.status !== 'paused' && job.status !== 'failed') return
    job.status = 'queued'; job.error = undefined; job.phase = '排队中'
    await writeFile(path.join(this.location(job), 'control.txt'), '')
    await this.save(); this.pump()
  }
  async cancel(id: string): Promise<void> {
    const job = this.get(id)
    if (job.status === 'running' || job.status === 'pausing') {
      await writeFile(path.join(this.location(job), 'control.txt'), 'cancel')
      job.status = 'pausing'; job.phase = '正在停止'
    } else if (job.status === 'queued' || job.status === 'paused') { job.status = 'cancelled'; job.endedAt = iso() }
    await this.save()
  }
  async beforeQuit(): Promise<void> {
    this.stopping = true
    if (this.activeId) await this.pause(this.activeId)
    if (this.activeDone) await this.activeDone
  }

  private pump(): void {
    if (this.stopping || this.activeId) return
    const job = this.jobs.find(x => x.status === 'queued')
    if (!job) return
    this.activeId = job.id
    this.activeDone = this.run(job).finally(() => { this.activeId = null; this.child = null; this.activeDone = null; this.pump() })
  }

  private async run(job: Job): Promise<void> {
    try {
      job.status = 'running'; job.startedAt ??= iso(); job.segmentStartedAt = iso(); await this.save()
      const dir = this.location(job)
      const table = path.join(dir, 'transitions.bin')
      const control = path.join(dir, 'control.txt')
      const seconds = this.settings.checkpointSeconds
      if (!existsSync(table) || !existsSync(path.join(dir, 'table.json'))) {
        job.phase = '生成转移表'; await this.save()
        const r = job.spec.rules
        await this.execute(job, 'tallnum_reachable', [...generatorRuleArgs(r), '--output', nativePath(table), '--checkpoint', 'generate.ckpt', '--checkpoint-seconds', String(seconds), '--control', nativePath(control), '--events', 'events.jsonl'], path.join(dir, 'generate.log'))
        if (job.status !== 'running') return
        await atomicJson(path.join(dir, 'table.json'), { coreVersion: job.coreVersion, rules: r, sha256: await fingerprint(table) })
      }
      const tableInfo = JSON.parse(await readFile(path.join(dir, 'table.json'), 'utf8'))
      if (tableInfo.coreVersion !== job.coreVersion || JSON.stringify({ ...tableInfo.rules, aggressiveness: tableInfo.rules.aggressiveness ?? 0 }) !== JSON.stringify({ ...job.spec.rules, aggressiveness: job.spec.rules.aggressiveness }) || tableInfo.sha256 !== await fingerprint(table)) throw new Error('转移表与任务规则或计算核心版本不匹配')
      const modelPath = `${table}.model.json`
      const modelInfo = JSON.parse(await readFile(modelPath, 'utf8'))
      assertModelRules(modelInfo, job.spec.rules)
      await atomicJson(`${table}.rules.json`, { ruleSha256: 'edge-recheck-v1', tableSha256: tableInfo.sha256, modelSha256: await fingerprint(modelPath), generatorSha256: await fingerprint(executable('tallnum_reachable')) })
      const stages = Array.from({ length: job.spec.repeats }, () => job.spec.stages).flat()
      for (let i = job.stageIndex; i < stages.length; i++) {
        job.stageIndex = i
        const stage = stages[i]
        job.phase = `${i + 1}/${stages.length} · 概率表值迭代`
        await this.save()
        if (stage.kind !== 'vi') throw new Error('新任务不能运行策略表阶段')
        await this.runVi(job, stage, table, control, i)
        if (job.status !== 'running') return
        job.stageIndex = i + 1; job.round = 0
        await this.save()
      }
      const last = stages.at(-1)
      if (last?.kind !== 'vi' || job.residual == null || job.residual > last.tolerance)
        throw new Error('最终概率表尚未收敛，请增加值迭代轮数后新建任务')
      job.status = 'completed'; job.phase = '计算完成'; job.endedAt = iso(); await this.event(job, { type: 'completed', probability: job.probability }); await this.save()
    } catch (error) {
      if (job.status === 'pausing') { job.status = (await readFile(path.join(this.location(job), 'control.txt'), 'utf8')).trim() === 'cancel' ? 'cancelled' : 'paused'; job.phase = job.status === 'paused' ? '已暂停' : '已取消' }
      else { job.status = 'failed'; job.error = error instanceof Error ? error.message : String(error); job.phase = '失败' }
      job.endedAt = iso(); await this.event(job, { type: job.status, error: job.error }); await this.save()
    } finally {
      if (job.segmentStartedAt) {
        job.elapsedMs = (job.elapsedMs ?? 0) + Math.max(0, Date.now() - new Date(job.segmentStartedAt).getTime())
        job.segmentStartedAt = undefined
        await this.save()
      }
      if (job.status === 'pausing') {
        job.status = (await readFile(path.join(this.location(job), 'control.txt'), 'utf8')).trim() === 'cancel' ? 'cancelled' : 'paused'
        job.phase = job.status === 'paused' ? '已暂停' : '已取消'
        await this.save()
      }
    }
  }

  private latest(job: Job): StageResult | undefined { return job.results.at(-1) }

  private async runVi(job: Job, stage: Extract<Stage, { kind: 'vi' }>, table: string, control: string, index: number): Promise<void> {
    const dir = this.location(job)
    const output = path.join(dir, `stage-${index + 1}.values.bin`)
    const checkpoint = path.join(dir, `stage-${index + 1}.vi.ckpt`)
    const prior = this.latest(job)?.valuesFile
    const start = Date.now()
    await this.execute(job, 'tallnum_vi', [nativePath(table), String(stage.rounds), String(stage.tolerance), nativePath(output), '--checkpoint', nativePath(checkpoint), '--checkpoint-seconds', String(this.settings.checkpointSeconds), '--control', nativePath(control), '--events', 'events.jsonl', '--aggressiveness', String(job.spec.rules.aggressiveness), ...(existsSync(checkpoint) ? ['--resume', nativePath(checkpoint)] : prior ? ['--initial-values', nativePath(prior)] : [])], path.join(dir, `stage-${index + 1}.log`))
    if (job.status !== 'running') return
    const result = JSON.parse(await readFile(`${table}.result.json`, 'utf8'))
    if (!Number.isFinite(result.max_delta) || result.max_delta < 0 ||
        !Number.isInteger(result.iterations) || result.iterations < 1)
      throw new Error('概率表求解结果无效')
    const pendingCsv = await readFile(`${table}.initial.csv`, 'utf8')
    const pendingProbabilities = readPendingProbabilities(pendingCsv, result.weighted)
    await writeFile(path.join(dir, `stage-${index + 1}.pending.csv`), pendingCsv, 'utf8')
    await this.record(job, { stage: index, kind: 'vi', round: result.iterations, probability: result.weighted,
      pendingProbabilities, residual: result.max_delta, elapsedMs: Date.now() - start,
      stopReason: result.max_delta <= stage.tolerance ? '达到阈值' : '达到轮数上限', valuesFile: output })
  }

  private async record(job: Job, result: StageResult): Promise<void> {
    job.results.push(result)
    job.probability = result.probability; job.residual = result.residual
    job.history.push({ time: iso(), probability: result.probability, residual: result.residual, stage: result.stage })
    await this.event(job, { type: 'stage_result', ...result })
    await this.save()
  }

  private execute(job: Job, name: string, args: string[], logfile: string): Promise<void> {
    const program = executable(name)
    if (!existsSync(program)) throw new Error(`缺少原生计算程序：${program}`)
    return new Promise((resolve, reject) => {
      const child = spawn(program, args, { cwd: this.location(job), windowsHide: true, shell: false })
      this.child = child
      let buffer = ''
      let lastProgressSave = 0
      const receive = (part: Buffer): void => {
        const data = part.toString('utf8'); void writeFile(logfile, data, { flag: 'a' })
        buffer += data
        const lines = buffer.split(/\r?\n/); buffer = lines.pop() ?? ''
        for (const line of lines) {
          const ksp = line.match(/^\s*(\d+)\s+KSP Residual norm\s+([0-9.eE+-]+)/)
          if (ksp) {
            job.kspIteration = Number(ksp[1]); job.residual = Number(ksp[2])
            if (Date.now() - lastProgressSave > 1000) { lastProgressSave = Date.now(); void this.save() }
          }
          const match = line.match(/(?:iteration|expanded|states)\s*[=:]\s*(\d+)/)
          const states = line.match(/(?:discovered|states)\s*[=:]\s*(\d+)/)
          if (states) job.states = Number(states[1])
          if (match && line.includes('iteration')) job.round = Number(match[1])
          const probability = line.match(/(?:weighted|initial policy value)\s*[=:]\s*([0-9.eE+-]+)/)
          if (probability) job.probability = Number(probability[1])
          const residual = line.match(/(?:delta|reported residual norm)\s*[=:]\s*([0-9.eE+-]+)/)
          if (residual) job.residual = Number(residual[1])
          if (probability || residual) { job.history.push({ time: iso(), probability: job.probability ?? 0, residual: job.residual, stage: job.stageIndex }); void this.save() }
        }
      }
      child.stdout.on('data', receive); child.stderr.on('data', receive)
      child.on('error', reject)
      child.on('close', code => {
        this.child = null
        if (code === 0) resolve()
        else reject(new Error(`${name} 退出，代码 ${code}。请查看阶段日志。`))
      })
    })
  }

  async chooseDirectory(): Promise<string | null> {
    const result = await dialog.showOpenDialog({ properties: ['openDirectory', 'createDirectory'], defaultPath: this.settings.defaultDirectory })
    return result.canceled ? null : result.filePaths[0]
  }
  async openDirectory(id: string): Promise<void> { await shell.openPath(this.location(this.get(id))) }
  async openReplay(file?: string): Promise<void> {
    let selected = file
    if (!selected) {
      const result = await dialog.showOpenDialog({ properties: ['openFile'], filters: [{ name: 'HTML 回放', extensions: ['html', 'htm'] }] })
      if (result.canceled) return
      selected = result.filePaths[0]
    }
    const absolute = path.resolve(selected)
    if (!/\.html?$/i.test(absolute) || !existsSync(absolute)) throw new Error('请选择有效的 HTML 回放文件')
    await shell.openExternal(new URL(`file:///${absolute.replace(/\\/g, '/')}`).href)
  }
  async logs(id: string): Promise<Array<{ name: string; text: string }>> {
    const dir = this.location(this.get(id))
    const names = (await readdir(dir)).filter(name => /^(generate|stage-[0-9]+(?:-round-[0-9]+)?)\.log$/.test(name)).slice(-20)
    return Promise.all(names.map(async name => ({ name, text: (await readFile(path.join(dir, name), 'utf8')).slice(-50000) })))
  }
  async exportResult(id: string, format: 'json' | 'csv'): Promise<string | null> {
    const job = this.get(id)
    const rows = job.results.flatMap(result => (result.pendingProbabilities ?? []).map(state => ({
      stage: result.stage + 1, q1: state.q1, q2: state.q2, successProbability: state.probability
    })))
    if (!rows.length) throw new Error('此任务没有待出数状态概率；请新建概率表任务')
    const result = await dialog.showSaveDialog({ defaultPath: `${job.spec.name}.${format}`, filters: [{ name: format.toUpperCase(), extensions: [format] }] })
    if (result.canceled || !result.filePath) return null
    const data = format === 'json'
      ? JSON.stringify({ name: job.spec.name, target: job.spec.rules.target, status: job.status,
        probabilityBasis: 'value-table', pendingStates: rows }, null, 2)
      : 'stage,q1,q2,success_probability\n' + rows.map(x =>
        `${x.stage},${x.q1},${x.q2},${x.successProbability}`).join('\n')
    await writeFile(result.filePath, data, 'utf8')
    return result.filePath
  }
  async setSettings(settings: Settings): Promise<void> {
    finite(settings.checkpointSeconds, 10, 3600, '检查点间隔')
    if (!Number.isInteger(settings.checkpointSeconds) || !path.isAbsolute(settings.defaultDirectory)) throw new Error('设置无效')
    this.settings = settings
    await atomicJson(settingsPath(), settings)
  }
  async recentReplays(id: string): Promise<string[]> { return (await readdir(this.location(this.get(id)))).filter(x => x.endsWith('.html')) }
}
