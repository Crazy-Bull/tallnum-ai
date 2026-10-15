export type Stage =
  | { kind: 'vi'; rounds: number; tolerance: number }
  | { kind: 'petsc'; rounds: number; algorithm: 'dgmres' | 'gmres' | 'fgmres'; maxKsp: number; rtol: number; atol: number; restart: number; preconditioner: 'jacobi' | 'none' | 'ilu' }

export interface Rules {
  cells: number
  exitKind?: 'custom' | 'single' | 'match' | 'extend'
  allBases?: boolean
  successNoExtraCombos?: boolean
  matchEdgeGuard?: boolean
  singleEdgeGuard?: boolean
  singleTidyExit?: boolean
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
  pendingProbabilities?: Array<{ q1: number; q2: number; probability: number }>
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
  { kind: 'vi', rounds: 5000, tolerance: 1e-9 }
]

export interface DesktopApi {
  peak13Status(): Promise<Peak13Status>
  peak13Templates(): Promise<string[]>
  peak13Start(request: { target: number; cells: number; directory: string; nodeLimit: number; allowedTemplates: string[] | null }): Promise<void>
  peak13Stop(): Promise<void>
  integerPlannerStatus(): Promise<IntegerPlannerStatus>
  integerPlannerStart(request: IntegerPlannerRequest): Promise<void>
  integerPlannerStop(): Promise<void>
  automationStatus(): Promise<AutomationStatus>
  automationStart(request: AutomationRequest): Promise<void>
  automationControl(mode: 'run' | 'paused' | 'step' | 'stop'): Promise<void>
  automationStop(): Promise<void>
  list(): Promise<Job[]>
  create(spec: JobSpec): Promise<Job>
  pause(id: string): Promise<void>
  resume(id: string): Promise<void>
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

export interface Peak13Step {
  kind: string
  before: Array<[number, number, boolean]>
  after: Array<[number, number, boolean]>
  template?: string
  target?: number
  policyCells?: number
  exit?: string
}
export interface Peak13Status {
  busy: boolean
  directory: string
  message: string
  error: string | null
  route: { target: number; cells: number; steps: Peak13Step[] } | null
  report: { status?: string; reason?: string; missingProbabilityTables?: string[]; five64Calls?: number; highestFiveCellCalls?: number; maximumFiveCellTarget?: number; highestTemplate?: string; rescueFive64Policies?: string[]; leafCounts?: Record<string, number>; randomExecutionVerified?: boolean; searchStatus?: string; lexicographicOrderProvenInScope?: boolean } | null
  validation: { attempts: number; successes: number; successRate: number; maximumSuccessfulFive64Calls: number; maximumSuccessfulHighestFiveCellCalls?: number; originalEngineVerified: boolean } | null
}

export interface IntegerPlannerRequest {
  target: number
  cells: 7 | 10
  ceiling: number | null
  directory: string
  maximum: number
  edgeDepth: number
  nodeLimit: number
  focusNodes: number
}
export interface IntegerPlannerResult {
  target: number
  cells: number
  status: 'proven' | 'candidate' | 'incomplete' | 'no-route'
  ceiling: number | null
  upperBound: number | null
  lowerBound: number | null
  countProven: boolean
  peakProven: boolean
  leafCalls: number
  proofStates?: number
  profile: Array<{ cells: number; target: number; count: number }>
  steps: Array<{ kind: string; target?: number; exit?: string; template?: string; policyCells?: number; availableCells?: number; before: Array<[number, number, boolean]>; after: Array<[number, number, boolean]> }>
  scope: { maximum: number; edgeDepth: number; minimumTemplateTarget?: number }
  randomExecutionVerified: false
  executionRisks?: Array<{ step: number; template: string; fixedTotal: number; unlockThreshold: number }>
}
export interface IntegerPlannerStatus {
  busy: boolean
  directory: string
  message: string
  error: string | null
  result: IntegerPlannerResult | null
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
