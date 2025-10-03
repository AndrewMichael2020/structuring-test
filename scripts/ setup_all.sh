#!/usr/bin/env bash
set -euo pipefail

# Setup Workload Identity Federation (OIDC) for GitHub Actions, create SAs,
# and automatically set the required GitHub Actions repository secrets.
#
# Requires:
#  - gcloud CLI authenticated and configured for the target project.
#  - gh (GitHub CLI) authenticated (`gh auth login`).

usage() {
  cat <<EOF
Usage: PROJECT_ID=<gcp-project-id> GITHUB_REPO=<owner/repo> bash scripts/setup_all.sh

This script will:
 1. Create the Workload Identity Pool and OIDC Provider for GitHub.
 2. Create Service Accounts for Terraform and Cloud Run deployment.
 3. Grant the necessary IAM roles.
 4. Bind the OIDC principal to the Service Accounts.
 5. Automatically set the following secrets in your GitHub repository:
    - GCP_WORKLOAD_IDP
    - GCP_TERRAFORM_SA
    - GCP_CLOUDRUN_SA
EOF
}

command -v gcloud >/dev/null 2>&1 || { echo "gcloud CLI not found. Install Google Cloud SDK first." >&2; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "gh (GitHub CLI) not found. Install it and run 'gh auth login'." >&2; exit 1; }

: "${PROJECT_ID:?PROJECT_ID is required. e.g., 'gcp-agents-tests'}"
: "${GITHUB_REPO:?GITHUB_REPO is required, format 'owner/repo'. e.g., 'AndrewMichael2020/structuring-test'}"

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
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="attribute.repository=='${GITHUB_REPO}'"

WORKLOAD_IDP_RESOURCE="${PROVIDER_PARENT}/providers/${PROVIDER_ID}"

echo "Creating Service Accounts (idempotent)"
TERRAFORM_SA_EMAIL="${TERRAFORM_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUDRUN_SA_EMAIL="${CLOUDRUN_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts describe "$TERRAFORM_SA_EMAIL" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$TERRAFORM_SA_ID" --display-name="Terraform Apply via GitHub WIF"

gcloud iam service-accounts describe "$CLOUDRUN_SA_EMAIL" >/dev/null 2>&1 || \
gcloud iam service-accounts create "$CLOUDRUN_SA_ID" --display-name="Cloud Run Deployer via GitHub WIF"

echo "Granting roles to Terraform SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${TERRAFORM_SA_EMAIL}" --role="roles/editor" --quiet

echo "Granting roles to Cloud Run deploy SA..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/run.admin" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/artifactregistry.writer" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/iam.serviceAccountUser" --quiet
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="roles/cloudbuild.builds.editor" --quiet

echo "Binding WIF principalSet to SAs (workloadIdentityUser)..."
PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "$TERRAFORM_SA_EMAIL" --role="roles/iam.workloadIdentityUser" --member="$PRINCIPAL_SET" --quiet
gcloud iam service-accounts add-iam-policy-binding "$CLOUDRUN_SA_EMAIL" --role="roles/iam.workloadIdentityUser" --member="$PRINCIPAL_SET" --quiet

echo ""
echo "✅ GCP configuration complete."
echo "🔐 Now setting secrets in GitHub repository: ${GITHUB_REPO}"

gh secret set GCP_WORKLOAD_IDP --body "${WORKLOAD_IDP_RESOURCE}" --repo "${GITHUB_REPO}"
gh secret set GCP_TERRAFORM_SA --body "${TERRAFORM_SA_EMAIL}" --repo "${GITHUB_REPO}"
gh secret set GCP_CLOUDRUN_SA  --body "${CLOUDRUN_SA_EMAIL}" --repo "${GITHUB_REPO}"

echo ""
echo "✅ All secrets have been set successfully."
echo "You can now re-run the failed GitHub Actions workflow."

```

### What to do next

1.  **Run the new setup script** from your Cloud Shell. This will re-configure GCP and, most importantly, set the GitHub secrets for you automatically.

   ```bash
   # Make sure you are logged into the GitHub CLI first: gh auth login
   PROJECT_ID=gcp-agents-tests GITHUB_REPO=AndrewMichael2020/structuring-test bash scripts/setup_all.sh
   ```

2.  **Re-run the GitHub Action.** After the script completes, go to the "Actions" tab in your GitHub repository and re-run the failed "CD" workflow.

This process will eliminate any possibility of an incorrect secret and should finally resolve the authentication error.

<!--
[PROMPT_SUGGESTION]The deployment succeeded! How can I view the application logs in Google Cloud?[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]Can you explain the IAM roles being granted in `setup_all.sh` and suggest how to tighten them for better security?[/PROMPT_SUGGESTION]
->