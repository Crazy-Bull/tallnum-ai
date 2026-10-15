import React, { useEffect, useState } from 'react'
import type { IntegerPlannerRequest, IntegerPlannerStatus } from '../../shared'

const exits: Record<string, string> = { single: '生成', match: '配对', extend: '补齐' }
const board = (blocks: Array<[number, number, boolean]>): string => blocks.length
  ? blocks.map(([v, span, group]) => group ? `Group(${v}，${span}格)` : String(v)).join(' · ') : '空盘面'

export function IntegerPlanner(): React.JSX.Element {
  const [request, setRequest] = useState<IntegerPlannerRequest>({ target: 10240, cells: 10, ceiling: null,
    directory: '', maximum: 20480, edgeDepth: 5, nodeLimit: 3000, focusNodes: 10000 })
  const [status, setStatus] = useState<IntegerPlannerStatus | null>(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [all, setAll] = useState(false)
  const [visible, setVisible] = useState(50)
  useEffect(() => {
    let disposed = false, fetching = false
    const refresh = async (): Promise<void> => {
      if (fetching) return
      fetching = true
      try { const next = await window.tallnum.integerPlannerStatus(); if (!disposed) setStatus(next) }
      catch (e) { if (!disposed) setError(String(e)) }
      finally { fetching = false }
    }
    void refresh(); const timer = setInterval(() => void refresh(), 700)
    return () => { disposed = true; clearInterval(timer) }
  }, [])
  const run = async (): Promise<void> => {
    setError(''); setStarting(true); setVisible(50)
    try { await window.tallnum.integerPlannerStart(request); setStatus(await window.tallnum.integerPlannerStatus()) }
    catch (e) { setError(String(e)) }
    finally { setStarting(false) }
  }
  const busy = starting || !!status?.busy, result = status?.result
  const steps = result?.steps.map((s, i) => ({ ...s, index: i + 1 }))
    .filter(s => all || s.template === `5:${result.ceiling}:${s.exit}`) || []
  const valid = Number.isInteger(request.target) && request.target >= 2 && request.target <= 65535
    && (request.target % 2 === 0 || request.target === 15) && request.maximum >= request.target
  return <>
    <header className="page-header"><div><span className="eyebrow">ROUTE PLANNER</span><h1>大数路线规划</h1><p>优先降低最高阶定式，再减少该阶调用。所有定式均为五格，定式目标至少为 24。</p></div></header>
    {(error || status?.error) && <div className="error" role="alert">{error || status?.error}</div>}
    <section className="panel"><h2>合成目标</h2><fieldset disabled={busy} className="planner-fields"><div className="form-grid">
      <label>目标数<input aria-label="目标数" type="number" min={2} max={65535} value={request.target} onChange={e => {
        const target = Number(e.target.value); setRequest({ ...request, target, maximum: Math.min(65535, Math.max(1024, 10 * target)) })
      }} /><small>支持非标准基，如 1728、54；普通目标须为偶数或 15。</small></label>
      <label>塔容量<select aria-label="塔容量" value={request.cells} onChange={e => setRequest({ ...request, cells: Number(e.target.value) as 7 | 10 })}><option value={7}>七格</option><option value={10}>十格</option></select></label>
      <label>定式上限<select aria-label="定式上限" value={request.ceiling ?? ''} onChange={e => setRequest({ ...request, ceiling: e.target.value ? Number(e.target.value) : null })}><option value="">自动寻找最低上限</option>{[24,32,40,48,60,64,80,96,128].map(v => <option key={v} value={v}>五格 {v} 及以下</option>)}</select></label>
      <label>保存目录<div className="input-action"><input aria-label="保存目录" placeholder="留空使用应用默认目录" value={request.directory} onChange={e => setRequest({ ...request, directory: e.target.value })} /><button onClick={() => void window.tallnum.chooseDirectory().then(directory => directory && setRequest({ ...request, directory })).catch(e => setError(String(e)))}>选择</button></div></label>
    </div><details><summary>搜索范围与预算</summary><div className="form-grid advanced">
      {([['maximum','中间数上限',request.target,65535],['edgeDepth','EDGE 嵌套深度',0,8],['nodeLimit','构造搜索预算',1,1000000],['focusNodes','每个子任务优化预算',1,1000000]] as const).map(([key,label,min,max]) => <label key={key}>{label}<input type="number" min={min} max={max} value={request[key]} onChange={e => setRequest({ ...request, [key]: Number(e.target.value) })} /></label>)}
    </div><p>预算耗尽保留候选；下界独立核对。相同参数可复用缓存。</p></details></fieldset>
      <div className="toolbar"><button className="primary" disabled={busy || !valid} onClick={() => void run()}>{busy ? '正在规划…' : '开始规划'}</button><button disabled={!status?.busy} onClick={() => void window.tallnum.integerPlannerStop().catch(e => setError(String(e)))}>停止计算</button></div>
      <p className="phase" aria-live="polite">{status?.message}</p>
    </section>
    {result && <><section className="panel"><h2>目标 {result.target} · {result.cells} 格</h2>
      <p>{result.status === 'proven' ? '该最高阶的最少调用数已在模型内证明' : result.status === 'candidate' ? '已有合法候选，最少次数尚未证明' : result.status === 'incomplete' ? '预算内尚未找到路线，可增加预算继续' : '当前范围内未找到路线'}</p>
      <div className="metrics planner-metrics"><div><small>最高使用定式</small><strong>{result.ceiling ? `五格 ${result.ceiling}` : '尚未确定'}</strong></div><div><small>候选调用次数（上界）</small><strong>{result.upperBound ?? '—'}</strong></div><div><small>最少次数下界</small><strong>{result.lowerBound ?? '—'}</strong></div><div><small>全部定式调用数</small><strong>{result.leafCalls || '—'}</strong></div></div>
      <p className="rule-note">{result.peakProven ? '最高定式上限已证明最低。' : '最高定式上限尚未证明最低。'} {result.countProven ? '上下界相等，调用次数证明闭合。' : '上下界尚未闭合。'} 范围：中间数 ≤ {result.scope.maximum}，EDGE 深度 ≤ {result.scope.edgeDepth}。结论适用于当前合成模型；尚未认证随机执行成功率，也未证明全部低阶或总调用数最少。</p>
      {!!result.executionRisks?.length && <div className="error" role="alert">此路线有 {result.executionRisks.length} 个实际抽数风险：例如步骤 {result.executionRisks[0].step} 在固定盘面总值 {result.executionRisks[0].fixedTotal} 时要求五格 60 单块，而数字 15 要到盘面总值达到 {result.executionRisks[0].unlockThreshold} 才解锁。请勿把这条结构路线当作已验证的实战路线。</div>}
      {result.profile.length > 0 && <details><summary>各阶定式调用分布</summary><div className="planner-profile">{result.profile.map(p => <span key={`${p.cells}:${p.target}`}>{p.cells}格 {p.target} · {p.count}次</span>)}</div></details>}
      <p className="phase">完整路线与证明保存至：{status?.directory}</p>
    </section>{result.steps.length > 0 && <section className="panel"><h2>合成步骤</h2><div className="toolbar"><button aria-pressed={!all} onClick={() => { setAll(false); setVisible(50) }}>只看最高阶调用</button><button aria-pressed={all} onClick={() => { setAll(true); setVisible(50) }}>查看全部步骤</button><span>{steps.length} 步</span></div>
      <ol className="planner-steps">{steps.slice(0,visible).map(s => <li key={s.index}><strong>步骤 {s.index} · {s.kind === 'leaf' ? `${s.policyCells}格 ${s.target} ${exits[s.exit || ''] || ''}` : s.kind === 'group' ? '组合普通成员' : 'EDGE 合并'}</strong><p>{board(s.before)} → {board(s.after)}</p>{s.availableCells !== undefined && <small>可用工作格：{s.availableCells}</small>}</li>)}</ol>
      {steps.length > visible && <button onClick={() => setVisible(visible + 100)}>再显示 100 步</button>}
    </section>}</>}
  </>
}
