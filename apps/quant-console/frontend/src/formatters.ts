import type { Metric } from './domain'

export function formatMetric(metric?: Metric): string {
  if (!metric || metric.validity !== 'VALID' || metric.value === null) return '不可用'
  if (metric.unit === 'ratio' || metric.unit === 'two_sided_ratio') {
    return new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(metric.value)
  }
  if (metric.unit === 'CNY') {
    return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(metric.value)
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(metric.value)
}

export function formatRatio(value: number | null | undefined): string {
  return value == null ? '不可用' : new Intl.NumberFormat('zh-CN', { style: 'percent', maximumFractionDigits: 2 }).format(value)
}

export function formatNumber(value: number | null | undefined): string {
  return value == null ? '不可用' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value)
}

