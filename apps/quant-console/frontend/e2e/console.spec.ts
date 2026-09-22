import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

declare const process: { env: Record<string, string | undefined> }

const snapshotId = 'a'.repeat(64)
const digest = 'd'.repeat(64)
const evidenceId = 'evidence:demo:one'
const metric = (name: string, value: number | null, unit = 'ratio') => ({
  name,
  value,
  unit,
  validity: value === null ? 'NOT_AVAILABLE' : 'VALID',
  unavailable_reason: value === null ? 'source missing' : null,
  basis: 'source_reported_full_period',
  scenario_id: 'DEMO_T1',
  data_use_level: 'SYNTHETIC',
  source_evidence_id: evidenceId,
})
const experiment = {
  artifact_id: 'demo:one',
  evidence_id: evidenceId,
  study_id: 'demo_study',
  study_revision: digest,
  experiment_id: 'SYNTHETIC_A',
  run_identity: digest,
  strategy_id: 'SYNTHETIC_A',
  family: 'DEMO',
  scenario_id: 'DEMO_T1',
  data_evaluability: 'VALID',
  benchmark_comparability: 'MATCHED_BENCHMARK_NOT_EVALUABLE',
  economic_outcome: 'NOT_EVALUABLE',
  engineering_status: 'PASS',
  research_validity: 'SYNTHETIC',
  data_use_level: 'SYNTHETIC',
  failure_reason: null,
  period: { start: '2025-01-02', end: '2025-01-06', sessions: 3 },
  metrics: {
    cagr: metric('cagr', -0.03),
    total_return: metric('total_return', -0.08),
    annualized_volatility: metric('annualized_volatility', 0.18),
    maximum_drawdown: metric('maximum_drawdown', -0.15),
    sharpe_ratio: metric('sharpe_ratio', -0.1),
    turnover: metric('turnover', 3, 'two_sided_ratio'),
    total_transaction_costs: metric('total_transaction_costs', 1234, 'CNY'),
  },
  matched_benchmark_id: 'demo:benchmark',
  revision_of: null,
}
const detail = {
  ...experiment,
  compatibility: {
    study_revision: digest,
    scenario_id: 'DEMO_T1',
    bars_sha256: digest,
    protocol_sha256: digest,
    base_protocol_sha256: digest,
    portfolio_sha256: digest,
    scores_sha256: digest,
    signals_sha256: digest,
    initial_cash: '1000000',
    cost_mode: 'real',
    execution_delay_sessions: 1,
  },
  execution: { fills: 4 },
  turnover_costs: { direct: 1234 },
  calendar_year_returns: { 2025: -0.08 },
  identities: { nav_sha256: digest },
  limitations: ['合成演示数据，不是研究结果'],
  source_sha256: digest,
  series: [
    { series_id: '1'.repeat(64), kind: 'NAV', unit: 'CNY', start: '2025-01-02', end: '2025-01-06', points: 3, source_sha256: digest, derivation: 'SOURCE_NAV_FULL_PRECISION' },
    { series_id: '2'.repeat(64), kind: 'DRAWDOWN', unit: 'ratio', start: '2025-01-02', end: '2025-01-06', points: 3, source_sha256: digest, derivation: 'RUNNING_PEAK_DRAWDOWN_V1' },
  ],
  curve_unavailable_reason: null,
}
const second = { ...experiment, artifact_id: 'demo:two', experiment_id: 'SYNTHETIC_B', run_identity: 'e'.repeat(64), evidence_id: 'evidence:demo:two' }

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    let body: unknown
    let headers: Record<string, string> = {}
    if (url.pathname === '/api/v1/snapshot') body = { schema_version: 2, mode: 'demo', snapshot_id: snapshotId, published_at: '2026-09-22T00:00:00Z', adapter_version: 'test' }
    else if (url.pathname === '/api/v1/runtime') body = { app_version: '1.5.0', current_snapshot_id: snapshotId, last_refresh: { status: 'PASS' } }
    else if (url.pathname.endsWith('/overview')) body = { snapshot_id: snapshotId, current_stage: 'SYNTHETIC_DEMO', registered_runs: 51, valid_runs: 19, not_evaluable_runs: 32, retained_candidates: 0, legacy_invalid_engineering_runs: 19, economic_outcome: 'NO_PROMOTABLE_CANDIDATE', latest_prospective_date: null, prospective_status: 'OPERATIONS_LOOP_RC', warnings: ['演示数据，不是研究结果'] }
    else if (url.pathname.endsWith('/experiments')) body = { snapshot_id: snapshotId, total: 2, page: 1, page_size: 10000, items: [experiment, second] }
    else if (url.pathname.endsWith('/comparisons/validate')) body = { snapshot_id: snapshotId, mode: 'DESCRIPTIVE_ONLY', reasons: ['匹配基准不可评价'], changed_fields: [], economic_inference_allowed: false, items: [detail, { ...detail, ...second }] }
    else if (url.pathname.endsWith('/exports/experiments')) {
      body = 'artifact_id,experiment_id\ndemo:one,SYNTHETIC_A\n'
      headers = { 'X-Quant-Snapshot-ID': snapshotId, 'Content-Disposition': 'attachment; filename="demo.csv"' }
    } else if (url.pathname.includes('/series/')) {
      const drawdown = url.pathname.endsWith('2'.repeat(64))
      body = {
        snapshot_id: snapshotId,
        meta: drawdown ? detail.series[1] : detail.series[0],
        points: [
          { date: '2025-01-02', value: drawdown ? '0' : '1000000' },
          { date: '2025-01-03', value: drawdown ? '-0.02' : '980000' },
          { date: '2025-01-06', value: drawdown ? '-0.08' : '920000' },
        ],
      }
    } else if (url.pathname.includes('/experiments/')) body = url.pathname.endsWith('demo:two') ? { ...detail, ...second } : detail
    else if (url.pathname.includes('/evidence/')) body = { evidence_id: evidenceId, source_kind: 'synthetic_fixture', study_id: 'demo_study', run_identity: digest, sha256: digest, schema_version: 1, data_use_level: 'SYNTHETIC', limitations: ['演示数据，不是研究结果'], absolute_paths_exposed: false }
    else if (url.pathname.endsWith('/signals')) body = { snapshot_id: snapshotId, historical: { summaries: { open_to_open_20: { evaluated_days: 10, mean_ic: 0.01, mean_rank_ic: 0.02, mean_top20_minus_bottom20: -0.01 } } }, attribution: { signals: {} }, measurement: { summaries: {} }, prospective: {} }
    else if (url.pathname.endsWith('/prospective')) body = { snapshot_id: snapshotId, latest_date: null, operations_status: 'OPERATIONS_LOOP_RC', input_status: 'MIXED_PROSPECTIVE_INPUT', data_capture_status: 'DEGRADED', profitability_status: 'INSUFFICIENT_PROSPECTIVE_EVIDENCE', accounts: { engineering_warm_start: { status: 'OBSERVED', latest: { trading_date: '2026-09-22', nav: '1000000', position_count: 20, top_count: 20, rejection_count: 0 }, observed_days: 1 }, fully_prospective_v1: { status: 'NOT_STARTED', latest: null, observed_days: 0 } }, days: [], diagnostics: {}, warnings: [], evidence_id: 'evidence:prospective:latest' }
    else if (url.pathname.endsWith('/health')) body = { snapshot_id: snapshotId, sources: [{ source_id: 'demo', verification_status: 'SYNTHETIC', manifest_sha256: null, matrix_sha256: null }], system_observation: { status: 'CURRENT_UNKNOWN', observed_at: null, timer: null, service: null, unit_hashes: null }, csi500: 'NOT_READ', live_broker: 'FORBIDDEN' }
    else body = { error: { code: 'NOT_FOUND', message: 'not found', request_id: 'test', recoverable: true } }
    await route.fulfill({ status: 200, contentType: typeof body === 'string' ? 'text/csv' : 'application/json', headers, body: typeof body === 'string' ? body : JSON.stringify(body) })
  })
}

