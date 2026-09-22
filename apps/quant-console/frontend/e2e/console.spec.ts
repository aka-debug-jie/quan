import { expect, test, type Page } from '@playwright/test'

declare const process: { env: Record<string, string | undefined> }

const metric = (value: number, unit = 'ratio') => ({ value, unit, validity: 'VALID', unavailable_reason: null })
const experiment = {
  artifact_id: 'demo:one', evidence_id: 'evidence:demo:one', study_id: 'demo_study', experiment_id: 'SYNTHETIC_A', strategy_id: 'SYNTHETIC_A', family: 'DEMO', scenario_id: 'DEMO_T1', data_evaluability: 'VALID', benchmark_comparability: 'MATCHED_BENCHMARK_NOT_EVALUABLE', economic_outcome: 'NOT_EVALUABLE', engineering_status: 'PASS', research_validity: 'SYNTHETIC', data_use_level: 'SYNTHETIC', failure_reason: null, period: { start: '2025-01-02', end: '2025-01-06', sessions: 3 }, metrics: { cagr: metric(-0.03), total_return: metric(-0.08), annualized_volatility: metric(0.18), maximum_drawdown: metric(-0.15), sharpe_ratio: metric(-0.1), turnover: metric(3, 'two_sided_ratio'), total_transaction_costs: metric(1234, 'CNY') }, nav_series: [{ date: '2025-01-02', nav: '1000000' }, { date: '2025-01-03', nav: '980000' }, { date: '2025-01-06', nav: '920000' }], calendar_year_returns: { 2025: -0.08 }, execution: { fills: 4 }, limitations: ['合成演示数据，不是研究结果'], compatibility: { study_revision: 'demo_study', scenario_id: 'DEMO_T1', bars_sha256: 'demo', protocol_sha256: 'demo', initial_cash: '1000000' },
}

async function mockApi(page: Page) {
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    let body: unknown
    if (url.pathname.endsWith('/snapshot')) body = { mode: 'demo', snapshot_id: 'a'.repeat(64), generated_at: '2026-09-22T00:00:00Z' }
    else if (url.pathname.endsWith('/overview')) body = { snapshot_id: 'a'.repeat(64), current_stage: 'SYNTHETIC_DEMO', registered_runs: 51, valid_runs: 19, not_evaluable_runs: 32, retained_candidates: 0, legacy_invalid_engineering_runs: 19, economic_outcome: 'NO_PROMOTABLE_CANDIDATE', latest_prospective_date: null, prospective_status: 'OPERATIONS_LOOP_RC', warnings: ['演示数据，不是研究结果'] }
    else if (url.pathname.endsWith('/experiments')) body = { total: 1, page: 1, page_size: 100, items: [experiment] }
    else if (url.pathname.endsWith('/comparisons/validate')) body = { mode: 'DESCRIPTIVE_ONLY', reasons: ['scenario_id 不一致'], items: [experiment, { ...experiment, artifact_id: 'demo:two', experiment_id: 'SYNTHETIC_B' }] }
    else if (url.pathname.endsWith('/exports/experiments')) body = 'artifact_id,experiment_id\ndemo:one,SYNTHETIC_A\n'
    else if (url.pathname.includes('/experiments/')) body = experiment
    else if (url.pathname.includes('/evidence/')) body = { source_kind: 'synthetic_fixture', sha256: 'synthetic', limitations: ['演示数据，不是研究结果'] }
    else if (url.pathname.endsWith('/signals')) body = { historical: { summaries: {} }, attribution: { signals: {} }, measurement: { summaries: {} }, prospective: {} }
    else if (url.pathname.endsWith('/prospective')) body = { operations_status: 'OPERATIONS_LOOP_RC', input_status: 'MIXED_PROSPECTIVE_INPUT', data_capture_status: 'DEGRADED', profitability_status: 'INSUFFICIENT_PROSPECTIVE_EVIDENCE', accounts: { engineering_warm_start: { status: 'OBSERVED', latest: { nav: '1000000' } }, fully_prospective_v1: { status: 'NOT_STARTED', latest: null } }, days: [] }
    else if (url.pathname.endsWith('/health')) body = { sources: [{ source_id: 'demo', verification_status: 'SYNTHETIC' }], system_observation: { status: 'CURRENT_UNKNOWN' }, csi500: 'NOT_READ', live_broker: 'FORBIDDEN' }
    else body = { detail: 'not found' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
}

test.beforeEach(async ({ page }) => { if (!process.env.QUANT_CONSOLE_REAL_URL) await mockApi(page) })

test('overview and all five pages are reachable with explicit demo boundary', async ({ page }) => {
  test.skip(Boolean(process.env.QUANT_CONSOLE_REAL_URL), 'synthetic CI flow')
  await page.goto('/')
  await expect(page.getByText('演示数据，不是研究结果').first()).toBeVisible()
  await expect(page.getByText('51')).toBeVisible()
  for (const name of ['实验中心', '信号诊断', '前瞻模拟', '数据与系统健康']) {
    await page.getByRole('link', { name }).click()
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible()
  }
})

test('experiment detail exposes real-source rule and evidence without inventing a benchmark', async ({ page }) => {
  test.skip(Boolean(process.env.QUANT_CONSOLE_REAL_URL), 'synthetic CI flow')
  await page.goto('/experiments')
  await page.getByRole('button', { name: 'SYNTHETIC_A' }).click()
  await expect(page.getByText('MATCHED_BENCHMARK_NOT_EVALUABLE')).toBeVisible()
  await expect(page.getByRole('img', { name: /真实净值曲线/ })).toBeVisible()
  await page.getByRole('button', { name: '查看来源证据' }).click()
  await expect(page.getByText(/synthetic_fixture/)).toBeVisible()
})

test('real mode exposes frozen counts and no demo banner', async ({ page }) => {
  test.skip(!process.env.QUANT_CONSOLE_REAL_URL, 'requires local approved real sources')
  const errors: string[] = []
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()) })
  await page.goto('/')
  await expect(page.getByText('51', { exact: true })).toBeVisible()
  await expect(page.getByText('19', { exact: true })).toBeVisible()
  await expect(page.getByText('32', { exact: true })).toBeVisible()
  await expect(page.getByText('演示数据，不是研究结果')).toHaveCount(0)
  await page.getByRole('link', { name: '实验中心' }).click()
  await page.getByPlaceholder('实验或策略名称').fill('AF7_TOP50_D20_EQ__REAL_T1_1M')
  await page.getByRole('button', { name: 'AF7_TOP50_D20_EQ__REAL_T1_1M' }).click()
  await expect(page.getByText('MATCHED_BENCHMARK_NOT_EVALUABLE')).toBeVisible()
  await expect(page.getByText('-5.22%')).toBeVisible()
  await page.getByRole('button', { name: '查看来源证据' }).click()
  await expect(page.getByText(/run_result/)).toBeVisible()
  await page.getByRole('link', { name: '前瞻模拟' }).click()
  await expect(page.getByText('尚未启动；不以 0 元或 0% 代替。')).toBeVisible()
  await page.getByRole('link', { name: '数据与系统健康' }).click()
  await expect(page.getByText(/PUBLISHED_JSON_ONLY/)).toBeVisible()
  if (process.env.QUANT_CONSOLE_CAPTURE_REAL) await page.screenshot({ path: `test-results/real-health-${test.info().project.name}.png`, fullPage: true })
  expect(errors).toEqual([])
})
