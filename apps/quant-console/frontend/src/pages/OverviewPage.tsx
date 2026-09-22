import { useQuery } from '@tanstack/react-query'
import { ErrorState, Loading, Page, StatusChip } from '../components'
import { overviewQuery } from '../queries'
import { useSnapshot } from '../snapshot-context'

export default function OverviewPage() {
  const { snapshotId } = useSnapshot()
  const query = useQuery(overviewQuery(snapshotId))
  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorState message={query.error.message} />
  const value = query.data
  return <Page title="研究总览" subtitle="显示已有证据和限制，不生成推荐或重新运行实验。">
    <div className="kpis">
      <Kpi label="注册运行" value={value.registered_runs} />
      <Kpi label="可评价" value={value.valid_runs} />
      <Kpi label="不可评价" value={value.not_evaluable_runs} />
      <Kpi label="晋级候选" value={value.retained_candidates} />
    </div>
    <div className="dashboard-grid">
      <section className="panel panel-feature">
        <span className="eyebrow">当前研究结论</span>
        <h2>强化研究已完成，未产生可晋级候选</h2>
        <div className="status-row">
          <StatusChip value={value.current_stage} />
          <StatusChip value={value.economic_outcome} />
        </div>
        <p>旧工程证据 {value.legacy_invalid_engineering_runs} 项，仅保留追溯，不重复计入当前 registry。工程测试通过不等于策略通过。</p>
      </section>
      <section className="panel">
        <span className="eyebrow">前瞻模拟</span>
        <h2>运行状态与盈利结论分开</h2>
        <div className="status-row">
          <StatusChip value={value.prospective_status} />
          <span>最新发布日：{value.latest_prospective_date ?? '尚无'}</span>
        </div>
        {value.warnings.length === 0
          ? <p className="muted">当前快照没有附加告警。</p>
          : value.warnings.map((warning) => <div className="warning-line" key={warning}><StatusChip value={warning} /></div>)}
      </section>
    </div>
    <section className="panel boundary-panel">
      <h2>使用边界</h2>
      <div className="boundary-grid">
        <div><strong>只读研究</strong><span>页面不能启动实验、抓取行情或修改账户。</span></div>
        <div><strong>非商业数据</strong><span>历史结果仅限本机非商业研究展示。</span></div>
        <div><strong>无策略晋级</strong><span>负结果与不可评价状态均按来源原样保留。</span></div>
      </div>
    </section>
  </Page>
}

function Kpi({ label, value }: { label: string; value: number }) {
  return <section className="kpi"><span>{label}</span><strong>{value}</strong></section>
}

