resource "google_project_service" "certificate_manager" {
  project            = var.project_id
  service            = "certificatemanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "iap" {
  project            = var.project_id
  service            = "iap.googleapis.com"
  disable_on_destroy = false
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
  domain      = var.hostname

  depends_on = [google_project_service.certificate_manager]

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
    domains = [var.hostname]
    dns_authorizations = [
      google_certificate_manager_dns_authorization.https.id
    ]
  }

  depends_on = [google_project_service.certificate_manager]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate_map" "https" {
  project     = var.project_id
  name        = "helpdesk-dev-https-map"
  description = "Certificate map for the HelpDesk Dev HTTPS Gateway"

  depends_on = [google_project_service.certificate_manager]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_certificate_manager_certificate_map_entry" "https" {
  project      = var.project_id
  name         = "helpdesk-dev-https-host"
  map          = google_certificate_manager_certificate_map.https.name
  hostname     = var.hostname
  certificates = [google_certificate_manager_certificate.https.id]
  description  = "Exact owner-selected HelpDesk Dev hostname"

  lifecycle {
    prevent_destroy = true
  }
}
