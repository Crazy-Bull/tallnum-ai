import { Localized } from './i18n'
import React, { useEffect, useState } from 'react'
import type { AutomationRequest, AutomationStatus } from '../../shared'

export function Automation(): React.JSX.Element {
  const [directory, setDirectory] = useState(() => localStorage.getItem('tallnum-automation-directory') || '')
  const [target, setTarget] = useState(768)
  const [plannerVersion, setPlannerVersion] = useState<1 | 2>(1)
  const [rounds, setRounds] = useState(5000)
  const [attempts, setAttempts] = useState(100)
  const [status, setStatus] = useState<AutomationStatus | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    const refresh = (): void => { void window.tallnum.automationStatus().then(s => { if (active) setStatus(s) }).catch(e => { if (active) setError(String(e)) }) }
    refresh(); const timer = setInterval(refresh, 1000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  async function act(fn: () => Promise<unknown>): Promise<void> {
    try { await fn(); setError(''); setStatus(await window.tallnum.automationStatus()) } catch (e) { setError(String(e)) }
  }
  function start(command: AutomationRequest['command']): void {
    localStorage.setItem('tallnum-automation-directory', directory)
    void act(() => window.tallnum.automationStart({ command, directory, target, rounds, attempts, plannerVersion }))
  }
  const busy = !!status?.busy
  return <Localized><>
    <header className="page-header"><div><span className="eyebrow">AUTOMATIC PLAY</span><h1>五格定式组合 · 目标 {target}</h1><p>{plannerVersion === 1 ? '七格二分、六格只取最均衡的一组三分。' : '搜索等值合并、Group 补齐与 EDGE 路线。'}按包含失败重开的总期望出数选择路线。</p></div></header>
    {(error || status?.error) && <p className="error-inline">{error || status?.error}</p>}
    <section className="panel"><h2>路线计算</h2><div className="form-grid">
      <label>规划器<select disabled={busy} value={plannerVersion} onChange={e => setPlannerVersion(Number(e.target.value) as 1 | 2)}><option value={1}>原版定式拆解</option><option value={2}>新版路线搜索</option></select></label>
      <label>最终普通块<input disabled={busy} type="number" min={2} max={65535} value={target} onChange={e => setTarget(Number(e.target.value))} /></label>
      <label>缺失五格策略的 VI 轮数<input disabled={busy} type="number" min={1} value={rounds} onChange={e => setRounds(Number(e.target.value))} /></label>
      <label>每条候选的模拟局数<input disabled={busy} type="number" min={1} value={attempts} onChange={e => setAttempts(Number(e.target.value))} /></label>
      <label className="span2">数据目录<div className="input-action"><input disabled={busy} value={directory} onChange={e => setDirectory(e.target.value)} /><button disabled={busy} onClick={() => void act(async () => { const dir = await window.tallnum.chooseDirectory(); if (dir) setDirectory(dir) })}>浏览…</button></div></label>
    </div><div className="toolbar">
      <button disabled={busy} onClick={() => start('plan')}>检查拆解与缺失定式</button>
      <button disabled={busy} onClick={() => start('prepare')}>补算并规划</button>
      <button disabled={busy || !status?.plan?.routes.length} onClick={() => start('validate')}>完整模拟验证</button>
      <button disabled={!busy} onClick={() => void act(() => window.tallnum.automationStop())}>停止当前任务</button>
    </div><p className="rule-note">小于 48 的子目标使用五格近似。预计算结果重复利用；近似排名需经过真实规则模拟后才能启动自动玩。</p></section>
    <section className="panel"><h2>真实网页执行</h2><div className="toolbar">
      <button disabled={busy || !status?.validation?.verified} onClick={() => start('play')}>连接当前游戏标签页</button>
      <button disabled={!busy || status?.command !== 'play'} onClick={() => void act(() => window.tallnum.automationControl('run'))}>连续运行</button>
      <button disabled={!busy || status?.command !== 'play'} onClick={() => void act(() => window.tallnum.automationControl('paused'))}>暂停</button>
      <button disabled={!busy || status?.command !== 'play'} onClick={() => void act(() => window.tallnum.automationControl('step'))}>单步</button>
    </div><p>直接连接现有 Chrome 游戏标签页，保留登录、盘面和窗口比例，连接后先暂停。首次使用需在 chrome://inspect/#remote-debugging 启用远程调试并允许连接。当前局已开始时先完成当前局。策略无法继续时仍投放至游戏结束；结算面板停留 10 秒，追加本局成功与否、最终投放数及首次达标投放数到 rounds.jsonl，再自动点击“再来一局”。达到 {target} 后，以底层块的虚拟半值继续模拟后半段路线；实际盘面保持原值。暂停可阻止自动重开，输入异常会保留窗口并暂停。</p></section>
    {status?.plan && <section className="panel"><h2>规划结果</h2><p>{status.plan.routes.length} 条非支配候选 · {status.plan.missing.length} 项缺失定式</p>
      <div className="results">{Object.entries(status.plan.triples || {}).map(([t, pair]) => <div key={t}><strong>六格 {t}</strong><span>{pair.a} ＋ {pair.a} ＋ {pair.b}（末项最多四格）</span></div>)}</div>
      {status.plan.missing.length > 0 && <p>待补算：{status.plan.missing.map(m => `${m.target} / ${{ single: '普通单格', match: '相邻合并', extend: '扩展 Group', buffer:'EDGE 配对块' }[m.exit] || m.exit}`).join('；')}</p>}
      {status.plan.routes.slice(0, 5).map((r, i) => <details key={r.id}><summary>候选 {i + 1} · 近似总期望出数 {r.metrics.expectedTotalDrops?.toFixed(2) ?? '无穷'}</summary><pre>{JSON.stringify(r, null, 2)}</pre></details>)}
    </section>}
    {status?.validation && <section className="panel"><h2>模拟复核</h2><p>{status.validation.verified ? '独立验证通过' : '尚未取得可执行的验证结果'}{status.validation.rankingUncertain ? '；候选置信区间重叠，排名尚不能明确区分。' : ''}</p>
      {status.validation.results.map((r, i) => <p key={r.routeId}>候选 {i + 1}：成功率 {(r.successRate * 100).toFixed(2)}% · 总期望出数 {r.expectedTotalDrops?.toFixed(2) ?? '不可估计'} · 不匹配 {r.incompatible} · 未结束 {r.unfinished}</p>)}
    </section>}
    <section className="panel"><h2>运行记录 {busy ? '· 运行中' : ''}</h2><pre>{status?.events.slice(-20).map(e => JSON.stringify(e)).join('\n') || '尚未运行。'}</pre></section>
  </></Localized>
}
