# These outputs describe the selected configuration; no cloud resources exist yet.
output "environment" {
  description = "The selected environment."
  value       = local.environment_id
}

output "project_id" {
  description = "The existing Google Cloud project ID."
  value       = var.project_id
}

output "region" {
  description = "The selected Google Cloud region."
  value       = var.region
}
