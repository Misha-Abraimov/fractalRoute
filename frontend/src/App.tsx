import { useEffect, useState } from 'react'
import { analyzeRoute, getRoute, getRoutes, uploadRoute } from './api/routes'
import { RouteList } from './components/RouteList'
import { RouteMap } from './components/RouteMap'
import { RouteSummary } from './components/RouteSummary'
import { RouteUpload } from './components/RouteUpload'
import { isVercelMode, maxGpxUploadBytes, maxGpxUploadMessage } from './config'
import { loadLocalRoutes, localRouteLimit, routeFromDirectAnalysis, saveLocalRoutes } from './localRoutes'
import type { StoredRoute } from './types/route'
import './App.css'

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : 'An unexpected error occurred.'
}

const pollingIntervalMilliseconds = 3000
const initialRoutes = isVercelMode ? loadLocalRoutes() : []

function App() {
  const [routes, setRoutes] = useState<StoredRoute[]>(initialRoutes)
  const [selectedRoute, setSelectedRoute] = useState<StoredRoute | null>(initialRoutes[0] ?? null)
  const [isLoading, setIsLoading] = useState(!isVercelMode)
  const [isUploading, setIsUploading] = useState(false)
  const [isSelecting, setIsSelecting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const selectedRouteId = selectedRoute?.id
  const selectedRouteStatus = selectedRoute?.status

  useEffect(() => {
    if (isVercelMode) return

    let isActive = true

    async function loadRoutes() {
      try {
        const savedRoutes = await getRoutes()
        if (!isActive) return
        setRoutes(savedRoutes)
        setSelectedRoute(savedRoutes[0] ?? null)
      } catch (loadError) {
        if (isActive) setError(messageFrom(loadError))
      } finally {
        if (isActive) setIsLoading(false)
      }
    }

    void loadRoutes()
    return () => {
      isActive = false
    }
  }, [])

  useEffect(() => {
    if (
      isVercelMode
      || !selectedRouteId
      || (selectedRouteStatus !== 'queued' && selectedRouteStatus !== 'processing')
    ) return
    const routeId = selectedRouteId

    let isActive = true
    let timer: number | undefined

    async function pollRoute() {
      try {
        const route = await getRoute(routeId)
        if (!isActive) return
        setSelectedRoute(route)
        setRoutes((current) => current.map((item) => item.id === route.id ? route : item))
        if (route.status === 'queued' || route.status === 'processing') {
          timer = window.setTimeout(pollRoute, pollingIntervalMilliseconds)
        }
      } catch (pollError) {
        if (!isActive) return
        setError(messageFrom(pollError))
        timer = window.setTimeout(pollRoute, pollingIntervalMilliseconds)
      }
    }

    timer = window.setTimeout(pollRoute, pollingIntervalMilliseconds)
    return () => {
      isActive = false
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [selectedRouteId, selectedRouteStatus])

  async function handleUpload(file: File) {
    if (file.size > maxGpxUploadBytes) {
      setError(maxGpxUploadMessage)
      return
    }

    setIsUploading(true)
    setError(null)
    try {
      if (isVercelMode) {
        const analysis = await analyzeRoute(file)
        const createdRoute = routeFromDirectAnalysis(analysis)
        const updatedRoutes = [
          createdRoute,
          ...routes.filter((route) => route.id !== createdRoute.id),
        ].slice(0, localRouteLimit)
        setRoutes(updatedRoutes)
        saveLocalRoutes(updatedRoutes)
        setSelectedRoute(createdRoute)
        return
      }

      const createdRoute = await uploadRoute(file)
      setRoutes((current) => [createdRoute, ...current.filter((route) => route.id !== createdRoute.id)])
      setSelectedRoute(createdRoute)
    } catch (uploadError) {
      setError(messageFrom(uploadError))
    } finally {
      setIsUploading(false)
    }
  }

  async function handleSelect(id: string) {
    if (id === selectedRoute?.id) return
    if (isVercelMode) {
      setSelectedRoute(routes.find((route) => route.id === id) ?? null)
      return
    }

    setIsSelecting(true)
    setError(null)
    try {
      const route = await getRoute(id)
      setSelectedRoute(route)
      setRoutes((current) => current.map((item) => item.id === route.id ? route : item))
    } catch (selectError) {
      setError(messageFrom(selectError))
    } finally {
      setIsSelecting(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#top" aria-label="Fractal Route home">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span>Fractal<span>Route</span></span>
        </a>
        <div className="header-meta">
          <span className={`system-status${error ? ' system-error' : ''}`}>
            <i /> {isLoading ? 'Connecting to API' : error ? 'API unavailable' : 'Analysis system online'}
          </span>
          <span className="version">Richardson analysis v0.3</span>
        </div>
      </header>

      <main id="top">
        <section className="intro-row">
          <div>
            <h1>Measure the route<br /><em>between the points.</em></h1>
          </div>
        </section>

        {error && (
          <div className="global-error" role="alert">
            <span><strong>Request failed.</strong> {error}</span>
            <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button>
          </div>
        )}

        <div className="dashboard-grid">
          <aside className="dashboard-sidebar">
            <RouteUpload
              isUploading={isUploading}
              isDirectAnalysis={isVercelMode}
              onUpload={handleUpload}
            />
            <RouteList
              routes={routes}
              selectedId={selectedRoute?.id ?? null}
              isLoading={isLoading}
              isSelecting={isSelecting}
              onSelect={handleSelect}
            />
          </aside>
          <div className="dashboard-main">
            <RouteMap route={selectedRoute} />
            <RouteSummary route={selectedRoute} />
          </div>
        </div>
      </main>

      <footer>
        <span>GPX trajectory → multi-scale analysis → corrected distance</span>
        <span>Local analysis workspace</span>
      </footer>
    </div>
  )
}

export default App
