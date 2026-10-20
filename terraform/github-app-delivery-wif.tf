# Dedicated, environment-bound identities for the protected application
# publisher and deployer jobs. These extend the existing helpdesk-github pool.

resource "google_service_account" "dev_app_publisher" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-app-publisher-dev"
  display_name = "HelpDesk Dev application image publisher"
  description  = "GitHub Actions identity for approved Dev application image publication"
  project      = var.project_id
}

resource "google_iam_workload_identity_pool_provider" "dev_app_publish" {
  count = var.environment == "dev" ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = "helpdesk-github"
  workload_identity_pool_provider_id = "github-app-publish-dev"
  display_name                       = "App image publication Dev"
  description                        = "HelpDeskCloud-App app-dev-delivery.yml in the protected dev-app-publish Environment"
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
    attribute.environment == "dev-app-publish" &&
    attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/app-dev-delivery.yml@refs/heads/dev"
  EOT

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "dev_app_publisher_wif" {
  count              = var.environment == "dev" ? 1 : 0
  service_account_id = google_service_account.dev_app_publisher[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/helpdesk-github/subject/repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:environment:dev-app-publish"
}

# Image upload is limited to the existing immutable Dev Docker repository.
resource "google_artifact_registry_repository_iam_member" "dev_app_publisher_writer" {
  count      = var.environment == "dev" ? 1 : 0
  project    = var.project_id
  location   = google_artifact_registry_repository.dev_images[0].location
  repository = google_artifact_registry_repository.dev_images[0].repository_id
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.dev_app_publisher[0].member
}

resource "google_service_account" "dev_app_deployer" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-app-deployer-dev"
  display_name = "HelpDesk Dev application deployer"
  description  = "GitHub Actions identity for approved Dev application deployment"
  project      = var.project_id
}

resource "google_iam_workload_identity_pool_provider" "dev_app_deploy" {
  count = var.environment == "dev" ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = "helpdesk-github"
  workload_identity_pool_provider_id = "github-app-deploy-dev"
  display_name                       = "App deployment Dev"
  description                        = "HelpDeskCloud-App app-dev-delivery.yml in the protected dev-app-deploy Environment"
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
    attribute.environment == "dev-app-deploy" &&
    attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/app-dev-delivery.yml@refs/heads/dev"
  EOT

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "dev_app_deployer_wif" {
  count              = var.environment == "dev" ? 1 : 0
  service_account_id = google_service_account.dev_app_deployer[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/helpdesk-github/subject/repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:environment:dev-app-deploy"
}

# The GKE DNS control-plane endpoint requires this unconditional project-level
# discovery/connect grant. Kubernetes API permissions stay namespace-scoped by
# the dedicated Role and RoleBinding in k8s/dev-delivery-rbac.yaml.
resource "google_project_iam_member" "dev_app_deployer_cluster_viewer" {
  count   = var.environment == "dev" ? 1 : 0
  project = var.project_id
  role    = "roles/container.clusterViewer"
  member  = google_service_account.dev_app_deployer[0].member
}
