"""Check the saved Dev plan and read-only post-apply evidence.

The workflow stores JSON in the runner's temporary directory. This script prints
only a decision or a short error, never plan or state contents.
"""

import json
import sys
from pathlib import Path


PROJECT = "helpdeskcloud-capstone-511905"
VPC = "helpdeskcloud-dev-vpc"
SUBNET = "helpdeskcloud-dev-subnet"
PSA = "helpdeskcloud-dev-psa"
SERVICE = "servicenetworking.googleapis.com"
PREFIX = "module.dev_network[0]."
NETWORK = {
    PREFIX + "google_compute_network.this": "google_compute_network",
    PREFIX + "google_compute_subnetwork.this": "google_compute_subnetwork",
    PREFIX + "google_compute_global_address.private_services": "google_compute_global_address",
    PREFIX + "google_service_networking_connection.private_services": "google_service_networking_connection",
}
PHASE6 = {
    "google_artifact_registry_repository.dev_images[0]": "google_artifact_registry_repository",
    "google_sql_database_instance.dev_postgres[0]": "google_sql_database_instance",
    "google_sql_database.dev_helpdesk[0]": "google_sql_database",
}
EXPECTED = NETWORK | PHASE6
VPC_LINK = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/global/networks/{VPC}"
VPC_PATH = f"projects/{PROJECT}/global/networks/{VPC}"
VPC_PEERING_PATH = f"projects/260283083469/global/networks/{VPC}"
PSA_ADDRESS = PREFIX + "google_compute_global_address.private_services"
SUBNET_ADDRESS = PREFIX + "google_compute_subnetwork.this"
ATTRIBUTION_LABEL = {"goog-terraform-provisioned": "true"}
MISSING = object()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def planned_resources(module):
    """Terraform can omit no-op entries from resource_changes; planned_values remains complete."""
    resources = list(module.get("resources", []))
    for child in module.get("child_modules", []):
        resources.extend(planned_resources(child))
    return resources


def only_item(value, message):
    require(isinstance(value, list) and len(value) == 1, message)
    return value[0]


def check_network(values):
    network = values["google_compute_network"]
    require(network.get("name") == VPC, "Unexpected VPC name")
    require(network.get("auto_create_subnetworks") is False, "VPC must use custom subnet mode")
    require(network.get("routing_mode") == "REGIONAL", "Unexpected VPC routing mode")

    subnet = values["google_compute_subnetwork"]
    require(subnet.get("name") == SUBNET and subnet.get("region") == "us-east1", "Unexpected subnet identity")
    require(subnet.get("ip_cidr_range") == "10.20.0.0/20", "Unexpected primary subnet CIDR")
    require(subnet.get("private_ip_google_access") is True, "Private Google Access must be enabled")
    ranges = subnet.get("secondary_ip_range", [])
    require(isinstance(ranges, list) and len(ranges) == 2, "Expected two secondary ranges")
    require({r.get("range_name"): r.get("ip_cidr_range") for r in ranges}
            == {"helpdeskcloud-dev-pods": "10.24.0.0/16", "helpdeskcloud-dev-services": "10.25.0.0/20"},
            "Unexpected secondary ranges")

    allocation = values["google_compute_global_address"]
    require(allocation.get("name") == PSA, "Unexpected private allocation name")
    require(allocation.get("address") == "10.30.0.0" and allocation.get("prefix_length") == 16, "Unexpected private allocation CIDR")
    require(allocation.get("purpose") == "VPC_PEERING" and allocation.get("address_type") == "INTERNAL", "Invalid private allocation type")

    connection = values["google_service_networking_connection"]
    require(connection.get("service") == SERVICE, "Unexpected service producer")
    require(connection.get("reserved_peering_ranges") == [PSA], "Connection must use the intended allocation")


