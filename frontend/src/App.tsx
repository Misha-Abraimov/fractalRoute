import { useCallback, useEffect, useState } from 'react'
import { analyzeRoute, getRoute, getRoutes, uploadRoute } from './api/routes'
import { AppHeader } from './components/AppHeader'
import { HelpModal } from './components/HelpModal'
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
  const [mobilePanel, setMobilePanel] = useState<'routes' | 'results'>('routes')
  const [isHelpOpen, setIsHelpOpen] = useState(false)
  const selectedRouteId = selectedRoute?.id
  const selectedRouteStatus = selectedRoute?.status
  const openHelp = useCallback(() => setIsHelpOpen(true), [])
  const closeHelp = useCallback(() => setIsHelpOpen(false), [])

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
        setMobilePanel('results')
        return
      }

      const createdRoute = await uploadRoute(file)
      setRoutes((current) => [createdRoute, ...current.filter((route) => route.id !== createdRoute.id)])
      setSelectedRoute(createdRoute)
      setMobilePanel('results')
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
      setMobilePanel('results')
      return
    }

    setIsSelecting(true)
    setError(null)
    try {
      const route = await getRoute(id)
      setSelectedRoute(route)
      setRoutes((current) => current.map((item) => item.id === route.id ? route : item))
      setMobilePanel('results')
    } catch (selectError) {
      setError(messageFrom(selectError))
    } finally {
      setIsSelecting(false)
    }
  }

  async function handleSampleRoute() {
    setError(null)
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}sample-route.gpx`)
      if (!response.ok) throw new Error('The sample route could not be loaded.')
      const file = new File(
        [await response.blob()],
        'sample-route.gpx',
        { type: 'application/gpx+xml' },
      )
      await handleUpload(file)
    } catch (sampleError) {
      setError(messageFrom(sampleError))
    }
  }

  const applicationStatus = error
    ? 'Needs attention'
    : isUploading
      ? isVercelMode ? 'Analyzing route…' : 'Uploading route…'
      : isSelecting
        ? 'Loading route…'
        : isLoading
          ? 'Loading routes…'
          : 'Ready'

  return (
    <div className="app-shell" id="app">
      <RouteMap route={selectedRoute} />
      <AppHeader status={applicationStatus} hasError={error !== null} />

      {error && (
        <div className="global-error" role="alert">
          <span><strong>Request failed.</strong> {error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      <main className="dashboard-overlays">
        <aside
          className={`controls-stack${mobilePanel === 'routes' ? ' mobile-active' : ''}`}
          id="routes-panel"
        >
          <div className="floating-panel upload-card">
            <RouteUpload
              isUploading={isUploading}
              isDirectAnalysis={isVercelMode}
              onUpload={handleUpload}
              onTrySample={handleSampleRoute}
              onOpenHelp={openHelp}
            />
          </div>
          <div className="floating-panel archive-card">
            <RouteList
              routes={routes}
              selectedId={selectedRoute?.id ?? null}
              isLoading={isLoading}
              isSelecting={isSelecting}
              onSelect={handleSelect}
            />
          </div>
        </aside>

        <aside
          className={`floating-panel results-panel${mobilePanel === 'results' ? ' mobile-active' : ''}`}
          id="results-panel"
        >
          <RouteSummary route={selectedRoute} />
        </aside>
      </main>

      <nav className="mobile-dock" aria-label="Dashboard panels">
        <button
          type="button"
          className={mobilePanel === 'routes' ? 'active' : ''}
          aria-controls="routes-panel"
          aria-expanded={mobilePanel === 'routes'}
          onClick={() => setMobilePanel('routes')}
        >
          Routes
        </button>
        <button
          type="button"
          className={mobilePanel === 'results' ? 'active' : ''}
          aria-controls="results-panel"
          aria-expanded={mobilePanel === 'results'}
          onClick={() => setMobilePanel('results')}
        >
          Results
        </button>
      </nav>

      <HelpModal
        isOpen={isHelpOpen}
        showLocalStorageNote={isVercelMode}
        onClose={closeHelp}
      />
    </div>
  )
}

export default App
