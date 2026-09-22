import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import type { Experiment, Metric } from './types'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

export function StatusChip({ value }: { value: string | null | undefined }) {
  const text = value ?? 'UNKNOWN'
  const tone = /VALID|PASS|COMPLETE|COMPARABLE|OBSERVED/.test(text) && !/NOT_|INVALID/.test(text) ? 'ok' : /NOT_|FAIL|DEGRADED|INVALID|MISSING/.test(text) ? 'warn' : 'neutral'
  return <span className={`status ${tone}`}><span aria-hidden="true" className="status-dot" />{text}</span>
}

export function MetricCard({ label, metric }: { label: string; metric?: Metric }) {
  if (!metric || metric.value === null) return <div className="metric"><span>{label}</span><strong>不可用</strong><small>{metric?.unavailable_reason ?? '来源未提供'}</small></div>
  const value = typeof metric.value === 'number' && metric.unit === 'ratio' ? `${(metric.value * 100).toFixed(2)}%` : metric.unit === 'CNY' ? `¥${Number(metric.value).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}` : String(metric.value)
  return <div className="metric"><span>{label}</span><strong className={typeof metric.value === 'number' && metric.value < 0 ? 'negative' : ''}>{value}</strong><small>{metric.unit}</small></div>
}

export function NavChart({ experiment }: { experiment: Experiment }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current || !experiment.nav_series?.length) return
    const chart = echarts.init(ref.current)
    chart.setOption({ animation: false, grid: { left: 55, right: 18, top: 20, bottom: 42 }, tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: experiment.nav_series.map((x) => x.date), axisLabel: { hideOverlap: true } }, yAxis: { type: 'value', scale: true }, series: [{ type: 'line', showSymbol: false, data: experiment.nav_series.map((x) => Number(x.nav)), lineStyle: { color: '#2563eb', width: 1.5 }, areaStyle: { color: 'rgba(37,99,235,.08)' } }] })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.removeEventListener('resize', resize); chart.dispose() }
  }, [experiment])
  if (!experiment.nav_series?.length) return <div className="empty">没有经校验的逐日净值来源，未绘制曲线。</div>
  return <div ref={ref} className="chart" role="img" aria-label={`${experiment.experiment_id} 真实净值曲线`} />
}

export function JsonBlock({ value }: { value: unknown }) { return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre> }
