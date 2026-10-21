# One network module owns the VPC, subnet, secondary ranges and private services access.
# GKE and private Cloud SQL consume these outputs; retaining its addresses preserves existing state.
# Stage and Prod have inputs ready but intentionally create no network resources yet.
module "dev_network" {
  count  = var.environment == "dev" ? 1 : 0
  source = "./modules/network"

  region                      = var.region
  vpc_name                    = "helpdeskcloud-dev-vpc"
  subnet_name                 = "helpdeskcloud-dev-subnet"
  subnet_cidr                 = "10.20.0.0/20"
  pods_range_name             = "helpdeskcloud-dev-pods"
  pods_cidr                   = "10.24.0.0/16"
  services_range_name         = "helpdeskcloud-dev-services"
  services_cidr               = "10.25.0.0/20"
  private_services_range_name = "helpdeskcloud-dev-psa"
  private_services_address    = "10.30.0.0"
  private_services_prefix     = 16
  private_services_provider   = "servicenetworking.googleapis.com"
}
