# Authentication comes from Application Default Credentials, including GitHub OIDC.
provider "google" {
  project = var.project_id
  region  = var.region
}
