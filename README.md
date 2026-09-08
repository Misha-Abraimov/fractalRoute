# Fractal Route

Fractal Route is a full-stack GPX analysis application that calculates a
corrected route distance and estimates trajectory complexity with a Richardson
multi-scale fractal analysis.

## Overview

The project combines a reusable Python analysis engine with a FastAPI API, a
React dashboard, PostgreSQL persistence, and an asynchronous AWS worker. A
stateless endpoint is available for direct analysis, while the persistent path
stores uploads and queues work so long-running calculations do not block API
requests.

## What it does

The dashboard lets users:

- upload GPX routes and queue analysis jobs;
- follow queued, processing, completed, and failed states;
- view route geometry with Mapbox GL;
- inspect corrected distance, fractal dimension, and fit quality; and
- revisit previously saved routes.

The analysis engine preserves GPX segment boundaries, converts coordinates to a
three-dimensional working representation, measures the trajectory at increasing
scales, and fits `ln(L) = ln(a) + (1 - D)ln(s)` to estimate fractal dimension
`D`.

## Architecture

```text
React + TypeScript + Mapbox GL
                ↓
             FastAPI
                ↓
      PostgreSQL / Amazon RDS
                ↓
         Amazon S3 + Amazon SQS
                ↓
   Dockerized Python worker
                ↓
           ECS Fargate
                ↓
PostgreSQL results + CloudWatch logs
```

The optional public/demo deployment uses a separate stateless path:

```text
Vercel Vite frontend → Vercel FastAPI Function → fractal_route.py
                         ↓
        corrected result + route geometry → browser localStorage
```

The API commits each new route transaction before publishing its job ID to SQS.
This ordering prevents a worker from receiving an ID before the corresponding
database row is visible.

## Tech stack

- Python 3.12, FastAPI, SQLAlchemy, Psycopg, and Boto3
- PostgreSQL 17 locally and Amazon RDS PostgreSQL on AWS
- React 19, TypeScript, Vite, Mapbox GL, and Nginx
- Docker and Docker Compose
- Amazon S3, SQS, ECR, ECS Fargate, RDS, Systems Manager Parameter Store,
  CloudWatch Logs, and IAM

## Key engineering features

- Reusable standard-library GPX and fractal-analysis module
- Synchronous/stateless and persistent/asynchronous API workflows
- SQS visibility-timeout retries, dead-letter queue support, and idempotent job
  handling
- Least-privilege IAM task roles and Parameter Store secret injection
- Structured CloudWatch benchmark logs with queue wait time, receive count,
  analysis duration, and total worker job duration
- Transaction ordering verified by a cross-session regression test
- SQLite-backed API and worker tests that require no live AWS services

## Repository structure

```text
fractalRoute/
├── api/                 # Stateless Vercel FastAPI Function
├── backend/
│   ├── app/             # FastAPI, persistence, schemas, and AWS adapters
│   ├── schema_upgrade.py
│   └── worker.py        # Standalone SQS analysis worker
├── frontend/            # React, TypeScript, Mapbox GL, and Nginx app
├── tests/               # Analysis fixtures, fakes, and library tests
├── deploy/
│   └── aws/             # Reusable IAM and ECS templates and deployment guide
├── fractal_route.py     # Reusable analysis engine and optional CLI
├── Dockerfile           # Shared API/worker Python image
├── compose.yaml         # Local PostgreSQL, API, worker, and frontend stack
└── requirements.txt
```

Root-level `test_*.py` files cover the API, database upgrade, persistence,
worker, and deployment templates.

## Local development

### Prerequisites

- Python 3.12
- Node.js 22 and npm
- PostgreSQL 17 when running the API without Docker
- Docker Engine or Docker Desktop with Compose for the containerized stack
- A public Mapbox token to render the map (the rest of the frontend can build
  without one)

Unit tests and frontend development do not require AWS credentials. The
persistent asynchronous upload workflow additionally requires an S3 bucket, SQS
queue, and credentials supplied through the normal AWS credential provider
chain.

### Backend

Create a PostgreSQL database named `fractal_route`, then from PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@localhost:5432/fractal_route"
python -m backend.schema_upgrade
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

On Unix-like systems, activate with `source .venv/bin/activate` and use `export
DATABASE_URL=...`. Interactive API documentation is available at
`http://127.0.0.1:8000/docs`.

The standalone CLI writes its CSV, JSON, Markdown, and SVG artifacts to the
ignored `results/` directory:

```powershell
python fractal_route.py path\to\route.gpx
```

### Frontend

In another shell:

```powershell
Set-Location frontend
Copy-Item .env.example .env.local
npm ci
npm run dev
```

Set `VITE_MAPBOX_ACCESS_TOKEN` in `frontend/.env.local`; never commit the real
token. Set `VITE_APP_MODE=async` when using the regular database-backed backend
described above. The dashboard runs at `http://127.0.0.1:5173`.

### Local worker

