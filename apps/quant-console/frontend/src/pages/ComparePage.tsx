import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { compareExperiments } from '../api'
import { EmptyState, ErrorState, Loading, Page, StatusChip } from '../components'
import { formatMetric } from '../formatters'
import { snapshotHref, useSnapshot } from '../snapshot-context'

export default function ComparePage() {
  const { snapshotId } = useSnapshot()
  const [params] = useSearchParams()
  const ids = params.getAll('id').slice(0, 4)
  const query = useQuery({
    queryKey: ['snapshot', snapshotId, 'comparison', ids],
    queryFn: ({ signal }) => compareExperiments(snapshotId, ids, signal),
    enabled: ids.length >= 2,
    staleTime: Infinity,
  })
  if (ids.length < 2) return <Page title="实验比较" subtitle="比较选择必须保存在 URL 中。">
    <EmptyState>没有足够的比较项。<Link to={snapshotHref('/experiments', snapshotId)}>返回实验中心选择 2–4 项</Link></EmptyState>
  </Page>
  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorState message={query.error.message} />
  const value = query.data
  return <Page
    title="实验比较"
    subtitle="先验证数据、协议、期间与场景，再并列已有结果；不自动评选赢家。"
    actions={<Link className="button button-ghost" to={snapshotHref('/experiments', snapshotId)}>调整选择</Link>}
  >
    <section className="panel compatibility-panel">
      <div className="section-head"><div><span className="eyebrow">兼容性检查</span><h2><StatusChip value={value.mode} /></h2></div>
        <span>{value.economic_inference_allowed ? '允许按当前口径作有限经济比较' : '不允许据此作经济优劣推断'}</span>
      </div>
      {value.changed_fields.length > 0 && <p>预注册变化轴：{value.changed_fields.join('、')}</p>}
      {value.reasons.length > 0 && <ul>{value.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    </section>
    <section className="panel table-wrap">
      <table className="data-table compare-table">
        <thead><tr><th>实验</th><th>绝对数据</th><th>匹配基准</th><th>净 CAGR</th><th>年化波动率</th><th>Sharpe</th><th>最大回撤</th><th>双边换手</th><th>交易次数</th><th>直接费用</th><th>经济结论</th></tr></thead>
        <tbody>{value.items.map((item) => <tr key={item.artifact_id}>
          <td><Link to={snapshotHref(`/experiments/${encodeURIComponent(item.artifact_id)}`, snapshotId)}>{item.experiment_id}</Link><small>{item.scenario_id}</small></td>
          <td><StatusChip value={item.data_evaluability} /></td>
          <td><StatusChip value={item.benchmark_comparability} /></td>
          <td>{formatMetric(item.metrics.cagr)}</td>
          <td>{formatMetric(item.metrics.annualized_volatility)}</td>
          <td>{formatMetric(item.metrics.sharpe_ratio)}</td>
          <td>{formatMetric(item.metrics.maximum_drawdown)}</td>
          <td>{formatMetric(item.metrics.turnover)}</td>
          <td>{formatMetric(item.metrics.trade_count)}</td>
          <td>{formatMetric(item.metrics.total_transaction_costs)}</td>
          <td><StatusChip value={item.economic_outcome} /></td>
        </tr>)}</tbody>
      </table>
    </section>
  </Page>
}
