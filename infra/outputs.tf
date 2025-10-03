output "cloud_run_url" {
  value = google_cloud_run_v2_service.frontend.uri
}

output "bucket_name" {
  value = google_storage_bucket.reports.name
}
