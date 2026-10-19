import { Localized } from './i18n'
import React from 'react'
import type { Rules } from '../../shared'
import { normalizeRules } from '../../calculator-rules'

export function ExitRules({ rules, update }: { rules: Rules; update: (part: Partial<Rules>) => void }): React.JSX.Element {
  const r = normalizeRules(rules)
  function preset(exitKind: Rules['exitKind']): void {
    update({ exitKind, matchEdgeGuard: false, singleEdgeGuard: false, singleTidyExit: false,
      ...(exitKind === 'custom' ? {} : { maxGoalCells: exitKind === 'single' ? 1 : exitKind === 'extend' ? 4 : 5,
        successNoExtraCombos: true, successSide: 'above' }) })
  }
  return <Localized><section className="advanced"><h3>定式出口与边界</h3><div className="form-grid">
    <label>出口预设<select value={r.exitKind} onChange={e => preset(e.target.value as Rules['exitKind'])}>
      <option value="custom">自定义目标</option><option value="single">single · 单格目标</option>
      <option value="match">match · 匹配目标</option><option value="extend">extend · 延伸目标（最多四格）</option>
    </select></label>
    <label>允许的基<select value={r.allBases ? 'all' : 'list'} onChange={e => update({ allBases: e.target.value === 'all' })}>
      <option value="list">使用高级设置中的基列表</option><option value="all">所有基（保留原奇数合成规则）</option>
    </select></label>
    <label>成功时无额外组合块<select value={String(r.successNoExtraCombos)} disabled={r.exitKind !== 'custom'} onChange={e => update({ successNoExtraCombos: e.target.value === 'true' })}><option value="true">开启 · 其他块必须是普通块</option><option value="false">关闭</option></select></label>
    <label>match 边界保护<select value={String(r.matchEdgeGuard)} disabled={r.exitKind !== 'match'} onChange={e => update({ matchEdgeGuard: e.target.value === 'true' })}><option value="false">关闭</option><option value="true">开启 · 防止与同目标锚点发生 EDGE 干扰</option></select></label>
    <label>六格 single 边界保护<select value={String(r.singleEdgeGuard)} disabled={r.exitKind !== 'single' || r.cells !== 6} onChange={e => update({ singleEdgeGuard: e.target.value === 'true' })}><option value="false">关闭</option><option value="true">开启 · 同目标锚点保护</option></select></label>
    <label>六格 single 整洁出口<select value={String(r.singleTidyExit)} disabled={r.exitKind !== 'single' || r.cells !== 6} onChange={e => update({ singleTidyExit: e.target.value === 'true' })}><option value="false">关闭</option><option value="true">开启 · 最多残留一格且数值 ≤ 8</option></select></label>
  </div><p className="rule-note">预设会设置目标占格上限、F 上方成功及无额外组合块。干净出口允许残留普通块；整洁出口按完整物理动作结束后的盘面判定。边界保护假设固定锚点等于目标。extend 预设只限制目标占格，完整衔接仍需路线验证。允许所有基可能显著增加状态数。</p></section></Localized>
}
