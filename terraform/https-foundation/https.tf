# Enable Certificate Manager and IAP once through the project bootstrap identity.
# The routine Terraform identity intentionally has no serviceusage.services.enable permission.

# The original FreeDNS certificate resources are deprecated but remain state-managed and protected.
# They share the certificate map with the active dynv6 entry; retire them only in a reviewed change.
locals {
  legacy_hostname = "helpdeskcloud.chickenkiller.com"
}

resource "google_compute_global_address" "https" {
  project      = var.project_id
  name         = "helpdesk-dev-https-ip"
  address_type = "EXTERNAL"
  ip_version   = "IPV4"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_compute_ssl_policy" "https" {
  project         = var.project_id
  name            = "helpdesk-dev-https-tls"
  profile         = "MODERN"
  min_tls_version = "TLS_1_2"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_dns_authorization" "https" {
  project     = var.project_id
  name        = "helpdesk-dev-https-dns-auth"
  location    = "global"
  description = "DNS authorization for the owner-selected HelpDesk Dev hostname"
  domain      = local.legacy_hostname

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate" "https" {
  project     = var.project_id
  name        = "helpdesk-dev-https-certificate"
  location    = "global"
  description = "Google-managed HTTPS certificate for the HelpDesk Dev hostname"

  managed {
    domains = [local.legacy_hostname]
    dns_authorizations = [
      google_certificate_manager_dns_authorization.https.id
    ]
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate_map" "https" {
  project     = var.project_id
  name        = "helpdesk-dev-https-map"
  description = "Certificate map for the HelpDesk Dev HTTPS Gateway"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate_map_entry" "https" {
  project      = var.project_id
  name         = "helpdesk-dev-https-host"
  map          = google_certificate_manager_certificate_map.https.name
  hostname     = local.legacy_hostname
  certificates = [google_certificate_manager_certificate.https.id]
  description  = "Exact owner-selected HelpDesk Dev hostname"

  lifecycle {
    prevent_destroy = true
  }
}

# Active hostname resources for helpdeskcloud.dynv6.net. Keep the legacy resources above intact.
resource "google_certificate_manager_dns_authorization" "dynv6" {
  project     = var.project_id
  name        = "helpdesk-dev-https-dynv6-dns-auth"
  location    = "global"
  description = "DNS authorization for the HelpDesk Dev dynv6 hostname"
  domain      = var.hostname

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate" "dynv6" {
  project     = var.project_id
  name        = "helpdesk-dev-https-dynv6-certificate"
  location    = "global"
  description = "Google-managed HTTPS certificate for the HelpDesk Dev dynv6 hostname"

  managed {
    domains = [var.hostname]
    dns_authorizations = [
      google_certificate_manager_dns_authorization.dynv6.id
    ]
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate_map_entry" "dynv6" {
  project      = var.project_id
  name         = "helpdesk-dev-https-dynv6-host"
  map          = google_certificate_manager_certificate_map.https.name
  hostname     = var.hostname
  certificates = [google_certificate_manager_certificate.dynv6.id]
  description  = "Exact dynv6 hostname for the HelpDesk Dev HTTPS frontend"

  lifecycle {
    prevent_destroy = true
  }
}
