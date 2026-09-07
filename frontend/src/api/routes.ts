import type { StoredRoute } from '../types/route'

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim().replace(/\/$/, '')

function routeUrl(path = ''): string {
  if (!apiBaseUrl) {
    throw new Error(
      'The API is not configured. Set VITE_API_BASE_URL in frontend/.env.local, then restart the frontend.',
    )
  }
  return `${apiBaseUrl}/api/routes${path}`
}

async function errorMessage(response: Response): Promise<string> {
  let detail = ''
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const value = (body as { detail?: unknown }).detail
      detail = typeof value === 'string' ? value : JSON.stringify(value)
    }
  } catch {
    // The status text below is more useful than a JSON parsing error.
  }
  return detail || response.statusText || `Request failed with status ${response.status}`
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, options)
  } catch {
    throw new Error(
      'Could not reach the route API. Confirm the backend is running and the API URL is correct.',
    )
  }
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.json() as Promise<T>
}

export function uploadRoute(file: File): Promise<StoredRoute> {
  const formData = new FormData()
  formData.append('file', file)
  return request<StoredRoute>(routeUrl(), { method: 'POST', body: formData })
}

export function getRoutes(): Promise<StoredRoute[]> {
  return request<StoredRoute[]>(routeUrl())
}

export function getRoute(id: string): Promise<StoredRoute> {
  return request<StoredRoute>(routeUrl(`/${encodeURIComponent(id)}`))
}
