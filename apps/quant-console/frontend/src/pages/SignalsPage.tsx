import * as Tabs from '@radix-ui/react-tabs'
import { useQuery } from '@tanstack/react-query'
import { ErrorState, JsonDisclosure, Loading, Page } from '../components'
import { formatNumber, formatRatio } from '../formatters'
import { signalsQuery } from '../queries'
import { useSnapshot } from '../snapshot-context'

export default function SignalsPage() {
  const { snapshotId } = useSnapshot()
  const query = useQuery(signalsQuery(snapshotId))
  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorState message={query.error.message} />
  const value = query.data
  const historical = records(record(value.historical).summaries)
  const attribution = records(record(value.attribution).signals)
  const measurement = records(record(value.measurement).summaries)
  return <Page title="信号诊断" subtitle="标签区间、分组来源、风险暴露和缺失边界分别展示；不把统计标签画成投资净值。">
    <Tabs.Root defaultValue="ic" className="tabs">
      <Tabs.List aria-label="信号诊断视图">
        <Tabs.Trigger value="ic">IC / Rank-IC</Tabs.Trigger>
        <Tabs.Trigger value="attribution">Top / Pool / Bottom</Tabs.Trigger>
        <Tabs.Trigger value="measurement">缺失标签边界</Tabs.Trigger>
        <Tabs.Trigger value="prospective">前瞻摘要</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="ic" className="panel">
        <h2>历史标签区间</h2>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>标签区间</th><th>有效日</th><th>平均 IC</th><th>平均 Rank-IC</th><th>Top−Bottom</th></tr></thead>
          <tbody>{Object.entries(historical).map(([name, row]) => <tr key={name}><td>{name}</td><td>{text(row.evaluated_days)}</td><td>{formatNumber(num(row.mean_ic))}</td><td>{formatNumber(num(row.mean_rank_ic))}</td><td>{formatRatio(num(row.mean_top20_minus_bottom20))}</td></tr>)}</tbody>
        </table></div>
      </Tabs.Content>
      <Tabs.Content value="attribution" className="panel">
        <h2>20日分组与风险暴露</h2>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>信号</th><th>Top−池</th><th>池−Bottom</th><th>Top−Bottom</th><th>波动相关</th></tr></thead>
          <tbody>{Object.entries(attribution).map(([name, raw]) => {
            const labels = record(record(raw.labels).open_to_open_20)
            const vol = record(record(raw.risk_exposures).vol60)
            return <tr key={name}><td>{name}</td><td>{formatRatio(num(labels.mean_top_minus_pool))}</td><td>{formatRatio(num(labels.mean_pool_minus_bottom))}</td><td>{formatRatio(num(labels.mean_top_minus_bottom))}</td><td>{formatNumber(num(vol.mean_daily_score_correlation))}</td></tr>
          })}</tbody>
        </table></div>
      </Tabs.Content>
      <Tabs.Content value="measurement" className="panel">
        <h2>缺失标签边界审计</h2>
        <div className="table-wrap"><table className="data-table"><thead><tr><th>标签</th><th>总日数</th><th>任意缺失日</th><th>Top 不完整</th><th>Bottom 不完整</th></tr></thead>
          <tbody>{Object.entries(measurement).map(([name, row]) => <tr key={name}><td>{name}</td><td>{text(row.days)}</td><td>{text(row.days_with_any_missing_label)}</td><td>{text(row.days_with_incomplete_top)}</td><td>{text(row.days_with_incomplete_bottom)}</td></tr>)}</tbody>
        </table></div>
      </Tabs.Content>
      <Tabs.Content value="prospective" className="panel">
        <h2>已发布前瞻诊断</h2>
        <JsonDisclosure value={value.prospective} label="查看当前可用字段" />
        <p className="caption">没有逐日诊断序列时只显示来源汇总，不插值或补造时序。</p>
      </Tabs.Content>
    </Tabs.Root>
  </Page>
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function records(value: unknown): Record<string, Record<string, unknown>> {
  return Object.fromEntries(Object.entries(record(value)).map(([key, item]) => [key, record(item)]))
}

function num(value: unknown): number | null {
  return typeof value === 'number' ? value : null
}

function text(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '不可用'
}
