resource "google_iap_web_backend_service_iam_member" "helpdesk_user" {
  project             = var.project_id
  web_backend_service = var.backend_service_name
  role                = "roles/iap.httpsResourceAccessor"
  member              = "user:${var.allowed_email}"
}