test.beforeEach(async ({ page }) => { if (!process.env.QUANT_CONSOLE_REAL_URL) await mockApi(page) })

test('five pages preserve explicit demo and read-only boundaries', async ({ page }) => {
  test.skip(Boolean(process.env.QUANT_CONSOLE_REAL_URL), 'synthetic CI flow')
  await page.goto(`/?snapshot=${snapshotId}`)
  await expect(page.getByText('演示数据，不是研究结果').first()).toBeVisible()
  await expect(page.getByText('51', { exact: true })).toBeVisible()
  for (const name of ['实验中心', '信号诊断', '前瞻模拟', '数据与系统健康']) {
    await page.getByRole('link', { name }).click()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  }
  await expect(page.getByText('FORBIDDEN')).toBeVisible()
  await expect(page.getByText('NOT_READ')).toBeVisible()
})

test('URL-driven experiment detail, evidence and comparison survive direct navigation', async ({ page }) => {
  test.skip(Boolean(process.env.QUANT_CONSOLE_REAL_URL), 'synthetic CI flow')
  await page.goto(`/experiments?snapshot=${snapshotId}&q=SYNTHETIC_A&sort=cagr&direction=desc`)
  await expect(page.getByRole('button', { name: 'SYNTHETIC_A' })).toBeVisible()
  await page.getByRole('button', { name: 'SYNTHETIC_A' }).click()
  await expect(page).toHaveURL(/snapshot=/)
  await expect(page.getByText('MATCHED_BENCHMARK_NOT_EVALUABLE')).toBeVisible()
  await expect(page.getByRole('img', { name: /净值.*回撤/ })).toBeVisible()
  await page.getByRole('button', { name: '查看来源证据' }).click()
  await expect(page.getByText('synthetic_fixture')).toBeVisible()
  await page.getByRole('button', { name: '关闭' }).click()
  await page.goto(`/experiments/compare?snapshot=${snapshotId}&id=demo%3Aone&id=demo%3Atwo`)
  await expect(page.getByText('DESCRIPTIVE_ONLY')).toBeVisible()
  await expect(page.getByText(/不允许据此作经济优劣推断/)).toBeVisible()
})