For the optional asynchronous integration path, set `DATABASE_URL`,
`AWS_REGION`, `FRACTAL_ROUTE_S3_BUCKET`, and `FRACTAL_ROUTE_SQS_QUEUE_URL`, then
authenticate through a temporary AWS CLI profile and run:

```powershell
$env:AWS_PROFILE = "fractal-route"
python -m backend.worker
```

Do not store static AWS credentials in environment example files or source.

## Running with Docker

Copy the Compose configuration template and replace only the local copy's
placeholders:

```powershell
Copy-Item .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

The stack exposes the frontend on port `5173` and FastAPI on port `8000`.
PostgreSQL remains internal to the Compose network. The worker requires valid
S3/SQS application values and an AWS credential provider accessible to the
container; these are not baked into either image.

Stop the stack without deleting its PostgreSQL volume:

```powershell
docker compose down
```

## API overview

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Lightweight API health check |
| `POST /api/routes/analyze` | Synchronous, stateless GPX analysis |
| `POST /api/routes` | Store a GPX source and queue persistent analysis |
| `GET /api/routes` | List persisted routes, newest first |
| `GET /api/routes/{id}` | Retrieve one persisted route and its status/results |

The final distance field is `corrected_distance_m`, expressed in metres.

## Testing

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
Set-Location frontend
npm run lint
npm run build
```

The same checks run on every push and pull request through GitHub Actions.

## Public Vercel deployment

The public/demo deployment uses two Vercel projects imported from the same
GitHub repository, [`Misha-Abraimov/fractalRoute`](https://github.com/Misha-Abraimov/fractalRoute).
It does not use the persistent AWS workflow: GPX bytes are analyzed in memory by
the Python Function, the response contains the corrected distance and route
geometry, and the browser keeps at most 20 processed results in `localStorage`.
Original GPX contents are never placed in the browser archive or persisted by
the public API. Uploads larger than 4 MiB are rejected in both the browser and
the API.

### 1. Create the API project

In the Vercel dashboard, add a new project by importing
`Misha-Abraimov/fractalRoute` and configure it as follows:

- Project root directory: repository root (`.`)
- Python version: read from `.python-version` (`3.12`)
- FastAPI entry point: `api/index.py`, which exports `app`
- Environment variable:
  `ALLOWED_ORIGINS=https://<your-frontend-project>.vercel.app`

Deploy the API project first and copy its generated HTTPS URL. No database,
AWS, or static credential environment variables belong in this project.

### 2. Create the frontend project

Import the same GitHub repository into a second Vercel project and configure:

- Project root directory: `frontend`
- Framework preset: Vite
- Build command: `npm run build`
- Output directory: `dist`
- Environment variables:

```dotenv
VITE_APP_MODE=vercel
VITE_API_BASE_URL=https://<your-api-project>.vercel.app
VITE_MAPBOX_ACCESS_TOKEN=<your-public-mapbox-token>
```

`VITE_API_BASE_URL` must be the API project origin without a trailing path; the
frontend appends `/api/routes/analyze`. Do not hard-code a Vercel hostname in
source. If the frontend URL changes, update `ALLOWED_ORIGINS` on the API project
to the exact new origin and redeploy the API configuration.

### Deployment-mode behavior

- `VITE_APP_MODE=vercel` uses synchronous `POST /api/routes/analyze`, displays
  **Analyze Route**, performs no polling, and reads/writes only the capped local
  browser archive.
- Any other mode retains the existing persistent asynchronous API, database
  archive, queue/status UI, and polling behavior used by local Docker and AWS.

The stateless API also exposes `GET /api/health`. Production CORS origins are a
comma-separated `ALLOWED_ORIGINS` value; localhost and `127.0.0.1` development
origins remain supported, and wildcard CORS is not enabled.

## AWS deployment architecture

The tested asynchronous path stores private GPX sources in S3 and sends compact
route-ID jobs through SQS. A Docker image in ECR runs as an ECS Fargate worker,
reads its database URL from an SSM SecureString, writes results to RDS
PostgreSQL, and emits structured logs to CloudWatch. IAM execution and task roles
separate image/secret access from application access.

Deployment templates contain placeholders only. Resolved account IDs, ARNs,
queue URLs, bucket names, security-group IDs, and image digests stay in ignored
local files. See [`deploy/aws/README.md`](deploy/aws/README.md) for the manual
deployment guide.

## Performance / reliability

One observed AWS integration run processed a 1,415-point GPX with receive count
1, approximately 7 ms of queue wait, 171 ms of analysis time, and 288 ms of total
worker time. This is one test observation, not a performance guarantee; route
size, database latency, queue conditions, and infrastructure affect results.

Retries rely on SQS visibility behavior, terminal jobs are acknowledged only
after durable database state is committed, and duplicate deliveries do not
repeat completed analysis.

## Project status

The local application and AWS worker architecture have been deployed and tested
end to end. This repository does not claim that a permanent public production
instance is currently online.

## License

Licensed under the [MIT License](LICENSE).
