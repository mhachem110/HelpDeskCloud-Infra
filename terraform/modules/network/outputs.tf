# Later Cloud SQL and GKE phases can consume these resource-backed values.
output "vpc_name" {
  description = "VPC name."
  value       = google_compute_network.this.name
}

output "vpc_self_link" {
  description = "VPC self-link for future GKE and Cloud SQL resources."
  value       = google_compute_network.this.self_link
}

output "subnet_name" {
  description = "Regional subnet name."
  value       = google_compute_subnetwork.this.name
}

output "subnet_self_link" {
  description = "Subnet self-link for future GKE resources."
  value       = google_compute_subnetwork.this.self_link
}

output "subnet_cidr" {
  description = "Primary range for future GKE nodes."
  value       = google_compute_subnetwork.this.ip_cidr_range
}

output "pods_range_name" {
  description = "Secondary range name for future GKE Pods."
  value       = google_compute_subnetwork.this.secondary_ip_range[0].range_name
}

output "pods_cidr" {
  description = "Secondary CIDR for future GKE Pods."
  value       = google_compute_subnetwork.this.secondary_ip_range[0].ip_cidr_range
}

output "services_range_name" {
  description = "Secondary range name for future GKE Services."
  value       = google_compute_subnetwork.this.secondary_ip_range[1].range_name
}

output "services_cidr" {
  description = "Secondary CIDR for future GKE Services."
  value       = google_compute_subnetwork.this.secondary_ip_range[1].ip_cidr_range
}

output "private_services_range_name" {
  description = "Allocation name for future Cloud SQL private IP."
  value       = google_compute_global_address.private_services.name
}

output "private_services_connection_id" {
  description = "Private services connection ID; depend on this before Cloud SQL creation."
  value       = google_service_networking_connection.private_services.id
}
