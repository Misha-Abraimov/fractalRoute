import type { StoredRoute } from '../types/route'

interface RouteSummaryProps {
  route: StoredRoute | null
}

function formatDistance(value: number | null): string {
  if (value === null) return '—'
  return `${(value / 1000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 3 })} km`
}

function formatMetric(value: number | null, digits = 4): string {
  return value === null ? '—' : value.toFixed(digits)
}

function routeName(route: StoredRoute): string {
  return route.track_name?.trim() || route.filename
}

export function RouteSummary({ route }: RouteSummaryProps) {
  if (!route) {
    return (
      <section className="summary-panel summary-empty" aria-live="polite">
        <span className="eyebrow">Analysis output</span>
        <h2>Select a saved route or upload a GPX file</h2>
        <p>Distance and fractal measurements will appear here.</p>
      </section>
    )
  }

  if (route.status !== 'completed') {
    const statusCopy = route.status === 'queued'
      ? 'The GPX file is safely queued and waiting for an analysis worker.'
      : route.status === 'processing'
        ? 'The worker is calculating corrected distance and Richardson fractal dimension.'
        : 'Analysis could not be completed for this route.'

    return (
      <section className="summary-panel summary-pending" aria-live="polite">
        <div className="summary-title-row">
          <div>
            <span className="eyebrow">Analysis output · {route.status}</span>
            <h2>{routeName(route)}</h2>
            <p className="filename">{route.filename}</p>
          </div>
          <span className={`status-pill status-${route.status}`}>{route.status}</span>
        </div>
        <div className="job-state-copy">
          <span className={route.status === 'failed' ? 'job-state-mark failed-mark' : 'job-state-mark'} aria-hidden="true" />
          <div>
            <strong>{route.status === 'failed' ? 'Analysis failed' : 'Analysis in progress'}</strong>
            <p>{route.error_message || statusCopy}</p>
          </div>
        </div>
      </section>
    )
  }

  return (
    <section className="summary-panel" aria-labelledby="route-summary-heading">
      <div className="summary-title-row">
        <div>
          <span className="eyebrow">Analysis output · {route.status}</span>
          <h2 id="route-summary-heading">{routeName(route)}</h2>
          <p className="filename">{route.track_name ? route.filename : 'GPX route file'}</p>
        </div>
        <span className={`status-pill status-${route.status}`}>{route.status}</span>
      </div>

      {route.error_message && <div className="route-error">{route.error_message}</div>}

      <div className="hero-metric">
        <span>Corrected distance</span>
        <strong>{formatDistance(route.corrected_distance_m)}</strong>
        <small>Corrected route distance from the completed analysis</small>
      </div>

      <div className="metric-grid">
        <div className="metric-card accent-card">
          <span>Fractal dimension</span>
          <strong>{formatMetric(route.fractal_dimension)}</strong>
        </div>
        <div className="metric-card">
          <span>Fit quality R²</span>
          <strong>{formatMetric(route.r_squared)}</strong>
        </div>
        <div className="metric-card split-card">
          <span><b>{route.point_count?.toLocaleString() ?? '—'}</b> points</span>
          <span>
            <b>{route.segment_count?.toLocaleString() ?? '—'}</b>{' '}
            {route.segment_count === 1 ? 'segment' : 'segments'}
          </span>
        </div>
      </div>
    </section>
  )
}
