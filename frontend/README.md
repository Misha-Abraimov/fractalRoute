# FractalRoute frontend

Vite, React, and TypeScript dashboard for the persistent Fractal Route API.

## Local setup

1. Copy `.env.example` to `.env.local`.
2. Set `VITE_API_BASE_URL` to the local backend URL.
3. Add a public Mapbox access token as `VITE_MAPBOX_ACCESS_TOKEN`.
4. Run `npm install` and `npm run dev`.

The frontend uploads GPX files to `POST /api/routes`, loads the saved archive from
`GET /api/routes`, and retrieves individual records from `GET /api/routes/{id}`.