def check_phase6(values):
    registry = values["google_artifact_registry_repository"]
    require(registry.get("project") == PROJECT and registry.get("location") == "us-east1", "Unexpected registry project or region")
    require(registry.get("repository_id") == "helpdeskcloud-dev-images" and registry.get("format") == "DOCKER", "Unexpected Docker repository")
    require(only_item(registry.get("docker_config"), "Expected one Docker configuration").get("immutable_tags") is True,
            "Docker tags must be immutable")

    sql = values["google_sql_database_instance"]
    require(sql.get("project") == PROJECT and sql.get("region") == "us-east1", "Unexpected SQL project or region")
    require(sql.get("name") == "helpdeskcloud-dev-postgres" and sql.get("database_version") == "POSTGRES_17", "Unexpected SQL identity or engine")
    require(sql.get("deletion_protection") is True, "Terraform SQL deletion protection must be enabled")
    settings = only_item(sql.get("settings"), "Expected one SQL settings block")
    for field, expected in {"edition": "ENTERPRISE", "tier": "db-f1-micro", "availability_type": "ZONAL",
                            "disk_type": "PD_SSD", "disk_size": 10, "disk_autoresize": False,
                            "deletion_protection_enabled": True}.items():
        require(settings.get(field) == expected, f"Unexpected SQL {field}")
    backup = only_item(settings.get("backup_configuration"), "Expected one SQL backup configuration")
    require(backup.get("enabled") is True and backup.get("point_in_time_recovery_enabled") is False,
            "Unexpected SQL backup settings")
    retention = only_item(backup.get("backup_retention_settings"), "Expected one backup retention setting")
    require(retention.get("retained_backups") == 7 and retention.get("retention_unit") == "COUNT", "Unexpected backup retention")
    ip = only_item(settings.get("ip_configuration"), "Expected one SQL IP configuration")
    require(ip.get("ipv4_enabled") is False, "SQL public IPv4 must be disabled")
    require(ip.get("private_network") == VPC_LINK and ip.get("allocated_ip_range") == PSA,
            "SQL must use the existing VPC and PSA range")
    require(ip.get("ssl_mode") == "ENCRYPTED_ONLY", "SQL encrypted-only mode must be enabled")

    database = values["google_sql_database"]
    require(database.get("project") == PROJECT and database.get("name") == "helpdesk", "Unexpected SQL database")
    require(database.get("instance") == "helpdeskcloud-dev-postgres", "SQL database must use the intended instance")


def check_references(plan):
    root = plan.get("configuration", {}).get("root_module", {})
    module = root.get("module_calls", {}).get("dev_network", {}).get("module", {})
    network = {r.get("address"): r for r in module.get("resources", [])}
    resources = {r.get("address"): r for r in root.get("resources", [])}

    def references(expression, expected, label):
        require(expected in expression.get("references", []), f"Missing Terraform reference: {label}")

    for address, field, expected in (
        ("google_compute_subnetwork.this", "network", "google_compute_network.this.id"),
        ("google_compute_global_address.private_services", "network", "google_compute_network.this.id"),
        ("google_service_networking_connection.private_services", "network", "google_compute_network.this.id"),
        ("google_service_networking_connection.private_services", "reserved_peering_ranges", "google_compute_global_address.private_services.name"),
    ):
        references(network.get(address, {}).get("expressions", {}).get(field, {}), expected, f"{address}.{field}")

    sql = resources.get("google_sql_database_instance.dev_postgres", {})
    settings = only_item(sql.get("expressions", {}).get("settings"), "Missing SQL settings references")
    ip = only_item(settings.get("ip_configuration"), "Missing SQL IP references")
    references(ip.get("private_network", {}), "module.dev_network[0].vpc_self_link", "SQL private_network")
    references(ip.get("allocated_ip_range", {}), "module.dev_network[0].private_services_range_name", "SQL allocated_ip_range")
    require("module.dev_network" in sql.get("depends_on", []), "SQL must wait for private services connectivity")
    database = resources.get("google_sql_database.dev_helpdesk", {})
    references(database.get("expressions", {}).get("instance", {}),
               "google_sql_database_instance.dev_postgres[0].name", "database instance")


