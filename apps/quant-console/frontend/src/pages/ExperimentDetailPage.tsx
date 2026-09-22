import { useQueries, useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  Button,
  EmptyState,
  ErrorState,
  EvidenceDialog,
  JsonDisclosure,
  Loading,
  MetricCard,
  Page,
  StatusChip,
} from '../components'
import { formatRatio } from '../formatters'
import { evidenceQuery, experimentQuery, seriesQuery } from '../queries'
import { snapshotHref, useSnapshot } from '../snapshot-context'

const SeriesChart = lazy(() => import('../SeriesChart'))

export default function ExperimentDetailPage() {
  const { snapshotId } = useSnapshot()
  const { id = '' } = useParams()
  const detail = useQuery(experimentQuery(snapshotId, id))
  const [evidenceOpen, setEvidenceOpen] = useState(false)
  const evidence = useQuery({
    ...evidenceQuery(snapshotId, detail.data?.evidence_id ?? ''),
    enabled: evidenceOpen && Boolean(detail.data?.evidence_id),
  })
  const series = useQueries({
    queries: (detail.data?.series ?? []).map((item) => seriesQuery(snapshotId, item.series_id)),
  })
  if (detail.isPending) return <Loading />
  if (detail.isError) return <ErrorState message={detail.error.message} />
  const value = detail.data
  const loadedSeries = series.flatMap((query) => query.data ? [query.data] : [])
  const seriesError = series.find((query) => query.isError)?.error
  return <Page
    title={value.experiment_id}
    subtitle={`${value.study_id} · ${value.scenario_id}`}
    actions={<Link className="button button-ghost" to={snapshotHref('/experiments', snapshotId)}>返回实验中心</Link>}
  >
    <div className="status-row detail-status">
      <StatusChip value={value.data_evaluability} />
      <StatusChip value={value.benchmark_comparability} />
      <StatusChip value={value.economic_outcome} />
      <StatusChip value={value.research_validity} />
    </div>
    {value.failure_reason && <div className="alert alert-warning"><strong>不可评价原因</strong><p>{value.failure_reason}</p></div>}
    <div className="metrics">
      <MetricCard label="净 CAGR" metric={value.metrics.cagr} />
      <MetricCard label="总收益" metric={value.metrics.total_return} />
      <MetricCard label="年化波动率" metric={value.metrics.annualized_volatility} />
      <MetricCard label="Sharpe" metric={value.metrics.sharpe_ratio} />
      <MetricCard label="最大回撤" metric={value.metrics.maximum_drawdown} />
      <MetricCard label="双边换手" metric={value.metrics.turnover} />
      <MetricCard label="交易次数" metric={value.metrics.trade_count} />
      <MetricCard label="直接费用" metric={value.metrics.total_transaction_costs} />
    </div>
    <section className="panel">
      <div className="section-head"><div><span className="eyebrow">完整精度时序</span><h2>净值与回撤</h2></div>
        <span className="muted">{value.period ? `${value.period.start} 至 ${value.period.end} · ${value.period.sessions} 个交易日` : '期间不可用'}</span>
      </div>
      {value.series.length === 0
        ? <EmptyState>{value.curve_unavailable_reason ?? '没有经身份校验的时序。'}</EmptyState>
        : seriesError
          ? <ErrorState title="时序加载失败" message={seriesError.message} />
          : loadedSeries.length !== value.series.length
            ? <Loading label="正在按需加载净值与回撤…" />
            : <Suspense fallback={<Loading label="正在加载图表组件…" />}><SeriesChart series={loadedSeries} /></Suspense>}
      <p className="caption">上方指标始终使用来源全期间结果；图表缩放只改变视图。回撤曲线标记为 RUNNING_PEAK_DRAWDOWN_V1 派生展示。</p>
    </section>
    <div className="dashboard-grid">
      <section className="panel">
        <h2>年度表现</h2>
        {value.calendar_year_returns && Object.keys(value.calendar_year_returns).length
          ? <table className="data-table"><thead><tr><th>年度</th><th>收益</th></tr></thead><tbody>
            {Object.entries(value.calendar_year_returns).map(([year, result]) => <tr key={year}><td>{year}</td><td>{formatRatio(result)}</td></tr>)}
          </tbody></table>
          : <EmptyState>来源没有年度表现。</EmptyState>}
      </section>
      <section className="panel">
        <h2>执行与成本</h2>
        <JsonDisclosure value={{ execution: value.execution, turnover_costs: value.turnover_costs }} label="查看结构化执行记录" />
        <p className="caption">费用和换手来自历史研究产物，前端不重复计算。</p>
      </section>
    </div>
    <section className="panel">
      <div className="section-head"><div><span className="eyebrow">身份追溯</span><h2>协议与来源</h2></div><Button variant="secondary" onClick={() => setEvidenceOpen(true)}>查看来源证据</Button></div>
      <dl className="detail-list identity-list">
        <dt>运行身份</dt><dd className="mono">{value.run_identity}</dd>
        <dt>研究修订</dt><dd className="mono">{value.study_revision}</dd>
        <dt>源结果 SHA-256</dt><dd className="mono">{value.source_sha256}</dd>
        <dt>数据等级</dt><dd>{value.data_use_level}</dd>
        <dt>限制</dt><dd>{value.limitations.length ? value.limitations.join('；') : '无附加说明'}</dd>
      </dl>
    </section>
    <EvidenceDialog open={evidenceOpen} onOpenChange={setEvidenceOpen} evidence={evidence.data} />
  </Page>
}
