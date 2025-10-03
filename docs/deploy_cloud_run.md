# Deploy Frontend to Google Cloud Run

This guide covers local dev, containerization, CI/CD via GitHub Actions, and provisioning via Terraform.

## Prereqs
- GCP project with billing enabled
- Artifact Registry + Cloud Run APIs enabled (Terraform will enable if using infra here)
- GitHub repository with these secrets set:
  - GCP_PROJECT_ID
  - GCP_WORKLOAD_IDENTITY_PROVIDER (if using Workload Identity Federation)
  - GCP_SA_EMAIL (service account with permissions to deploy to Cloud Run and push to Artifact Registry)

## Local development
- Generate static API JSON and run Vite dev server or Express server
  - From `frontend/`:
    - `npm install`
    - `npm run dev` (Vite dev server, UI only)
    - Alternative: `npm run build && node server.js` (Express serves `dist` and `/api` routes)

## Docker build (manual)
- From repo root:
  - `docker build -t REGION-docker.pkg.dev/PROJECT/REPOSITORY/SERVICE:local ./frontend`
  - `docker run -e PORT=8080 -p 8080:8080 REGION-docker.pkg.dev/PROJECT/REPOSITORY/SERVICE:local`
  - Open http://localhost:8080

## GitHub Actions (CI/CD)
- Workflow: `.github/workflows/deploy-cloud-run.yml`
- On push to `main` affecting `frontend/**`, it builds and pushes the image and deploys to Cloud Run.
- Configure repository secrets:
  - `GCP_PROJECT_ID`
  - `GCP_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_SA_EMAIL`

## Terraform provisioning
- Files in `infra/terraform/`:
  - `cloud_run_frontend.tf` creates Artifact Registry and Cloud Run, enables APIs, grants public access
- Usage:
  - `cd infra/terraform`
  - Create `terraform.tfvars` with:
    - `project_id = "your-project-id"`
    - `region     = "us-central1"` (or preferred region)
    - `service_name = "accident-reports-frontend"`
    - `repository   = "frontend"`
  - `terraform init`
  - `terraform apply`
- Output: `cloud_run_url`

## Notes
- The container listens on `$PORT` (Cloud Run injects this). Default in dev is 5173; in container we use 8080.
- The Express server serves:
  - Static `dist` build
  - Static JSON under `/api` generated at build time
  - SPA catch-all routing for non-API paths
