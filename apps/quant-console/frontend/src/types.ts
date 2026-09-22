export type Metric = { value: number | string | null; unit: string; validity: string; unavailable_reason: string | null }
export type Experiment = {
  artifact_id: string
  evidence_id: string
  study_id: string
  experiment_id: string
  strategy_id: string
  family: string
  scenario_id: string
  data_evaluability: string
  benchmark_comparability: string
  economic_outcome: string
  engineering_status: string
  research_validity: string
  data_use_level: string
  metrics: Record<string, Metric>
  failure_reason: string | null
  period: { start: string; end: string; sessions: number } | null
  nav_series?: Array<{ date: string; nav: string }> | null
  calendar_year_returns?: Record<string, number> | null
  turnover_costs?: unknown
  execution?: unknown
  limitations?: string[]
}
export type Overview = {
  snapshot_id: string
  current_stage: string
  registered_runs: number
  valid_runs: number
  not_evaluable_runs: number
  retained_candidates: number
  legacy_invalid_engineering_runs: number
  economic_outcome: string
  latest_prospective_date: string | null
  prospective_status: string
  warnings: string[]
}
