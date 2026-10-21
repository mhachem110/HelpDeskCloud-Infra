import copy
import unittest

from dev_https_verify_foundation import render_report, verify_foundation


PROJECT_ID = "helpdeskcloud-capstone-511905"
PROJECT_NUMBER = "260283083469"
HOSTNAME = "helpdeskcloud.dynv6.net"
LEGACY_HOSTNAME = "helpdeskcloud.chickenkiller.com"
ADDRESS_SELF_LINK = (
    "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/"
    "global/addresses/helpdesk-dev-https-ip"
)
LEGACY_DNS_AUTH_ID = (
    "projects/helpdeskcloud-capstone-511905/locations/global/"
    "dnsAuthorizations/helpdesk-dev-https-dns-auth"
)
LEGACY_CERTIFICATE_ID = (
    "projects/helpdeskcloud-capstone-511905/locations/global/"
    "certificates/helpdesk-dev-https-certificate"
)
LEGACY_CERTIFICATE_NUMBER_ID = (
    "projects/260283083469/locations/global/certificates/helpdesk-dev-https-certificate"
)
DNS_AUTH_ID = (
    "projects/helpdeskcloud-capstone-511905/locations/global/"
    "dnsAuthorizations/helpdesk-dev-https-dynv6-dns-auth"
)
CERTIFICATE_ID = (
    "projects/helpdeskcloud-capstone-511905/locations/global/"
    "certificates/helpdesk-dev-https-dynv6-certificate"
)
CERTIFICATE_NUMBER_ID = (
    "projects/260283083469/locations/global/certificates/helpdesk-dev-https-dynv6-certificate"
)
MAP_ID = (
    "projects/helpdeskcloud-capstone-511905/locations/global/"
    "certificateMaps/helpdesk-dev-https-map"
)
LEGACY_ENTRY_ID = f"{MAP_ID}/certificateMapEntries/helpdesk-dev-https-host"
ENTRY_ID = f"{MAP_ID}/certificateMapEntries/helpdesk-dev-https-dynv6-host"
RECORD = {
    "data": "new-dynv6-test-target.3.authorize.certificatemanager.goog.",
    "name": "_acme-challenge.helpdeskcloud.dynv6.net.",
    "type": "CNAME",
}
LEGACY_RECORD = {
    "data": "b0726ea6-edc2-409e-a0ad-97136e1bb253.3.authorize.certificatemanager.goog.",
    "name": "_acme-challenge.helpdeskcloud.chickenkiller.com.",
    "type": "CNAME",
}


def state_resource(resource_type, name, resource_id):
    return {
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "instances": [{"attributes": {"id": resource_id}}],
    }


def live_documents():
    return {
        "project": {"projectId": PROJECT_ID, "projectNumber": PROJECT_NUMBER},
        "address": {
            "name": "helpdesk-dev-https-ip",
            "address": "34.8.56.208",
            "addressType": "EXTERNAL",
            "status": "RESERVED",
            "networkTier": "PREMIUM",
            "selfLink": ADDRESS_SELF_LINK,
        },
        "ssl_policy": {
            "name": "helpdesk-dev-https-tls",
            "profile": "MODERN",
            "minTlsVersion": "TLS_1_2",
            "selfLink": (
                "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/"
                "global/sslPolicies/helpdesk-dev-https-tls"
            ),
        },
        "legacy_dns_authorization": {
            "name": LEGACY_DNS_AUTH_ID,
            "domain": LEGACY_HOSTNAME,
            "dnsResourceRecord": copy.deepcopy(LEGACY_RECORD),
        },
        "legacy_certificate": {
            "name": LEGACY_CERTIFICATE_ID,
            "managed": {
                "domains": [LEGACY_HOSTNAME],
                "dnsAuthorizations": [
                    "projects/260283083469/locations/global/dnsAuthorizations/helpdesk-dev-https-dns-auth"
                ],
                "state": "PROVISIONING",
            },
        },
        "legacy_map_entry": {
            "name": LEGACY_ENTRY_ID,
            "hostname": LEGACY_HOSTNAME,
            "certificates": [LEGACY_CERTIFICATE_NUMBER_ID],
        },
        "dns_authorization": {
            "name": DNS_AUTH_ID,
            "domain": HOSTNAME,
            "dnsResourceRecord": copy.deepcopy(RECORD),
        },
        "certificate": {
            "name": CERTIFICATE_ID,
            "managed": {
                "domains": [HOSTNAME],
                "dnsAuthorizations": [
                    "projects/260283083469/locations/global/dnsAuthorizations/helpdesk-dev-https-dynv6-dns-auth"
                ],
                "state": "PROVISIONING",
                "authorizationAttemptInfo": [
                    {"domain": HOSTNAME, "state": "AUTHORIZING"}
                ],
            },
        },
        "certificate_map": {"name": MAP_ID},
        "map_entry": {
            "name": ENTRY_ID,
            "hostname": HOSTNAME,
            "certificates": [CERTIFICATE_NUMBER_ID],
        },
        "terraform_state": {
            "serial": 6,
            "resources": [
                state_resource("google_compute_global_address", "https",
                               "projects/helpdeskcloud-capstone-511905/global/addresses/helpdesk-dev-https-ip"),
                state_resource("google_compute_ssl_policy", "https",
                               "projects/helpdeskcloud-capstone-511905/global/sslPolicies/helpdesk-dev-https-tls"),
                state_resource("google_certificate_manager_dns_authorization", "https", LEGACY_DNS_AUTH_ID),
                state_resource("google_certificate_manager_certificate", "https", LEGACY_CERTIFICATE_ID),
                state_resource("google_certificate_manager_certificate_map", "https", MAP_ID),
                state_resource("google_certificate_manager_certificate_map_entry", "https", LEGACY_ENTRY_ID),
                state_resource("google_certificate_manager_dns_authorization", "dynv6", DNS_AUTH_ID),
                state_resource("google_certificate_manager_certificate", "dynv6", CERTIFICATE_ID),
                state_resource("google_certificate_manager_certificate_map_entry", "dynv6", ENTRY_ID),
            ],
            "outputs": {
                "https_static_ip_address": {"value": "34.8.56.208"},
                "https_static_ip_name": {"value": "helpdesk-dev-https-ip"},
                "https_certificate_map_name": {"value": "helpdesk-dev-https-map"},
                "https_ssl_policy_name": {"value": "helpdesk-dev-https-tls"},
                "dns_authorization_record": {"value": copy.deepcopy(LEGACY_RECORD)},
                "dynv6_dns_authorization_record": {"value": copy.deepcopy(RECORD)},
            },
        },
    }