def permitted_drift(entry):
    """Accept only two known readback representations, with every other field identical."""
    address = entry.get("address")
    if (entry.get("mode") != "managed" or address not in (PSA_ADDRESS, SUBNET_ADDRESS)
            or entry.get("type") != NETWORK[address]):
        return False
    change = entry.get("change", {})
    before, after = change.get("before"), change.get("after")
    if change.get("actions") != ["update"] or not isinstance(before, dict) or not isinstance(after, dict):
        return False

    if address == PSA_ADDRESS:
        if (before.get("name") != PSA or after.get("name") != PSA
                or before.get("labels", MISSING) is not None or after.get("labels", MISSING) != {}
                or before.get("terraform_labels", MISSING) != ATTRIBUTION_LABEL
                or after.get("terraform_labels", MISSING) != ATTRIBUTION_LABEL
                or before.get("effective_labels", MISSING) != ATTRIBUTION_LABEL
                or after.get("effective_labels", MISSING) != ATTRIBUTION_LABEL):
            return False
        return {k: v for k, v in before.items() if k != "labels"} == {
            k: v for k, v in after.items() if k != "labels"}

    before_logs, after_logs = before.get("log_config"), after.get("log_config")
    if (not isinstance(before_logs, list) or len(before_logs) != 1
            or not isinstance(after_logs, list) or len(after_logs) != 1
            or not isinstance(before_logs[0], dict) or not isinstance(after_logs[0], dict)):
        return False
    before_log, after_log = before_logs[0], after_logs[0]
    before_fields = before_log.get("metadata_fields", MISSING)
    after_fields = after_log.get("metadata_fields", MISSING)
    empty_fields = (MISSING, None, [])
    if (before_log.get("metadata") != "EXCLUDE_ALL_METADATA"
            or after_log.get("metadata") != "EXCLUDE_ALL_METADATA"
            or before_fields not in empty_fields or after_fields not in empty_fields
            or (before_fields is MISSING and after_fields is MISSING)
            or (before_fields is not MISSING and after_fields is not MISSING and before_fields == after_fields)):
        return False
    # Compare the complete resource snapshots after removing only the inert field.
    before_copy, after_copy = dict(before), dict(after)
    before_copy["log_config"] = [{k: v for k, v in before_log.items() if k != "metadata_fields"}]
    after_copy["log_config"] = [{k: v for k, v in after_log.items() if k != "metadata_fields"}]
    return before_copy == after_copy


def check_drift(plan):
    drift = plan.get("resource_drift", [])
    require(isinstance(drift, list), "Unexpected resource drift format")
    require(len({entry.get("address") for entry in drift if isinstance(entry, dict)}) == len(drift),
            "Duplicate or malformed resource drift")
    require(all(isinstance(entry, dict) and permitted_drift(entry) for entry in drift),
            "Unexpected resource drift requires review; run the Dev Plan diagnostic")
    # A drift observation never authorizes a requested operation on that resource.
    for entry in drift:
        if entry.get("address") == PSA_ADDRESS:
            requested = [change for change in plan.get("resource_changes", [])
                         if change.get("address") == PSA_ADDRESS]
            require(all(change.get("change", {}).get("actions") == ["no-op"] for change in requested),
                    "PSA drift is readback only; a proposed resource change requires review")


def check_plan(plan):
    for name, expected in {"project_id": PROJECT, "region": "us-east1", "environment": "dev"}.items():
        require(plan.get("variables", {}).get(name, {}).get("value") == expected, f"Unexpected {name}")
    # Drift is separate from requested actions; only two exact provider readbacks are allowed.
    check_drift(plan)
    planned = planned_resources(plan.get("planned_values", {}).get("root_module", {}))
    managed = [r for r in planned if r.get("mode") == "managed"]
    require(len(managed) == len(EXPECTED) and {r.get("address") for r in managed} == set(EXPECTED),
            "Planned Dev infrastructure must contain exactly seven expected addresses")
    require(all(r.get("type") == EXPECTED[r["address"]] for r in managed),
            "Unexpected planned resource type")
    changes = [c for c in plan.get("resource_changes", []) if c.get("mode") == "managed"]
    require(len({c.get("address") for c in changes}) == len(changes), "Duplicate resource change")
    require(all(c.get("address") in EXPECTED and c.get("type") == EXPECTED[c["address"]] for c in changes),
            "Unexpected resource address or type")
    actions = {c["address"]: c.get("change", {}).get("actions") for c in changes}
    require(all(actions.get(address, ["no-op"]) == ["no-op"] for address in NETWORK),
            "Existing network change, replacement, or deletion requires review")
    creates = {address for address in PHASE6 if actions.get(address) == ["create"]}
    require(all(actions.get(address, ["no-op"]) in (["create"], ["no-op"]) for address in PHASE6),
            "Phase 6 update, replacement, or deletion requires review")
    require(not creates or creates == set(PHASE6), "Partial Phase 6 deployment requires manual review")
    # Check the complete planned values, including no-op resources omitted from resource_changes.
    values = {r["type"]: r.get("values", {}) for r in managed}
    check_network(values)
    check_phase6(values)
    check_references(plan)
    return "apply" if creates else "no_changes"


