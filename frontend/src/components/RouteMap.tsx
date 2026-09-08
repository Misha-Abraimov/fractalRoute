import { useEffect, useRef } from 'react'
import mapboxgl, { type GeoJSONSource, type Map as MapboxMap } from 'mapbox-gl'
import type { MultiLineStringGeometry, StoredRoute } from '../types/route'

interface RouteMapProps {
  route: StoredRoute | null
}

const sourceId = 'selected-route'
const lineLayerId = 'selected-route-line'
const casingLayerId = 'selected-route-casing'

function geometryFeature(geometry: MultiLineStringGeometry) {
  return { type: 'Feature' as const, properties: {}, geometry }
}

function fitRoute(map: MapboxMap, geometry: MultiLineStringGeometry) {
  const coordinates = geometry.coordinates.flat()
  if (coordinates.length === 0) return

  const bounds = new mapboxgl.LngLatBounds(coordinates[0], coordinates[0])
  coordinates.slice(1).forEach((coordinate) => bounds.extend(coordinate))
  const viewportWidth = map.getContainer().clientWidth
  const padding = viewportWidth > 1100
    ? { top: 104, bottom: 72, left: 390, right: 370 }
    : viewportWidth > 760
      ? { top: 96, bottom: 64, left: 334, right: 320 }
      : { top: 86, bottom: 230, left: 36, right: 36 }

  map.fitBounds(bounds, { padding, duration: 700, maxZoom: 16 })
}

export function RouteMap({ route }: RouteMapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapboxMap | null>(null)
  const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim()

  useEffect(() => {
    if (!containerRef.current || !token) return

    mapboxgl.accessToken = token
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: [-83.0458, 42.3314],
      zoom: 9,
      attributionControl: true,
    })
    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), 'top-right')
    mapRef.current = map

    const resizeObserver = new ResizeObserver(() => map.resize())
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      map.remove()
      mapRef.current = null
    }
  }, [token])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !route?.geometry) return

    const updateRoute = () => {
      if (!route.geometry) return
      const feature = geometryFeature(route.geometry)
      const source = map.getSource(sourceId) as GeoJSONSource | undefined

      if (source) {
        source.setData(feature)
      } else {
        map.addSource(sourceId, { type: 'geojson', data: feature })
        map.addLayer({
          id: casingLayerId,
          type: 'line',
          source: sourceId,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#071d22', 'line-width': 8, 'line-opacity': 0.82 },
        })
        map.addLayer({
          id: lineLayerId,
          type: 'line',
          source: sourceId,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': '#8fffc1', 'line-width': 3.5 },
        })
      }
      fitRoute(map, route.geometry)
    }

    if (map.loaded()) updateRoute()
    else map.once('load', updateRoute)

    return () => {
      map.off('load', updateRoute)
    }
  }, [route])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    const handleResize = () => {
      map.resize()
      if (route?.geometry) fitRoute(map, route.geometry)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [route])

  if (!token) {
    return (
      <section className="map-panel map-placeholder">
        <div className="map-grid" aria-hidden="true" />
        <div className="map-message">
          <span className="map-message-icon">⌖</span>
          <strong>Mapbox token needed</strong>
          <p>Add <code>VITE_MAPBOX_ACCESS_TOKEN</code> to <code>frontend/.env.local</code>, then restart Vite.</p>
        </div>
      </section>
    )
  }

  return (
    <section className="map-panel">
      <div ref={containerRef} className="map-container" aria-label="Map of the selected GPS route" />
      {!route?.geometry && <div className="map-empty-message">Select a completed route to draw its track.</div>}
      <div className="map-caption">
        <span className="route-swatch" />
        <span>{route?.track_name || route?.filename || 'Selected route'}</span>
        <span className="map-caption-meta">WGS 84</span>
      </div>
    </section>
  )
}
