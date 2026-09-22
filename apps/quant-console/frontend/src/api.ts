import createClient from 'openapi-fetch'
import type { paths } from './generated/api-schema'
import type {
  CompatibilityResult,
  EvidenceSummary,
  ExperimentDetail,
  ExperimentPage,
  ExportRequest,
  HealthSummary,
  Overview,
  ProspectiveSummary,
  ReloadResult,
  RuntimeStatus,
  SeriesResponse,
  SignalsSummary,
  SnapshotMeta,
  StudyList,
} from './domain'

const client = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? 'http://127.0.0.1' : window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})

export class ApiClientError extends Error {
  status: number
  code: string
  recoverable: boolean

  constructor(status: number, code: string, message: string, recoverable = false) {
    super(message)
    this.name = 'ApiClientError'
    this.status = status
    this.code = code
    this.recoverable = recoverable
  }
}

type ApiResult<T> = { data?: T; error?: unknown; response: Response }

function unwrap<T>({ data, error, response }: ApiResult<T>): T {
  if (data !== undefined) return data
  const envelope = error as { error?: { code?: string; message?: string; recoverable?: boolean } }
  throw new ApiClientError(
    response.status,
    envelope.error?.code ?? 'REQUEST_FAILED',
    envelope.error?.message ?? `请求失败（HTTP ${response.status}）`,
    envelope.error?.recoverable ?? response.status >= 500,
  )
}

export async function getSnapshot(signal?: AbortSignal): Promise<SnapshotMeta> {
  return unwrap(await client.GET('/api/v1/snapshot', { signal }))
}

export async function getRuntime(signal?: AbortSignal): Promise<RuntimeStatus> {
  return unwrap(await client.GET('/api/v1/runtime', { signal }))
}

export async function getOverview(snapshotId: string, signal?: AbortSignal): Promise<Overview> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/overview', {
    params: { path: { snapshot_id: snapshotId } },
    signal,
  }))
}

export async function getStudies(snapshotId: string, signal?: AbortSignal): Promise<StudyList> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/studies', {
    params: { path: { snapshot_id: snapshotId } },
    signal,
  }))
}

export async function getExperiments(snapshotId: string, signal?: AbortSignal): Promise<ExperimentPage> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/experiments', {
    params: {
      path: { snapshot_id: snapshotId },
      query: { page: 1, page_size: 10000, sort: 'experiment_id', direction: 'asc' },
    },
    signal,
  }))
}

export async function getExperiment(
  snapshotId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<ExperimentDetail> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/experiments/{artifact_id}', {
    params: { path: { snapshot_id: snapshotId, artifact_id: artifactId } },
    signal,
  }))
}

export async function getSeries(
  snapshotId: string,
  seriesId: string,
  signal?: AbortSignal,
): Promise<SeriesResponse> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/series/{series_id}', {
    params: { path: { snapshot_id: snapshotId, series_id: seriesId } },
    signal,
  }))
}

export async function compareExperiments(
  snapshotId: string,
  artifactIds: string[],
  signal?: AbortSignal,
): Promise<CompatibilityResult> {
  return unwrap(await client.POST('/api/v1/snapshots/{snapshot_id}/comparisons/validate', {
    params: { path: { snapshot_id: snapshotId } },
    body: { artifact_ids: artifactIds },
    signal,
  }))
}

export async function getSignals(snapshotId: string, signal?: AbortSignal): Promise<SignalsSummary> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/signals', {
    params: { path: { snapshot_id: snapshotId } },
    signal,
  }))
}

export async function getProspective(
  snapshotId: string,
  signal?: AbortSignal,
): Promise<ProspectiveSummary> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/prospective', {
    params: { path: { snapshot_id: snapshotId } },
    signal,
  }))
}

export async function getHealth(snapshotId: string, signal?: AbortSignal): Promise<HealthSummary> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/health', {
    params: { path: { snapshot_id: snapshotId } },
    signal,
  }))
}

export async function getEvidence(
  snapshotId: string,
  evidenceId: string,
  signal?: AbortSignal,
): Promise<EvidenceSummary> {
  return unwrap(await client.GET('/api/v1/snapshots/{snapshot_id}/evidence/{evidence_id}', {
    params: { path: { snapshot_id: snapshotId, evidence_id: evidenceId } },
    signal,
  }))
}

export async function reloadSnapshot(signal?: AbortSignal): Promise<ReloadResult> {
  return unwrap(await client.POST('/api/v1/snapshot/reload', { signal }))
}

export async function exportExperiments(snapshotId: string, payload: ExportRequest): Promise<void> {
  const response = await fetch(
    `/api/v1/snapshots/${encodeURIComponent(snapshotId)}/exports/experiments`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  )
  if (!response.ok) {
    const error = await response.json() as { error?: { code?: string; message?: string } }
    throw new ApiClientError(
      response.status,
      error.error?.code ?? 'EXPORT_FAILED',
      error.error?.message ?? '安全导出失败',
    )
  }
  if (response.headers.get('X-Quant-Snapshot-ID') !== snapshotId) {
    throw new ApiClientError(409, 'EXPORT_SNAPSHOT_MISMATCH', '导出快照身份不一致')
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `quant-console-${snapshotId.slice(0, 12)}.csv`
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
