export type Stage =
  | { kind: 'vi'; rounds: number; tolerance: number }
  | { kind: 'petsc'; rounds: number; algorithm: 'dgmres' | 'gmres' | 'fgmres'; maxKsp: number; rtol: number; atol: number; restart: number; preconditioner: 'jacobi' | 'none' | 'ilu' }

export interface Rules {
  cells: number
  maxValue?: number
  target: number
  aggressiveness: number
  maxGoalCells: number
  bases: number[]
  successSide: 'above' | 'both'
}

export interface JobSpec {
  name: string
  directory: string
  rules: Rules
  stages: Stage[]
  repeats: number
}

export interface StageResult {
  stage: number
  kind: Stage['kind']
  round: number
  probability: number
  residual: number | null
  kspIterations?: number
  elapsedMs: number
  stopReason: string
  valuesFile: string
  policyFile?: string
}

export interface Job {
  coreVersion?: string
  id: string
  spec: JobSpec
  status: 'queued' | 'running' | 'pausing' | 'paused' | 'completed' | 'failed' | 'cancelled'
  phase: string
  stageIndex: number
  round: number
  kspIteration?: number | null
  states: number | null
  probability: number | null
  residual: number | null
  createdAt: string
  startedAt?: string
  elapsedMs?: number
  segmentStartedAt?: string
  endedAt?: string
  error?: string
  results: StageResult[]
  history: Array<{ time: string; probability: number; residual: number | null; stage: number }>
}

export const DEFAULT_STAGE: Stage[] = [
  { kind: 'vi', rounds: 5000, tolerance: 1e-9 },
  { kind: 'petsc', rounds: 3, algorithm: 'dgmres', maxKsp: 2000, rtol: 1e-10, atol: 1e-14, restart: 50, preconditioner: 'jacobi' }
]

export interface DesktopApi {
  automationStatus(): Promise<AutomationStatus>
  automationStart(request: AutomationRequest): Promise<void>
  automationControl(mode: 'run' | 'paused' | 'step' | 'stop'): Promise<void>
  automationStop(): Promise<void>
  list(): Promise<Job[]>
  create(spec: JobSpec): Promise<Job>
  pause(id: string): Promise<void>
  resume(id: string): Promise<void>
  updateBudget(id: string, budget: { maxKsp: number; rtol: number; atol: number; restart: number }): Promise<void>
  cancel(id: string): Promise<void>
  chooseDirectory(): Promise<string | null>
  openDirectory(id: string): Promise<void>
  openReplay(path?: string): Promise<void>
  logs(id: string): Promise<Array<{ name: string; text: string }>>
  exportResult(id: string, type: 'json' | 'csv'): Promise<string | null>
  getSettings(): Promise<{ checkpointSeconds: number; defaultDirectory: string }>
  setSettings(settings: { checkpointSeconds: number; defaultDirectory: string }): Promise<void>
  onJobs(callback: (jobs: Job[]) => void): () => void
}

export interface AutomationRequest {
  plannerVersion?: 1 | 2
  command: 'plan' | 'prepare' | 'validate' | 'play'
  directory: string
  target: number
  rounds: number
  attempts: number
}
export interface AutomationStatus {
  busy: boolean
  command: string
  directory: string
  events: Array<Record<string, unknown>>
  error: string | null
  plan: { status: string; target: number; routes: Array<{ id: string; metrics: { expectedTotalDrops: number | null } }>; missing: Array<{ key: string; target: number; exit: string }>; triples?: Record<string, { a: number; b: number }> } | null
  validation: { verified: boolean; selectedRoute: string | null; rankingUncertain: boolean; results: Array<{ routeId: string; expectedTotalDrops: number | null; successRate: number; incompatible: number; unfinished: number }> } | null
}
