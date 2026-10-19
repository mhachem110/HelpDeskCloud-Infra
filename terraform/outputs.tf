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

# Registry outputs identify where a later application pipeline will publish images.
output "artifact_registry_repository_id" {
  description = "Dev Docker repository ID; null outside Dev."
  value       = try(google_artifact_registry_repository.dev_images[0].repository_id, null)
}

output "artifact_registry_location" {
  description = "Dev Docker repository region; null outside Dev."
  value       = try(google_artifact_registry_repository.dev_images[0].location, null)
}

output "artifact_registry_resource_name" {
  description = "Dev Docker repository name returned by the provider; null outside Dev."
  value       = try(google_artifact_registry_repository.dev_images[0].name, null)
}

output "docker_image_repository" {
  description = "Image path before the tag or digest; null outside Dev."
  value       = try(format("%s-docker.pkg.dev/%s/%s/helpdeskcloud", google_artifact_registry_repository.dev_images[0].location, var.project_id, google_artifact_registry_repository.dev_images[0].repository_id), null)
}

# SQL outputs describe infrastructure. They do not establish a database login.
output "cloud_sql_instance_name" {
  description = "Dev PostgreSQL instance name; null outside Dev."
  value       = try(google_sql_database_instance.dev_postgres[0].name, null)
}

output "cloud_sql_connection_name" {
  description = "Instance connection name for a future Auth Proxy; null outside Dev."
  value       = try(google_sql_database_instance.dev_postgres[0].connection_name, null)
}

output "cloud_sql_region" {
  description = "Dev PostgreSQL region; null outside Dev."
  value       = try(google_sql_database_instance.dev_postgres[0].region, null)
}

output "cloud_sql_database_version" {
  description = "Dev PostgreSQL engine version; null outside Dev."
  value       = try(google_sql_database_instance.dev_postgres[0].database_version, null)
}

output "cloud_sql_database_name" {
  description = "Named Dev database; null outside Dev."
  value       = try(google_sql_database.dev_helpdesk[0].name, null)
}

output "cloud_sql_private_ip" {
  description = "Dev instance private IP after creation; null outside Dev."
  value       = try(google_sql_database_instance.dev_postgres[0].private_ip_address, null)
}

output "cloud_sql_vpc_self_link" {
  description = "Existing Dev VPC used by Cloud SQL; null outside Dev."
  value       = try(module.dev_network[0].vpc_self_link, null)
}

output "cloud_sql_private_services_range_name" {
  description = "Existing PSA allocation selected for Cloud SQL; null outside Dev."
  value       = try(module.dev_network[0].private_services_range_name, null)
}

# Phase 7 handoff values are null outside Dev; no credentials are exported.
output "gke_cluster_name" {
  description = "Dev Autopilot cluster name."
  value       = try(google_container_cluster.dev[0].name, null)
}

output "gke_cluster_location" {
  description = "Dev cluster region."
  value       = try(google_container_cluster.dev[0].location, null)
}

output "gke_mode" {
  description = "Cluster operating mode; null outside Dev."
  value       = try(google_container_cluster.dev[0].enable_autopilot ? "AUTOPILOT" : "STANDARD", null)
}

output "gke_workload_pool" {
  description = "Workload Identity Federation pool used by Kubernetes service accounts."
  value       = try(google_container_cluster.dev[0].workload_identity_config[0].workload_pool, null)
}

output "gke_node_service_account" {
  description = "Dedicated identity for GKE nodes and image pulls."
  value       = try(google_service_account.dev_gke_nodes[0].email, null)
}

output "app_service_account" {
  description = "Dev runtime identity used by the Cloud SQL Auth Proxy."
  value       = try(google_service_account.dev_app[0].email, null)
}

output "migration_service_account" {
  description = "One-time migration proxy identity."
  value       = try(google_service_account.dev_migration[0].email, null)
}

output "migration_runner_service_account" {
  description = "Dev GitHub Actions identity for approved namespace-scoped migration Job submission."
  value       = try(google_service_account.dev_app_migration_runner[0].email, null)
}

output "app_connection_secret" {
  description = "Secret Manager resource name; the payload is never in Terraform."
  value       = try(google_secret_manager_secret.dev_app_connection[0].id, null)
}

output "migration_admin_secret" {
  description = "Migration password secret metadata resource name only."
  value       = try(google_secret_manager_secret.dev_admin_password[0].id, null)
}
