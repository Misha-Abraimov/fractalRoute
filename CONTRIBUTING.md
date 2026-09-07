# Contributing

Thank you for improving Fractal Route. Keep changes focused, preserve the public
API unless a breaking change is intentional, and do not commit GPX location data,
environment files, credentials, or resolved AWS identifiers.

## Development checks

Before opening a pull request, run:

```powershell
.\.venv\Scripts\python.exe -m unittest -v
Set-Location frontend
npm ci
npm run lint
npm run build
```

Add or update tests for behavior changes. AWS-facing code should be exercised
through the existing fakes unless a live integration test is explicitly planned
and reviewed. Use `corrected distance` or `corrected route distance` for the final
distance result in user-facing text.
