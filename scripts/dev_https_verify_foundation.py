#!/usr/bin/env python3
"""Verify live Dev HTTPS foundation resources against their exact Terraform state."""

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path


PROJECT_NUMBER_PATTERN = re.compile(r"^[0-9]+$")
EXPECTED_ADDRESS = "34.8.56.208"
LEGACY_HOSTNAME = "helpdeskcloud.chickenkiller.com"
DYNV6_HOSTNAME = "helpdeskcloud.dynv6.net"


class Verification:
    def __init__(self):
        self.passed = []
        self.failed = []

    def check(self, label, condition, expected, actual):
        if condition:
            self.passed.append(f"[PASS] {label}: {actual}")
        else:
            self.failed.append(f"[FAIL] {label}: expected {expected!r}; actual {actual!r}")


def full_name(project, collection, name):
    return f"projects/{project}/locations/global/{collection}/{name}"


def state_resources(state):
    """Return managed resource addresses and IDs from a Terraform state pull."""
    found = {}
    for resource in state.get("resources", []):
        if resource.get("mode", "managed") != "managed":
            continue
        module = resource.get("module")
        prefix = f"{module}." if module else ""
        address = f"{prefix}{resource.get('type')}.{resource.get('name')}"
        ids = [
            instance.get("attributes", {}).get("id")
            for instance in resource.get("instances", [])
        ]
        found[address] = ids
    return found


def output_value(outputs, name):
    item = outputs.get(name)
    return item.get("value") if isinstance(item, dict) and "value" in item else item


