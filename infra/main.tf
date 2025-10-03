terraform {
  # The GCS backend will be configured dynamically by the manage_infra.sh script.
  # This allows the bucket to be created before Terraform initializes the backend.
  backend "gcs" {}
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "iam.googleapis.com",
    "cloudbuild.googleapis.com",
    "storage.googleapis.com"
  ])
  service = each.key
}

resource "google_storage_bucket" "reports" {
  name                        = var.bucket_name
  location                    = var.region
  force_destroy               = true
  uniform_bucket_level_access = true
  cors {
    origin          = ["*"]
    method          = ["GET", "HEAD", "OPTIONS"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}

resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

resource "google_storage_bucket_iam_member" "run_sa_read" {
  bucket = google_storage_bucket.reports.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "web-app"
  description   = "Containers for Accident Reports frontend"
  format        = "DOCKER"
}

resource "google_service_account" "run_sa" {
  account_id   = "cr-frontend-sa"
  display_name = "Cloud Run SA for accident reports"
}

resource "google_project_iam_member" "run_sa_roles" {
  for_each = toset([
    "roles/run.admin",
    "roles/artifactregistry.admin", # Allows creating the repo on first deploy from source
    "roles/iam.serviceAccountUser",
    "roles/cloudbuild.builds.editor",
    "roles/storage.objectAdmin",
    "roles/serviceusage.serviceUsageConsumer",
    "roles/cloudbuild.serviceAgent",
    "roles/logging.viewer" # Allows viewing build logs
  ])
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.run_sa.email}"
}

resource "google_cloud_run_v2_service" "frontend" {
  name     = var.service_name
  location = var.region
  template {
    service_account = google_service_account.run_sa.email
    containers {
      # Use a public placeholder image for initial creation. The CD pipeline will deploy the real image later.
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      env {
        name  = "GCS_BUCKET"
        value = google_storage_bucket.reports.name
      }
      env {
        name  = "NODE_ENV"
        value = "production"
      }
      resources {
        cpu_idle = true
        limits = { cpu = "1", memory = "512Mi" }
      }
    }
    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }
  }
  ingress = "INGRESS_TRAFFIC_ALL"
  depends_on = [
    google_project_service.apis,
    google_project_iam_member.run_sa_service_account_user # Ensure roles are granted before service creation
  ]

  # Ignore changes to the image, as it will be updated by the CD pipeline.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }
}

data "google_iam_policy" "run_sa_self_policy" {
  binding {
    role = "roles/run.serviceAgent"
    members = [
      "serviceAccount:${google_service_account.run_sa.email}"
    ]
  }
}

resource "google_cloud_run_service_iam_member" "invoker" {
  location = var.region
  service  = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
