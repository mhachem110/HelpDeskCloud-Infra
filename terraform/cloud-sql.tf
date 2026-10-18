# Only Dev receives a database. The existing network module keeps its state addresses.
resource "google_sql_database_instance" "dev_postgres" {
  count = var.environment == "dev" ? 1 : 0

  name             = "helpdeskcloud-dev-postgres"
  region           = var.region
  database_version = "POSTGRES_17"

  # Terraform and the Cloud SQL API both block accidental instance deletion.
  deletion_protection = true

  settings {
    edition                     = "ENTERPRISE"
    tier                        = "db-f1-micro"
    availability_type           = "ZONAL"
    disk_type                   = "PD_SSD"
    disk_size                   = 10
    disk_autoresize             = false
    deletion_protection_enabled = true

    # Record query durations for troubleshooting without logging SQL text.
    database_flags {
      name  = "log_duration"
      value = "on"
    }

    # Daily backups retain the latest seven copies. PITR is a later cost decision.
    backup_configuration {
      enabled                        = true
      start_time                     = "04:00"
      point_in_time_recovery_enabled = false

      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    # Use the already deployed VPC and allocated PSA range; never expose public IPv4.
    ip_configuration {
      ipv4_enabled       = false
      private_network    = module.dev_network[0].vpc_self_link
      allocated_ip_range = module.dev_network[0].private_services_range_name
      ssl_mode           = "ENCRYPTED_ONLY"
    }
  }

  # The instance must wait for the existing service networking connection.
  depends_on = [module.dev_network]
}

# Create the named database only; application users, passwords, and schema come later.
resource "google_sql_database" "dev_helpdesk" {
  count = var.environment == "dev" ? 1 : 0

  name     = "helpdesk"
  instance = google_sql_database_instance.dev_postgres[0].name

  lifecycle {
    prevent_destroy = true
  }
}
