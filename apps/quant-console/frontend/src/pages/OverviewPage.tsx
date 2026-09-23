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
  const closure = value.closure_counts
  return <Page title="研究总览" subtitle="显示已有证据和限制，不生成推荐或重新运行实验。">
    <div className="kpis">
      <Kpi label="注册运行" value={value.registered_runs} />
      <Kpi label="可评价" value={value.valid_runs} />
      <Kpi label="不可评价" value={value.not_evaluable_runs} />
      <Kpi label="待审核候选" value={value.retained_candidates} />
    </div>
    <div className="dashboard-grid">
      <section className="panel panel-feature">
        <span className="eyebrow">当前研究结论</span>
        <h2>{closure ? '本轮历史重评结果已发布' : '强化研究已完成，未产生可晋级候选'}</h2>
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
    {closure && <section className="panel">
      <h2>研究修订与历史版本</h2>
      <p>上轮强化研究：登记 {closure.old_registered_runs} 项，可评价 {closure.old_valid_runs} 项，不可评价 {closure.old_not_evaluable_runs} 项，保留候选 {closure.old_retained_candidates} 项。原结果仍可在实验中心查看。</p>
      <p>本轮：旧运行修订 {closure.revised_runs} 项，新增机制对照 {closure.new_control_runs} 项，资本规模诊断 {closure.conditional_scale_runs} 项，复用旧结果 {closure.cache_reuse_from_old_study} 项；当前可评价 {closure.valid_runs} 项，不可评价 {closure.not_evaluable_runs} 项。</p>
    </section>}
    <section className="panel boundary-panel">
      <h2>使用边界</h2>
      <div className="boundary-grid">
        <div><strong>只读研究</strong><span>页面不能启动实验、抓取行情或修改账户。</span></div>
        <div><strong>非商业数据</strong><span>历史结果仅限本机非商业研究展示。</span></div>
        <div><strong>研究级候选</strong><span>负结果与不可评价状态均按来源原样保留；候选不自动部署。</span></div>
      </div>
    </section>
  </Page>
}

function Kpi({ label, value }: { label: string; value: number }) {
  return <section className="kpi"><span>{label}</span><strong>{value}</strong></section>
}
