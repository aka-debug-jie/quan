export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  if (!response.ok) throw new Error((await response.json().catch(() => ({ detail: response.statusText }))).detail)
  return response.json() as Promise<T>
}
