/* eslint-disable react-refresh/only-export-components -- provider and its typed hook form one module */
import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, useEffect, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { SnapshotMeta } from './domain'
import { snapshotQuery } from './queries'

interface SnapshotContextValue {
  snapshotId: string
  current?: SnapshotMeta
  pinnedIsCurrent: boolean
}

const SnapshotContext = createContext<SnapshotContextValue | null>(null)

export function SnapshotProvider({ children }: { children: ReactNode }) {
  const current = useQuery(snapshotQuery())
  const [params, setParams] = useSearchParams()
  const requested = params.get('snapshot')
  useEffect(() => {
    if (!requested && current.data?.snapshot_id) {
      const next = new URLSearchParams(params)
      next.set('snapshot', current.data.snapshot_id)
      setParams(next, { replace: true })
    }
  }, [current.data?.snapshot_id, params, requested, setParams])
  if (current.isPending || (!requested && !current.data)) {
    return <div className="app-loading" role="status">正在锁定展示快照…</div>
  }
  if (current.isError && !requested) {
    return <div className="app-loading error" role="alert">当前展示快照不可用：{current.error.message}</div>
  }
  const snapshotId = requested ?? current.data?.snapshot_id
  if (!snapshotId) return null
  return <SnapshotContext.Provider value={{
    snapshotId,
    current: current.data,
    pinnedIsCurrent: current.data?.snapshot_id === snapshotId,
  }}>{children}</SnapshotContext.Provider>
}

export function useSnapshot(): SnapshotContextValue {
  const value = useContext(SnapshotContext)
  if (!value) throw new Error('SnapshotProvider is required')
  return value
}

export function snapshotHref(path: string, snapshotId: string): string {
  const url = new URL(path, 'http://local.invalid')
  url.searchParams.set('snapshot', snapshotId)
  return `${url.pathname}${url.search}`
}
