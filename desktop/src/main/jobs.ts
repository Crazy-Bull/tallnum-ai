import { app, BrowserWindow, dialog, shell } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID, createHash } from 'node:crypto'
import { createReadStream, existsSync } from 'node:fs'
import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import type { Job, JobSpec, Stage, StageResult } from '../shared'

const LEGACY_CORE_VERSION = 'tallnum-v4-desktop-1'
const CORE_VERSION = 'tallnum-v4-desktop-3-edge-bound'
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
  for (const [value, min, max, label] of [
    [r.maxValue ?? r.target, r.target, 65535, '最大出现数字'], [r.cells, 1, 255, '空格数'], [r.target, 1, 65535, '目标数字'], [r.maxGoalCells, 1, 5, '最终占格上限']
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
    else if (stage.kind === 'petsc') {
      if (!['gmres', 'dgmres', 'fgmres'].includes(stage.algorithm) || !['jacobi', 'none', 'ilu'].includes(stage.preconditioner)) throw new Error('PETSc 算法或预条件方式无效')
      finite(stage.maxKsp, 1, 1000000, 'KSP 迭代上限')
      finite(stage.restart, 1, 10000, '重启长度')
      finite(stage.rtol, Number.MIN_VALUE, 0.999999, '相对残差阈值')
      finite(stage.atol, Number.MIN_VALUE, 0.999999, '绝对残差阈值')
    } else throw new Error('未知阶段')
  }
}

