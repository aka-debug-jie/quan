import * as Dialog from '@radix-ui/react-dialog'
import * as Tooltip from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'
import type { EvidenceSummary, Metric } from './domain'
import { formatMetric } from './formatters'

export function Button({
  children,
  variant = 'primary',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
}) {
  return <button className={`button button-${variant}`} {...props}>{children}</button>
}

export function StatusChip({ value }: { value: string | null | undefined }) {
  const text = value || 'UNKNOWN'
  const kind = statusKind(text)
  return <span className={`status status-${kind}`}><span aria-hidden="true" className="status-dot" />{text}</span>
}

export function MetricCard({ label, metric }: { label: string; metric?: Metric }) {
  return <section className="metric-card">
    <span>{label}</span>
    <strong>{formatMetric(metric)}</strong>
    <small>{metric?.validity === 'VALID' ? metric.unit : metric?.unavailable_reason ?? '暂无来源指标'}</small>
  </section>
}

export function Page({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string
  subtitle: string
  actions?: ReactNode
  children: ReactNode
}) {
  return <main>
    <header className="page-head">
      <div><h1>{title}</h1><p>{subtitle}</p></div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
    {children}
  </main>
}

export function Loading({ label = '正在读取已发布快照…' }: { label?: string }) {
  return <div className="loading" role="status"><span className="spinner" />{label}</div>
}

export function ErrorState({
  title = '加载失败',
  message,
  action,
}: {
  title?: string
  message: string
  action?: ReactNode
}) {
  return <div className="alert alert-error" role="alert">
    <strong>{title}</strong><p>{message}</p>{action}
  </div>
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function Hint({ label, children }: { label: string; children: ReactNode }) {
  return <Tooltip.Provider delayDuration={250}>
    <Tooltip.Root>
      <Tooltip.Trigger asChild><button className="hint" aria-label={label}>?</button></Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="tooltip" sideOffset={6}>{children}<Tooltip.Arrow className="tooltip-arrow" /></Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  </Tooltip.Provider>
}

export function EvidenceDialog({
  open,
  onOpenChange,
  evidence,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  evidence?: EvidenceSummary
}) {
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Portal>
      <Dialog.Overlay className="dialog-overlay" />
      <Dialog.Content className="dialog-content" aria-describedby="evidence-description">
        <Dialog.Close className="dialog-close" aria-label="关闭">×</Dialog.Close>
        <Dialog.Title>来源证据</Dialog.Title>
        <Dialog.Description id="evidence-description">
          仅展示安全身份、哈希、数据等级和限制，不暴露本机路径。
        </Dialog.Description>
        {!evidence ? <Loading /> : <dl className="detail-list">
          <dt>来源类型</dt><dd>{evidence.source_kind}</dd>
          <dt>研究</dt><dd>{evidence.study_id ?? '不适用'}</dd>
          <dt>运行身份</dt><dd className="mono">{evidence.run_identity ?? '不适用'}</dd>
          <dt>SHA-256</dt><dd className="mono">{evidence.sha256 ?? evidence.receipt_sha256 ?? '未提供'}</dd>
          <dt>数据等级</dt><dd>{evidence.data_use_level ?? '未提供'}</dd>
          <dt>限制</dt><dd>{(evidence.limitations ?? []).length ? evidence.limitations?.join('；') : '无附加说明'}</dd>
        </dl>}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

export function JsonDisclosure({ value, label = '查看原始结构' }: { value: unknown; label?: string }) {
  return <details className="json-disclosure"><summary>{label}</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
}

function statusKind(value: string): 'good' | 'warn' | 'bad' | 'neutral' {
  if (/VALID|PASS|COMPLETE|COMPARABLE|OBSERVED|REFERENCE/.test(value) && !/NOT_|INVALID|INCOMPLETE/.test(value)) return 'good'
  if (/FAIL|INVALID|FORBIDDEN|NO_EDGE|NO_PROMOTABLE/.test(value)) return 'bad'
  if (/NOT_|UNKNOWN|MIXED|DEGRADED|INSUFFICIENT|RC/.test(value)) return 'warn'
  return 'neutral'
}
