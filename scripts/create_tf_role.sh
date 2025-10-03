#!/usr/bin/env bash
set -euo pipefail

# Creates a custom IAM role with the minimum permissions required for
# the Terraform configuration in this project.

: "${PROJECT_ID:?PROJECT_ID is required. e.g., 'gcp-agents-tests'}"

ROLE_ID="terraform_applier"

echo "Checking for custom role ${ROLE_ID} in project ${PROJECT_ID}..."

if gcloud iam roles describe "${ROLE_ID}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Custom role ${ROLE_ID} already exists. Updating..."
  gcloud iam roles update "${ROLE_ID}" --project "${PROJECT_ID}" \
    --file=- <<EOF
title: "Terraform Applier"
description: "Minimal permissions for the structuring-test Terraform configuration"
stage: "GA"
includedPermissions:
  - storage.buckets.create
  - storage.buckets.get
  - storage.buckets.update
  - storage.buckets.setIamPolicy
  - artifactregistry.repositories.create
  - artifactregistry.repositories.get
  - run.services.create
  - run.services.get
  - run.services.update
  - run.services.setIamPolicy
  - iam.serviceAccounts.create
  - iam.serviceAccounts.get
EOF
else
  echo "Custom role ${ROLE_ID} not found. Creating..."
  gcloud iam roles create "${ROLE_ID}" --project "${PROJECT_ID}" \
    --title "Terraform Applier" \
    --description "Minimal permissions for the structuring-test Terraform configuration" \
    --stage "GA" \
    --permissions "storage.buckets.create,storage.buckets.get,storage.buckets.update,storage.buckets.setIamPolicy,artifactregistry.repositories.create,artifactregistry.repositories.get,run.services.create,run.services.get,run.services.update,run.services.setIamPolicy,iam.serviceAccounts.create,iam.serviceAccounts.get"
fi

echo "✅ Custom role '${ROLE_ID}' created/updated successfully."
echo "You can now update 'setup_all.sh' and 'setup_wif.sh' to use this role."
echo "Replace 'roles/editor' with 'projects/${PROJECT_ID}/roles/${ROLE_ID}' for the terraform-applier service account."
