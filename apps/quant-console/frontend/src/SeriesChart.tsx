import { LineChart } from 'echarts/charts'
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'
import type { SeriesResponse } from './domain'

echarts.use([
  LineChart,
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  TooltipComponent,
  CanvasRenderer,
])

export default function SeriesChart({ series }: { series: SeriesResponse[] }) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current || series.length === 0) return
    let chart: ReturnType<typeof echarts.init> | undefined
    try {
      chart = echarts.init(host.current, undefined, { renderer: 'canvas' })
      const nav = series.find((item) => item.meta.kind === 'NAV')
      const drawdown = series.find((item) => item.meta.kind === 'DRAWDOWN')
      const dates = nav?.points.map((point) => point.date) ?? drawdown?.points.map((point) => point.date) ?? []
      chart.setOption({
        animation: false,
        aria: { enabled: true, description: '经校验的净值与由净值派生的回撤时序' },
        tooltip: {
          trigger: 'axis',
          valueFormatter: (value: unknown) => typeof value === 'number'
            ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
            : String(value),
        },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
          { left: 62, right: 24, top: 34, height: '50%' },
          { left: 62, right: 24, top: '68%', height: '17%' },
        ],
        xAxis: [
          { type: 'category', data: dates, boundaryGap: false, axisLabel: { hideOverlap: true } },
          { type: 'category', data: dates, boundaryGap: false, gridIndex: 1, axisLabel: { hideOverlap: true } },
        ],
        yAxis: [
          { type: 'value', name: 'NAV', scale: true },
          {
            type: 'value',
            name: '回撤',
            gridIndex: 1,
            axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
          },
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1] },
          { type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 18 },
        ],
        series: [
          ...(nav ? [{
            name: 'NAV',
            type: 'line',
            data: nav.points.map((point) => Number(point.value)),
            showSymbol: false,
            sampling: 'lttb',
            lineStyle: { width: 2, color: '#2563eb' },
            itemStyle: { color: '#2563eb' },
            xAxisIndex: 0,
            yAxisIndex: 0,
          }] : []),
          ...(drawdown ? [{
            name: '回撤',
            type: 'line',
            data: drawdown.points.map((point) => Number(point.value)),
            showSymbol: false,
            sampling: 'lttb',
            areaStyle: { color: 'rgba(220, 38, 38, 0.18)' },
            lineStyle: { width: 1.5, color: '#dc2626' },
            itemStyle: { color: '#dc2626' },
            xAxisIndex: 1,
            yAxisIndex: 1,
          }] : []),
        ],
      })
      const observer = new ResizeObserver(() => chart?.resize())
      observer.observe(host.current)
      return () => {
        observer.disconnect()
        chart?.dispose()
      }
    } catch (cause) {
      chart?.dispose()
      if (host.current) {
        host.current.className = 'alert alert-error'
        host.current.setAttribute('role', 'alert')
        host.current.textContent = `图表不可用：${cause instanceof Error ? cause.message : '图表初始化失败'}`
      }
    }
  }, [series])
  return <div ref={host} className="series-chart" role="img" aria-label="真实净值与回撤曲线" />
}
