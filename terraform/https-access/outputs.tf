output "iap_backend_service_name" {
  description = "Global IAP protected backend service receiving the single user grant."
  # Keep this as the GKE-generated name; the provider may normalize the IAM
  # resource field to a fully qualified path during readback.
  value = var.backend_service_name
}

output "iap_allowed_member" {
  description = "Exact IAP principal granted access."
  value       = google_iap_web_backend_service_iam_member.helpdesk_user.member
}
