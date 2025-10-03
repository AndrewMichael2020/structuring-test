#!/usr/bin/env bash
set -euo pipefail

# Unified script to manage GCP infrastructure and Workload Identity Federation.
#
# Actions:
#   - setup:      (Default) Idempotently creates WIF, SAs, IAM, and sets secrets.
#   - destroy:    Destroys Terraform-managed resources (like the GCS bucket).
#   - recreate:   Destroys and then re-applies Terraform-managed resources.
#   - teardown:   Destroys Terraform resources AND deletes SAs, WIF pool/provider.
#
# Requires:
#  - gcloud CLI authenticated and configured for the target project.
#  - gh (GitHub CLI) authenticated (`gh auth login`).
#  - terraform CLI installed.

usage() {
  cat <<EOF
Usage: PROJECT_ID=<gcp-project-id> GITHUB_REPO=<owner/repo> bash scripts/manage_infra.sh [action]

Actions:
  setup       (Default) Configures WIF, SAs, IAM, and sets GitHub secrets.
  destroy     Destroys Terraform-managed resources (GCS bucket, etc.).
  recreate    Destroys and then re-applies Terraform resources.
  teardown    Destroys all resources including WIF pool, provider, and SAs.

Examples:
  # Initial setup
  PROJECT_ID=... GITHUB_REPO=... bash scripts/manage_infra.sh

  # Destroy and recreate the GCS bucket
  PROJECT_ID=... GITHUB_REPO=... bash scripts/manage_infra.sh recreate
EOF
}

ACTION=${1:-setup}

command -v gcloud >/dev/null 2>&1 || { echo "gcloud CLI not found. Install Google Cloud SDK first." >&2; exit 1; }
command -v gh >/dev/null 2>&1 || { echo "gh (GitHub CLI) not found. Install it and run 'gh auth login'." >&2; exit 1; }
command -v terraform >/dev/null 2>&1 || { echo "terraform CLI not found. Install it first." >&2; exit 1; }

: "${PROJECT_ID:?PROJECT_ID is required. e.g., 'gcp-agents-tests'}"
: "${GITHUB_REPO:?GITHUB_REPO is required, format 'owner/repo'. e.g., 'AndrewMichael2020/structuring-test'}"

# --- Configuration ---
POOL_ID=${POOL_ID:-github-pool}
PROVIDER_ID=${PROVIDER_ID:-github-actions}
TERRAFORM_SA_ID=${TERRAFORM_SA_ID:-terraform-applier}
CLOUDRUN_SA_ID=${CLOUDRUN_SA_ID:-github-cloudrun-deployer}
TF_CUSTOM_ROLE_ID="terraform_applier"

TERRAFORM_SA_EMAIL="${TERRAFORM_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
CLOUDRUN_SA_EMAIL="${CLOUDRUN_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
INFRA_DIR="${SCRIPT_DIR}/../infra"

# --- Helper Functions ---

configure_gcp() {
    echo "▶️ Configuring GCP Project: ${PROJECT_ID}"
    gcloud config set project "$PROJECT_ID" >/dev/null
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

    echo "▶️ Enabling required APIs..."
    gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
      run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com serviceusage.googleapis.com \
      --quiet
}

manage_terraform() {
    local tf_action=$1
    echo "▶️ Running 'terraform ${tf_action}' in ${INFRA_DIR}..."
    (
        cd "$INFRA_DIR"
        terraform init -upgrade
        terraform "${tf_action}" -auto-approve \
            -var="project_id=${PROJECT_ID}" \
            -var="region=us-west1" \
            -var="service_name=accident-reports-frontend" \
            -var="bucket_name=${PROJECT_ID}-report-artifacts"
    )
}

