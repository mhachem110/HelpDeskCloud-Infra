# Dedicated GitHub Actions identity for the separately approved one-time Dev
# database migration. The Google service-account account ID is limited to 30
# characters; the workflow and RBAC use this shortened stable email.
resource "google_service_account" "dev_app_migration_runner" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-app-migr-runner-dev"
  display_name = "helpdesk-app-migration-runner-dev"
  description  = "GitHub Actions identity for the approved Dev database migration Job"
  project      = var.project_id
}

# Add a migration-only provider to the existing helpdesk-github pool. This is
# separate from both the infra provider and the supporting-image publisher.
resource "google_iam_workload_identity_pool_provider" "dev_app_migration" {
  count = var.environment == "dev" ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = "helpdesk-github"
  workload_identity_pool_provider_id = "github-app-migration-dev"
  display_name                       = "App database migration Dev"
  description                        = "HelpDeskCloud-App dev-db-migration.yml in the protected dev-db-migration Environment"
  disabled                           = false

  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
    "attribute.environment"         = "assertion.environment"
    "attribute.workflow_ref"        = "assertion.workflow_ref"
  }

  attribute_condition = <<-EOT
    attribute.repository == "mhachem110/HelpDeskCloud-App" &&
    attribute.repository_id == "1423008128" &&
    attribute.repository_owner_id == "150286776" &&
    attribute.ref == "refs/heads/dev" &&
    attribute.environment == "dev-db-migration" &&
    attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/dev-db-migration.yml@refs/heads/dev"
  EOT

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# The App repository's OIDC settings were verified with immutable subject
# claims enabled. Environment jobs use
# repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:environment:<name>;
# this exact binding substitutes the reviewed dev-db-migration Environment.
resource "google_service_account_iam_member" "dev_app_migration_runner_wif" {
  count              = var.environment == "dev" ? 1 : 0
  service_account_id = google_service_account.dev_app_migration_runner[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/helpdesk-github/subject/repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:environment:dev-db-migration"
}

# gcloud get-credentials needs container.clusters.get and
# container.clusters.getCredentials. Keep clusterViewer conditionally scoped to
# the one existing Dev cluster; Kubernetes API verbs remain separately limited
# by k8s/dev-migration-runner-rbac.yaml in the helpdesk-dev namespace.
resource "google_project_iam_member" "dev_app_migration_runner_cluster_viewer" {
  count   = var.environment == "dev" ? 1 : 0
  project = var.project_id
  role    = "roles/container.clusterViewer"
  member  = google_service_account.dev_app_migration_runner[0].member

  condition {
    title       = "helpdesk-dev-migration-runner-cluster"
    description = "Allow cluster discovery only for the existing Dev GKE cluster"
    expression  = <<-CEL
      resource.type == "container.googleapis.com/Cluster" &&
      resource.name == "projects/helpdeskcloud-capstone-511905/locations/us-east1/clusters/helpdeskcloud-dev-gke"
    CEL
  }
}
