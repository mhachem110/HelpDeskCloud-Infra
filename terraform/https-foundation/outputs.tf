output "https_static_ip_name" {
  description = "Retained global address name to reference from the GKE Gateway."
  value       = google_compute_global_address.https.name
}

output "https_static_ip_address" {
  description = "Retained global IPv4 address; publish the hostname A record only after IAP and route checks."
  value       = google_compute_global_address.https.address
}

output "https_certificate_map_name" {
  description = "Certificate Manager map name to reference from GKE Gateway."
  value       = google_certificate_manager_certificate_map.https.name
}

output "https_ssl_policy_name" {
  description = "TLS 1.2+ SSL policy name to reference from GCPGatewayPolicy."
  value       = google_compute_ssl_policy.https.name
}

output "dns_authorization_record" {
  description = "CNAME record to publish through the user's chosen DNS provider. This root never edits public DNS."
  value = {
    name = google_certificate_manager_dns_authorization.https.dns_resource_record[0].name
    type = google_certificate_manager_dns_authorization.https.dns_resource_record[0].type
    data = google_certificate_manager_dns_authorization.https.dns_resource_record[0].data
  }
}
