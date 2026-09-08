export type RouteStatus = 'queued' | 'processing' | 'completed' | 'failed'

export type Position = [longitude: number, latitude: number]

export interface MultiLineStringGeometry {
  type: 'MultiLineString'
  coordinates: Position[][]
}

export interface StoredRoute {
  id: string
  filename: string
  track_name: string | null
  status: RouteStatus
  point_count: number | null
  segment_count: number | null
  corrected_distance_m: number | null
  fractal_dimension: number | null
  r_squared: number | null
  geometry: MultiLineStringGeometry | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}

export interface DirectRouteAnalysis {
  filename: string
  track_name: string | null
  point_count: number
  segment_count: number
  corrected_distance_m: number
  fractal_dimension: number
  r_squared: number
  geometry: MultiLineStringGeometry
}
