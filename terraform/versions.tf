# Keep the CLI and Google provider versions predictable across machines and CI.
terraform {
  required_version = "= 1.16.2"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.8.0"
    }
  }
}
