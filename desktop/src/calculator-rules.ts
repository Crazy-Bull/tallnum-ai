import type { Rules } from './shared'

export function normalizeRules(r: Rules): Rules {
  return { ...r, exitKind: r.exitKind ?? 'custom', allBases: r.allBases ?? false,
    successNoExtraCombos: r.successNoExtraCombos ?? true, matchEdgeGuard: r.matchEdgeGuard ?? false,
    singleEdgeGuard: r.singleEdgeGuard ?? false, singleTidyExit: r.singleTidyExit ?? false }
}

export function validateExitRules(input: Rules): void {
  const r = normalizeRules(input)
  if (!['custom', 'single', 'match', 'extend'].includes(r.exitKind!)) throw new Error('定式出口类型无效')
  for (const key of ['allBases', 'successNoExtraCombos', 'matchEdgeGuard', 'singleEdgeGuard', 'singleTidyExit'] as const)
    if (typeof r[key] !== 'boolean') throw new Error(`${key} 必须为布尔值`)
  if (r.exitKind === 'single' && r.maxGoalCells !== 1) throw new Error('single 出口要求目标块占 1 格')
  if (r.exitKind === 'extend' && r.maxGoalCells > 4) throw new Error('extend 出口最多占 4 格，预留一格用于衔接')
  if (r.exitKind !== 'custom' && (!r.successNoExtraCombos || r.successSide !== 'above')) throw new Error('定式出口要求干净出口且位于 F 上方')
  if (r.matchEdgeGuard && r.exitKind !== 'match') throw new Error('match 边界保护要求 match 出口')
  if ((r.singleEdgeGuard || r.singleTidyExit) && (r.exitKind !== 'single' || r.cells !== 6 || !r.successNoExtraCombos))
    throw new Error('single 边界保护和整洁出口仅支持六格、干净、单格目标模型')
}

export function generatorRuleArgs(input: Rules): string[] {
  const r = normalizeRules(input)
  validateExitRules(r)
  return ['--cells', String(r.cells), '--target', String(r.target), '--max-value', String(r.maxValue ?? r.target),
    '--max-goal-cells', String(r.maxGoalCells), '--bases', r.allBases ? 'all' : r.bases.join(','), '--success-side', r.successSide,
    '--success-no-extra-combos', r.successNoExtraCombos ? '1' : '0', '--match-edge-guard', r.matchEdgeGuard ? '1' : '0',
    '--single-edge-guard', r.singleEdgeGuard ? '1' : '0', '--single-tidy-exit', r.singleTidyExit ? '1' : '0']
}

export function assertModelRules(model: Record<string, unknown>, input: Rules): void {
  const r = normalizeRules(input)
  if (model.maxValue !== (r.maxValue ?? r.target)) throw new Error('转移表的最大出现数字与任务不一致')
  for (const key of ['successNoExtraCombos', 'matchEdgeGuard', 'singleEdgeGuard', 'singleTidyExit'] as const)
    if (model[key] !== r[key]) throw new Error(`转移表规则 ${key} 与任务不一致，请重新生成`)
}
