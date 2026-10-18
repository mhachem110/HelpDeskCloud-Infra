variable "project_id" {
  description = "The existing Google Cloud project ID."
  type        = string
}

variable "environment" {
  description = "The target environment for this configuration."
  type        = string

  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "Environment must be dev, stage, or prod."
  }
}

variable "region" {
  description = "The primary Google Cloud region."
  type        = string
}
