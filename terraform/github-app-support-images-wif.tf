# Dedicated GitHub identity for the separately approved supporting-image publisher.
# The requested descriptive name is retained as display_name. Google service-account
# account IDs are limited to 30 characters, so the email local part is abbreviated.
resource "google_service_account" "dev_app_support_image_publisher" {
  count        = var.environment == "dev" ? 1 : 0
  account_id   = "helpdesk-app-support-pub-dev"
  display_name = "helpdesk-app-support-image-publisher-dev"
  description  = "GitHub Actions identity for approved Dev supporting-image publication"
  project      = var.project_id
}

# This provider is added to the existing helpdesk-github pool. It does not create
# or alter the pool or the infrastructure-only github-infra-dev provider.
resource "google_iam_workload_identity_pool_provider" "dev_app_support_images" {
  count = var.environment == "dev" ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = "helpdesk-github"
  workload_identity_pool_provider_id = "github-app-support-images-dev"
  display_name                       = "App supporting images Dev"
  description                        = "HelpDeskCloud-App supporting-images-ci.yml on dev with the protected publication Environment"
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
    attribute.environment == "dev-supporting-images-publish" &&
    attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/supporting-images-ci.yml@refs/heads/dev"
  EOT

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# The subject was checked in the App repository's Actions > OIDC settings:
# immutable claims are enabled and the displayed prefix is
# repo:mhachem110@150286776/HelpDeskCloud-App@1423008128. The publishing job's
# protected Environment supplies the environment suffix used by this principal.
resource "google_service_account_iam_member" "dev_app_support_images_wif" {
  count              = var.environment == "dev" ? 1 : 0
  service_account_id = google_service_account.dev_app_support_image_publisher[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/helpdesk-github/subject/repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:environment:dev-supporting-images-publish"
}

# Upload permission is granted only on the already managed Dev image repository.
resource "google_artifact_registry_repository_iam_member" "dev_app_support_images_writer" {
  count      = var.environment == "dev" ? 1 : 0
  project    = var.project_id
  location   = google_artifact_registry_repository.dev_images[0].location
  repository = google_artifact_registry_repository.dev_images[0].repository_id
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.dev_app_support_image_publisher[0].member
}
