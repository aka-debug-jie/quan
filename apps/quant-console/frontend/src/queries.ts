import { queryOptions } from '@tanstack/react-query'
import {
  getEvidence,
  getExperiment,
  getExperiments,
  getHealth,
  getOverview,
  getProspective,
  getRuntime,
  getSeries,
  getSignals,
  getSnapshot,
  getStudies,
} from './api'

export const snapshotQuery = () => queryOptions({
  queryKey: ['snapshot', 'current'],
  queryFn: ({ signal }) => getSnapshot(signal),
  staleTime: 30_000,
  refetchInterval: 60_000,
  refetchOnWindowFocus: false,
})

export const runtimeQuery = () => queryOptions({
  queryKey: ['runtime'],
  queryFn: ({ signal }) => getRuntime(signal),
  staleTime: 30_000,
  refetchInterval: 60_000,
})

export const overviewQuery = (snapshotId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'overview'],
  queryFn: ({ signal }) => getOverview(snapshotId, signal),
  staleTime: Infinity,
})

export const studiesQuery = (snapshotId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'studies'],
  queryFn: ({ signal }) => getStudies(snapshotId, signal),
  staleTime: Infinity,
})

export const experimentsQuery = (snapshotId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'experiments'],
  queryFn: ({ signal }) => getExperiments(snapshotId, signal),
  staleTime: Infinity,
})

export const experimentQuery = (snapshotId: string, artifactId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'experiment', artifactId],
  queryFn: ({ signal }) => getExperiment(snapshotId, artifactId, signal),
  staleTime: Infinity,
})

export const seriesQuery = (snapshotId: string, seriesId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'series', seriesId],
  queryFn: ({ signal }) => getSeries(snapshotId, seriesId, signal),
  staleTime: Infinity,
})

export const signalsQuery = (snapshotId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'signals'],
  queryFn: ({ signal }) => getSignals(snapshotId, signal),
  staleTime: Infinity,
})

export const prospectiveQuery = (snapshotId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'prospective'],
  queryFn: ({ signal }) => getProspective(snapshotId, signal),
  staleTime: Infinity,
})

export const healthQuery = (snapshotId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'health'],
  queryFn: ({ signal }) => getHealth(snapshotId, signal),
  staleTime: Infinity,
})

export const evidenceQuery = (snapshotId: string, evidenceId: string) => queryOptions({
  queryKey: ['snapshot', snapshotId, 'evidence', evidenceId],
  queryFn: ({ signal }) => getEvidence(snapshotId, evidenceId, signal),
  staleTime: Infinity,
  enabled: Boolean(evidenceId),
})

