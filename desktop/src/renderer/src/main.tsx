import { Localized, LocaleProvider, LanguageSelector } from './i18n'
import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import type { DesktopApi, Job, JobSpec, Stage, StageResult } from '../../shared'
import { DEFAULT_STAGE } from '../../shared'
import './style.css'
import { Automation } from './Automation'
import { IntegerPlanner } from './IntegerPlanner'
import { Peak13Planner } from './Peak13Planner'
import { ExitRules } from './ExitRules'

declare global { interface Window { tallnum: DesktopApi } }

const defaultSpec: JobSpec = {
  name: '5 格合成 48', directory: '',
  rules: { cells: 5, target: 48, aggressiveness: 0, maxGoalCells: 5, bases: [1, 3, 5, 15], successSide: 'above' },
  stages: structuredClone(DEFAULT_STAGE), repeats: 1
}
const pct = (v: number | null | undefined): string => v == null ? '—' : `${(v * 100).toFixed(8)}%`
const statusText: Record<Job['status'], string> = { queued: '排队', running: '运行中', pausing: '保存中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消' }
const number = (v: string): number => Number(v)

export function App(): React.JSX.Element {
  const [view, setView] = useState<'new' | 'jobs' | 'compare' | 'settings' | 'automation' | 'planner' | 'peak13'>('new')
  const [jobs, setJobs] = useState<Job[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [spec, setSpec] = useState<JobSpec>(defaultSpec)
  const [baseInput, setBaseInput] = useState('')
  const [advanced, setAdvanced] = useState(false)
  const [error, setError] = useState('')
  const [compareIds, setCompareIds] = useState<[string, string]>(['', ''])
  const [compareRounds, setCompareRounds] = useState<[number, number]>([-1, -1])
  const [settings, setSettings] = useState({ checkpointSeconds: 120, defaultDirectory: '' })
  const [presets, setPresets] = useState<Record<string, Stage[]>>(() => { try { return JSON.parse(localStorage.getItem('tallnum-presets') || '{}') } catch { return {} } })
  const [presetName, setPresetName] = useState('')
  const [logs, setLogs] = useState<Array<{ name: string; text: string }>>([])

  useEffect(() => {
    void window.tallnum.list().then(setJobs)
    void window.tallnum.getSettings().then(s => { setSettings(s); setSpec(old => ({ ...old, directory: s.defaultDirectory })) })
    return window.tallnum.onJobs(setJobs)
  }, [])
  useEffect(() => setLogs([]), [selected])

  const current = jobs.find(x => x.id === selected)
  const first = jobs.find(x => x.id === compareIds[0])
  const second = jobs.find(x => x.id === compareIds[1])
  const firstResult = first?.results[compareRounds[0]] ?? first?.results.at(-1)
  const secondResult = second?.results[compareRounds[1]] ?? second?.results.at(-1)
  const stageCount = spec.stages.length * spec.repeats

  const rulesSummary = useMemo(() => `固定发牌 2、4、6、8、10、15，各占 1/6；基列表仅限制中间过程允许出现的数字，不改变发牌。普通目标块占 1 格；中间组合最多占 5 格。成功位置：${spec.rules.successSide === 'above' ? 'F 上方紧邻' : 'F 两侧紧邻'}。猝死率＝激进度 × 7.5 ÷ 目标数字；成功步免除猝死，免费操作不承担风险。当前未成功出数步的猝死率：${pct(spec.rules.aggressiveness * 7.5 / spec.rules.target)}。`, [spec.rules.successSide, spec.rules.aggressiveness, spec.rules.target])

  function updateRules(part: Partial<JobSpec['rules']>): void { setSpec(old => ({ ...old, rules: { ...old.rules, ...part } })) }
  function updateStage(i: number, part: Partial<Stage>): void { setSpec(old => ({ ...old, stages: old.stages.map((s, j) => j === i ? { ...s, ...part } as Stage : s) })) }
  function moveStage(i: number, direction: number): void {
    setSpec(old => { const stages = [...old.stages]; const j = i + direction; if (j < 0 || j >= stages.length) return old; [stages[i], stages[j]] = [stages[j], stages[i]]; return { ...old, stages } })
  }
  function addBase(): void {
    const v = Number(baseInput.trim())
    if (!Number.isInteger(v) || v < 1 || v > 65535 || v % 2 !== 1 || spec.rules.bases.includes(v)) { setError('请输入未重复的 1–65535 正奇数'); return }
    updateRules({ bases: [...spec.rules.bases, v].sort((a, b) => a - b) }); setBaseInput(''); setError('')
  }
  async function create(): Promise<void> {
    try { const job = await window.tallnum.create(spec); setSelected(job.id); setView('jobs'); setError('') } catch (e) { setError(String(e)) }
  }
  function savePreset(): void {
    const name = presetName.trim()
    if (!name) { setError('请输入预设名称'); return }
    if (spec.stages.some(stage => stage.kind !== 'vi')) { setError('只能保存概率表值迭代预设'); return }
    const next = { ...presets, [name]: structuredClone(spec.stages) }
    setPresets(next); localStorage.setItem('tallnum-presets', JSON.stringify(next)); setPresetName(''); setError('')
  }
  async function action(fn: () => Promise<unknown>): Promise<void> { try { await fn(); setError('') } catch (e) { setError(String(e)) } }

  return <Localized><div className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-icon">T</div><div><strong>Tallnum</strong><small>本地计算器</small></div></div>
      <nav>
        {([['new', '新建计算', '＋'], ['jobs', '任务', '◫'], ['compare', '结果对比', '◩'], ['planner', '结构路线规划', '↗'], ['peak13', '概率表路线规划', '◆'], ['automation', '自动玩', '▷'], ['settings', '设置', '⚙']] as const).map(([id, label, icon]) => <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}><span>{icon}</span>{label}{id === 'jobs' && <em>{jobs.length}</em>}</button>)}
      </nav>
      <LanguageSelector /><div className="side-bottom">Windows x64 · 本地运行<br />概率表规则 v5</div>
    </aside>
    <main className="workspace">
      {view === 'automation' && <Automation />}
      {view === 'planner' && <IntegerPlanner />}
      {view === 'peak13' && <Peak13Planner />}
      {error && <div className="error" role="alert">{error}<button onClick={() => setError('')}>×</button></div>}
      {view === 'new' && <>
        <header className="page-header"><div><span className="eyebrow">NEW CALCULATION</span><h1>新建计算</h1><p>设定目标与计算流程，任务创建后会固定规则并加入队列。</p></div><button className="primary" onClick={() => void create()}>开始计算 <span>↗</span></button></header>
        <section className="panel"><div className="panel-head"><span className="step">01</span><div><h2>基础设置</h2><p>每个任务只计算一个目标。</p></div></div>
          <div className="form-grid">
            <label>任务名称<input value={spec.name} maxLength={100} onChange={e => setSpec({ ...spec, name: e.target.value })} /></label>
            <label>空格数 <small>不包含 F · 5–255</small><input type="number" min="5" max="255" value={spec.rules.cells} onChange={e => updateRules({ cells: number(e.target.value), ...(number(e.target.value) === 6 ? {} : { singleEdgeGuard: false, singleTidyExit: false }) })} /></label>
            <label>目标数字 <small>24–65535</small><input type="number" min="24" max="65535" value={spec.rules.target} onChange={e => updateRules({ target: number(e.target.value) })} /></label>
            <label>最大出现数字 <small>留空时等于目标；可允许更大的中间块</small><input type="number" min={spec.rules.target} max="65535" value={spec.rules.maxValue ?? ''} onChange={e => updateRules({ maxValue: e.target.value === '' ? undefined : number(e.target.value) })} /></label>
            <label>激进度 <small>默认 0 · 越大越偏向快速成功</small><input type="number" min="0" max={spec.rules.target / 7.5} step="any" value={spec.rules.aggressiveness} onChange={e => updateRules({ aggressiveness: number(e.target.value) })} /></label>
            <label>最终目标块占格上限 <small>1–5</small><input type="number" min="1" max="5" value={spec.rules.maxGoalCells} disabled={spec.rules.exitKind === 'single'} onChange={e => updateRules({ maxGoalCells: number(e.target.value) })} /></label>
            <label className="span2">保存目录<div className="input-action"><input value={spec.directory} onChange={e => setSpec({ ...spec, directory: e.target.value })} /><button onClick={() => void window.tallnum.chooseDirectory().then(dir => dir && setSpec(old => ({ ...old, directory: dir })))}>浏览…</button></div></label>
          </div>
          <button className="text-button" onClick={() => setAdvanced(!advanced)}>{advanced ? '收起高级设置' : '展开高级设置'} <span>{advanced ? '⌃' : '⌄'}</span></button>
          {advanced && <div className="advanced"><div className="form-grid"><label className="span2">允许的基 <small>正奇数，不重复</small><div className="tags">{spec.rules.bases.map(x => <span key={x}>{x}<button title={`移除 ${x}`} onClick={() => updateRules({ bases: spec.rules.bases.filter(b => b !== x) })}>×</button></span>)}<input value={baseInput} onChange={e => setBaseInput(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addBase() } }} placeholder="输入后按 Enter" /><button onClick={addBase}>添加</button></div></label><label>成功位置<select value={spec.rules.successSide} disabled={!!spec.rules.exitKind && spec.rules.exitKind !== 'custom'} onChange={e => updateRules({ successSide: e.target.value as 'above' | 'both' })}><option value="above">F 上方紧邻</option><option value="both">F 两侧紧邻</option></select></label></div></div>}
          <ExitRules rules={spec.rules} update={updateRules} />
          <div className="rule-note">{rulesSummary}</div>
        </section>
        <section className="panel"><div className="panel-head"><span className="step">02</span><div><h2>计算流程</h2><p>按概率表值迭代；每阶段输出 36 种待出数状态的成功概率。</p></div><span className="count">{stageCount} 个阶段</span></div>
          <div className="preset-row"><span>预设</span><button onClick={() => setSpec(old => ({ ...old, stages: structuredClone(DEFAULT_STAGE) }))}>默认概率表值迭代</button>{Object.keys(presets).filter(name => presets[name].every(stage => stage.kind === 'vi')).map(name => <button key={name} data-i18n-skip onClick={() => setSpec(old => ({ ...old, stages: structuredClone(presets[name]) }))}>{name}</button>)}<input placeholder="新预设名称" value={presetName} onChange={e => setPresetName(e.target.value)} /><button onClick={savePreset}>保存当前流程</button></div>
          <div className="stages">{spec.stages.map((stage, i) => <div className="stage" key={i}><div className="stage-top"><span className="stage-index">{String(i + 1).padStart(2, '0')}</span><span className={`stage-type ${stage.kind}`}>{stage.kind === 'vi' ? '概率表值迭代' : '历史策略表阶段'}</span><div className="stage-actions"><button title="上移" onClick={() => moveStage(i, -1)}>↑</button><button title="下移" onClick={() => moveStage(i, 1)}>↓</button><button title="删除" disabled={spec.stages.length <= 1} onClick={() => setSpec(old => ({ ...old, stages: old.stages.filter((_, j) => j !== i) }))}>×</button></div></div>
            {stage.kind === 'vi' ? <div className="stage-fields"><label>最大迭代轮数<input type="number" min="1" value={stage.rounds} onChange={e => updateStage(i, { rounds: number(e.target.value) })} /></label><label>单轮最大变化阈值<input type="number" step="any" value={stage.tolerance} onChange={e => updateStage(i, { tolerance: number(e.target.value) })} /></label><p>达到阈值后进入下一阶段。</p></div> : <p>历史策略表阶段不能用于新任务。</p>}
          </div>)}</div>
          <div className="flow-footer"><div><button onClick={() => setSpec(old => ({ ...old, stages: [...old.stages, { kind: 'vi', rounds: 2000, tolerance: 1e-9 }] }))}>＋ VI 阶段</button></div><label>重复整套流程 <input type="number" min="1" max="100" value={spec.repeats} onChange={e => setSpec({ ...spec, repeats: number(e.target.value) })} /> 次</label></div>
        </section>
      </>}
      {view === 'jobs' && <><header className="page-header"><div><span className="eyebrow">LOCAL JOBS</span><h1>计算任务</h1><p>任务按创建顺序串行运行。关闭窗口后可从托盘重新打开。</p></div><button className="primary" onClick={() => setView('new')}>＋ 新建任务</button></header><div className="job-layout"><section className="panel job-list"><h2>任务列表</h2>{jobs.length === 0 && <p className="empty">还没有任务。先创建一次计算。</p>}{jobs.map(job => <button key={job.id} className={`job-item ${selected === job.id ? 'selected' : ''}`} onClick={() => setSelected(job.id)}><div><strong data-i18n-skip>{job.spec.name}</strong><span className={`status ${job.status}`}>{statusText[job.status]}</span></div><small>{job.spec.rules.cells} 格 · 目标 {job.spec.rules.target} · {new Date(job.createdAt).toLocaleString()}</small><b>{job.results.at(-1)?.pendingProbabilities?.length ? '36 种待出数状态' : '等待概率表'}</b></button>)}</section><section className="panel job-detail">{current ? <><div className="detail-title"><div><span className="eyebrow">JOB DETAIL</span><h2 data-i18n-skip>{current.spec.name}</h2></div><span className={`status ${current.status}`}>{statusText[current.status]}</span></div><div className="metrics"><div><small>待出数状态</small><strong>{current.results.at(-1)?.pendingProbabilities?.length ?? '—'}</strong></div><div><small>状态数</small><strong>{current.states?.toLocaleString() ?? '—'}</strong></div><div><small>值迭代轮次</small><strong>{current.round || '—'}</strong></div><div><small>对应残差 / 变化</small><strong>{current.residual?.toExponential(3) ?? '—'}</strong></div></div><p className="rule-note">激进度 {current.spec.rules.aggressiveness ?? 0} · 每个未成功出数步猝死率 {pct((current.spec.rules.aggressiveness ?? 0) * 7.5 / current.spec.rules.target)} · 成功步免除猝死。此参数偏向快速成功，不保证指定平均步数。</p><p className="phase">{current.phase}{current.startedAt && ` · 已用 ${Math.round(((current.elapsedMs ?? 0) + (current.segmentStartedAt ? Math.max(0, Date.now() - new Date(current.segmentStartedAt).getTime()) : 0)) / 60000)} 分钟`}</p>{current.error && <p className="error-inline">{current.error}</p>}<div className="toolbar">{current.status === 'running' && <button onClick={() => void action(() => window.tallnum.pause(current.id))}>暂停</button>}{(current.status === 'paused' || current.status === 'failed') && <button onClick={() => void action(() => window.tallnum.resume(current.id))}>继续</button>}{['queued', 'running', 'paused'].includes(current.status) && <button onClick={() => void action(() => window.tallnum.cancel(current.id))}>取消</button>}<button onClick={() => void action(() => window.tallnum.openDirectory(current.id))}>打开任务目录</button><button onClick={() => void action(() => window.tallnum.openReplay())}>打开回放 HTML</button><button onClick={() => void action(async () => setLogs(await window.tallnum.logs(current.id)))}>读取日志</button><button onClick={() => void action(() => window.tallnum.exportResult(current.id, 'json'))}>导出 JSON</button><button onClick={() => void action(() => window.tallnum.exportResult(current.id, 'csv'))}>导出 CSV</button></div><h3>阶段结果：待出数状态成功概率</h3><div className="results">{current.results.map((r, i) => <div key={i}><span>阶段 {r.stage + 1} · {r.kind.toUpperCase()} · 第 {r.round} 轮</span><PendingMatrix result={r} /><small>{r.stopReason} · 残差 {r.residual?.toExponential(3) ?? '—'} · {(r.elapsedMs / 1000).toFixed(1)} 秒</small></div>)}</div><details><summary>规则与流程</summary><pre>{JSON.stringify(current.spec, null, 2)}</pre></details><details><summary>阶段日志</summary>{logs.length === 0 ? <p>点击「读取日志」查看最近的日志内容。</p> : logs.map(log => <div key={log.name}><strong>{log.name}</strong><pre>{log.text}</pre></div>)}</details></> : <div className="empty">选择左侧任务查看详情。</div>}</section></div></>}
      {view === 'compare' && <>
        <header className="page-header"><div><span className="eyebrow">RESULT COMPARISON</span><h1>结果对比</h1><p>可选择不同任务，或同一任务的不同阶段结果。</p></div></header>
        <section className="panel">
          <div className="compare-select">
            {([0, 1] as const).map(side => {
              const job = side === 0 ? first : second
              return <Localized key={side}><div>
                <label>{side === 0 ? '基准任务' : '对比任务'}<select value={compareIds[side]} onChange={e => { const next: [string, string] = [...compareIds]; next[side] = e.target.value; setCompareIds(next); const rounds: [number, number] = [...compareRounds]; rounds[side] = -1; setCompareRounds(rounds) }}><option value="">请选择</option>{jobs.map(j => <option data-i18n-skip key={j.id} value={j.id}>{j.spec.name}</option>)}</select></label>
                {job && <label>阶段结果<select value={compareRounds[side]} onChange={e => { const rounds: [number, number] = [...compareRounds]; rounds[side] = Number(e.target.value); setCompareRounds(rounds) }}><option value={-1}>最新结果</option>{job.results.map((result, i) => <option key={i} value={i}>阶段 {result.stage + 1} · {result.kind.toUpperCase()} · 第 {result.round} 轮</option>)}</select></label>}
              </div></Localized>
            })}
          </div>
          {first && second && <><PendingComparison first={firstResult} second={secondResult} /><div className="comparison"><p>激进度：{first.spec.rules.aggressiveness ?? 0} / {second.spec.rules.aggressiveness ?? 0}；非零时成功概率包含猝死风险。</p><p>规则差异：{JSON.stringify(first.spec.rules) === JSON.stringify(second.spec.rules) ? '相同' : '不同，请核对各任务规则'}</p></div></>}
        </section>
      </>}

      {view === 'settings' && <><header className="page-header"><div><span className="eyebrow">PREFERENCES</span><h1>设置</h1><p>设置仅保存在本机。</p></div></header><section className="panel settings-panel"><label>检查点间隔（秒）<input type="number" min="10" max="3600" value={settings.checkpointSeconds} onChange={e => setSettings({ ...settings, checkpointSeconds: number(e.target.value) })} /></label><label>默认保存目录<div className="input-action"><input value={settings.defaultDirectory} onChange={e => setSettings({ ...settings, defaultDirectory: e.target.value })} /><button onClick={() => void window.tallnum.chooseDirectory().then(dir => dir && setSettings({ ...settings, defaultDirectory: dir }))}>浏览…</button></div></label><button className="primary" onClick={() => void action(async () => { await window.tallnum.setSettings(settings); setSpec(old => ({ ...old, directory: settings.defaultDirectory })) })}>保存设置</button></section></>}
    </main>
  </div></Localized>
}


