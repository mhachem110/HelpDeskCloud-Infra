# The bucket and prefix are supplied by an environment .gcs.tfbackend file at init.
terraform {
  backend "gcs" {}
}
