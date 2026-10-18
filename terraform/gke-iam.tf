# Node identity performs GKE system tasks and pulls images; it is not a Pod identity.
resource "google_service_account" "dev_gke_nodes" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-gke-node-dev"
  display_name = "HelpDesk Dev GKE nodes"
  project      = var.project_id
}

resource "google_project_iam_member" "dev_gke_node_runtime" {
  count   = var.environment == "dev" ? 1 : 0
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = google_service_account.dev_gke_nodes[0].member
}

resource "google_artifact_registry_repository_iam_member" "dev_gke_image_pull" {
  count      = var.environment == "dev" ? 1 : 0
  project    = var.project_id
  location   = google_artifact_registry_repository.dev_images[0].location
  repository = google_artifact_registry_repository.dev_images[0].repository_id
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.dev_gke_nodes[0].member
}

# The application proxy gets Cloud SQL Client through KSA-to-GSA impersonation.
resource "google_service_account" "dev_app" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-app-dev"
  display_name = "HelpDesk Dev application"
  project      = var.project_id
}

resource "google_project_iam_member" "dev_app_cloudsql" {
  count   = var.environment == "dev" ? 1 : 0
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.dev_app[0].member
}

resource "google_service_account_iam_member" "dev_app_workload_identity" {
  count              = var.environment == "dev" ? 1 : 0
  service_account_id = google_service_account.dev_app[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[helpdesk-dev/helpdesk-dev-app]"
}

# One-time schema migration has a separate identity from the running application.
resource "google_service_account" "dev_migration" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-migrate-dev"
  display_name = "HelpDesk Dev database migration"
  project      = var.project_id
}

resource "google_project_iam_member" "dev_migration_cloudsql" {
  count   = var.environment == "dev" ? 1 : 0
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = google_service_account.dev_migration[0].member
}

resource "google_service_account_iam_member" "dev_migration_workload_identity" {
  count              = var.environment == "dev" ? 1 : 0
  service_account_id = google_service_account.dev_migration[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[helpdesk-dev/helpdesk-dev-migrate]"
}
