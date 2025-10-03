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