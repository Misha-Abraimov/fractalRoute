import type { StoredRoute } from '../types/route'

interface RouteSummaryProps {
  route: StoredRoute | null
}

function formatMiles(value: number | null): string {
  if (value === null) return '—'
  return `${(value / 1609.344).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} mi`
}

function formatKilometers(value: number): string {
  return `${(value / 1000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} km`
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
        <span className="eyebrow">Route analysis</span>
        <h2>Upload a GPX route to view corrected-distance results.</h2>
        <p>Distance, fractal dimension, and fit quality will appear here.</p>
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
        <span>Corrected Distance</span>
        <strong>{formatMiles(route.corrected_distance_m)}</strong>
        {route.corrected_distance_m !== null && (
          <small className="distance-equivalent">{formatKilometers(route.corrected_distance_m)}</small>
        )}
      </div>

      <div className="metric-grid">
        <div className="metric-card accent-card">
          <span>Fractal dimension</span>
          <strong>{formatMetric(route.fractal_dimension)}</strong>
        </div>
        <div className="metric-card">
          <span>R² fit quality</span>
          <strong>{formatMetric(route.r_squared)}</strong>
        </div>
        <div className="metric-card">
          <span>Point count</span>
          <strong>{route.point_count?.toLocaleString() ?? '—'}</strong>
        </div>
        <div className="metric-card">
          <span>Segment count</span>
          <strong>
            {route.segment_count?.toLocaleString() ?? '—'}{' '}
            <small>{route.segment_count === 1 ? 'segment' : 'segments'}</small>
          </strong>
        </div>
      </div>
    </section>
  )
}
