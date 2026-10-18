# Only Dev receives a Docker image repository in Phase 6.
resource "google_artifact_registry_repository" "dev_images" {
  count = var.environment == "dev" ? 1 : 0

  repository_id = "helpdeskcloud-dev-images"
  location      = var.region
  format        = "DOCKER"
  description   = "Docker images for HelpDesk Cloud Dev"

  # Keep release tags stable so a future GKE rollout can use immutable images.
  docker_config {
    immutable_tags = true
  }
}
