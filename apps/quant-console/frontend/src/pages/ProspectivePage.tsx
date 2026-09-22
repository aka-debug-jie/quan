import { useQuery } from '@tanstack/react-query'
import { EmptyState, ErrorState, Loading, Page, StatusChip } from '../components'
import type { ProspectiveDay } from '../domain'
import { formatNumber } from '../formatters'
import { prospectiveQuery } from '../queries'
import { useSnapshot } from '../snapshot-context'

export default function ProspectivePage() {
  const { snapshotId } = useSnapshot()
  const query = useQuery(prospectiveQuery(snapshotId))
  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorState message={query.error.message} />
  const value = query.data
  return <Page title="前瞻模拟" subtitle="只读取已发布 JSON；不能控制 timer、账户、持仓或订单。">
    <div className="status-row detail-status">
      <StatusChip value={value.operations_status} />
      <StatusChip value={value.input_status} />
      <StatusChip value={value.data_capture_status} />
      <StatusChip value={value.profitability_status} />
    </div>
    {value.warnings.map((warning) => <div className="warning-line" key={warning}><StatusChip value={warning} /></div>)}
    <div className="dashboard-grid">
      <Account title="工程预热账户" status={value.accounts.engineering_warm_start.status} latest={value.accounts.engineering_warm_start.latest} days={value.accounts.engineering_warm_start.observed_days} />
      <Account title="完全前瞻账户" status={value.accounts.fully_prospective_v1.status} latest={value.accounts.fully_prospective_v1.latest} days={value.accounts.fully_prospective_v1.observed_days} />
    </div>
    <section className="panel">
      <div className="section-head"><div><span className="eyebrow">不可回写的发布记录</span><h2>每日状态</h2></div><span className="muted">最新：{value.latest_date ?? '尚无'}</span></div>
      {value.days.length === 0 ? <EmptyState>尚无已发布前瞻记录。</EmptyState> : <div className="table-wrap"><table className="data-table">
        <thead><tr><th>交易日</th><th>阶段</th><th>输入</th><th>抓取</th><th>信号</th><th>账户</th><th>覆盖</th><th>持仓</th><th>成交</th><th>拒绝</th></tr></thead>
        <tbody>{value.days.map((day, index) => <tr key={`${day.trading_date}-${index}`}>
          <td>{day.trading_date ?? '未知'}</td><td>{day.paper_account_phase ?? '未知'}</td>
          <td><StatusChip value={day.INPUT_STATUS} /></td><td><StatusChip value={day.DATA_CAPTURE_STATUS} /></td>
          <td><StatusChip value={day.SHADOW_SIGNAL_STATUS} /></td><td><StatusChip value={day.PAPER_ACCOUNT_STATUS} /></td>
          <td>{formatNumber(day.coverage)}</td><td>{day.position_count}</td><td>{day.fills_today ?? '不可用'}</td><td>{day.rejection_count}</td>
        </tr>)}</tbody>
      </table></div>}
    </section>
  </Page>
}

function Account({ title, status, latest, days }: { title: string; status: string; latest: ProspectiveDay | null; days: number }) {
  return <section className="panel account-card"><div className="section-head"><h2>{title}</h2><StatusChip value={status} /></div>
    {!latest ? <EmptyState>尚未启动；不以 0 元或 0% 代替。</EmptyState> : <dl className="account-metrics">
      <div><dt>观察日</dt><dd>{days}</dd></div>
      <div><dt>NAV</dt><dd>{latest.nav ?? '不可用'}</dd></div>
      <div><dt>现金</dt><dd>{latest.cash ?? '不可用'}</dd></div>
      <div><dt>持仓数</dt><dd>{latest.position_count}</dd></div>
      <div><dt>平均 IC</dt><dd>{formatNumber(latest.mean_ic)}</dd></div>
      <div><dt>平均 Rank-IC</dt><dd>{formatNumber(latest.mean_rank_ic)}</dd></div>
    </dl>}
  </section>
}
