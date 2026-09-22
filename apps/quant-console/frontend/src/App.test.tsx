import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

afterEach(() => vi.restoreAllMocks())

test('renders real status counts without converting engineering success into strategy success', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const value = url.endsWith('/snapshot')
      ? { mode: 'demo', snapshot_id: 'a'.repeat(64), generated_at: '2026-09-22T00:00:00Z' }
      : { snapshot_id: 'a'.repeat(64), current_stage: 'COMPLETE', registered_runs: 51, valid_runs: 19, not_evaluable_runs: 32, retained_candidates: 0, legacy_invalid_engineering_runs: 19, economic_outcome: 'NO_PROMOTABLE_CANDIDATE', latest_prospective_date: null, prospective_status: 'OPERATIONS_LOOP_RC', warnings: [] }
    return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  render(<MemoryRouter><App /></MemoryRouter>)
  expect(await screen.findByText('51')).toBeInTheDocument()
  expect(screen.getByText('32')).toBeInTheDocument()
  expect(screen.getByText('演示数据，不是研究结果')).toBeInTheDocument()
  expect(screen.getByText(/工程测试通过不等于策略通过/)).toBeInTheDocument()
})
