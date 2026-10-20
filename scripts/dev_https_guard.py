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
CERTIFICATE_READBACK_ADDRESS = "google_certificate_manager_certificate.https"
CERTIFICATE_READBACK_TYPE = "google_certificate_manager_certificate"
CERTIFICATE_STATUS_FIELDS = {
    "managed[0].authorization_attempt_info[0].state": {
        "STATE_UNSPECIFIED", "AUTHORIZING", "AUTHORIZED", "FAILED",
    },
    "managed[0].authorization_attempt_info[0].failure_reason": {
        "FAILURE_REASON_UNSPECIFIED", "CONFIG", "CAA", "RATE_LIMITED",
    },
}
CERTIFICATE_DETAILS_FIELD = "managed[0].authorization_attempt_info[0].details"
CERTIFICATE_STATUS_KEYS = {"domain", "state", "failure_reason", "details"}
_MISSING = object()
SENSITIVE_DRIFT_PATH = re.compile(
    r"(?:secret|password|token|credential|private|oauth|email|member|authorization|signature|key|description)",
    re.IGNORECASE,
)


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


def check_actions(plan, expected, certificate_hostname=None):
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
    check_provider_readback_drift(plan.get("resource_drift", []), expected, certificate_hostname)
    prior = plan.get("prior_state", {}).get("values", {}).get("root_module", {}).get("resources", [])
    require(all(item.get("address") in expected for item in prior),
            "prior state contains an unexpected address")
    return by_address


def check_provider_readback_drift(drift, expected, certificate_hostname=None):
    """Allow only confirmed provider readback differences that cannot change config.

    Terraform 1.16.2 with google provider 7.8.0 reports labels/custom_features as
    null in the saved state and empty collection values after refresh. The normal
    resource-change guard still requires these retained resources to be no-ops.
    Certificate Manager also refreshes its output-only authorization diagnostics
    as DNS validation progresses; only the exact fields and hostname are allowed.
    """
    seen = set()
    missing = object()
    for item in drift:
        address = item.get("address")
        if address == CERTIFICATE_READBACK_ADDRESS:
            require(address in expected and expected[address] == CERTIFICATE_READBACK_TYPE,
                    f"unexpected prior-state drift exists in the HTTPS root: {describe_drift(item)}")
            require(certificate_hostname is not None,
                    "certificate status drift requires the exact reviewed hostname")
            check_certificate_status_readback_drift(item, certificate_hostname)
            require(address not in seen, "duplicate provider readback drift resource")
            seen.add(address)
            continue
        allowed = PROVIDER_READBACK_DRIFT.get(address)
        require(address in expected and allowed is not None,
                f"unexpected prior-state drift exists in the HTTPS root: {describe_drift(item)}")
        resource_type, field, before_value, after_value = allowed
        require(item.get("mode", "managed") == "managed" and item.get("type") == resource_type,
                f"provider readback drift is on an unexpected resource type: {describe_drift(item)}")
        change = item.get("change", {})
        require(change.get("actions") == ["update"],
                f"provider readback drift must be a refresh-only update: {describe_drift(item)}")
        before = change.get("before")
        after = change.get("after")
        require(isinstance(before, dict) and isinstance(after, dict),
                f"provider readback drift is missing its before/after values: {describe_drift(item)}")
        changed_fields = {
            key for key in set(before) | set(after)
            if before.get(key, missing) != after.get(key, missing)
        }
        require(changed_fields == {field} and before.get(field, missing) == before_value and
                after.get(field, missing) == after_value,
                "provider readback drift differs from the exact confirmed null-to-empty field: "
                f"expected only {field}={before_value!r}->{after_value!r}; {describe_drift(item)}")
        require(address not in seen, "duplicate provider readback drift resource")
        seen.add(address)


def _drift_differences(left, right, path=""):
    if left is _MISSING or right is _MISSING:
        yield path, left, right
    elif isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else str(key)
            yield from _drift_differences(left.get(key, _MISSING), right.get(key, _MISSING), child)
    elif isinstance(left, list) and isinstance(right, list):
        for index in range(max(len(left), len(right))):
            child = f"{path}[{index}]"
            yield from _drift_differences(left[index] if index < len(left) else _MISSING,
                                          right[index] if index < len(right) else _MISSING, child)
    elif left != right:
        yield path, left, right


def _is_missing_or_none(value):
    return value is _MISSING or value is None


