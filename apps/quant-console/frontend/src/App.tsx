import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import { api } from './api'
import { JsonBlock, MetricCard, NavChart, StatusChip } from './components'
import type { Experiment, Overview } from './types'
import './styles.css'

type Load<T> = { data?: T; error?: string }

function useApi<T>(path: string): Load<T> {
  const [state, setState] = useState<Load<T>>({})
  useEffect(() => { let live = true; api<T>(path).then((data) => live && setState({ data })).catch((error: Error) => live && setState({ error: error.message })); return () => { live = false } }, [path])
  return state
}

function Loading({ state }: { state: Load<unknown> }) {
  if (state.error) return <div className="error">加载失败：{state.error}</div>
  return <div className="loading">正在读取已发布快照…</div>
}

function OverviewPage() {
  const state = useApi<Overview>('/overview')
  if (!state.data) return <Loading state={state} />
  const v = state.data
  return <Page title="研究总览" subtitle="显示已有证据，不生成推荐或重新运行实验。">
    <div className="kpis"><Kpi label="注册运行" value={v.registered_runs} /><Kpi label="可评价" value={v.valid_runs} /><Kpi label="不可评价" value={v.not_evaluable_runs} /><Kpi label="晋级候选" value={v.retained_candidates} /></div>
    <section className="panel"><h2>当前结论</h2><div className="status-row"><StatusChip value={v.current_stage} /><StatusChip value={v.economic_outcome} /></div><p>旧工程证据 {v.legacy_invalid_engineering_runs} 项，未计入注册运行。工程测试通过不等于策略通过。</p></section>
    <section className="panel"><h2>前瞻模拟</h2><div className="status-row"><StatusChip value={v.prospective_status} /><span>最新发布日：{v.latest_prospective_date ?? '尚无'}</span></div>{v.warnings.map((x) => <p className="warning" key={x}>{x}</p>)}</section>
  </Page>
}

