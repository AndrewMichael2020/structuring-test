# Deploy Frontend to Google Cloud Run

This guide covers local dev, containerization, CI/CD via GitHub Actions (OIDC), and provisioning via Terraform for the frontend in `app/`.

## Prerequisites
- GCP project with billing enabled
- APIs: Artifact Registry, Cloud Run, Cloud Build, IAM, Storage (Terraform can enable these)
- GitHub repository secrets for OIDC:
  - `GCP_WORKLOAD_IDP` — Workload Identity Provider resource name
  - `GCP_CLOUDRUN_SA` — Service Account email to deploy Cloud Run
  - `GCP_TERRAFORM_SA` — Service Account email for Terraform (if using the infra workflow)

## Local development
- From `app/`:
  - `npm ci`
  - UI only: `npm run dev`
  - Express + API (after build): `npm run build && GCS_BUCKET=<bucket> npm start`
  - Offline demo (local markdown): `PORT=8093 DEV_FAKE=0 LOCAL_REPORTS_DIR=../events/reports NODE_ENV=production npm start`

## Container build (manual)
Build and run locally with Docker to mimic Cloud Run:

```bash
docker build -t REGION-docker.pkg.dev/PROJECT/web-app/accident-reports-frontend:local ./app
docker run -e PORT=8080 -e NODE_ENV=production -e GCS_BUCKET=accident-reports-artifacts -p 8080:8080 REGION-docker.pkg.dev/PROJECT/web-app/accident-reports-frontend:local
# open http://localhost:8080/healthz
```

## GitHub Actions (CI/CD)
- Workflows:
  - CI: `.github/workflows/ci.yml` — lint, tests, vite build, schema validate
  - CD: `.github/workflows/cd.yml` — authenticates with OIDC, builds with Cloud Buildpacks, deploys Cloud Run, smoke test
  - Terraform: `.github/workflows/tf-plan-apply.yml` — init/plan/apply for infra

Secrets required:
- `GCP_WORKLOAD_IDP`
- `GCP_CLOUDRUN_SA`
- `GCP_TERRAFORM_SA` (for Terraform workflow)

## Terraform provisioning
Infra files in `infra/` provision:
- Public GCS bucket for artifacts (`bucket_name` var)
- Artifact Registry repository `web-app`
- Cloud Run v2 service with public invoker and env vars

Usage:
```bash
cd infra
terraform init
terraform apply -auto-approve \
  -var="project_id=YOUR_PROJECT" \
  -var="region=us-west1" \
  -var="service_name=accident-reports-frontend" \
  -var="bucket_name=accident-reports-artifacts"
```

Outputs:
- `cloud_run_url` — URL of the deployed service

## Notes
- Cloud Run injects `$PORT`; the Express server reads it automatically.
- The server serves the built SPA (`dist/`), proxies `/api` to GCS (or reads from `LOCAL_REPORTS_DIR`), and provides a health check at `/healthz`.
