terraform {
  backend "local" {}
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

resource "google_cloud_run_v2_service" "frontend" {
  name     = var.service_name
  location = var.region
  template {
    service_account = google_service_account.run_sa.email
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/web-app/${var.service_name}:latest"
      env { name = "GCS_BUCKET" value = var.bucket_name }
      env { name = "NODE_ENV" value = "production" }
      resources {
        cpu_idle = true
        limits = { cpu = "1", memory = "512Mi" }
      }
    }
    scaling { min_instance_count = 0 max_instance_count = 3 }
  }
  ingress = "INGRESS_TRAFFIC_ALL"
  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_service_iam_member" "invoker" {
  location = var.region
  service  = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
