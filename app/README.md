# Accident Reports Frontend

Display-only React + Tailwind UI, served by Express and deployed to Cloud Run. Artifacts are read from a public GCS bucket.

## Local dev

- Node 20+
- Install deps: `npm ci`
- Run UI: `npm run dev` (Vite)
- Run server: `GCS_BUCKET=accident-reports-artifacts npm start` (serves built app)

Build the UI first with `npm run build` to serve static files via Express.

## Env

- GCS_BUCKET: name of the GCS bucket that contains `reports/list.json` and `reports/<id>.md`.

## Tests

- Lint: `npm run lint`
- Unit tests: `npm test`