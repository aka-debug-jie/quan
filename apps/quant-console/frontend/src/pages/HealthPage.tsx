import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { reloadSnapshot } from '../api'
import { Button, ErrorState, JsonDisclosure, Loading, Page, StatusChip } from '../components'
import { healthQuery, runtimeQuery, snapshotQuery } from '../queries'
import { useSnapshot } from '../snapshot-context'

export default function HealthPage() {
  const { snapshotId, current } = useSnapshot()
  const health = useQuery(healthQuery(snapshotId))
  const runtime = useQuery(runtimeQuery())
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const reload = useMutation({
    mutationFn: () => reloadSnapshot(),
    onSuccess: async (result) => {
      const next = new URLSearchParams(params)
      next.set('snapshot', result.snapshot.snapshot_id)
      setParams(next, { replace: true })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: snapshotQuery().queryKey }),
        queryClient.invalidateQueries({ queryKey: runtimeQuery().queryKey }),
      ])
    },
  })
  if (health.isPending || runtime.isPending) return <Loading />
  if (health.isError) return <ErrorState message={health.error.message} />
  if (runtime.isError) return <ErrorState message={runtime.error.message} />
  return <Page
    title="数据与系统健康"
    subtitle="来源完整性和 systemd 观测均绑定明确时间；页面不会把旧观测称为实时在线。"
    actions={<Button
      variant="secondary"
      disabled={reload.isPending || current?.mode === 'demo'}
      onClick={() => reload.mutate()}
    >{reload.isPending ? '正在重载…' : '重载已发布来源'}</Button>}
  >
    {reload.isError && <ErrorState title="重载失败" message={reload.error.message} />}
    {reload.data && <div className="alert alert-success">重载完成：{reload.data.changed ? '已切换到新快照' : '内容未变化，继续使用相同身份'}。</div>}
    <div className="kpis health-kpis">
      <section className="kpi"><span>当前展示快照</span><strong className="mono small">{snapshotId.slice(0, 12)}</strong></section>
      <section className="kpi"><span>应用版本</span><strong>{runtime.data.app_version}</strong></section>
      <section className="kpi"><span>交易入口</span><strong>{health.data.live_broker}</strong></section>
      <section className="kpi"><span>CSI500</span><strong>{health.data.csi500}</strong></section>
    </div>
    <section className="panel">
      <h2>来源完整性</h2>
      <div className="table-wrap"><table className="data-table health-table">
        <thead><tr><th>来源</th><th>验证</th><th>Manifest</th><th>Matrix / 最近日期</th><th>账户库读取</th></tr></thead>
        <tbody>{health.data.sources.map((source) => <tr key={source.source_id}>
          <td>{source.source_id}</td><td><StatusChip value={source.verification_status} /></td>
          <td className="mono">{source.manifest_sha256?.slice(0, 16) ?? '不适用'}</td>
          <td className="mono">{source.matrix_sha256?.slice(0, 16) ?? source.latest_report_date ?? '不适用'}</td>
          <td>{source.sqlite_read === undefined || source.sqlite_read === null ? '不适用' : source.sqlite_read ? '是' : '否'}</td>
        </tr>)}</tbody>
      </table></div>
    </section>
    <div className="dashboard-grid">
      <section className="panel">
        <h2>前瞻系统观测</h2>
        <div className="status-row"><StatusChip value={health.data.system_observation.status} /><span>{health.data.system_observation.observed_at ?? '未观测'}</span></div>
        <JsonDisclosure value={{ timer: health.data.system_observation.timer, service: health.data.system_observation.service, unit_hashes: health.data.system_observation.unit_hashes }} />
      </section>
      <section className="panel">
        <h2>Console 最近刷新</h2>
        <JsonDisclosure value={runtime.data.last_refresh} label="查看刷新状态" />
        <p className="caption">重载只重读固定白名单结构化产物并写入 Console 自己的 runtime。</p>
      </section>
    </div>
  </Page>
}
