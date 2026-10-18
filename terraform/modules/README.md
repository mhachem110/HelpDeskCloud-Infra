# Terraform module inventory

`network/` defines the custom VPC, subnet and secondary ranges, private services
allocation, and service connection. The root configuration calls it only for Dev.
Stage and Prod remain disabled. Phase 6 keeps its one Docker repository and one
Cloud SQL instance/database in two small root files rather than adding modules
that would only wrap a single resource. Those resources reference the network
module's real VPC and private-services-range outputs. Future GKE components can
be reviewed for a module when they are implemented.
