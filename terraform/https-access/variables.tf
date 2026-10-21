variable "project_id" {
  description = "Existing HelpDeskCloud project."
  type        = string
  default     = "helpdeskcloud-capstone-511905"
  validation {
    condition     = var.project_id == "helpdeskcloud-capstone-511905"
    error_message = "This root is scoped only to the approved HelpDeskCloud Dev project."
  }
}

variable "region" {
  description = "Existing Dev GKE region."
  type        = string
  default     = "us-east1"
  validation {
    condition     = var.region == "us-east1"
    error_message = "This root is scoped only to the existing us-east1 Dev deployment."
  }
}

variable "backend_service_name" {
  description = "Exact GKE Gateway backend discovered from the approved HelpDesk HTTPRoute and Service NEG."
  type        = string
  validation {
    condition     = can(regex("^gkegw1?-[a-z0-9-]{1,56}$", var.backend_service_name))
    error_message = "Use the exact GKE Gateway generated global backend name (gkegw-* or gkegw1-*); arbitrary backends are rejected."
  }
}

variable "allowed_email" {
  description = "One owner-selected Google account allowed through IAP; no default or inferred address is used."
  type        = string
  validation {
    condition     = can(regex("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$", var.allowed_email))
    error_message = "Provide exactly one Google account email address."
  }
}