type Settings = { checkpointSeconds: number; defaultDirectory: string }
class RecoverableSolverError extends Error {}

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
    if (job.coreVersion !== CORE_VERSION) throw new Error('旧任务的 EDGE 规则或检查点版本已变更，请按原参数新建任务重新计算')
    if (job.status !== 'paused' && job.status !== 'failed') return
    job.status = 'queued'; job.error = undefined; job.phase = '排队中'
    await writeFile(path.join(this.location(job), 'control.txt'), '')
    await this.save(); this.pump()
  }
  async updateBudget(id: string, budget: { maxKsp: number; rtol: number; atol: number; restart: number }): Promise<void> {
    const job = this.get(id)
    if (job.status !== 'paused' && job.status !== 'failed') throw new Error('只能调整已暂停任务的求解预算')
    const stage = job.spec.stages[job.stageIndex % job.spec.stages.length]
    if (stage?.kind !== 'petsc') throw new Error('当前阶段不是 PETSc')
    finite(budget.maxKsp, 1, 1000000, 'KSP 迭代上限')
    finite(budget.restart, 1, 10000, '重启长度')
    finite(budget.rtol, Number.MIN_VALUE, 0.999999, '相对残差阈值')
    finite(budget.atol, Number.MIN_VALUE, 0.999999, '绝对残差阈值')
    if (!Number.isInteger(budget.maxKsp) || !Number.isInteger(budget.restart)) throw new Error('迭代数和重启长度必须为整数')
    Object.assign(stage, budget)
    await atomicJson(path.join(this.location(job), 'spec.json'), { coreVersion: job.coreVersion, spec: job.spec })
    await this.event(job, { type: 'budget_changed', stage: job.stageIndex, budget })
    await this.save()
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
        await this.execute(job, 'tallnum_reachable', ['--cells', String(r.cells), '--target', String(r.target), '--max-value', String(r.maxValue ?? r.target), '--max-goal-cells', String(r.maxGoalCells), '--bases', r.bases.join(','), '--success-side', r.successSide, '--output', nativePath(table), '--checkpoint', 'generate.ckpt', '--checkpoint-seconds', String(seconds), '--control', nativePath(control), '--events', 'events.jsonl'], path.join(dir, 'generate.log'))
        if (job.status !== 'running') return
        await atomicJson(path.join(dir, 'table.json'), { coreVersion: job.coreVersion, rules: r, sha256: await fingerprint(table) })
      }
      const tableInfo = JSON.parse(await readFile(path.join(dir, 'table.json'), 'utf8'))
      if (tableInfo.coreVersion !== job.coreVersion || JSON.stringify({ ...tableInfo.rules, aggressiveness: tableInfo.rules.aggressiveness ?? 0 }) !== JSON.stringify({ ...job.spec.rules, aggressiveness: job.spec.rules.aggressiveness }) || tableInfo.sha256 !== await fingerprint(table)) throw new Error('转移表与任务规则或计算核心版本不匹配')
      const modelPath = `${table}.model.json`
      const modelInfo = JSON.parse(await readFile(modelPath, 'utf8'))
      if (modelInfo.maxValue !== (job.spec.rules.maxValue ?? job.spec.rules.target)) throw new Error('转移表的最大出现数字与任务不一致')
      await atomicJson(`${table}.rules.json`, { ruleSha256: 'edge-recheck-v1', tableSha256: tableInfo.sha256, modelSha256: await fingerprint(modelPath), generatorSha256: await fingerprint(executable('tallnum_reachable')) })
      const stages = Array.from({ length: job.spec.repeats }, () => job.spec.stages).flat()
      const last = stages.at(-1)
      if (last?.kind !== 'petsc' || last.rounds < 2) stages.push({ kind: 'petsc', rounds: 3, algorithm: 'dgmres', maxKsp: 20000, rtol: 1e-10, atol: 1e-12, restart: 50, preconditioner: 'jacobi' })
      for (let i = job.stageIndex; i < stages.length; i++) {
        job.stageIndex = i
        const stage = stages[i]
        job.phase = `${i + 1}/${stages.length} · ${stage.kind === 'vi' ? 'VI' : 'PETSc'}`
        await this.save()
        if (stage.kind === 'vi') await this.runVi(job, stage, table, control, i)
        else await this.runPetsc(job, stage, table, control, i)
        if (job.status !== 'running') return
        job.stageIndex = i + 1; job.round = 0
        await this.save()
      }
      await this.evaluateActual(job, table, control, stages.length)
      if (job.status !== 'running') return
      job.status = 'completed'; job.phase = '计算完成'; job.endedAt = iso(); await this.event(job, { type: 'completed', probability: job.probability }); await this.save()
    } catch (error) {
      if (job.status === 'pausing') { job.status = (await readFile(path.join(this.location(job), 'control.txt'), 'utf8')).trim() === 'cancel' ? 'cancelled' : 'paused'; job.phase = job.status === 'paused' ? '已暂停' : '已取消' }
      else if (error instanceof RecoverableSolverError) { job.status = 'paused'; job.error = error.message; job.phase = 'PETSc 等待调整求解预算' }
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

  private async evaluateActual(job: Job, table: string, control: string, index: number): Promise<void> {
    const prior = this.latest(job)
    if (!prior?.policyFile) throw new Error('最终 PETSc 策略缺失')
    const stem = path.join(this.location(job), 'final-actual')
    const start = Date.now()
    job.phase = 'PETSc 复核实际成功率（无人工猝死）'; await this.save()
    await this.execute(job, 'tallnum_policy_eval', ['-tallnum_table', nativePath(table), '-tallnum_policy', nativePath(prior.policyFile), '-tallnum_input_aggressiveness', String(job.spec.rules.aggressiveness), '-tallnum_aggressiveness', '0', '-tallnum_save_values', nativePath(`${stem}.values.bin`), '-tallnum_result', nativePath(`${stem}.json`), '-tallnum_control', nativePath(control), '-ksp_type', 'dgmres', '-ksp_gmres_restart', '50', '-ksp_rtol', '1e-10', '-ksp_atol', '1e-12', '-ksp_max_it', '20000', '-pc_type', 'jacobi'], `${stem}.log`)
    if (job.status !== 'running') return
    const result = JSON.parse(await readFile(`${stem}.json`, 'utf8'))
    if (!result.converged || result.aggressiveness !== 0 || !Number.isFinite(result.weighted_policy_value)) throw new Error('最终实际成功率求解未收敛')
    await this.record(job, { stage: index, kind: 'petsc', round: 1, probability: result.weighted_policy_value, residual: result.true_residual_inf, kspIterations: result.iterations, elapsedMs: Date.now() - start, stopReason: '固定策略实际成功率复核', valuesFile: `${stem}.values.bin`, policyFile: prior.policyFile })
  }
  private async runVi(job: Job, stage: Extract<Stage, { kind: 'vi' }>, table: string, control: string, index: number): Promise<void> {
    const dir = this.location(job)
    const output = path.join(dir, `stage-${index + 1}.values.bin`)
    const checkpoint = path.join(dir, `stage-${index + 1}.vi.ckpt`)
    const prior = this.latest(job)?.valuesFile
    const start = Date.now()
    await this.execute(job, 'tallnum_vi', [nativePath(table), String(stage.rounds), String(stage.tolerance), nativePath(output), '--checkpoint', nativePath(checkpoint), '--checkpoint-seconds', String(this.settings.checkpointSeconds), '--control', nativePath(control), '--events', 'events.jsonl', ...(job.coreVersion === CORE_VERSION ? ['--aggressiveness', String(job.spec.rules.aggressiveness)] : []), ...(existsSync(checkpoint) ? ['--resume', nativePath(checkpoint)] : prior ? ['--initial-values', nativePath(prior)] : [])], path.join(dir, `stage-${index + 1}.log`))
    if (job.status !== 'running') return
    const result = JSON.parse(await readFile(`${table}.result.json`, 'utf8'))
    await this.record(job, { stage: index, kind: 'vi', round: result.iterations, probability: result.weighted, residual: result.max_delta, elapsedMs: Date.now() - start, stopReason: result.max_delta <= stage.tolerance ? '达到阈值' : '达到轮数上限', valuesFile: output })
  }

  private async runPetsc(job: Job, stage: Extract<Stage, { kind: 'petsc' }>, table: string, control: string, index: number): Promise<void> {
    const dir = this.location(job)
    let values = this.latest(job)?.valuesFile
    let previousPolicy = this.latest(job)?.policyFile
    for (let round = job.round; round < stage.rounds; round++) {
      job.round = round; await this.save()
      const stem = path.join(dir, `stage-${index + 1}-round-${round + 1}`)
      const policy = `${stem}.policy.bin`
      const output = `${stem}.values.bin`
      const resultPath = `${stem}.json`
      const checkpoint = `${stem}.ckpt`
      const start = Date.now()
      job.kspIteration = null
      const args = ['-tallnum_table', nativePath(table), '-tallnum_save_policy', nativePath(policy), '-tallnum_save_values', nativePath(output), '-tallnum_result', nativePath(resultPath), '-ksp_type', stage.algorithm, '-ksp_rtol', String(stage.rtol), '-ksp_atol', String(stage.atol), '-ksp_max_it', String(stage.maxKsp), '-ksp_monitor', '-pc_type', stage.preconditioner, '-tallnum_control', nativePath(control), '-tallnum_checkpoint', nativePath(checkpoint), '-tallnum_checkpoint_seconds', String(this.settings.checkpointSeconds), '-tallnum_events', 'events.jsonl']
      if (job.coreVersion === CORE_VERSION) args.push('-tallnum_aggressiveness', String(job.spec.rules.aggressiveness))
      if (existsSync(checkpoint) && existsSync(policy)) args.push('-tallnum_policy', nativePath(policy), '-tallnum_resume_values', nativePath(checkpoint))
      else {
        if (values) args.push('-tallnum_values', nativePath(values))
        else args.push('-tallnum_auto_policy', '1')
        if (previousPolicy && values) args.push('-tallnum_previous_policy', nativePath(previousPolicy))
      }
      if (stage.preconditioner === 'ilu') args.push('-tallnum_explicit_matrix', '1')
      args.push('-ksp_gmres_restart', String(stage.restart))
      try { await this.execute(job, 'tallnum_policy_eval', args, `${stem}.log`) }
      catch (error) {
        if (job.status === 'pausing') throw error
        if (existsSync(resultPath) || existsSync(checkpoint)) throw new RecoverableSolverError(`PETSc 未收敛或数值异常。诊断位于 ${nativePath(resultPath)}；可调整预算后继续。`)
        throw error
      }
      if (job.status !== 'running') return
      const result = JSON.parse(await readFile(resultPath, 'utf8'))
      if (!Number.isFinite(result.weighted_policy_value) || result.ksp_reason <= 0) throw new Error(`PETSc 未收敛；诊断已保存到 ${resultPath}`)
      let changed = true
      if (previousPolicy && existsSync(previousPolicy)) changed = (await fingerprint(policy)) !== (await fingerprint(previousPolicy))
      await this.record(job, { stage: index, kind: 'petsc', round: round + 1, probability: result.weighted_policy_value, residual: result.true_residual_inf ?? null, kspIterations: result.iterations, elapsedMs: Date.now() - start, stopReason: changed ? '固定策略求解完成' : '策略不再变化', valuesFile: output, policyFile: policy })
      job.round = round + 1
      values = output; previousPolicy = policy
      if (!changed) break
    }
  }

  private async record(job: Job, result: StageResult): Promise<void> {
    job.results.push(result)
    job.probability = result.probability; job.residual = result.residual
    job.history.push({ time: iso(), probability: result.probability, residual: result.residual, stage: result.stage })
    await this.event(job, { type: 'stage_result', ...result })
    await this.save()
  }

  private execute(job: Job, name: string, args: string[], logfile: string): Promise<void> {
    const program = executable(job.coreVersion === LEGACY_CORE_VERSION ? `${name}_legacy` : name)
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
    const result = await dialog.showSaveDialog({ defaultPath: `${job.spec.name}.${format}`, filters: [{ name: format.toUpperCase(), extensions: [format] }] })
    if (result.canceled || !result.filePath) return null
    const data = format === 'json' ? JSON.stringify({ spec: job.spec, status: job.status, results: job.results }, null, 2) : 'stage,kind,round,probability,residual,elapsed_ms,stop_reason,aggressiveness,sudden_death_probability,success_step_exempt\n' + job.results.map(x => [x.stage + 1, x.kind, x.round, x.probability, x.residual ?? '', x.elapsedMs, JSON.stringify(x.stopReason), job.spec.rules.aggressiveness, job.spec.rules.aggressiveness * 7.5 / job.spec.rules.target, true].join(',')).join('\n')
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
