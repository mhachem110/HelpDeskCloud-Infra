# Dev uses the deployed VPC and subnet. No network ranges or node pools are recreated.
resource "google_container_cluster" "dev" {
  count = var.environment == "dev" ? 1 : 0

  name             = "helpdeskcloud-dev-gke"
  project          = var.project_id
  location         = var.region
  enable_autopilot = true

  network         = module.dev_network[0].vpc_self_link
  subnetwork      = module.dev_network[0].subnet_self_link
  networking_mode = "VPC_NATIVE"

  ip_allocation_policy {
    cluster_secondary_range_name  = module.dev_network[0].pods_range_name
    services_secondary_range_name = module.dev_network[0].services_range_name
  }

  # Nodes have internal addresses. Cloud Shell can use the authenticated DNS endpoint.
  private_cluster_config {
    enable_private_nodes = true
  }

  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic = true
    }
    ip_endpoints_config {
      enabled = false
    }
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  secret_manager_config {
    enabled = true
  }

  release_channel {
    channel = "REGULAR"
  }

  # Autopilot creates its own node pools using this dedicated node identity.
  cluster_autoscaling {
    auto_provisioning_defaults {
      service_account = google_service_account.dev_gke_nodes[0].email
    }
  }

  deletion_protection = true

  # The node account needs its runtime role and image access before cluster creation.
  depends_on = [
    google_project_iam_member.dev_gke_node_runtime,
    google_artifact_registry_repository_iam_member.dev_gke_image_pull,
  ]
}