SENSITIVE_PARTS = {"id", "name", "project", "region", "self_link", "network", "subnetwork", "ip_cidr_range",
                   "secondary_ip_range", "address", "prefix_length", "purpose", "address_type", "routing_mode",
                   "private_ip_google_access", "peerings", "reserved_peering_ranges", "service", "iam", "firewall",
                   "public_ip_address", "ipv4_enabled", "deletion_protection"}


def changed_paths(before, after, prefix=""):
    """Return attribute names only, never their values."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        paths = []
        for key in sorted(before.keys() | after.keys()):
            path = f"{prefix}.{key}" if prefix else key
            paths.extend(changed_paths(before.get(key, MISSING), after.get(key, MISSING), path))
        return paths
    if isinstance(before, list) and isinstance(after, list):
        paths = []
        for index in range(max(len(before), len(after))):
            path = f"{prefix}[{index}]"
            paths.extend(changed_paths(before[index] if index < len(before) else None,
                                       after[index] if index < len(after) else None, path))
        return paths
    return [prefix or "<unknown>"]


def known_value(value, label=False):
    """Show only the two documented, non-secret attribute representations."""
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if label and value == ATTRIBUTION_LABEL:
        return "goog-terraform-provisioned=true"
    if not label and value == []:
        return "[]"
    return "<unexpected value withheld>"


def classify_address_labels(value):
    """Classify the PSA labels map without exposing unexpected keys or values."""
    if value == {}:
        return "empty map"
    if value == ATTRIBUTION_LABEL:
        return "goog-terraform-provisioned=true"
    if isinstance(value, dict):
        return "unexpected map (contents withheld)"
    return known_value(value, label=True)


def attribution_status(value):
    """Report label presence in provider-computed maps, never their other contents."""
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if not isinstance(value, dict):
        return "unexpected type (contents withheld)"
    if value.get("goog-terraform-provisioned") == "true":
        return "expected attribution label present"
    return "expected attribution label absent or different (contents withheld)"


def diagnose_drift(plan):
    drift = plan.get("resource_drift", [])
    if not drift:
        return ["No resource_drift entries in this plan; this does not prove the earlier drift is resolved."]
    lines = [f"Terraform reported drift for {len(drift)} resource(s). Only two known non-secret fields are summarized."]
    for entry in drift:
        change = entry.get("change", {})
        paths = changed_paths(change.get("before"), change.get("after")) or ["<unknown>"]
        sensitive = any(any(part in SENSITIVE_PARTS for part in path.replace("[", ".").split("."))
                        for path in paths)
        lines.append(f"{entry.get('address', '<unknown>')} ({entry.get('type', '<unknown>')}): "
                     f"actions={','.join(change.get('actions', [])) or 'unknown'}; "
                     f"security-sensitive paths={'yes' if sensitive else 'possible'}; "
                     f"paths={', '.join(paths)}")
        before, after = change.get("before"), change.get("after")
        if entry.get("address") == PSA_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            lines.append("  labels: before=" + known_value(before.get("labels", MISSING), label=True)
                         + "; after=" + classify_address_labels(after.get("labels", MISSING)))
            for field in ("terraform_labels", "effective_labels"):
                lines.append("  " + field + ": before=" + attribution_status(before.get(field, MISSING))
                             + "; after=" + attribution_status(after.get(field, MISSING)))
        if entry.get("address") == SUBNET_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            before_logs, after_logs = before.get("log_config"), after.get("log_config")
            if (isinstance(before_logs, list) and len(before_logs) == 1 and isinstance(before_logs[0], dict)
                    and isinstance(after_logs, list) and len(after_logs) == 1 and isinstance(after_logs[0], dict)):
                lines.append("  log_config[0].metadata_fields: before="
                             + known_value(before_logs[0].get("metadata_fields", MISSING))
                             + "; after=" + known_value(after_logs[0].get("metadata_fields", MISSING)))
    lines.append("Only exact documented normalization patterns may pass; all other drift remains blocked.")
    return lines


def verify_deployment(paths):
    network, subnet, address, connections, registry, registry_iam, project_iam, sql, databases, outputs = [read_json(p) for p in paths[:10]]
    state_addresses = set(Path(paths[10]).read_text(encoding="utf-8").splitlines())
    require(state_addresses == set(EXPECTED), "Dev state does not contain exactly the seven expected resources")
    require(network.get("name") == VPC and network.get("autoCreateSubnetworks") is False, "VPC verification failed")
    require(network.get("selfLink") == VPC_LINK, "VPC self-link verification failed")
    require(network.get("routingConfig", {}).get("routingMode") == "REGIONAL", "VPC routing verification failed")

    require(subnet.get("name") == SUBNET and subnet.get("region", "").endswith("/regions/us-east1"), "Subnet identity verification failed")
    require(subnet.get("ipCidrRange") == "10.20.0.0/20" and subnet.get("privateIpGoogleAccess") is True, "Subnet settings verification failed")
    actual_ranges = {r.get("rangeName"): r.get("ipCidrRange") for r in subnet.get("secondaryIpRanges", [])}
    require(actual_ranges == {"helpdeskcloud-dev-pods": "10.24.0.0/16", "helpdeskcloud-dev-services": "10.25.0.0/20"}, "Secondary range verification failed")
    require(subnet.get("network") == network.get("selfLink"), "Subnet is attached to the wrong VPC")

    require(address.get("name") == PSA and address.get("purpose") == "VPC_PEERING", "PSA allocation verification failed")
    require(address.get("addressType") == "INTERNAL" and address.get("address") == "10.30.0.0" and int(address.get("prefixLength", -1)) == 16, "PSA CIDR verification failed")
    require(address.get("network") == network.get("selfLink"), "PSA allocation is attached to the wrong VPC")

    if isinstance(connections, dict):
        connections = connections.get("connections", [])
    require(isinstance(connections, list), "Unexpected Service Networking response")
    matched = [c for c in connections if c.get("network") in (VPC_PATH, VPC_PEERING_PATH)
               and PSA in c.get("reservedPeeringRanges", []) and c.get("service") in (SERVICE, "services/" + SERVICE)]
    require(len(matched) == 1 and matched[0].get("peering"), "PSA connection verification failed")
    require(any(p.get("name") == matched[0]["peering"] and p.get("state") == "ACTIVE"
                for p in network.get("peerings", [])), "Service Networking peering is not active")

    require(registry.get("name") == f"projects/{PROJECT}/locations/us-east1/repositories/helpdeskcloud-dev-images",
            "Artifact Registry identity verification failed")
    registry_id = registry["name"].rsplit("/", 1)[-1]
    require(registry.get("format") == "DOCKER" and registry.get("dockerConfig", {}).get("immutableTags") is True,
            "Artifact Registry Docker or immutable-tag verification failed")
    check_iam(registry_iam, "repository")
    check_iam(project_iam, "project")

    require(sql.get("name") == "helpdeskcloud-dev-postgres" and sql.get("region") == "us-east1",
            "Cloud SQL identity verification failed")
    require(sql.get("databaseVersion") == "POSTGRES_17", "Cloud SQL engine verification failed")
    require(sql.get("state") == "RUNNABLE", "Cloud SQL instance is not RUNNABLE")
    settings = sql.get("settings", {})
    for field, expected in {"edition": "ENTERPRISE", "tier": "db-f1-micro", "availabilityType": "ZONAL",
                            "dataDiskType": "PD_SSD", "storageAutoResize": False}.items():
        require(settings.get(field) == expected, f"Cloud SQL {field} verification failed")
    require(settings.get("deletionProtectionEnabled") is True,
            "Cloud SQL API deletion protection verification failed")
    require(int(settings.get("dataDiskSizeGb", -1)) == 10, "Cloud SQL disk size verification failed")
    backup = settings.get("backupConfiguration", {})
    require(backup.get("enabled") is True and backup.get("pointInTimeRecoveryEnabled") is False,
            "Cloud SQL backup verification failed")
    require(int(backup.get("backupRetentionSettings", {}).get("retainedBackups", -1)) == 7,
            "Cloud SQL backup retention verification failed")
    ip = settings.get("ipConfiguration", {})
    # Cloud SQL returns a project-qualified path; the Compute API uses a full selfLink.
    require(ip.get("ipv4Enabled") is False and ip.get("privateNetwork") in (VPC_PATH, VPC_LINK),
            "Cloud SQL must use only the intended private VPC")
    require(ip.get("allocatedIpRange") == PSA and ip.get("sslMode") == "ENCRYPTED_ONLY",
            "Cloud SQL PSA or encryption verification failed")
    addresses = sql.get("ipAddresses", [])
    private_ips = [item.get("ipAddress") for item in addresses if item.get("type") == "PRIVATE"]
    require(len(private_ips) == 1 and private_ips[0], "Cloud SQL private IP is missing")
    require(not any(item.get("type") == "PRIMARY" for item in addresses),
            "Cloud SQL has an unexpected public IP")
    require(isinstance(databases, list) and any(db.get("name") == "helpdesk" and
            db.get("instance") == "helpdeskcloud-dev-postgres" for db in databases),
            "helpdesk database verification failed")

    expected_outputs = {
        "environment": "dev", "project_id": PROJECT, "region": "us-east1",
        "vpc_name": VPC, "subnet_name": SUBNET, "subnet_cidr": "10.20.0.0/20",
        "pods_range_name": "helpdeskcloud-dev-pods", "pods_cidr": "10.24.0.0/16",
        "services_range_name": "helpdeskcloud-dev-services", "services_cidr": "10.25.0.0/20",
        "private_services_range_name": PSA,
    }
    require(all(outputs.get(k, {}).get("value") == v for k, v in expected_outputs.items()), "Terraform outputs do not match Dev design")
    for key in ("vpc_self_link", "subnet_self_link", "private_services_connection_id"):
        require(outputs.get(key, {}).get("value"), f"Terraform output {key} is empty")
    require(outputs["vpc_self_link"]["value"] == network.get("selfLink"), "VPC output mismatch")
    require(outputs["subnet_self_link"]["value"] == subnet.get("selfLink"), "Subnet output mismatch")
    for key, expected in {
        "artifact_registry_repository_id": registry_id,
        "artifact_registry_location": "us-east1",
        # The provider's name output is the repository ID; the API name above is the full resource path.
        "artifact_registry_resource_name": registry_id,
        "docker_image_repository": f"us-east1-docker.pkg.dev/{PROJECT}/{registry_id}/helpdeskcloud",
        "cloud_sql_instance_name": sql["name"],
        "cloud_sql_region": "us-east1",
        "cloud_sql_database_version": "POSTGRES_17",
        "cloud_sql_database_name": "helpdesk",
        "cloud_sql_private_ip": private_ips[0],
        "cloud_sql_connection_name": sql.get("connectionName"),
        "cloud_sql_vpc_self_link": network["selfLink"],
        "cloud_sql_private_services_range_name": PSA,
    }.items():
        require(expected and outputs.get(key, {}).get("value") == expected, f"Terraform output {key} mismatch")


def check_iam(policy, label):
    require(isinstance(policy, dict) and isinstance(policy.get("bindings", []), list), f"Invalid {label} IAM evidence")
    require(not any({"allUsers", "allAuthenticatedUsers"} & set(binding.get("members", []))
                    for binding in policy.get("bindings", [])), f"Public {label} IAM binding requires review")


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "check-plan":
            print(check_plan(read_json(sys.argv[2])))
        elif len(sys.argv) == 3 and sys.argv[1] == "diagnose-drift":
            print("\n".join(diagnose_drift(read_json(sys.argv[2]))))
        elif len(sys.argv) == 3 and sys.argv[1] == "check-project-iam":
            check_iam(read_json(sys.argv[2]), "project")
            print("No direct public project IAM binding found")
        elif len(sys.argv) == 13 and sys.argv[1] == "verify-deployment":
            verify_deployment(sys.argv[2:])
            print("Seven Dev resources, remote state addresses, IAM exposure, and outputs verified")
        else:
            raise ValueError("Usage: dev_infra_guard.py check-plan PLAN_JSON | diagnose-drift PLAN_JSON | "
                             "check-project-iam PROJECT_IAM_JSON | "
                             "verify-deployment VPC SUBNET ADDRESS CONNECTIONS REGISTRY REGISTRY_IAM PROJECT_IAM SQL DATABASES OUTPUTS STATE_LIST")
    except (ValueError, KeyError, IndexError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"Dev infrastructure guard stopped: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
