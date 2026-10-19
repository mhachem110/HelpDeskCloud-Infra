# Terraform owns secret metadata and IAM only. Owners add password-bearing versions later.
resource "google_secret_manager_secret" "dev_app_connection" {
  count               = var.environment == "dev" ? 1 : 0
  secret_id           = "helpdesk-dev-db-connection"
  project             = var.project_id
  deletion_protection = true

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret" "dev_admin_password" {
  count               = var.environment == "dev" ? 1 : 0
  secret_id           = "helpdesk-dev-db-admin-password"
  project             = var.project_id
  deletion_protection = true

  replication {
    auto {}
  }
}

# The managed CSI driver uses the Kubernetes workload principal directly.
resource "google_secret_manager_secret_iam_member" "dev_app_secret_access" {
  count     = var.environment == "dev" ? 1 : 0
  secret_id = google_secret_manager_secret.dev_app_connection[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/helpdesk-dev/sa/helpdesk-dev-app"
}

resource "google_secret_manager_secret_iam_member" "dev_admin_secret_access" {
  count     = var.environment == "dev" ? 1 : 0
  secret_id = google_secret_manager_secret.dev_admin_password[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/helpdesk-dev/sa/helpdesk-dev-migrate"
}
