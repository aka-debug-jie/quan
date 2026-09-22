import { useQuery } from '@tanstack/react-query'
import {
  ClientSideRowModelModule,
  ColumnApiModule,
  ModuleRegistry,
  PaginationModule,
  QuickFilterModule,
  RowApiModule,
  RowSelectionModule,
  themeQuartz,
  type ColDef,
  type GridApi,
  type GridReadyEvent,
  type SelectionChangedEvent,
  type SortChangedEvent,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { exportExperiments } from '../api'
import { Button, ErrorState, Loading, Page, StatusChip } from '../components'
import type { ExperimentSummary, ExportRequest } from '../domain'
import { formatMetric } from '../formatters'
import { experimentsQuery } from '../queries'
import { snapshotHref, useSnapshot } from '../snapshot-context'

ModuleRegistry.registerModules([
  ClientSideRowModelModule,
  ColumnApiModule,
  PaginationModule,
  QuickFilterModule,
  RowApiModule,
  RowSelectionModule,
])

const gridTheme = themeQuartz.withParams({
  accentColor: '#2563eb',
  backgroundColor: '#ffffff',
  borderColor: '#dbe3ee',
  fontFamily: 'Inter, "Noto Sans SC", system-ui, sans-serif',
  foregroundColor: '#172033',
  headerBackgroundColor: '#f5f7fb',
  headerTextColor: '#475569',
  rowHoverColor: '#f7faff',
  selectedRowBackgroundColor: '#eaf2ff',
  spacing: 7,
})
const layoutKey = 'quant-console.v1.5.experiment-grid.columns.v1'

export default function ExperimentsPage() {
  const { snapshotId } = useSnapshot()
  const query = useQuery(experimentsQuery(snapshotId))
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const gridApi = useRef<GridApi<ExperimentSummary>>()
  const [actionError, setActionError] = useState<string>()
  const q = params.get('q') ?? ''
  const [draft, setDraft] = useState(q)
  const study = params.get('study') ?? ''
  const family = params.get('family') ?? ''
  const status = params.get('status') ?? ''
  const sort = params.get('sort') ?? 'experiment_id'
  const direction = params.get('direction') === 'desc' ? 'desc' : 'asc'
  const selected = params.getAll('compare').slice(0, 4)

  const rows = useMemo(() => {
    const items = query.data?.items ?? []
    return items.filter((item) => {
      if (study && item.study_id !== study) return false
      if (family && item.family !== family) return false
      if (status && item.data_evaluability !== status) return false
      return true
    })
  }, [family, query.data?.items, status, study])

  const columns = useMemo<ColDef<ExperimentSummary>[]>(() => [
    {
      headerName: '实验',
      field: 'experiment_id',
      minWidth: 280,
      pinned: 'left',
      sort: sort === 'experiment_id' ? direction : undefined,
      cellRenderer: ({ data }: { data?: ExperimentSummary }) => data
        ? <button className="grid-link" onClick={() => navigate(snapshotHref(`/experiments/${encodeURIComponent(data.artifact_id)}`, snapshotId))}>{data.experiment_id}</button>
        : null,
    },
    { headerName: '研究', field: 'study_id', minWidth: 160, sort: sort === 'study_id' ? direction : undefined },
    { headerName: '家族', field: 'family', minWidth: 150, sort: sort === 'family' ? direction : undefined },
    { headerName: '场景', field: 'scenario_id', minWidth: 190, sort: sort === 'scenario_id' ? direction : undefined },
    {
      headerName: '绝对数据',
      field: 'data_evaluability',
      minWidth: 160,
      cellRenderer: ({ value }: { value?: string }) => <StatusChip value={value} />,
    },
    {
      headerName: '匹配基准',
      field: 'benchmark_comparability',
      minWidth: 240,
      cellRenderer: ({ value }: { value?: string }) => <StatusChip value={value} />,
    },
    {
      headerName: '净 CAGR',
      colId: 'cagr',
      valueGetter: ({ data }) => data?.metrics.cagr?.value,
      valueFormatter: ({ data }) => formatMetric(data?.metrics.cagr),
      minWidth: 125,
      sort: sort === 'cagr' ? direction : undefined,
    },
    {
      headerName: '年化波动率',
      colId: 'annualized_volatility',
      valueGetter: ({ data }) => data?.metrics.annualized_volatility?.value,
      valueFormatter: ({ data }) => formatMetric(data?.metrics.annualized_volatility),
      minWidth: 140,
      sort: sort === 'annualized_volatility' ? direction : undefined,
    },
    {
      headerName: 'Sharpe',
      colId: 'sharpe_ratio',
      valueGetter: ({ data }) => data?.metrics.sharpe_ratio?.value,
      valueFormatter: ({ data }) => formatMetric(data?.metrics.sharpe_ratio),
      minWidth: 115,
      sort: sort === 'sharpe_ratio' ? direction : undefined,
    },
    {
      headerName: '最大回撤',
      colId: 'maximum_drawdown',
      valueGetter: ({ data }) => data?.metrics.maximum_drawdown?.value,
      valueFormatter: ({ data }) => formatMetric(data?.metrics.maximum_drawdown),
      minWidth: 130,
      sort: sort === 'maximum_drawdown' ? direction : undefined,
    },
    {
      headerName: '双边换手',
      colId: 'turnover',
      valueGetter: ({ data }) => data?.metrics.turnover?.value,
      valueFormatter: ({ data }) => formatMetric(data?.metrics.turnover),
      minWidth: 130,
      sort: sort === 'turnover' ? direction : undefined,
    },
    {
      headerName: '交易次数',
      colId: 'trade_count',
      valueGetter: ({ data }) => data?.metrics.trade_count?.value,
      valueFormatter: ({ data }) => formatMetric(data?.metrics.trade_count),
      minWidth: 115,
      sort: sort === 'trade_count' ? direction : undefined,
    },
    {
      headerName: '经济结论',
      field: 'economic_outcome',
      minWidth: 220,
      cellRenderer: ({ value }: { value?: string }) => <StatusChip value={value} />,
    },
  ], [direction, navigate, snapshotId, sort])

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const onSelectionChanged = (event: SelectionChangedEvent<ExperimentSummary>) => {
    const nodes = event.api.getSelectedNodes()
    if (nodes.length > 4) {
      nodes[nodes.length - 1]?.setSelected(false)
      return
    }
    const next = new URLSearchParams(params)
    next.delete('compare')
    nodes.flatMap((node) => node.data ? [node.data.artifact_id] : []).forEach((id) => next.append('compare', id))
    setParams(next, { replace: true })
  }

  const selectedKey = selected.join('|')
  const restoreSelection = useCallback((api: GridApi<ExperimentSummary>) => {
    const wanted = new Set(selectedKey ? selectedKey.split('|') : [])
    api.forEachNode((node) => node.setSelected(Boolean(node.data && wanted.has(node.data.artifact_id))))
  }, [selectedKey])

  useEffect(() => {
    if (gridApi.current && query.data) restoreSelection(gridApi.current)
  }, [query.data, restoreSelection])

  const onSortChanged = (event: SortChangedEvent<ExperimentSummary>) => {
    const state = event.api.getColumnState().find((column) => column.sort)
    if (!state?.colId || !state.sort) return
    const next = new URLSearchParams(params)
    next.set('sort', state.colId)
    next.set('direction', state.sort)
    setParams(next, { replace: true })
  }

  const runExport = async (scope: 'selected' | 'filtered') => {
    const filterStatus = status === 'VALID' || status === 'NOT_EVALUABLE' || status === 'UNKNOWN'
      ? status
      : null
    const payload: ExportRequest = scope === 'selected'
      ? { scope, artifact_ids: selected, format: 'csv', filters: { q: '' }, sort, direction }
      : { scope, artifact_ids: [], format: 'csv', filters: { q, study: study || null, family: family || null, status: filterStatus }, sort, direction }
    setActionError(undefined)
    try {
      await exportExperiments(snapshotId, payload)
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '安全导出失败')
    }
  }

  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorState message={query.error.message} />

  const studies = [...new Set(query.data.items.map((item) => item.study_id))]
  const families = [...new Set(query.data.items.map((item) => item.family))]

  return <Page title="实验中心" subtitle="绝对结果、匹配基准与经济结论分别展示；列表来自完整聚合 ledger。">
    <section className="panel toolbar-panel">
      <div className="toolbar">
        <label className="search-field">搜索
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onCompositionEnd={(event) => updateParam('q', event.currentTarget.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') updateParam('q', draft) }}
            placeholder="实验、策略或家族"
          />
        </label>
        <label>研究<select value={study} onChange={(event) => updateParam('study', event.target.value)}>
          <option value="">全部</option>{studies.map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label>家族<select value={family} onChange={(event) => updateParam('family', event.target.value)}>
          <option value="">全部</option>{families.map((value) => <option key={value}>{value}</option>)}
        </select></label>
        <label>绝对数据<select value={status} onChange={(event) => updateParam('status', event.target.value)}>
          <option value="">全部</option><option value="VALID">可评价</option><option value="NOT_EVALUABLE">不可评价</option>
        </select></label>
      </div>
      <div className="toolbar-actions">
        <span>显示 {rows.length} / {query.data.total} 项，已选 {selected.length} 项</span>
        <Button variant="secondary" disabled={selected.length < 2} onClick={() => {
          const next = new URLSearchParams()
          next.set('snapshot', snapshotId)
          selected.forEach((id) => next.append('id', id))
          navigate(`/experiments/compare?${next}`)
        }}>比较</Button>
        <Button variant="secondary" disabled={selected.length === 0} onClick={() => void runExport('selected')}>导出选中</Button>
        <Button variant="ghost" onClick={() => void runExport('filtered')}>导出筛选结果</Button>
        <Button variant="ghost" onClick={() => {
          localStorage.removeItem(layoutKey)
          gridApi.current?.resetColumnState()
        }}>重置列布局</Button>
      </div>
    </section>
    {actionError && <div className="alert alert-error" role="alert">安全导出失败：{actionError}</div>}
    <section className="panel grid-panel" aria-label="实验结果表格">
      <AgGridReact<ExperimentSummary>
        theme={gridTheme}
        rowData={rows}
        columnDefs={columns}
        defaultColDef={{ sortable: true, resizable: true }}
        getRowId={({ data }) => data.artifact_id}
        quickFilterText={q}
        rowSelection={{ mode: 'multiRow', checkboxes: true, headerCheckbox: false }}
        pagination
        paginationPageSize={50}
        paginationPageSizeSelector={[25, 50, 100]}
        onGridReady={(event: GridReadyEvent<ExperimentSummary>) => {
          gridApi.current = event.api
          restoreColumnLayout(event.api)
          restoreSelection(event.api)
        }}
        onSelectionChanged={onSelectionChanged}
        onSortChanged={onSortChanged}
        onColumnMoved={({ api, finished }) => { if (finished) saveColumnLayout(api) }}
        onColumnResized={({ api, finished }) => { if (finished) saveColumnLayout(api) }}
        onColumnVisible={({ api }) => saveColumnLayout(api)}
      />
    </section>
  </Page>
}

function saveColumnLayout(api: GridApi<ExperimentSummary>) {
  localStorage.setItem(layoutKey, JSON.stringify(api.getColumnState()))
}

function restoreColumnLayout(api: GridApi<ExperimentSummary>) {
  const raw = localStorage.getItem(layoutKey)
  if (!raw) return
  try {
    api.applyColumnState({ state: JSON.parse(raw) as ReturnType<typeof api.getColumnState>, applyOrder: true })
  } catch (error) {
    console.warn('忽略损坏的本地列布局', error)
    localStorage.removeItem(layoutKey)
  }
}