function ExperimentsPage() {
  const [query, setQuery] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const path = `/experiments?q=${encodeURIComponent(query)}&status=${encodeURIComponent(status)}&page_size=100`
  const state = useApi<{ total: number; items: Experiment[] }>(path)
  const navigate = useNavigate()
  const compare = async () => { const result = await api<{ mode: string; reasons: string[]; items: Experiment[] }>('/comparisons/validate', { method: 'POST', body: JSON.stringify({ artifact_ids: selected }) }); sessionStorage.setItem('quant-comparison', JSON.stringify(result)); navigate('/experiments/compare') }
  const exportSelected = async () => {
    const response = await fetch('/api/v1/exports/experiments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ artifact_ids: selected, format: 'csv' }) })
    if (!response.ok) throw new Error('安全导出失败')
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'quant-console-export.csv'
    anchor.click()
    URL.revokeObjectURL(url)
  }
  return <Page title="实验中心" subtitle="绝对结果、匹配基准和经济结论分别展示。">
    <div className="toolbar"><label>搜索<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="实验或策略名称" /></label><label>状态<select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">全部</option><option value="VALID">可评价</option><option value="NOT_EVALUABLE">不可评价</option></select></label><button disabled={selected.length < 2 || selected.length > 4} onClick={compare}>比较 {selected.length || ''}</button><button disabled={selected.length === 0} onClick={exportSelected}>安全导出</button></div>
    {!state.data ? <Loading state={state} /> : <div className="table-wrap"><table><thead><tr><th>选择</th><th>实验</th><th>阶段</th><th>场景</th><th>数据</th><th>基准</th><th>净 CAGR</th><th>最大回撤</th><th>结论</th></tr></thead><tbody>{state.data.items.map((item) => <tr key={item.artifact_id}><td><input aria-label={`选择 ${item.experiment_id}`} type="checkbox" checked={selected.includes(item.artifact_id)} onChange={(e) => setSelected((old) => e.target.checked ? [...old, item.artifact_id].slice(-4) : old.filter((x) => x !== item.artifact_id))} /></td><td><button className="link-button" onClick={() => navigate(`/experiments/${encodeURIComponent(item.artifact_id)}`)}>{item.experiment_id}</button></td><td>{item.study_id}</td><td>{item.scenario_id}</td><td><StatusChip value={item.data_evaluability} /></td><td><StatusChip value={item.benchmark_comparability} /></td><td>{formatRatio(item.metrics.cagr?.value)}</td><td>{formatRatio(item.metrics.maximum_drawdown?.value)}</td><td><StatusChip value={item.economic_outcome} /></td></tr>)}</tbody></table></div>}
  </Page>
}

function ExperimentDetailPage() {
  const { id = '' } = useParams()
  const state = useApi<Experiment>(`/experiments/${encodeURIComponent(id)}`)
  const [evidence, setEvidence] = useState<unknown>()
  if (!state.data) return <Loading state={state} />
  const v = state.data
  return <Page title={v.experiment_id} subtitle={`${v.study_id} · ${v.scenario_id}`}><div className="status-row"><StatusChip value={v.data_evaluability} /><StatusChip value={v.benchmark_comparability} /><StatusChip value={v.economic_outcome} /></div>{v.failure_reason && <div className="error">不可评价原因：{v.failure_reason}</div>}<div className="metrics"><MetricCard label="净 CAGR" metric={v.metrics.cagr} /><MetricCard label="总收益" metric={v.metrics.total_return} /><MetricCard label="Sharpe" metric={v.metrics.sharpe_ratio} /><MetricCard label="最大回撤" metric={v.metrics.maximum_drawdown} /><MetricCard label="双边换手" metric={v.metrics.turnover} /><MetricCard label="直接费用" metric={v.metrics.total_transaction_costs} /></div><section className="panel"><h2>真实净值</h2><NavChart experiment={v} /><p className="caption">图表只来自经哈希校验的逐日 NAV；缩放不会重算上方全期指标。</p></section><section className="panel"><h2>年度与执行</h2><JsonBlock value={{ calendar_year_returns: v.calendar_year_returns, execution: v.execution }} /></section><button onClick={() => api(`/evidence/${encodeURIComponent(v.evidence_id)}`).then(setEvidence)}>查看来源证据</button>{evidence !== undefined && <section className="drawer"><h2>来源证据</h2><JsonBlock value={evidence} /></section>}</Page>
}

function ComparePage() {
  const raw = sessionStorage.getItem('quant-comparison')
  const result = raw ? JSON.parse(raw) as { mode: string; reasons: string[]; items: Experiment[] } : null
  return <Page title="实验比较" subtitle="只有完全兼容的实验才允许解释为同口径比较。">{!result ? <div className="empty">请先从实验中心选择 2–4 项。</div> : <><div className="status-row"><StatusChip value={result.mode} />{result.reasons.map((x) => <span className="warning" key={x}>{x}</span>)}</div><div className="compare-grid">{result.items.map((item) => <section className="panel" key={item.artifact_id}><h2>{item.experiment_id}</h2><MetricCard label="净 CAGR" metric={item.metrics.cagr} /><MetricCard label="最大回撤" metric={item.metrics.maximum_drawdown} /><MetricCard label="换手" metric={item.metrics.turnover} /></section>)}</div>{result.mode !== 'COMPARABLE' && <p className="warning">当前仅作描述性并排展示，不计算改善百分比，也不宣布胜出。</p>}</>}</Page>
}

function SignalsPage() {
  const state = useApi<Record<string, unknown>>('/signals')
  if (!state.data) return <Page title="信号诊断" subtitle="标签统计不是账户收益，也不是未来建议。"><Loading state={state} /></Page>
  const historical = state.data.historical as { summaries?: Record<string, Record<string, number>> }
  const attribution = state.data.attribution as { signals?: Record<string, { labels?: Record<string, Record<string, number>>; risk_exposures?: Record<string, Record<string, number>> }> }
  const measurement = state.data.measurement as { summaries?: Record<string, Record<string, number>> }
  return <Page title="信号诊断" subtitle="标签统计不是账户收益，也不是未来建议。">
    <section className="panel"><h2>历史 IC / Rank-IC</h2><div className="table-wrap"><table><thead><tr><th>标签区间</th><th>有效日</th><th>平均 IC</th><th>平均 Rank-IC</th><th>Top−Bottom</th></tr></thead><tbody>{Object.entries(historical.summaries ?? {}).map(([name, row]) => <tr key={name}><td>{name}</td><td>{row.evaluated_days}</td><td>{formatNumber(row.mean_ic)}</td><td>{formatNumber(row.mean_rank_ic)}</td><td>{formatRatio(row.mean_top20_minus_bottom20)}</td></tr>)}</tbody></table></div></section>
    <section className="panel"><h2>20日 Top / Pool / Bottom 与风险暴露</h2><div className="table-wrap"><table><thead><tr><th>信号</th><th>Top−池</th><th>池−Bottom</th><th>Top−Bottom</th><th>波动相关</th></tr></thead><tbody>{Object.entries(attribution.signals ?? {}).map(([name, value]) => { const label = value.labels?.open_to_open_20 ?? {}; const vol = value.risk_exposures?.vol60 ?? {}; return <tr key={name}><td>{name}</td><td>{formatRatio(label.mean_top_minus_pool)}</td><td>{formatRatio(label.mean_pool_minus_bottom)}</td><td>{formatRatio(label.mean_top_minus_bottom)}</td><td>{formatNumber(vol.mean_daily_score_correlation)}</td></tr> })}</tbody></table></div></section>
    <section className="panel"><h2>缺失标签边界审计</h2><div className="table-wrap"><table><thead><tr><th>标签</th><th>总日数</th><th>任意缺失日</th><th>Top不完整</th><th>Bottom不完整</th></tr></thead><tbody>{Object.entries(measurement.summaries ?? {}).map(([name, row]) => <tr key={name}><td>{name}</td><td>{row.days}</td><td>{row.days_with_any_missing_label}</td><td>{row.days_with_incomplete_top}</td><td>{row.days_with_incomplete_bottom}</td></tr>)}</tbody></table></div></section>
  </Page>
}

function ProspectivePage() {
  const state = useApi<Record<string, any>>('/prospective') // eslint-disable-line @typescript-eslint/no-explicit-any
  return <Page title="前瞻模拟" subtitle="所有订单均为本地模拟订单，不是买入推荐。">{!state.data ? <Loading state={state} /> : <><div className="status-row"><StatusChip value={state.data.operations_status} /><StatusChip value={state.data.input_status} /><StatusChip value={state.data.data_capture_status} /><StatusChip value={state.data.profitability_status} /></div><div className="compare-grid"><Account title="工程预热账户" value={state.data.accounts.engineering_warm_start} /><Account title="完全前瞻账户" value={state.data.accounts.fully_prospective_v1} /></div><section className="panel"><h2>每日发布记录</h2><JsonBlock value={state.data.days} /></section></>}</Page>
}

function HealthPage() {
  const state = useApi<Record<string, unknown>>('/health')
  if (!state.data) return <Page title="数据与系统健康" subtitle="系统状态均带观测时间；未实时确认时不会显示在线。"><Loading state={state} /></Page>
  const sources = (state.data.sources ?? []) as Array<Record<string, unknown>>
  const system = (state.data.system_observation ?? {}) as Record<string, unknown>
  const timer = (system.timer ?? {}) as Record<string, unknown>
  const service = (system.service ?? {}) as Record<string, unknown>
  return <Page title="数据与系统健康" subtitle="系统状态均带观测时间；未实时确认时不会显示在线。">
    <div className="compare-grid">{sources.map((source) => <section className="panel" key={String(source.source_id)}><h2>{String(source.source_id)}</h2><StatusChip value={String(source.verification_status)} /><dl><dt>最新报告</dt><dd>{String(source.latest_report_date ?? '不可用')}</dd><dt>Matrix SHA</dt><dd className="mono">{String(source.matrix_sha256 ?? '不适用')}</dd><dt>活动账本读取</dt><dd>{source.sqlite_read === false ? '否' : '不适用'}</dd></dl></section>)}</div>
    <section className="panel"><h2>前瞻任务：上次只读观测</h2><div className="status-row"><StatusChip value={String(system.status ?? 'CURRENT_UNKNOWN')} /><span>{String(system.observed_at ?? '未观测')}</span></div><div className="health-grid"><div><strong>Timer</strong><p>{String(timer.ActiveState ?? '未知')} / {String(timer.SubState ?? '未知')}</p><small>下次：{String(timer.NextElapseUSecRealtime ?? '未知')}</small></div><div><strong>最近 Service</strong><p>{String(service.Result ?? '未知')} / exit {String(service.ExecMainStatus ?? '未知')}</p><small>当前：{String(service.ActiveState ?? '未知')}</small></div><div><strong>安全边界</strong><p>CSI500：{String(state.data.csi500)}</p><small>Live broker：{String(state.data.live_broker)}</small></div></div></section>
    <section className="panel"><h2>最近快照刷新</h2><JsonBlock value={state.data.last_refresh} /></section>
  </Page>
}

function Account({ title, value }: { title: string; value: Record<string, unknown> }) { return <section className="panel"><h2>{title}</h2><StatusChip value={String(value.status)} />{value.latest ? <JsonBlock value={value.latest} /> : <p className="empty">尚未启动；不以 0 元或 0% 代替。</p>}</section> }
function Kpi({ label, value }: { label: string; value: number }) { return <div className="kpi"><span>{label}</span><strong>{value}</strong></div> }
function formatRatio(value: number | string | null | undefined) { return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—' }
function formatNumber(value: number | string | null | undefined) { return typeof value === 'number' ? value.toFixed(4) : '—' }
function Page({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) { return <main><header className="page-head"><h1>{title}</h1><p>{subtitle}</p></header>{children}</main> }

export default function App() {
  const meta = useApi<{ mode: string; snapshot_id: string; generated_at: string }>('/snapshot')
  return <div className="app"><aside><div className="brand">Quant Console <small>V1</small></div><nav>{[['/', '总览'], ['/experiments', '实验中心'], ['/signals', '信号诊断'], ['/prospective', '前瞻模拟'], ['/health', '数据与系统健康']].map(([to, label]) => <NavLink key={to} to={to} end={to === '/'}>{label}</NavLink>)}</nav><div className="snapshot">{meta.data?.mode === 'demo' && <strong>演示数据，不是研究结果</strong>}<span>{meta.data ? `快照 ${meta.data.snapshot_id.slice(0, 10)}` : '快照未就绪'}</span></div></aside><div className="content"><Routes><Route path="/" element={<OverviewPage />} /><Route path="/experiments" element={<ExperimentsPage />} /><Route path="/experiments/compare" element={<ComparePage />} /><Route path="/experiments/:id" element={<ExperimentDetailPage />} /><Route path="/signals" element={<SignalsPage />} /><Route path="/prospective" element={<ProspectivePage />} /><Route path="/health" element={<HealthPage />} /></Routes></div></div>
}
