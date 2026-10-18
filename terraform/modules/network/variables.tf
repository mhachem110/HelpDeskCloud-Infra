# The caller supplies names and non-overlapping ranges for its environment.
variable "region" {
  description = "Region of the subnet."
  type        = string
}

variable "vpc_name" {
  description = "Name of the custom VPC."
  type        = string
}

variable "subnet_name" {
  description = "Name of the regional subnet."
  type        = string
}

variable "subnet_cidr" {
  description = "Primary subnet CIDR for future GKE nodes."
  type        = string
}

variable "pods_range_name" {
  description = "Secondary range name for future GKE Pods."
  type        = string
}

variable "pods_cidr" {
  description = "Secondary CIDR for future GKE Pods."
  type        = string
}

variable "services_range_name" {
  description = "Secondary range name for future GKE Services."
  type        = string
}

variable "services_cidr" {
  description = "Secondary CIDR for future GKE Services."
  type        = string
}

variable "private_services_range_name" {
  description = "Name of the private services access allocation."
  type        = string
}

variable "private_services_address" {
  description = "Starting IPv4 address of the private services access range."
  type        = string
}

variable "private_services_prefix" {
  description = "Prefix length of the private services access allocation."
  type        = number
}

variable "private_services_provider" {
  description = "Google service producer for private services access."
  type        = string
}
