import React, { useEffect, useState } from 'react'
import type { Peak13Status, Peak13Step } from '../../shared'

const describe = (blocks: Peak13Step['before']): string => blocks.map(([value, span, group]) =>
  group ? `组合 ${value}（${span} 格）` : String(value)).join(' · ') || '空盘面'
const action = (step: Peak13Step): string => step.kind === 'leaf'
  ? `${step.policyCells} 格 ${step.target} ${step.exit === 'single' ? '生成' : step.exit === 'match' ? '配对' : '补齐'}`
  : step.kind === 'group' ? '连接组合成员' : step.kind === 'edge' ? '边缘合并' : '盘面连接'
const validTemplate = (key: string): boolean => {
  const match = /^(\d+):(\d+):(single|match|extend)$/.exec(key)
  if (!match) return false
  const cells = Number(match[1]), target = Number(match[2])
  return cells >= 5 && cells <= 255 && target >= 24 && target <= 65535
}

export function Peak13Planner(): React.JSX.Element {
  const [request, setRequest] = useState({ target: 10240, cells: 10, directory: '', nodeLimit: 100000 })
  const [status, setStatus] = useState<Peak13Status | null>(null)
  const [error, setError] = useState('')
  const [visible, setVisible] = useState(30)
  const [peakOnly, setPeakOnly] = useState(true)
  const [catalogTemplates, setCatalogTemplates] = useState<string[]>([])
  const [customTemplates, setCustomTemplates] = useState<string[] | null>(null)
  const [newTemplate, setNewTemplate] = useState('')
  useEffect(() => {
    let disposed = false
    const refresh = async (): Promise<void> => {
      try { const next = await window.tallnum.peak13Status(); if (!disposed) setStatus(next) }
      catch (e) { if (!disposed) setError(String(e)) }
    }
    void refresh()
    void window.tallnum.peak13Templates().then(keys => { if (!disposed) setCatalogTemplates(keys) }).catch(e => { if (!disposed) setError(String(e)) })
    const timer = setInterval(() => void refresh(), 700)
    return () => { disposed = true; clearInterval(timer) }
  }, [])
  const run = async (): Promise<void> => {
    setError(''); setVisible(30); setPeakOnly(customTemplates === null && request.cells === 10 && request.target === 10240)
    try { await window.tallnum.peak13Start({ ...request, allowedTemplates: customTemplates }); setStatus(await window.tallnum.peak13Status()) }
    catch (e) { setError(String(e)) }
  }
  const steps = (status?.route?.steps || []).map((step, index) => ({ ...step, index: index + 1 }))
    .filter(step => !peakOnly || step.template?.startsWith(`5:${status?.report?.maximumFiveCellTarget}:`))
  const validation = status?.validation
  const highestTemplate = status?.report?.maximumFiveCellTarget ? `五格 ${status.report.maximumFiveCellTarget}` : '未使用五格定式'
  const addTemplate = (): void => {
    const key = newTemplate.trim()
    if (!validTemplate(key)) {
      setError('定式格式须为 格数:目标:出口，例如 5:80:single；至少五格，目标至少 24')
      return
    }
    setCustomTemplates([...new Set([...(customTemplates || []), key])].sort())
    setNewTemplate(''); setError('')
  }
  return <>
    <header className="page-header"><div><span className="eyebrow">PROBABILITY ROUTE PLANNER</span><h1>概率表路线规划</h1><p>先降低最高五格定式，再减少该阶调用次数。通过动态规划复用构造，输出前核对完整盘面和概率表。</p></div></header>
    {(error || status?.error) && <div className="error" role="alert">{error || status?.error}</div>}
    <section className="panel"><h2>生成路线</h2><p className="phase">定式至少 5 格、目标至少 24；定式目标上限由数值范围与用户选择决定。搜索只使用待出数状态概率表；路线的随机成功率须另行实测。</p>
      <fieldset disabled={status?.busy} className="planner-fields"><div className="form-grid peak13-form">
        <label>塔容量<input aria-label="概率路线塔容量" type="number" min="1" max="255" value={request.cells} onChange={e => setRequest({ ...request, cells: Number(e.target.value) })} /></label>
        <label>普通单块目标<input aria-label="概率路线目标" type="number" min="2" max="65535" value={request.target} onChange={e => setRequest({ ...request, target: Number(e.target.value) })} /></label>
        <label>搜索预算<input aria-label="概率路线搜索预算" type="number" min="1" max="1000000" value={request.nodeLimit} onChange={e => setRequest({ ...request, nodeLimit: Number(e.target.value) })} /></label>
        <label>结果目录<input aria-label="概率路线结果目录" value={request.directory} placeholder="留空使用应用目录" onChange={e => setRequest({ ...request, directory: e.target.value })} /></label>
      </div></fieldset>
      <fieldset disabled={status?.busy} className="template-picker"><legend>允许使用的定式（至少五格）</legend>
        <div className="toolbar"><button aria-pressed={customTemplates === null} onClick={() => setCustomTemplates(null)}>默认：全部已有定式</button><button aria-pressed={customTemplates !== null} onClick={() => setCustomTemplates(customTemplates || [...catalogTemplates])}>自选定式</button></div>
        {customTemplates !== null && <><p className="phase">只搜索勾选的目标与出口；可加入尚无概率表的定式，结果会明确报告缺口。</p>
          <div className="template-options">{[...new Set([...catalogTemplates, ...customTemplates])].sort((a, b) => Number(a.split(':')[0]) - Number(b.split(':')[0]) || Number(a.split(':')[1]) - Number(b.split(':')[1]) || a.localeCompare(b)).map(key => <label key={key}><input type="checkbox" checked={customTemplates.includes(key)} onChange={e => setCustomTemplates(e.target.checked ? [...customTemplates, key] : customTemplates.filter(item => item !== key))} />{key}{!catalogTemplates.includes(key) && <small>缺表</small>}</label>)}</div>
          <div className="input-action template-add"><input aria-label="添加定式" placeholder="例如 7:96:single" value={newTemplate} onChange={e => setNewTemplate(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTemplate() } }} /><button onClick={addTemplate}>添加定式</button></div>
          <p className="phase">已允许 {customTemplates.length} 种定式。</p></>}
      </fieldset>
      <div className="toolbar"><button className="primary" disabled={status?.busy || customTemplates?.length === 0 || !Number.isInteger(request.cells) || request.cells < 1 || request.cells > 255 || !Number.isInteger(request.target) || request.target < 2 || request.target > 65535 || !Number.isInteger(request.nodeLimit) || request.nodeLimit < 1} onClick={() => void run()}>{status?.busy ? '正在搜索…' : '生成路线'}</button><button disabled={!status?.busy} onClick={() => void window.tallnum.peak13Stop().catch(e => setError(String(e)))}>停止</button></div>
      <p className="phase" aria-live="polite">{status?.message}</p>
    </section>
    {!status?.route && status?.report && <section className="panel"><h2>搜索结果</h2><p>{status.report.reason || status.report.status}</p>{!!status.report.missingProbabilityTables?.length && <p>待补的目标定式概率表：{status.report.missingProbabilityTables.join('、')}</p>}<p className="rule-note">此结果只针对所选定式与搜索范围；无法构造不等于游戏无解。预算耗尽表示结果尚未确定。</p></section>}
    {status?.route && status.report && <><section className="panel"><h2>{status.report.status === 'missing-probability-tables' ? '结构路线（待补概率表）' : '路线结果'}</h2>{status.report.status === 'missing-probability-tables' && <p className="rule-note">{status.report.reason} 缺少：{status.report.missingProbabilityTables?.join('、')}。结构保存在 {status.directory} 的 structural-route.json；目前不可执行。</p>}<div className="metrics planner-metrics">
      <div><small>最高阶五格调用</small><strong>{status.report.highestFiveCellCalls ?? Object.entries(status.report.leafCounts || {}).filter(([key]) => key.startsWith(`5:${status.report?.maximumFiveCellTarget}:`)).reduce((total, [, count]) => total + count, 0)}</strong></div>
      <div><small>最高阶五格定式</small><strong>{highestTemplate}</strong></div>
      <div><small>100 局实测成功</small><strong>{validation ? `${validation.successes} / ${validation.attempts}` : '未认证'}</strong></div>
      <div><small>成功局最高阶调用最多</small><strong>{validation ? (validation.maximumSuccessfulHighestFiveCellCalls ?? validation.maximumSuccessfulFive64Calls) : '—'}</strong></div>
    </div><p className="rule-note">{validation ? `概率表模拟成功率 ${(validation.successRate * 100).toFixed(0)}%；原游戏引擎${validation.originalEngineVerified ? '已核验 100 局回放' : '尚未核验回放'}。保命回退的额外调用不计入规划主路线次数。此结果只对应与受测路线完全一致的版本。` : status.report.status === 'missing-probability-tables' ? '仅完成理想出口的结构核验；补齐待出数概率表后方可执行。' : `该路线仅核对理想出口与概率表定式契约，尚未经过整局随机成功率测试。${status.report.lexicographicOrderProvenInScope ? '在当前目录及搜索范围内，最高阶优先、次数其次的目标已证明最优。' : '最优性尚未证明，可增加搜索预算。'}`} 完整路线和搜索报告保存在 {status.directory}</p>
      <details><summary>定式调用分布</summary><div className="planner-profile">{Object.entries(status.report.leafCounts || {}).map(([key, count]) => <span key={key}>{key} · {count} 次</span>)}</div></details>
    </section><section className="panel"><h2>合成步骤</h2><div className="toolbar"><button aria-pressed={peakOnly} onClick={() => { setPeakOnly(true); setVisible(30) }}>只看最高阶五格</button><button aria-pressed={!peakOnly} onClick={() => { setPeakOnly(false); setVisible(30) }}>全部步骤</button><span>{steps.length} 步</span></div>
      <ol className="planner-steps">{steps.slice(0, visible).map(step => <li key={step.index}><strong>第 {step.index} 步 · {action(step)}</strong><p>{describe(step.before)} → {describe(step.after)}</p></li>)}</ol>
      {visible < steps.length && <button onClick={() => setVisible(visible + 100)}>再显示 100 步</button>}
    </section></>}
  </>
}