def _validate_certificate_status_side(values, hostname):
    managed = values.get("managed")
    require(isinstance(managed, list) and len(managed) == 1 and
            managed[0].get("domains") == [hostname],
            "certificate status readback must retain the exact configured hostname")
    status = managed[0].get("authorization_attempt_info", _MISSING)
    if _is_missing_or_none(status) or status == []:
        return
    require(isinstance(status, list) and len(status) == 1 and isinstance(status[0], dict),
            "certificate authorization status must contain only the single configured hostname")
    attempt = status[0]
    require(set(attempt) <= CERTIFICATE_STATUS_KEYS and attempt.get("domain") == hostname,
            "certificate authorization status is outside the exact configured hostname")
    for field, allowed_values in CERTIFICATE_STATUS_FIELDS.items():
        key = field.rsplit(".", 1)[1]
        value = attempt.get(key, _MISSING)
        require(_is_missing_or_none(value) or value in allowed_values,
                f"certificate authorization status has an unknown {key} enum")
    details = attempt.get("details", _MISSING)
    require(_is_missing_or_none(details) or isinstance(details, str) and len(details) <= 2048,
            "certificate authorization details must be a bounded provider status string")


def check_certificate_status_readback_drift(item, hostname):
    require(item.get("mode", "managed") == "managed" and item.get("type") == CERTIFICATE_READBACK_TYPE,
            f"provider readback drift is on an unexpected certificate resource type: {describe_drift(item)}")
    change = item.get("change", {})
    require(change.get("actions") == ["update"],
            f"certificate provider readback drift must be a refresh-only update: {describe_drift(item)}")
    before = change.get("before")
    after = change.get("after")
    require(isinstance(before, dict) and isinstance(after, dict),
            f"certificate provider readback drift is missing before/after values: {describe_drift(item)}")
    differences = list(_drift_differences(before, after))
    require(bool(differences), "certificate provider readback drift has no changed fields")
    allowed_paths = {"labels", *CERTIFICATE_STATUS_FIELDS, CERTIFICATE_DETAILS_FIELD}
    for path, _, _ in differences:
        require(path in allowed_paths,
                f"certificate provider readback drift changed a configured or unreviewed field: "
                f"{describe_drift(item)}")
    _validate_certificate_status_side(before, hostname)
    _validate_certificate_status_side(after, hostname)

    for path, before_value, after_value in differences:
        if path == "labels":
            require(before_value is None and after_value == {},
                    "certificate labels readback drift must be exactly null-to-empty")
        elif path == CERTIFICATE_DETAILS_FIELD:
            require((_is_missing_or_none(before_value) or isinstance(before_value, str)) and
                    (_is_missing_or_none(after_value) or isinstance(after_value, str)) and
                    (before_value is _MISSING or before_value is None or len(before_value) <= 2048) and
                    (after_value is _MISSING or after_value is None or len(after_value) <= 2048),
                    "certificate authorization details drift must be a bounded output-only status string")
        else:
            allowed_values = CERTIFICATE_STATUS_FIELDS[path]
            require((_is_missing_or_none(before_value) or before_value in allowed_values) and
                    (_is_missing_or_none(after_value) or after_value in allowed_values),
                    f"certificate authorization status drift contains an unknown value for {path.rsplit('.', 1)[1]}")


def describe_drift(item):
    """Return a bounded, secret-redacted summary for an HTTPS-root drift item."""
    change = item.get("change", {})
    before = change.get("before")
    after = change.get("after")
    paths = []

    if isinstance(before, dict) and isinstance(after, dict):
        for path, left, right in _drift_differences(before, after):
            if SENSITIVE_DRIFT_PATH.search(path):
                left_text = right_text = "<redacted>"
            else:
                left_text = _format_drift_value(left)
                right_text = _format_drift_value(right)
            paths.append(f"{path}: {left_text} -> {right_text}")
    if not paths:
        paths = ["changed fields unavailable"]
    if len(paths) > 8:
        paths = [*paths[:8], f"... and {len(paths) - 8} more field(s)"]
    return (f"address={item.get('address', '<unknown>')}, type={item.get('type', '<unknown>')}, "
            f"actions={change.get('actions', '<unknown>')}, fields=[{' ; '.join(paths)}]")


def _format_drift_value(value):
    if value is _MISSING:
        return "<missing>"

    def redact_nested(candidate, path=""):
        if SENSITIVE_DRIFT_PATH.search(path):
            return "<redacted>"
        if isinstance(candidate, dict):
            return {key: redact_nested(item, f"{path}.{key}" if path else str(key))
                    for key, item in candidate.items()}
        if isinstance(candidate, list):
            return [redact_nested(item, f"{path}[{index}]") for index, item in enumerate(candidate)]
        if isinstance(candidate, str) and ("@" in candidate or len(candidate) > 160):
            return "<redacted>"
        return candidate

    text = json.dumps(redact_nested(value), sort_keys=True, separators=(",", ":"), default=str)
    return text if len(text) <= 200 else f"{text[:197]}..."


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
    changes = check_actions(plan, FOUNDATION, hostname)
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
