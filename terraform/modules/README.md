# Future Terraform modules

`network/` defines the custom VPC, subnet and secondary ranges, private services
allocation, and service connection. The root configuration calls it only for Dev.
Stage and Prod remain disabled. IAM and later infrastructure modules require
separate review before they are added.