def verify_foundation(documents, project_id, hostname, expected_ip=EXPECTED_ADDRESS):
    """Validate retained legacy resources and the new dynv6 certificate foundation."""
    result = Verification()
    project = documents["project"]
    address = documents["address"]
    ssl = documents["ssl_policy"]
    legacy_authorization = documents["legacy_dns_authorization"]
    legacy_certificate = documents["legacy_certificate"]
    legacy_map_entry = documents["legacy_map_entry"]
    authorization = documents["dns_authorization"]
    certificate = documents["certificate"]
    certificate_map = documents["certificate_map"]
    map_entry = documents["map_entry"]
    state = documents["terraform_state"]
    state_outputs = state.get("outputs", {})

    result.check("Reviewed dynv6 hostname", hostname == DYNV6_HOSTNAME, DYNV6_HOSTNAME, hostname)
    project_number = str(project.get("projectNumber", ""))
    result.check(
        "GCP project identity",
        project.get("projectId") == project_id and PROJECT_NUMBER_PATTERN.fullmatch(project_number) is not None,
        {"projectId": project_id, "projectNumber": "numeric project number"},
        {"projectId": project.get("projectId"), "projectNumber": project_number},
    )
    if not PROJECT_NUMBER_PATTERN.fullmatch(project_number):
        project_number = "<invalid-project-number>"

    address_self_link = (
        f"https://www.googleapis.com/compute/v1/projects/{project_id}/global/addresses/"
        "helpdesk-dev-https-ip"
    )
    actual_ip = address.get("address")
    try:
        parsed_ip = ipaddress.ip_address(actual_ip)
        is_ipv4 = parsed_ip.version == 4
    except (ValueError, TypeError):
        is_ipv4 = False
    result.check(
        "Reserved external IPv4 address",
        address.get("name") == "helpdesk-dev-https-ip"
        and address.get("selfLink") == address_self_link
        and address.get("addressType") == "EXTERNAL"
        and address.get("status") == "RESERVED"
        and is_ipv4 and actual_ip == expected_ip
        and address.get("ipVersion") in (None, "", "IPV4"),
        {"project": project_id, "name": "helpdesk-dev-https-ip", "address": expected_ip,
         "addressType": "EXTERNAL", "IPv4": True, "status": "RESERVED"},
        {"name": address.get("name"), "address": actual_ip, "addressType": address.get("addressType"),
         "ipVersion": address.get("ipVersion", "<omitted by API>"), "status": address.get("status"),
         "selfLink": address.get("selfLink")},
    )
    if address.get("ipVersion") in (None, "") and is_ipv4:
        result.passed.append("[INFO] Compute API omitted its default ipVersion field; IPv4 was confirmed by parsing the reserved address.")

    ssl_self_link = (
        f"https://www.googleapis.com/compute/v1/projects/{project_id}/global/sslPolicies/"
        "helpdesk-dev-https-tls"
    )
    result.check(
        "HTTPS SSL policy",
        ssl.get("name") == "helpdesk-dev-https-tls" and ssl.get("selfLink") == ssl_self_link
        and ssl.get("profile") == "MODERN" and ssl.get("minTlsVersion") == "TLS_1_2",
        {"project": project_id, "name": "helpdesk-dev-https-tls", "profile": "MODERN", "minTlsVersion": "TLS_1_2"},
        {"name": ssl.get("name"), "selfLink": ssl.get("selfLink"), "profile": ssl.get("profile"),
         "minTlsVersion": ssl.get("minTlsVersion")},
    )

    legacy_dns_name = full_name(project_id, "dnsAuthorizations", "helpdesk-dev-https-dns-auth")
    legacy_record = legacy_authorization.get("dnsResourceRecord")
    expected_legacy_record = output_value(state_outputs, "dns_authorization_record")
    result.check(
        "Retained legacy DNS authorization",
        legacy_authorization.get("name") == legacy_dns_name
        and legacy_authorization.get("domain") == LEGACY_HOSTNAME
        and isinstance(legacy_record, dict) and legacy_record.get("type") == "CNAME"
        and legacy_record.get("name") == f"_acme-challenge.{LEGACY_HOSTNAME}."
        and legacy_record == expected_legacy_record,
        {"name": legacy_dns_name, "domain": LEGACY_HOSTNAME, "record": expected_legacy_record},
        {"name": legacy_authorization.get("name"), "domain": legacy_authorization.get("domain"),
         "record": legacy_record},
    )

    dns_name = full_name(project_id, "dnsAuthorizations", "helpdesk-dev-https-dynv6-dns-auth")
    expected_record = output_value(state_outputs, "dynv6_dns_authorization_record")
    actual_record = authorization.get("dnsResourceRecord")
    result.check(
        "New dynv6 Certificate Manager DNS authorization",
        authorization.get("name") == dns_name and authorization.get("domain") == hostname
        and isinstance(actual_record, dict) and actual_record.get("type") == "CNAME"
        and actual_record.get("name") == f"_acme-challenge.{hostname}."
        and isinstance(actual_record.get("data"), str)
        and actual_record.get("data", "").endswith(".authorize.certificatemanager.goog.")
        and actual_record.get("data") != (legacy_record or {}).get("data")
        and actual_record == expected_record,
        {"name": dns_name, "domain": hostname,
         "record": {"type": "CNAME", "name": f"_acme-challenge.{hostname}.",
                    "data": "new target matching dynv6 Terraform state output"}},
        {"name": authorization.get("name"), "domain": authorization.get("domain"),
         "record": actual_record},
    )

    legacy_certificate_name = full_name(project_id, "certificates", "helpdesk-dev-https-certificate")
    legacy_dns_reference = full_name(project_number, "dnsAuthorizations", "helpdesk-dev-https-dns-auth")
    legacy_managed = legacy_certificate.get("managed") if isinstance(legacy_certificate.get("managed"), dict) else {}
    result.check(
        "Retained legacy managed certificate",
        legacy_certificate.get("name") == legacy_certificate_name
        and legacy_managed.get("domains") == [LEGACY_HOSTNAME]
        and legacy_managed.get("dnsAuthorizations") == [legacy_dns_reference],
        {"name": legacy_certificate_name, "domains": [LEGACY_HOSTNAME],
         "dnsAuthorizations": [legacy_dns_reference]},
        {"name": legacy_certificate.get("name"), "domains": legacy_managed.get("domains"),
         "dnsAuthorizations": legacy_managed.get("dnsAuthorizations")},
    )

    certificate_name = full_name(project_id, "certificates", "helpdesk-dev-https-dynv6-certificate")
    dns_reference = full_name(project_number, "dnsAuthorizations", "helpdesk-dev-https-dynv6-dns-auth")
    managed = certificate.get("managed") if isinstance(certificate.get("managed"), dict) else {}
    result.check(
        "New dynv6 managed certificate and DNS reference",
        certificate.get("name") == certificate_name
        and managed.get("domains") == [hostname]
        and managed.get("dnsAuthorizations") == [dns_reference],
        {"name": certificate_name, "domains": [hostname], "dnsAuthorizations": [dns_reference]},
        {"name": certificate.get("name"), "domains": managed.get("domains"),
         "dnsAuthorizations": managed.get("dnsAuthorizations")},
    )
    certificate_state = str(managed.get("state") or certificate.get("state") or "UNKNOWN")
    result.check("Managed certificate status is reported", certificate_state != "UNKNOWN",
                 "a live Certificate Manager state", certificate_state)
    attempts = managed.get("authorizationAttemptInfo") or []
    attempt_state = next((item.get("state") for item in attempts
                          if isinstance(item, dict) and item.get("domain") == hostname), "not reported")
    result.passed.append(f"[INFO] Certificate status: {certificate_state}; DNS authorization attempt: {attempt_state}.")

    map_name = full_name(project_id, "certificateMaps", "helpdesk-dev-https-map")
    result.check("Certificate map identity", certificate_map.get("name") == map_name, map_name,
                 certificate_map.get("name"))
    legacy_entry_name = f"{map_name}/certificateMapEntries/helpdesk-dev-https-host"
    legacy_certificate_reference = full_name(project_number, "certificates", "helpdesk-dev-https-certificate")
    result.check(
        "Retained legacy Certificate Manager map entry",
        legacy_map_entry.get("name") == legacy_entry_name
        and legacy_map_entry.get("hostname") == LEGACY_HOSTNAME
        and legacy_map_entry.get("certificates") == [legacy_certificate_reference],
        {"name": legacy_entry_name, "hostname": LEGACY_HOSTNAME,
         "certificates": [legacy_certificate_reference]},
        {"name": legacy_map_entry.get("name"), "hostname": legacy_map_entry.get("hostname"),
         "certificates": legacy_map_entry.get("certificates")},
    )
    entry_name = f"{map_name}/certificateMapEntries/helpdesk-dev-https-dynv6-host"
    certificate_reference = full_name(project_number, "certificates", "helpdesk-dev-https-dynv6-certificate")
    result.check(
        "New dynv6 Certificate Manager map entry",
        map_entry.get("name") == entry_name and map_entry.get("hostname") == hostname
        and map_entry.get("certificates") == [certificate_reference],
        {"name": entry_name, "hostname": hostname, "certificates": [certificate_reference]},
        {"name": map_entry.get("name"), "hostname": map_entry.get("hostname"),
         "certificates": map_entry.get("certificates")},
    )

    expected_ids = {
        "google_compute_global_address.https": f"projects/{project_id}/global/addresses/helpdesk-dev-https-ip",
        "google_compute_ssl_policy.https": f"projects/{project_id}/global/sslPolicies/helpdesk-dev-https-tls",
        "google_certificate_manager_dns_authorization.https": legacy_dns_name,
        "google_certificate_manager_certificate.https": legacy_certificate_name,
        "google_certificate_manager_certificate_map.https": map_name,
        "google_certificate_manager_certificate_map_entry.https": legacy_entry_name,
        "google_certificate_manager_dns_authorization.dynv6": dns_name,
        "google_certificate_manager_certificate.dynv6": certificate_name,
        "google_certificate_manager_certificate_map_entry.dynv6": entry_name,
    }
    actual_ids = state_resources(state)
    state_matches = set(actual_ids) == set(expected_ids) and all(
        actual_ids.get(resource_address) == [resource_id]
        for resource_address, resource_id in expected_ids.items()
    )
    result.check("Terraform state contains exactly the nine expected HTTPS resources", state_matches,
                 {"addresses and IDs": expected_ids}, actual_ids)

    outputs_match = (
        output_value(state_outputs, "https_static_ip_address") == expected_ip
        and output_value(state_outputs, "https_static_ip_name") == "helpdesk-dev-https-ip"
        and output_value(state_outputs, "https_certificate_map_name") == "helpdesk-dev-https-map"
        and output_value(state_outputs, "https_ssl_policy_name") == "helpdesk-dev-https-tls"
        and expected_record == actual_record and expected_legacy_record == legacy_record
    )
    result.check(
        "Terraform outputs match live IP, map, SSL policy and both DNS authorizations",
        outputs_match,
        {"ip": expected_ip, "map": "helpdesk-dev-https-map", "sslPolicy": "helpdesk-dev-https-tls",
         "legacyDnsAuthorizationRecord": legacy_record, "dynv6DnsAuthorizationRecord": actual_record},
        {"ip": output_value(state_outputs, "https_static_ip_address"),
         "map": output_value(state_outputs, "https_certificate_map_name"),
         "sslPolicy": output_value(state_outputs, "https_ssl_policy_name"),
         "legacyDnsAuthorizationRecord": expected_legacy_record,
         "dynv6DnsAuthorizationRecord": expected_record},
    )
    report_record = actual_record if isinstance(actual_record, dict) else {}
    return result, certificate_state, attempt_state, report_record, actual_ip

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_report(result, certificate_state, attempt_state, record, address):
    status = "PASS" if not result.failed else "FAIL"
    lines = ["HTTPS Foundation Verification", "", f"Verification status: {status}", ""]
    lines.extend(result.passed)
    lines.extend(result.failed)
    if record:
        lines.extend(
            [
                "",
                f"Reserved IP: {address or 'unavailable'}",
                f"Certificate status: {certificate_state}",
                f"DNS authorization attempt: {attempt_state}",
                "Domain: helpdeskcloud.dynv6.net",
                "Record type: CNAME",
                f"Full record name: {record.get('name', 'unavailable')}",
                f"Data/Target: {record.get('data', 'unavailable')}",
                "Remaining DNS requirement: publish this exact CNAME in dynv6 and wait for Certificate Manager to report ACTIVE.",
                "Gateway: not activated by this verification.",
            ]
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-file", required=True)
    parser.add_argument("--address-file", required=True)
    parser.add_argument("--ssl-policy-file", required=True)
    parser.add_argument("--legacy-dns-authorization-file", required=True)
    parser.add_argument("--legacy-certificate-file", required=True)
    parser.add_argument("--legacy-map-entry-file", required=True)
    parser.add_argument("--dns-authorization-file", required=True)
    parser.add_argument("--certificate-file", required=True)
    parser.add_argument("--certificate-map-file", required=True)
    parser.add_argument("--map-entry-file", required=True)
    parser.add_argument("--terraform-state-file", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--expected-ip", default=EXPECTED_ADDRESS)
    parser.add_argument("--summary-file")
    args = parser.parse_args()

    try:
        documents = {
            "project": load_json(args.project_file),
            "address": load_json(args.address_file),
            "ssl_policy": load_json(args.ssl_policy_file),
            "legacy_dns_authorization": load_json(args.legacy_dns_authorization_file),
            "legacy_certificate": load_json(args.legacy_certificate_file),
            "legacy_map_entry": load_json(args.legacy_map_entry_file),
            "dns_authorization": load_json(args.dns_authorization_file),
            "certificate": load_json(args.certificate_file),
            "certificate_map": load_json(args.certificate_map_file),
            "map_entry": load_json(args.map_entry_file),
            "terraform_state": load_json(args.terraform_state_file),
        }
        result, certificate_state, attempt_state, record, address = verify_foundation(
            documents, args.project_id, args.hostname, args.expected_ip
        )
        report = render_report(result, certificate_state, attempt_state, record, address)
        print(report, end="")
        if args.summary_file:
            with Path(args.summary_file).open("a", encoding="utf-8") as summary:
                summary.write(report)
        return 1 if result.failed else 0
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, AttributeError) as error:
        print(f"HTTPS Foundation Verification\n\nVerification status: FAIL\n[FAIL] Could not read verification data: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
