Option A # Accident Reports Frontend (React + Tailwind + Express)

Modern, display-only UI for browsing accident reports. The Express server serves the SPA and exposes simple API routes that fetch markdown reports from GCS (or a local directory) and return sanitized HTML.

## Features

- React 18 + Vite + TailwindCSS (with typography plugin)
- Express server with API routes:
	- `GET /api/reports/list` → GCS `reports/list.json` or DEV_FAKE sample
	- `GET /api/reports/:id` → fetch report markdown, strip front matter, convert to sanitized HTML, return `{ id, content_markdown, content_html, meta }`
- Local file mode: read markdown from `LOCAL_REPORTS_DIR` for offline testing
- Sanitized HTML via `sanitize-html`; script tags are removed

## Getting started (local)

Requirements: Node 20+

1) Install dependencies

```bash
npm ci
```

2) Option A: Vite dev server (UI only)

```bash
npm run dev
```

3) Option B: Express server (serves built UI + API)

```bash
# build UI
npm run build

# serve with GCS bucket
GCS_BUCKET=accident-reports-artifacts npm start

# or serve local markdown reports (no GCS needed)
PORT=8093 DEV_FAKE=0 LOCAL_REPORTS_DIR=../events/reports NODE_ENV=production npm start
```

Open a report: http://localhost:8093/reports/1976c2189c78

## Environment variables

- `GCS_BUCKET` — bucket containing `reports/list.json` and `reports/<id>.md`

Note on `reports/list.json`:

- The frontend expects a canonical manifest at `gs://<GCS_BUCKET>/reports/list.json` that lists available reports. If this file is missing, the server will attempt a public bucket listing fallback, but it's preferable to generate and upload a manifest.
- The repository includes `scripts/build_reports_list.py` which scans `events/reports/*.md` and writes a `list.json` (optionally uploading it to your bucket when `GCS_BUCKET` is set). Typically this should be created after report-generation in your pipeline, e.g., as a post-step in the report generation job or as part of `store_artifacts` / upload artifacts flow.
- Accepted shapes:
	- Legacy (array): `[{"id":"<event_id>","title":"...","region":"...","date":"YYYY-MM-DD"}, ...]`
	- Canonical (object): `{ "reports": [ {"id": "<event_id>", ...}, ... ], "generated_at": "<iso>", "version": 1 }`
	- The frontend now gracefully handles either; prefer the canonical object for future metadata expansion.

- `DEV_FAKE` — when `1`, `/api/reports/list` returns a local mock list
- `LOCAL_REPORTS_DIR` — directory of local `.md` files for `/api/reports/:id`
- `PORT` — server port (Cloud Run sets this automatically)
- `REPORTS_LIST_MODE` — `object` (default) returns `{reports:[],generated_at,version,count}`; set to `array` to return legacy bare array shape for compatibility testing.
- `DEBUG_API` — when `1`, enables `/api/debug/state` diagnostic endpoint (non-secret fields only) to verify bucket wiring in deployed environments.
- `GIT_COMMIT` — optional commit SHA injected by CI; exposed via `X-App-Commit` header and `/api/debug/state`.
- `REPORTS_CACHE_TTL_MS` — in-memory cache duration for manifest (0 = disabled). Small values (1000–5000) reduce GCS fetch frequency.

## Diagnostics & Health

Runtime checks:
- `/api/reports/list` → Should return object with `reports` (or array in legacy mode). Non-empty after successful publish.
- `/api/debug/state` (enable with `DEBUG_API=1`) → Returns bucket name, manifest URL, status, reportCount.

Cloud Run post-deploy verification (local dev container example):
```bash
python scripts/check_cloud_run_reports.py --base https://<your-cloud-run-host> --expect-min 1
```

Headers of interest:
- `X-App-Commit`: Present when `GIT_COMMIT` provided; helps verify fresh revision.

If this script reports zero reports while direct bucket fetch returns items:
1. Ensure the deployed image includes latest frontend bundle (`ListPage.jsx` accepting object shape).
2. Confirm `GCS_BUCKET` env var in Cloud Run revision.
3. Hard refresh browser to bypass cached JS assets.
4. Inspect `/api/debug/state` (set `DEBUG_API=1`).

## Tests & lint

```bash
npm run lint
npm test
```

Notes:
- Jest tests include server behavior and HTML sanitization.

## Build & preview

```bash
npm run build
npm run preview
```

## Deploy

- GitHub Actions CD workflow: `.github/workflows/cd.yml` (Cloud Run deploy via OIDC)
- Terraform infra: `../infra/` provisions Artifact Registry, Cloud Run, and GCS bucket

At minimum, set GitHub secrets:
- `GCP_WORKLOAD_IDP`
- `GCP_CLOUDRUN_SA`

## Troubleshooting

- Warning: `GCS_BUCKET not set` — Either set `GCS_BUCKET` or run in local mode with `LOCAL_REPORTS_DIR`.
- Report returns 404 — Ensure file exists in GCS (`reports/<id>.md`) or in `LOCAL_REPORTS_DIR`.
- Scripts showing up in content — The server sanitizes output; ensure you’re using `content_html` from the API, not rendering raw markdown on the client.