output "iap_backend_service_name" {
  description = "Global IAP protected backend service receiving the single user grant."
  value       = google_iap_web_backend_service_iam_member.helpdesk_user.web_backend_service
}

output "iap_allowed_member" {
  description = "Exact IAP principal granted access."
  value       = google_iap_web_backend_service_iam_member.helpdesk_user.member
}
