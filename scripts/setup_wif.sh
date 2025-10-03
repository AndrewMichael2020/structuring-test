#!/usr/bin/env bash
set -euo pipefail

# Setup Workload Identity Federation (OIDC) for GitHub Actions and create SAs.
# Requires: gcloud CLI authenticated and configured for the target project.

usage() {
  cat <<EOF
Usage: PROJECT_ID=<gcp-project-id> GITHUB_REPO=<owner/repo> \
       [POOL_ID=github-pool] [PROVIDER_ID=github-actions] \
       [TERRAFORM_SA_ID=terraform-applier] [CLOUDRUN_SA_ID=github-cloudrun-deployer] \
       bash scripts/setup_wif.sh

Creates:
 - Workload Identity Pool and OIDC Provider for GitHub
 - Service Accounts for Terraform apply and Cloud Run deploy
 - IAM bindings to allow OIDC principalSet to impersonate the SAs
Prints values to set GitHub Secrets:
 - GCP_WORKLOAD_IDP (provider resource path)
 - GCP_TERRAFORM_SA (terraform SA email)
 - GCP_CLOUDRUN_SA (cloud run deploy SA email)
EOF
}

command -v gcloud >/dev/null 2>&1 || { echo "gcloud CLI not found. Install Google Cloud SDK first."; exit 1; }

: "${PROJECT_ID:?PROJECT_ID is required}"
: "${GITHUB_REPO:?GITHUB_REPO is required, format owner/repo}"

POOL_ID=${POOL_ID:-github-pool}
PROVIDER_ID=${PROVIDER_ID:-github-actions}
TERRAFORM_SA_ID=${TERRAFORM_SA_ID:-terraform-applier}
CLOUDRUN_SA_ID=${CLOUDRUN_SA_ID:-github-cloudrun-deployer}

echo "Project: ${PROJECT_ID}"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "Enabling required APIs..."
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  serviceusage.googleapis.com \
  --quiet

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

echo "Creating Workload Identity Pool: ${POOL_ID} (idempotent)"
gcloud iam workload-identity-pools describe "$POOL_ID" --location=global >/dev/null 2>&1 || \
gcloud iam workload-identity-pools create "$POOL_ID" \
  --location=global \
  --display-name="GitHub OIDC Pool" \
  --description="OIDC from GitHub Actions"

echo "Creating OIDC Provider: ${PROVIDER_ID} (idempotent)"
PROVIDER_PARENT="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"
gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --location=global --workload-identity-pool="$POOL_ID" >/dev/null 2>&1 || \
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --location=global \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub Actions" \
  --description="GitHub Actions OIDC Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref,attribute.actor=assertion.actor,attribute.workflow=assertion.workflow" \
  --attribute-condition="attribute.repository=='${GITHUB_REPO}'"

WORKLOAD_IDP_RESOURCE="${PROVIDER_PARENT}/providers/${PROVIDER_ID}"

echo "Creating Service Accounts (idempotent)"
TERRAFORM_SA_EMAIL="${TERRAFORM_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUDRUN_SA_EMAIL="${CLOUDRUN_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts describe "$TERRAFORM_SA_EMAIL" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$TERRAFORM_SA_ID" --display-name="Terraform Apply via GitHub WIF"

gcloud iam service-accounts describe "$CLOUDRUN_SA_EMAIL" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$CLOUDRUN_SA_ID" --display-name="Cloud Run Deployer via GitHub WIF"

echo "Granting roles to Terraform SA (broad for demo; tighten later)"
# For demos, roles/editor is easiest. Consider replacing with a curated minimal set.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${TERRAFORM_SA_EMAIL}" \
  --role="roles/editor" --quiet

echo "Granting roles to Cloud Run deploy SA"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/run.admin" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/artifactregistry.writer" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/iam.serviceAccountUser" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/cloudbuild.builds.editor" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/cloudbuild.builds.editor" --quiet

echo "Binding WIF principalSet to SAs (workloadIdentityUser)"
PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "$TERRAFORM_SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="$PRINCIPAL_SET" --quiet

gcloud iam service-accounts add-iam-policy-binding "$CLOUDRUN_SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="$PRINCIPAL_SET" --quiet

cat <<EOF

Success! Set these GitHub Actions repository secrets:

  GCP_WORKLOAD_IDP = ${WORKLOAD_IDP_RESOURCE}
  GCP_TERRAFORM_SA = ${TERRAFORM_SA_EMAIL}
  GCP_CLOUDRUN_SA  = ${CLOUDRUN_SA_EMAIL}

Optional (gh CLI):
  gh secret set GCP_WORKLOAD_IDP --body '${WORKLOAD_IDP_RESOURCE}'
  gh secret set GCP_TERRAFORM_SA --body '${TERRAFORM_SA_EMAIL}'
  gh secret set GCP_CLOUDRUN_SA  --body '${CLOUDRUN_SA_EMAIL}'

EOF

# Optionally set via gh CLI automatically when GH_SET=1
if [[ "${GH_SET:-}" == "1" ]]; then
  if command -v gh >/dev/null 2>&1; then
    echo "Setting GitHub secrets via gh CLI for repo ${GITHUB_REPO}..."
    gh secret set GCP_WORKLOAD_IDP --body "${WORKLOAD_IDP_RESOURCE}" -R "${GITHUB_REPO}"
    gh secret set GCP_TERRAFORM_SA --body "${TERRAFORM_SA_EMAIL}" -R "${GITHUB_REPO}"
    gh secret set GCP_CLOUDRUN_SA  --body "${CLOUDRUN_SA_EMAIL}" -R "${GITHUB_REPO}"
    echo "GitHub secrets set."
  else
    echo "gh CLI not found; skipping automatic secret creation."
  fi
fi
