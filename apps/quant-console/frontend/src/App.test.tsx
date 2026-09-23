import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'
import { formatMetric } from './formatters'
import { overviewQuery } from './queries'

const snapshotId = 'a'.repeat(64)

afterEach(() => vi.restoreAllMocks())

test('renders snapshot-bound real states without turning research gaps into zero', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input)
    const body = url.endsWith('/api/v1/snapshot')
      ? { schema_version: 2, mode: 'demo', snapshot_id: snapshotId, published_at: '2026-09-22T00:00:00Z', adapter_version: 'test' }
      : {
          snapshot_id: snapshotId,
          current_stage: 'COMPLETE',
          registered_runs: 51,
          valid_runs: 19,
          not_evaluable_runs: 32,
          retained_candidates: 0,
          legacy_invalid_engineering_runs: 19,
          economic_outcome: 'NO_PROMOTABLE_CANDIDATE',
          latest_prospective_date: null,
          prospective_status: 'OPERATIONS_LOOP_RC',
          warnings: [],
        }
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/?snapshot=${snapshotId}`]}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('51')).toBeInTheDocument()
  expect(screen.getByText('32')).toBeInTheDocument()
  expect(screen.getByText('演示数据，不是研究结果')).toBeInTheDocument()
  expect(screen.getByText(/工程测试通过不等于策略通过/)).toBeInTheDocument()
})

test('shows retained upgrade counts beside the new closure revision', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input)
    const body = url.endsWith('/api/v1/snapshot')
      ? { schema_version: 2, mode: 'real', snapshot_id: snapshotId, published_at: '2026-09-23T00:00:00Z', adapter_version: 'test' }
      : {
          snapshot_id: snapshotId,
          current_stage: 'CN_RESEARCH_CLOSURE_NEXT',
          registered_runs: 55,
          valid_runs: 35,
          not_evaluable_runs: 20,
          retained_candidates: 0,
          legacy_invalid_engineering_runs: 19,
          economic_outcome: 'SEE_PAIRED_STATISTICS',
          latest_prospective_date: null,
          prospective_status: 'OPERATIONS_LOOP_RC',
          warnings: [],
          closure_counts: {
            old_registered_runs: 51,
            old_valid_runs: 19,
            old_not_evaluable_runs: 32,
            old_retained_candidates: 0,
            revised_runs: 51,
            new_control_runs: 4,
            conditional_scale_runs: 0,
            cache_reuse_from_old_study: 0,
            valid_runs: 35,
            not_evaluable_runs: 20,
            retained_candidates: 0,
          },
        }
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/?snapshot=${snapshotId}`]}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(/上轮强化研究：登记 51 项，可评价 19 项，不可评价 32 项/)).toBeInTheDocument()
  expect(screen.getByText(/旧运行修订 51 项，新增机制对照 4 项/)).toBeInTheDocument()
  expect(screen.getByText('本轮历史重评结果已发布')).toBeInTheDocument()
})

test('formatting preserves unavailable and negative semantics', () => {
  expect(formatMetric()).toBe('不可用')
  expect(formatMetric({
    name: 'cagr',
    value: null,
    unit: 'ratio',
    validity: 'NOT_AVAILABLE',
    unavailable_reason: 'source missing',
    basis: 'source',
    scenario_id: 'BASE',
    data_use_level: 'SYNTHETIC',
    source_evidence_id: 'evidence:test',
  })).toBe('不可用')
  expect(formatMetric({
    name: 'cagr',
    value: -0.052,
    unit: 'ratio',
    validity: 'VALID',
    unavailable_reason: null,
    basis: 'source',
    scenario_id: 'BASE',
    data_use_level: 'SYNTHETIC',
    source_evidence_id: 'evidence:test',
  })).toBe('-5.2%')
})

test('query identities isolate immutable snapshots', () => {
  expect(overviewQuery('a'.repeat(64)).queryKey).not.toEqual(overviewQuery('b'.repeat(64)).queryKey)
})