const pendingNumbers = [2, 4, 6, 8, 10, 15]

function PendingMatrix({ result }: { result: StageResult | undefined }): React.JSX.Element {
  const rows = result?.pendingProbabilities
  if (!rows?.length) return <Localized><p className="empty">尚无待出数状态概率。旧策略表结果请新建概率表任务重新计算。</p></Localized>
  const byState = new Map(rows.map(row => [`${row.q1}:${row.q2}`, row.probability]))
  return <Localized><div className="pending-scroll"><table className="pending-table"><caption>两枚可见待出数对应的成功概率</caption><thead><tr><th>第一枚 ↓ / 第二枚 →</th>{pendingNumbers.map(q => <th key={q}>{q}</th>)}</tr></thead><tbody>{pendingNumbers.map(q1 => <tr key={q1}><th>{q1}</th>{pendingNumbers.map(q2 => <td key={q2}>{pct(byState.get(`${q1}:${q2}`))}</td>)}</tr>)}</tbody></table></div></Localized>
}

function PendingComparison({ first, second }: { first: StageResult | undefined; second: StageResult | undefined }): React.JSX.Element {
  if (!first?.pendingProbabilities?.length || !second?.pendingProbabilities?.length)
    return <Localized><p className="empty">请选择两个有待出数状态概率的阶段。</p></Localized>
  const secondValues = new Map(second.pendingProbabilities.map(row => [`${row.q1}:${row.q2}`, row.probability]))
  return <Localized><div className="pending-scroll"><table className="pending-table"><caption>各待出数状态：基准 / 对比 / 提升百分点</caption><thead><tr><th>第一枚</th><th>第二枚</th><th>基准</th><th>对比</th><th>提升百分点</th></tr></thead><tbody>{first.pendingProbabilities.map(row => {
    const value = secondValues.get(`${row.q1}:${row.q2}`)
    return <Localized key={`${row.q1}:${row.q2}`}><tr><td>{row.q1}</td><td>{row.q2}</td><td>{pct(row.probability)}</td><td>{pct(value)}</td><td>{value == null ? '—' : ((value - row.probability) * 100).toFixed(8)}</td></tr></Localized>
  })}</tbody></table></div></Localized>
}

createRoot(document.getElementById('root')!).render(<LocaleProvider><App /></LocaleProvider>)
