import type { StoredRoute } from '../types/route'

interface RouteListProps {
  routes: StoredRoute[]
  selectedId: string | null
  isLoading: boolean
  isSelecting: boolean
  onSelect: (id: string) => void
}

function routeName(route: StoredRoute): string {
  return route.track_name?.trim() || route.filename
}

function routeDate(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? 'Unknown date'
    : parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

export function RouteList({ routes, selectedId, isLoading, isSelecting, onSelect }: RouteListProps) {
  return (
    <section className="route-list-panel" aria-labelledby="saved-routes-heading">
      <div className="panel-heading list-heading">
        <div>
          <span className="eyebrow">Route archive</span>
          <h2 id="saved-routes-heading">Saved tracks</h2>
        </div>
        <span className="route-count">{routes.length.toString().padStart(2, '0')}</span>
      </div>

      {isLoading ? (
        <div className="list-state"><span className="spinner" />Loading saved routes…</div>
      ) : routes.length === 0 ? (
        <div className="list-state empty-state">
          <span className="empty-glyph" aria-hidden="true">⌁</span>
          <strong>No saved routes yet</strong>
          <span>Your first uploaded GPX track will appear here.</span>
        </div>
      ) : (
        <div className="route-list">
          {routes.map((route, index) => (
            <button
              className={`route-row${route.id === selectedId ? ' selected' : ''}`}
              type="button"
              key={route.id}
              disabled={isSelecting}
              onClick={() => onSelect(route.id)}
              aria-pressed={route.id === selectedId}
            >
              <span className="route-index">{String(index + 1).padStart(2, '0')}</span>
              <span className="route-row-copy">
                <strong>{routeName(route)}</strong>
                <small>
                  {route.track_name ? `${route.filename} · ${routeDate(route.created_at)}` : routeDate(route.created_at)}
                </small>
              </span>
              <span className="route-row-meta">
                <small className={`status status-${route.status}`}>{route.status}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  )
}
