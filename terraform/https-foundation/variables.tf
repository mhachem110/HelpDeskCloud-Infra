variable "project_id" {
  description = "Existing HelpDeskCloud project that owns the retained HTTPS foundation."
  type        = string
  default     = "helpdeskcloud-capstone-511905"
  validation {
    condition     = var.project_id == "helpdeskcloud-capstone-511905"
    error_message = "This root is scoped only to the approved HelpDeskCloud Dev project."
  }
}

variable "region" {
  description = "Existing Dev GKE region; global resources remain global."
  type        = string
  default     = "us-east1"
  validation {
    condition     = var.region == "us-east1"
    error_message = "This root is scoped only to the existing us-east1 Dev deployment."
  }
}

variable "hostname" {
  description = "Configured DNS name for the future HTTPS frontend. No default is provided."
  type        = string
  validation {
    condition = (
      length(var.hostname) <= 253 &&
      length(split(".", var.hostname)) >= 2 &&
      alltrue([for label in split(".", var.hostname) : can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", label))]) &&
      !can(regex("^[0-9.]+$", var.hostname))
    )
    error_message = "Provide one lower-case DNS hostname; IP addresses and wildcards are not accepted."
  }
}