class DevHttpsFoundationVerificationTests(unittest.TestCase):
    def verify(self, documents):
        return verify_foundation(documents, PROJECT_ID, HOSTNAME)

    def test_accepts_preserved_legacy_state_and_pending_dynv6_certificate(self):
        result, cert_state, auth_state, record, address = self.verify(live_documents())
        self.assertEqual(result.failed, [])
        self.assertTrue(any("ipVersion field" in line for line in result.passed))
        self.assertEqual(cert_state, "PROVISIONING")
        self.assertEqual(auth_state, "AUTHORIZING")
        self.assertEqual(record, RECORD)
        self.assertEqual(address, "34.8.56.208")
        report = render_report(result, cert_state, auth_state, record, address)
        self.assertIn("Verification status: PASS", report)
        self.assertIn("Domain: helpdeskcloud.dynv6.net", report)
        self.assertIn("Full record name: _acme-challenge.helpdeskcloud.dynv6.net.", report)
        self.assertIn(RECORD["data"], report)

    def test_rejects_non_ipv4_or_changed_reserved_address(self):
        documents = live_documents()
        documents["address"]["address"] = "2001:db8::1"
        result, *_ = self.verify(documents)
        self.assertTrue(any("Reserved external IPv4 address" in line for line in result.failed))
        documents = live_documents()
        documents["address"]["address"] = "34.8.56.209"
        result, *_ = self.verify(documents)
        self.assertTrue(any("Reserved external IPv4 address" in line for line in result.failed))

    def test_rejects_explicit_ipv6_even_if_address_is_ipv4(self):
        documents = live_documents()
        documents["address"]["ipVersion"] = "IPV6"
        result, *_ = self.verify(documents)
        self.assertTrue(any("Reserved external IPv4 address" in line for line in result.failed))

    def test_rejects_wrong_project_or_location_in_certificate_manager_names(self):
        documents = live_documents()
        documents["certificate_map"]["name"] = (
            "projects/another-project/locations/us-east1/certificateMaps/helpdesk-dev-https-map"
        )
        result, *_ = self.verify(documents)
        self.assertTrue(any("Certificate map identity" in line for line in result.failed))

    def test_rejects_wrong_dns_authorization_reference_in_dynv6_certificate(self):
        documents = live_documents()
        documents["certificate"]["managed"]["dnsAuthorizations"] = [
            "projects/999999/locations/global/dnsAuthorizations/helpdesk-dev-schema-001"
        ]
        result, *_ = self.verify(documents)
        self.assertTrue(any("New dynv6 managed certificate" in line for line in result.failed))

    def test_rejects_wrong_certificate_reference_in_dynv6_map_entry(self):
        documents = live_documents()
        documents["map_entry"]["certificates"] = [
            "projects/260283083469/locations/global/certificates/unrelated"
        ]
        result, *_ = self.verify(documents)
        self.assertTrue(any("New dynv6 Certificate Manager map entry" in line for line in result.failed))

    def test_rejects_wrong_cname_or_state_output(self):
        documents = live_documents()
        documents["dns_authorization"]["dnsResourceRecord"]["data"] = "wrong.example.net."
        result, *_ = self.verify(documents)
        self.assertTrue(any("New dynv6 Certificate Manager DNS authorization" in line for line in result.failed))
        documents = live_documents()
        documents["terraform_state"]["outputs"]["https_static_ip_address"]["value"] = "34.8.56.209"
        result, *_ = self.verify(documents)
        self.assertTrue(any("Terraform outputs" in line for line in result.failed))

    def test_rejects_reuse_of_old_cname_target(self):
        documents = live_documents()
        documents["dns_authorization"]["dnsResourceRecord"]["data"] = LEGACY_RECORD["data"]
        documents["terraform_state"]["outputs"]["dynv6_dns_authorization_record"]["value"]["data"] = LEGACY_RECORD["data"]
        result, *_ = self.verify(documents)
        self.assertTrue(any("New dynv6 Certificate Manager DNS authorization" in line
                            for line in result.failed))

    def test_rejects_state_missing_resources_or_unexpected_resources(self):
        documents = live_documents()
        documents["terraform_state"]["resources"].pop()
        result, *_ = self.verify(documents)
        self.assertTrue(any("Terraform state" in line for line in result.failed))
        documents = live_documents()
        documents["terraform_state"]["resources"].append(
            state_resource("google_compute_global_forwarding_rule", "unexpected", "unexpected")
        )
        result, *_ = self.verify(documents)
        self.assertTrue(any("Terraform state" in line for line in result.failed))


if __name__ == "__main__":
    unittest.main()