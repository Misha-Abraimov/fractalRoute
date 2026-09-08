# FractalRoute frontend

Vite, React, and TypeScript dashboard with persistent and public/demo modes.

## Local setup

1. Copy `.env.example` to `.env.local`.
2. Set `VITE_API_BASE_URL` to the local backend URL.
3. Add a public Mapbox access token as `VITE_MAPBOX_ACCESS_TOKEN`.
4. The example uses `VITE_APP_MODE=vercel` for direct stateless analysis with a
   browser-local archive. Change it to `async` for the persistent local/AWS
   workflow.
5. Run `npm install` and `npm run dev`.

The persistent mode uploads GPX files to `POST /api/routes`, loads the database
archive from `GET /api/routes`, and retrieves records from
`GET /api/routes/{id}`. Vercel mode calls `POST /api/routes/analyze`
synchronously and stores up to 20 processed results (never original GPX data)
in browser `localStorage`. Both modes enforce a 4 MiB upload limit in the UI.
