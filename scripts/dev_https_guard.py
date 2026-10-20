"""Narrow plan and live-policy guard for the two opt-in HTTPS Terraform roots."""

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path


PROJECT = "helpdeskcloud-capstone-511905"
FOUNDATION = {
    "google_compute_global_address.https": "google_compute_global_address",
    "google_compute_ssl_policy.https": "google_compute_ssl_policy",
    "google_certificate_manager_dns_authorization.https": "google_certificate_manager_dns_authorization",
    "google_certificate_manager_certificate.https": "google_certificate_manager_certificate",
    "google_certificate_manager_certificate_map.https": "google_certificate_manager_certificate_map",
    "google_certificate_manager_certificate_map_entry.https": "google_certificate_manager_certificate_map_entry",
}
ACCESS = {
    "google_iap_web_backend_service_iam_member.helpdesk_user": "google_iap_web_backend_service_iam_member",
}
PROVIDER_READBACK_DRIFT = {
    "google_compute_global_address.https": ("google_compute_global_address", "labels", None, {}),
    "google_compute_ssl_policy.https": ("google_compute_ssl_policy", "custom_features", None, []),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def resource_values(plan, expected, mode="managed"):
    root = plan.get("planned_values", {}).get("root_module", {})
    resources = [item for item in root.get("resources", []) if item.get("mode", "managed") == mode]
    by_address = {item.get("address"): item for item in resources}
    require(len(by_address) == len(resources), "duplicate planned resource address")
    require(set(by_address) == set(expected), "planned resources differ from the exact HTTPS allowlist")
    for address, resource_type in expected.items():
        require(by_address[address].get("type") == resource_type, "resource type changed at an approved address")
    return by_address


def check_actions(plan, expected):
    changes = plan.get("resource_changes", [])
    managed = [item for item in changes if item.get("mode", "managed") == "managed"]
    by_address = {item.get("address"): item for item in managed}
    require(len(by_address) == len(managed), "duplicate resource change address")
    require(set(by_address) == set(expected), "resource changes differ from the exact HTTPS allowlist")
    for address, change in by_address.items():
        require(change.get("type") == expected[address], "resource type changed in the saved plan")
        actions = change.get("change", {}).get("actions", [])
        require(actions in (["create"], ["no-op"]),
                "only an exact create or no-op is allowed; updates, deletes and replacements require review")
    check_provider_readback_drift(plan.get("resource_drift", []), expected)
    prior = plan.get("prior_state", {}).get("values", {}).get("root_module", {}).get("resources", [])
    require(all(item.get("address") in expected for item in prior),
            "prior state contains an unexpected address")
    return by_address


def check_provider_readback_drift(drift, expected):
    """Allow only the two confirmed provider null-to-empty refresh differences.

    Terraform 1.16.2 with google provider 7.8.0 reports labels/custom_features as
    null in the saved state and empty collection values after refresh. The normal
    resource-change guard still requires these retained resources to be no-ops.
    """
    seen = set()
    missing = object()
    for item in drift:
        address = item.get("address")
        allowed = PROVIDER_READBACK_DRIFT.get(address)
        require(address in expected and allowed is not None,
                "unexpected prior-state drift exists in the HTTPS root")
        resource_type, field, before_value, after_value = allowed
        require(item.get("mode", "managed") == "managed" and item.get("type") == resource_type,
                "provider readback drift is on an unexpected resource type")
        change = item.get("change", {})
        require(change.get("actions") == ["update"],
                "provider readback drift must be a refresh-only update")
        before = change.get("before")
        after = change.get("after")
        require(isinstance(before, dict) and isinstance(after, dict),
                "provider readback drift is missing its before/after values")
        changed_fields = {
            key for key in set(before) | set(after)
            if before.get(key, missing) != after.get(key, missing)
        }
        require(changed_fields == {field} and before.get(field, missing) == before_value and
                after.get(field, missing) == after_value,
                "provider readback drift differs from the exact confirmed null-to-empty field")
        require(address not in seen, "duplicate provider readback drift resource")
        seen.add(address)


def configuration_references(plan, address, expression_path):
    expressions = configuration_expressions(plan, address)
    expression = expressions
    for path_part in expression_path:
        if isinstance(path_part, int):
            if not isinstance(expression, list) or path_part >= len(expression):
                return []
            expression = expression[path_part]
        else:
            if not isinstance(expression, dict):
                return []
            expression = expression.get(path_part, {})
    if isinstance(expression, dict):
        return expression.get("references", [])
    return []


def configuration_expressions(plan, address):
    module = plan.get("configuration", {}).get("root_module", {})
    resources = {}

    def collect(current):
        for resource in current.get("resources", []):
            resources[resource.get("address")] = resource.get("expressions", {})
        for child in current.get("module_calls", {}).values():
            collect(child.get("module", {}))

    collect(module)
    return resources.get(address, {})


def check_foundation(plan, hostname):
    values = resource_values(plan, FOUNDATION)
    changes = check_actions(plan, FOUNDATION)
    address = changes["google_compute_global_address.https"].get("change", {}).get("after") or values[
        "google_compute_global_address.https"]["values"]
    # The provider returns an empty ip_version for a global IPv4 reservation.
    # Check the configuration source as well as the provider readback so that
    # accepting this omission cannot permit an IPv6 or internal address.
    address_expression = configuration_expressions(plan, "google_compute_global_address.https")
    address_type_expression = address_expression.get("address_type")
    ip_version_expression = address_expression.get("ip_version")
    require(isinstance(address_type_expression, dict) and
            address_type_expression.get("constant_value") == "EXTERNAL" and
            isinstance(ip_version_expression, dict) and ip_version_expression.get("constant_value") == "IPV4",
            "global address configuration must explicitly request external IPv4")
    live_address = address.get("address")
    if live_address:
        try:
            is_ipv4 = ipaddress.ip_address(live_address).version == 4
        except ValueError:
            is_ipv4 = False
        require(is_ipv4, "existing global reservation must remain IPv4")
    require(address.get("project") == PROJECT and address.get("name") == "helpdesk-dev-https-ip" and
            address.get("address_type") in (None, "", "EXTERNAL") and
            address.get("ip_version") in (None, "", "IPV4"),
            "global address must use the exact external IPv4 reservation or its documented provider defaults")
    require("network_tier" not in address, "global address must use Google's global external tier")

    ssl = changes["google_compute_ssl_policy.https"].get("change", {}).get("after") or values[
        "google_compute_ssl_policy.https"]["values"]
    require(ssl.get("project") == PROJECT and ssl.get("name") == "helpdesk-dev-https-tls" and
            ssl.get("profile") == "MODERN" and ssl.get("min_tls_version") == "TLS_1_2",
            "TLS policy must require TLS 1.2 and the exact MODERN profile")

    dns = changes["google_certificate_manager_dns_authorization.https"].get("change", {}).get("after") or values[
        "google_certificate_manager_dns_authorization.https"]["values"]
    require(dns.get("project") == PROJECT and dns.get("name") == "helpdesk-dev-https-dns-auth" and
            dns.get("location") == "global" and dns.get("domain") == hostname,
            "DNS authorization must target only the supplied hostname")

    certificate = changes["google_certificate_manager_certificate.https"].get("change", {}).get("after") or values[
        "google_certificate_manager_certificate.https"]["values"]
    managed = certificate.get("managed") or []
    require(certificate.get("project") == PROJECT and certificate.get("name") ==
            "helpdesk-dev-https-certificate" and certificate.get("location") == "global" and
            len(managed) == 1 and managed[0].get("domains") == [hostname],
            "managed certificate must cover only the supplied hostname")
    require("google_certificate_manager_dns_authorization.https.id" in configuration_references(
        plan, "google_certificate_manager_certificate.https", ["managed", 0, "dns_authorizations"]),
        "managed certificate must reference only the reviewed DNS authorization")

    cert_map = changes["google_certificate_manager_certificate_map.https"].get("change", {}).get("after") or values[
        "google_certificate_manager_certificate_map.https"]["values"]
    require(cert_map.get("project") == PROJECT and cert_map.get("name") == "helpdesk-dev-https-map",
            "Certificate Manager map is outside the reviewed scope")

    entry = changes["google_certificate_manager_certificate_map_entry.https"].get("change", {}).get("after") or values[
        "google_certificate_manager_certificate_map_entry.https"]["values"]
    require(entry.get("project") == PROJECT and entry.get("name") == "helpdesk-dev-https-host" and
            entry.get("map") == "helpdesk-dev-https-map" and entry.get("hostname") == hostname,
            "Certificate Manager map entry must match only the supplied hostname")
    certs = entry.get("certificates") or []
    if len(certs) == 1 and isinstance(certs[0], str):
        require("helpdesk-dev-https-certificate" in certs[0],
                "Certificate Manager map entry must reference the reviewed managed certificate")
    else:
        require("google_certificate_manager_certificate.https.id" in configuration_references(
            plan, "google_certificate_manager_certificate_map_entry.https", ["certificates"]),
            "Certificate Manager map entry must reference the reviewed managed certificate")


def check_access(plan, backend_service_name, allowed_email):
    require(re.fullmatch(r"gkegw-[a-z0-9-]{1,50}", backend_service_name) is not None,
            "backend name must be one generated global GKE Gateway backend")
    require(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", allowed_email) is not None,
            "access principal must be one email address")
    values = resource_values(plan, ACCESS)
    changes = check_actions(plan, ACCESS)
    resource = changes["google_iap_web_backend_service_iam_member.helpdesk_user"].get("change", {}).get("after") or values[
        "google_iap_web_backend_service_iam_member.helpdesk_user"]["values"]
    require(resource.get("project") == PROJECT and resource.get("web_backend_service") == backend_service_name and
            resource.get("role") == "roles/iap.httpsResourceAccessor" and
            resource.get("member") == f"user:{allowed_email}",
            "IAP grant must be one exact user on the supplied backend service")
    require(resource.get("member") not in {"allUsers", "allAuthenticatedUsers"},
            "public IAP principals are forbidden")


def verify_access_policy(policy, allowed_email):
    bindings = policy.get("bindings", [])
    accessor_members = [member for binding in bindings
                        if binding.get("role") == "roles/iap.httpsResourceAccessor"
                        for member in binding.get("members", [])]
    require(accessor_members == [f"user:{allowed_email}"],
            "live IAP backend policy must contain exactly the configured user grant")


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    foundation = commands.add_parser("check-foundation")
    foundation.add_argument("plan_json")
    foundation.add_argument("--hostname", required=True)
    access = commands.add_parser("check-access")
    access.add_argument("plan_json")
    access.add_argument("--backend-service-name", required=True)
    access.add_argument("--allowed-email", required=True)
    verify = commands.add_parser("verify-access-policy")
    verify.add_argument("policy_json")
    verify.add_argument("--allowed-email", required=True)
    args = parser.parse_args()
    if args.command == "check-foundation":
        check_foundation(read_json(args.plan_json), args.hostname)
        print("HTTPS foundation plan contains only the exact retained IP, TLS and certificate resources.")
    elif args.command == "check-access":
        check_access(read_json(args.plan_json), args.backend_service_name, args.allowed_email)
        print("IAP access plan contains only the exact single-user backend grant.")
    else:
        verify_access_policy(read_json(args.policy_json), args.allowed_email)
        print("Live IAP backend policy contains exactly the configured user access grant.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as error:
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(f"Dev HTTPS guard stopped: {message}", file=sys.stderr)
        sys.exit(1)