setup_all() {
    configure_gcp

    echo "▶️ Creating Workload Identity Pool: ${POOL_ID} (idempotent)"
    gcloud iam workload-identity-pools describe "$POOL_ID" --location=global >/dev/null 2>&1 || \
    gcloud iam workload-identity-pools create "$POOL_ID" --location=global --display-name="GitHub OIDC Pool"

    echo "▶️ Creating OIDC Provider: ${PROVIDER_ID} (idempotent)"
    PROVIDER_PARENT="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}"
    gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" --location=global --workload-identity-pool="$POOL_ID" >/dev/null 2>&1 || \
    gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
      --location=global --workload-identity-pool="$POOL_ID" --display-name="GitHub Actions" \
      --issuer-uri="https://token.actions.githubusercontent.com" \
      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
      --attribute-condition="attribute.repository=='${GITHUB_REPO}'"

    echo "▶️ Creating Service Accounts (idempotent)"
    gcloud iam service-accounts describe "$TERRAFORM_SA_EMAIL" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$TERRAFORM_SA_ID" --display-name="Terraform Apply via GitHub WIF"
    gcloud iam service-accounts describe "$CLOUDRUN_SA_EMAIL" >/dev/null 2>&1 || \
    gcloud iam service-accounts create "$CLOUDRUN_SA_ID" --display-name="Cloud Run Deployer via GitHub WIF"

    echo "▶️ Granting roles to Terraform SA..."
    # Note: Assumes create_tf_role.sh exists to create the custom role
    if [ -f "${SCRIPT_DIR}/create_tf_role.sh" ]; then
        bash "${SCRIPT_DIR}/create_tf_role.sh" >/dev/null

        echo "▶️ Binding custom role to Terraform SA (with retries for propagation)..."
        for i in {1..5}; do
            if gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${TERRAFORM_SA_EMAIL}" --role="projects/${PROJECT_ID}/roles/${TF_CUSTOM_ROLE_ID}" --quiet >/dev/null 2>&1; then
                echo "   Custom role bound successfully."
                break
            fi
            if [ "$i" -eq 5 ]; then
                echo "   Error: Failed to bind custom role after multiple attempts. Please check permissions." >&2
                exit 1
            fi
            echo "   Role not ready, retrying in 5 seconds... (Attempt $i/5)"
            sleep 5
        done
    else
        echo "   Warning: create_tf_role.sh not found. Granting 'roles/editor' to Terraform SA as a fallback."
        gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${TERRAFORM_SA_EMAIL}" --role="roles/editor" --quiet >/dev/null
    fi

    echo "▶️ Granting roles to Cloud Run deploy SA..."
    ROLES=(
      "roles/run.admin"
      "roles/artifactregistry.writer"
      "roles/iam.serviceAccountUser"
      "roles/cloudbuild.builds.editor"
      "roles/storage.objectAdmin"
      "roles/serviceusage.serviceUsageConsumer"
      "roles/cloudbuild.serviceAgent" # Grants permissions to access Cloud Build GCS buckets
    )
    for role in "${ROLES[@]}"; do
      gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${CLOUDRUN_SA_EMAIL}" --role="$role" --quiet
    done

    echo "▶️ Binding WIF principalSet to SAs (workloadIdentityUser)..."
    PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"
    gcloud iam service-accounts add-iam-policy-binding "$TERRAFORM_SA_EMAIL" --role="roles/iam.workloadIdentityUser" --member="$PRINCIPAL_SET" --quiet
    gcloud iam service-accounts add-iam-policy-binding "$CLOUDRUN_SA_EMAIL" --role="roles/iam.workloadIdentityUser" --member="$PRINCIPAL_SET" --quiet

    echo "▶️ Applying Terraform configuration..."
    manage_terraform "apply"

    echo "▶️ Setting secrets in GitHub repository: ${GITHUB_REPO}"
    WORKLOAD_IDP_RESOURCE="${PROVIDER_PARENT}/providers/${PROVIDER_ID}"
    gh secret set GCP_WORKLOAD_IDP --body "${WORKLOAD_IDP_RESOURCE}" --repo "${GITHUB_REPO}"
    gh secret set GCP_TERRAFORM_SA --body "${TERRAFORM_SA_EMAIL}" --repo "${GITHUB_REPO}"
    gh secret set GCP_CLOUDRUN_SA  --body "${CLOUDRUN_SA_EMAIL}" --repo "${GITHUB_REPO}"

    echo "✅ Setup complete."
}

teardown_all() {
    configure_gcp
    echo "🔥 Tearing down all resources..."

    manage_terraform "destroy"

    echo "▶️ Deleting Service Accounts..."
    gcloud iam service-accounts delete "$TERRAFORM_SA_EMAIL" --quiet || echo "Terraform SA already deleted."
    gcloud iam service-accounts delete "$CLOUDRUN_SA_EMAIL" --quiet || echo "Cloud Run SA already deleted."

    echo "▶️ Deleting Workload Identity Pool Provider..."
    gcloud iam workload-identity-pools providers delete "$PROVIDER_ID" --location=global --workload-identity-pool="$POOL_ID" --quiet || echo "WIF Provider already deleted."

    echo "▶️ Deleting Workload Identity Pool..."
    gcloud iam workload-identity-pools delete "$POOL_ID" --location=global --quiet || echo "WIF Pool already deleted."

    echo "▶️ Deleting Custom IAM Role..."
    gcloud iam roles delete "$TF_CUSTOM_ROLE_ID" --project="$PROJECT_ID" --quiet || echo "Custom role already deleted."

    echo "✅ Teardown complete."
}

# --- Main Execution Logic ---

case "$ACTION" in
  setup)
    setup_all
    ;;
  destroy)
    configure_gcp
    manage_terraform "destroy"
    echo "✅ Terraform destroy complete."
    ;;
  recreate)
    configure_gcp
    manage_terraform "destroy"
    manage_terraform "apply"
    echo "✅ Terraform recreate complete."
    ;;
  teardown)
    teardown_all
    ;;
  *)
    usage
    exit 1
    ;;
esac