# Configuration outputs exist for every environment.
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

# Network outputs are null when Stage or Prod has no network module instance.
output "vpc_name" {
  description = "Dev VPC name; null outside Dev."
  value       = try(module.dev_network[0].vpc_name, null)
}

output "vpc_self_link" {
  description = "Dev VPC self-link for later GKE and Cloud SQL configuration."
  value       = try(module.dev_network[0].vpc_self_link, null)
}

output "subnet_name" {
  description = "Dev regional subnet name; null outside Dev."
  value       = try(module.dev_network[0].subnet_name, null)
}

output "subnet_self_link" {
  description = "Dev subnet self-link for future GKE."
  value       = try(module.dev_network[0].subnet_self_link, null)
}

output "subnet_cidr" {
  description = "Primary subnet CIDR for future GKE nodes."
  value       = try(module.dev_network[0].subnet_cidr, null)
}

output "pods_range_name" {
  description = "Secondary range name for future GKE Pods."
  value       = try(module.dev_network[0].pods_range_name, null)
}

output "pods_cidr" {
  description = "Secondary CIDR for future GKE Pods."
  value       = try(module.dev_network[0].pods_cidr, null)
}

output "services_range_name" {
  description = "Secondary range name for future GKE Services."
  value       = try(module.dev_network[0].services_range_name, null)
}

output "services_cidr" {
  description = "Secondary CIDR for future GKE Services."
  value       = try(module.dev_network[0].services_cidr, null)
}

output "private_services_range_name" {
  description = "Allocation name for future Cloud SQL private IP."
  value       = try(module.dev_network[0].private_services_range_name, null)
}

output "private_services_connection_id" {
  description = "Connection ID; future Cloud SQL must wait for this connection."
  value       = try(module.dev_network[0].private_services_connection_id, null)
}
