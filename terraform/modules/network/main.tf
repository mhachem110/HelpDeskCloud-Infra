# Custom-mode VPC: no automatic regional subnets or public-facing firewall rules.
resource "google_compute_network" "this" {
  #checkov:skip=CKV2_GCP_18:No custom firewall in Phase 5; implied ingress deny applies, and GKE creates its required rules later.
  name                    = var.vpc_name
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

# One regional subnet carries future GKE nodes, Pods, and Services.
resource "google_compute_subnetwork" "this" {
  name                     = var.subnet_name
  region                   = var.region
  network                  = google_compute_network.this.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  secondary_ip_range {
    range_name    = var.pods_range_name
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = var.services_range_name
    ip_cidr_range = var.services_cidr
  }

  # Sample flow logs for future network troubleshooting; logging can incur usage charges.
  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.5
    metadata             = "EXCLUDE_ALL_METADATA"
  }
}

# Reserve a global internal range for Google's service producer network.
resource "google_compute_global_address" "private_services" {
  name          = var.private_services_range_name
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = var.private_services_address
  prefix_length = var.private_services_prefix
  network       = google_compute_network.this.id
}

# The references create the VPC -> allocation -> service connection dependency.
resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.this.id
  service                 = var.private_services_provider
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}
