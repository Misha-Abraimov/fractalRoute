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
  raw_3d_ecef_polyline_length_m: number | null
  corrected_distance_m: number | null
  fractal_dimension: number | null
  r_squared: number | null
  geometry: MultiLineStringGeometry | null
  error_message: string | null
  created_at: string
  completed_at: string | null
}
