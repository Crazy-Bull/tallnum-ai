export type PendingProbability = { q1: number; q2: number; probability: number }

const SPAWN = [2, 4, 6, 8, 10, 15]

export function readPendingProbabilities(csv: string, weighted: number): PendingProbability[] {
  const lines = csv.trim().split(/\r?\n/)
  if (lines.shift() !== 'q1,q2,weight,value' || lines.length !== 36) throw new Error('待出数概率文件格式无效')
  const rows = lines.map((line, index) => {
    const fields = line.split(',')
    if (fields.length !== 4) throw new Error('待出数概率文件列数无效')
    const [q1, q2, weight, probability] = fields.map(Number)
    if (q1 !== SPAWN[Math.floor(index / 6)] || q2 !== SPAWN[index % 6] ||
        Math.abs(weight - 1 / 36) > 1e-12 || !Number.isFinite(probability) ||
        probability < -1e-9 || probability > 1 + 1e-9)
      throw new Error('待出数概率文件包含无效状态')
    return { q1, q2, probability: Math.max(0, Math.min(1, probability)) }
  })
  const mean = rows.reduce((sum, row) => sum + row.probability / 36, 0)
  if (!Number.isFinite(weighted) || Math.abs(mean - weighted) > 1e-8)
    throw new Error('待出数概率与值迭代结果不一致')
  return rows
}
