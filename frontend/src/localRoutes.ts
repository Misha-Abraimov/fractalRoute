import type { DirectRouteAnalysis, MultiLineStringGeometry, StoredRoute } from './types/route'

const storageKey = 'fractal-route:public-analyses:v1'
export const localRouteLimit = 20

function finiteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isGeometry(value: unknown): value is MultiLineStringGeometry {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as { type?: unknown; coordinates?: unknown }
  return (
    candidate.type === 'MultiLineString'
    && Array.isArray(candidate.coordinates)
    && candidate.coordinates.every(
      (line) => Array.isArray(line) && line.every(
        (position) => (
          Array.isArray(position)
          && position.length >= 2
          && finiteNumber(position[0])
          && finiteNumber(position[1])
        ),
      ),
    )
  )
}

function isStoredRoute(value: unknown): value is StoredRoute {
  if (typeof value !== 'object' || value === null) return false
  const route = value as Partial<StoredRoute>
  return (
    typeof route.id === 'string'
    && typeof route.filename === 'string'
    && (route.track_name === null || typeof route.track_name === 'string')
    && route.status === 'completed'
    && Number.isInteger(route.point_count)
    && Number.isInteger(route.segment_count)
    && finiteNumber(route.corrected_distance_m)
    && finiteNumber(route.fractal_dimension)
    && finiteNumber(route.r_squared)
    && isGeometry(route.geometry)
    && route.error_message === null
    && typeof route.created_at === 'string'
    && (route.completed_at === null || typeof route.completed_at === 'string')
  )
}

function clientRouteId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function routeFromDirectAnalysis(analysis: DirectRouteAnalysis): StoredRoute {
  const now = new Date().toISOString()
  return {
    id: clientRouteId(),
    filename: analysis.filename,
    track_name: analysis.track_name,
    status: 'completed',
    point_count: analysis.point_count,
    segment_count: analysis.segment_count,
    corrected_distance_m: analysis.corrected_distance_m,
    fractal_dimension: analysis.fractal_dimension,
    r_squared: analysis.r_squared,
    geometry: analysis.geometry,
    error_message: null,
    created_at: now,
    completed_at: now,
  }
}

export function parseLocalRoutes(serialized: string | null): StoredRoute[] {
  if (!serialized) return []
  try {
    const value: unknown = JSON.parse(serialized)
    if (!Array.isArray(value)) return []
    return value.filter(isStoredRoute).slice(0, localRouteLimit)
  } catch {
    return []
  }
}

export function loadLocalRoutes(): StoredRoute[] {
  try {
    return parseLocalRoutes(window.localStorage.getItem(storageKey))
  } catch {
    return []
  }
}

export function saveLocalRoutes(routes: StoredRoute[]): void {
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(routes.slice(0, localRouteLimit)))
  } catch {
    // Storage may be unavailable or full; the current analysis remains in memory.
  }
}