test('critical and serious accessibility findings are absent on overview', async ({ page }) => {
  test.skip(Boolean(process.env.QUANT_CONSOLE_REAL_URL), 'synthetic CI flow')
  await page.goto(`/?snapshot=${snapshotId}`)
  await expect(page.getByRole('heading', { name: '研究总览' })).toBeVisible()
  const result = await new AxeBuilder({ page }).analyze()
  expect(result.violations.filter((item) => item.impact === 'critical' || item.impact === 'serious')).toEqual([])
})

test('real mode exposes frozen counts, dual status and separate prospective accounts', async ({ page }) => {
  test.skip(!process.env.QUANT_CONSOLE_REAL_URL, 'requires approved local real sources')
  const errors: string[] = []
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  await page.goto('/')
  await expect(page.getByText('51', { exact: true })).toBeVisible()
  await expect(page.getByText('19', { exact: true })).toBeVisible()
  await expect(page.getByText('32', { exact: true })).toBeVisible()
  await expect(page.getByText('演示数据，不是研究结果')).toHaveCount(0)
  await page.getByRole('link', { name: '实验中心' }).click()
  await page.getByPlaceholder('实验、策略或家族').fill('AF7_TOP50_D20_EQ__REAL_T1_1M')
  await page.getByPlaceholder('实验、策略或家族').press('Enter')
  await page.getByRole('button', { name: 'AF7_TOP50_D20_EQ__REAL_T1_1M' }).click()
  await expect(page.getByText('MATCHED_BENCHMARK_NOT_EVALUABLE')).toBeVisible()
  await expect(page.getByText('-5.22%')).toBeVisible()
  await page.getByRole('button', { name: '查看来源证据' }).click()
  await expect(page.getByText('run_result')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('heading', { name: '来源证据' })).toHaveCount(0)
  await page.getByRole('link', { name: '前瞻模拟' }).click()
  await expect(page.getByText('尚未启动；不以 0 元或 0% 代替。')).toBeVisible()
  await page.getByRole('link', { name: '数据与系统健康' }).click()
  await expect(page.getByText('PUBLISHED_JSON_ONLY')).toBeVisible()
  if (process.env.QUANT_CONSOLE_CAPTURE_REAL) {
    await page.screenshot({ path: `test-results/real-health-${test.info().project.name}.png`, fullPage: true })
  }
  expect(errors).toEqual([])
})
