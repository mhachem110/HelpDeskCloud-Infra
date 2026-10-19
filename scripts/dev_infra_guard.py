"""Check the saved Dev plan and read-only post-apply evidence.

The workflow stores JSON in the runner's temporary directory. This script prints
only a decision or a short error, never plan or state contents.
"""

import json
import sys
from copy import deepcopy
from pathlib import Path


PROJECT = "helpdeskcloud-capstone-511905"
PROJECT_NUMBER = "260283083469"
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
# A phase adds exact addresses here; existing addresses remain protected as no-ops.
PHASE7 = {
    "google_container_cluster.dev[0]": "google_container_cluster",
    "google_service_account.dev_gke_nodes[0]": "google_service_account",
    "google_service_account.dev_app[0]": "google_service_account",
    "google_service_account.dev_migration[0]": "google_service_account",
    "google_project_iam_member.dev_gke_node_runtime[0]": "google_project_iam_member",
    "google_project_iam_member.dev_app_cloudsql[0]": "google_project_iam_member",
    "google_project_iam_member.dev_migration_cloudsql[0]": "google_project_iam_member",
    "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]": "google_artifact_registry_repository_iam_member",
    "google_service_account_iam_member.dev_app_workload_identity[0]": "google_service_account_iam_member",
    "google_service_account_iam_member.dev_migration_workload_identity[0]": "google_service_account_iam_member",
    "google_secret_manager_secret.dev_app_connection[0]": "google_secret_manager_secret",
    "google_secret_manager_secret.dev_admin_password[0]": "google_secret_manager_secret",
    "google_secret_manager_secret_iam_member.dev_app_secret_access[0]": "google_secret_manager_secret_iam_member",
    "google_secret_manager_secret_iam_member.dev_admin_secret_access[0]": "google_secret_manager_secret_iam_member",
}
# Apply #12 logs confirm that these six Phase 7 resources completed before the
# remaining operations failed. Recovery is allowed only if the fresh plan's
# prior state and refresh show precisely this inventory.
APPLY12_COMPLETED = frozenset({
    "google_service_account.dev_gke_nodes[0]",
    "google_service_account.dev_app[0]",
    "google_service_account.dev_migration[0]",
    "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]",
    "google_secret_manager_secret.dev_app_connection[0]",
    "google_secret_manager_secret.dev_admin_password[0]",
})
APPLY12_REMAINING = frozenset(PHASE7) - APPLY12_COMPLETED
BASE = NETWORK | PHASE6
EXPECTED = BASE | PHASE7
VPC_LINK = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/global/networks/{VPC}"
VPC_PATH = f"projects/{PROJECT}/global/networks/{VPC}"
VPC_PEERING_PATH = f"projects/{PROJECT_NUMBER}/global/networks/{VPC}"
PSA_ADDRESS = PREFIX + "google_compute_global_address.private_services"
SUBNET_ADDRESS = PREFIX + "google_compute_subnetwork.this"
REGISTRY_ADDRESS = "google_artifact_registry_repository.dev_images[0]"
REGISTRY_REPOSITORY_ID = "helpdeskcloud-dev-images"
REGISTRY_REPOSITORY_PATH = (
    f"projects/{PROJECT}/locations/us-east1/repositories/{REGISTRY_REPOSITORY_ID}"
)
SQL_ADDRESS = "google_sql_database_instance.dev_postgres[0]"
CLUSTER_ADDRESS = "google_container_cluster.dev[0]"
SECRET_READBACK_NAMES = {
    "google_secret_manager_secret.dev_app_connection[0]": "helpdesk-dev-db-connection",
    "google_secret_manager_secret.dev_admin_password[0]": "helpdesk-dev-db-admin-password",
}
PROJECT_IAM_READBACKS = {
    "google_project_iam_member.dev_gke_node_runtime[0]": (
        "roles/container.defaultNodeServiceAccount",
        f"serviceAccount:helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com",
    ),
    "google_project_iam_member.dev_app_cloudsql[0]": (
        "roles/cloudsql.client",
        f"serviceAccount:helpdesk-app-dev@{PROJECT}.iam.gserviceaccount.com",
    ),
    "google_project_iam_member.dev_migration_cloudsql[0]": (
        "roles/cloudsql.client",
        f"serviceAccount:helpdesk-migrate-dev@{PROJECT}.iam.gserviceaccount.com",
    ),
}
SECRET_EMPTY_MAP_FIELDS = ("annotations", "labels", "version_aliases")
ATTRIBUTION_LABEL = {"goog-terraform-provisioned": "true"}
MISSING = object()

# Terraform records these counted resource traversals alongside their selected
# attribute. Keep this allowlist literal: another instance, attribute, or
# resource must not become an approved identity reference by prefix matching.
STRICT_REFERENCE_PARENTS = {
    "google_service_account.dev_gke_nodes[0]": "google_service_account.dev_gke_nodes",
    "google_service_account.dev_app[0]": "google_service_account.dev_app",
    "google_service_account.dev_migration[0]": "google_service_account.dev_migration",
    "google_secret_manager_secret.dev_app_connection[0]": "google_secret_manager_secret.dev_app_connection",
    "google_secret_manager_secret.dev_admin_password[0]": "google_secret_manager_secret.dev_admin_password",
}


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


def state_resources(module):
    """Return all resources from Terraform's complete prior-state representation."""
    resources = list(module.get("resources", []))
    for child in module.get("child_modules", []):
        resources.extend(state_resources(child))
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
    # Cloud SQL can read the same VPC back as a project path or Compute self-link.
    # Both forms must identify this exact project and network.
    require(ip.get("private_network") in (VPC_LINK, VPC_PATH),
            "SQL must use only the intended private VPC")
    require(ip.get("allocated_ip_range") == PSA,
            "SQL must use the existing PSA range")
    require(ip.get("ssl_mode") == "ENCRYPTED_ONLY", "SQL encrypted-only mode must be enabled")

    database = values["google_sql_database"]
    require(database.get("project") == PROJECT and database.get("name") == "helpdesk", "Unexpected SQL database")
    require(database.get("instance") == "helpdeskcloud-dev-postgres", "SQL database must use the intended instance")


def check_references(plan):
    root = plan.get("configuration", {}).get("root_module", {})
    module = root.get("module_calls", {}).get("dev_network", {}).get("module", {})
    network = {r.get("address"): r for r in module.get("resources", [])}
    resources = {r.get("address"): r for r in root.get("resources", [])}

    def references(expression, expected, label, exact=False):
        require(isinstance(expression, dict), f"Malformed Terraform references: {label}")
        actual = expression.get("references")
        require(isinstance(actual, list) and all(isinstance(reference, str) and reference for reference in actual),
                f"Malformed Terraform references: {label}")
        if exact:
            require(set(expression) == {"references"}, f"Malformed Terraform references: {label}")
            allowed = {expected}
            resource_address = expected.rsplit(".", 1)[0]
            if resource_address in STRICT_REFERENCE_PARENTS:
                allowed.update((resource_address, STRICT_REFERENCE_PARENTS[resource_address]))
            # The full reference is mandatory; Terraform may also report either
            # or both of its approved parent traversals in any order.
            require(expected in actual and len(actual) == len(set(actual)) and set(actual) <= allowed,
                    f"Missing or unexpected Terraform reference: {label}")
        else:
            require(expected in actual, f"Missing or unexpected Terraform reference: {label}")

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

    cluster = resources.get("google_container_cluster.dev", {})
    expressions = cluster.get("expressions", {})
    for field, expected in (
        ("network", "module.dev_network[0].vpc_self_link"),
        ("subnetwork", "module.dev_network[0].subnet_self_link"),
    ):
        references(expressions.get(field, {}), expected, f"GKE {field}")
    ip_ranges = only_item(expressions.get("ip_allocation_policy"), "Missing GKE range references")
    references(ip_ranges.get("cluster_secondary_range_name", {}),
               "module.dev_network[0].pods_range_name", "GKE Pod range")
    references(ip_ranges.get("services_secondary_range_name", {}),
               "module.dev_network[0].services_range_name", "GKE Service range")
    defaults = only_item(only_item(expressions.get("cluster_autoscaling"), "Missing GKE node identity")
                         .get("auto_provisioning_defaults"), "Missing GKE node identity")
    references(defaults.get("service_account", {}), "google_service_account.dev_gke_nodes[0].email",
               "GKE node identity", exact=True)
    require("google_project_iam_member.dev_gke_node_runtime" in cluster.get("depends_on", [])
            and "google_artifact_registry_repository_iam_member.dev_gke_image_pull" in cluster.get("depends_on", []),
            "GKE must wait for node permissions")

    for address, field, expected in (
        ("google_artifact_registry_repository_iam_member.dev_gke_image_pull", "member", "google_service_account.dev_gke_nodes[0].member"),
        ("google_service_account_iam_member.dev_app_workload_identity", "service_account_id", "google_service_account.dev_app[0].name"),
        ("google_service_account_iam_member.dev_migration_workload_identity", "service_account_id", "google_service_account.dev_migration[0].name"),
        ("google_secret_manager_secret_iam_member.dev_app_secret_access", "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access", "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
    ):
        references(resources.get(address, {}).get("expressions", {}).get(field, {}), expected, address,
                   exact=True)

    # These account identifiers are the source of computed service-account emails and names.
    for address, account_id in (
        ("google_service_account.dev_gke_nodes", "helpdesk-gke-node-dev"),
        ("google_service_account.dev_app", "helpdesk-app-dev"),
        ("google_service_account.dev_migration", "helpdesk-migrate-dev"),
    ):
        expressions = resources.get(address, {}).get("expressions", {})
        require(expressions.get("account_id", {}).get("constant_value") == account_id,
                f"Unexpected service-account account_id expression: {address}")
        references(expressions.get("project", {}), "var.project_id", f"{address}.project", exact=True)

    # Check the roles and identities in configuration as well as the evaluated plan.
    role_specs = (
        ("google_project_iam_member.dev_gke_node_runtime", "roles/container.defaultNodeServiceAccount",
         "member", "google_service_account.dev_gke_nodes[0].member"),
        ("google_project_iam_member.dev_app_cloudsql", "roles/cloudsql.client",
         "member", "google_service_account.dev_app[0].member"),
        ("google_project_iam_member.dev_migration_cloudsql", "roles/cloudsql.client",
         "member", "google_service_account.dev_migration[0].member"),
        ("google_artifact_registry_repository_iam_member.dev_gke_image_pull", "roles/artifactregistry.reader",
         "member", "google_service_account.dev_gke_nodes[0].member"),
        ("google_service_account_iam_member.dev_app_workload_identity", "roles/iam.workloadIdentityUser",
         "service_account_id", "google_service_account.dev_app[0].name"),
        ("google_service_account_iam_member.dev_migration_workload_identity", "roles/iam.workloadIdentityUser",
         "service_account_id", "google_service_account.dev_migration[0].name"),
        ("google_secret_manager_secret_iam_member.dev_app_secret_access", "roles/secretmanager.secretAccessor",
         "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access", "roles/secretmanager.secretAccessor",
         "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
    )
    for address, role, identity_field, identity_reference in role_specs:
        expressions = resources.get(address, {}).get("expressions", {})
        require(expressions.get("role", {}).get("constant_value") == role,
                f"Unexpected IAM role expression: {address}")
        references(expressions.get(identity_field, {}), identity_reference,
                   f"{address}.{identity_field}", exact=True)

    # These policies contain static pool names, so Terraform cannot infer that
    # GKE must finish creating the pool before it writes the bindings.
    for address in (
        "google_service_account_iam_member.dev_app_workload_identity",
        "google_service_account_iam_member.dev_migration_workload_identity",
        "google_secret_manager_secret_iam_member.dev_app_secret_access",
        "google_secret_manager_secret_iam_member.dev_admin_secret_access",
    ):
        require("google_container_cluster.dev" in resources.get(address, {}).get("depends_on", []),
                f"{address} must wait for the GKE Workload Identity pool")


def after_unknown_at(change, path):
    """Read one Terraform after_unknown leaf without treating missing metadata as unknown."""
    value = change.get("after_unknown", {})
    for part in path:
        if isinstance(part, int):
            if not isinstance(value, list) or part >= len(value):
                return False
            value = value[part]
        else:
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
    return value is True


def expected_or_unknown(values, address, path, expected, changes, creates, label):
    """Accept a computed result only for a new approved resource and an exact unknown marker."""
    value = values
    for part in path:
        if isinstance(part, int):
            value = value[part] if isinstance(value, list) and part < len(value) else MISSING
        else:
            value = value.get(part, MISSING) if isinstance(value, dict) else MISSING
    change = changes.get(address, {}).get("change", {})
    if after_unknown_at(change, path):
        # Terraform's JSON plan may omit an unknown leaf from planned_values or
        # represent it as null. The exact marker and configuration references
        # establish whether the field is a computed value for this resource.
        require(address in creates and (value is None or value is MISSING),
                f"Unexpected unknown value for {label}")
        return
    require(value == expected, f"Unexpected {label}")


def check_phase7(values, plan, creates):
    """Verify the new resources by address, since several share an IAM resource type."""
    changes = {c.get("address"): c for c in plan.get("resource_changes", [])}

    def item(address):
        return values[address]

    cluster = item("google_container_cluster.dev[0]")
    require(cluster.get("project") == PROJECT and cluster.get("name") == "helpdeskcloud-dev-gke"
            and cluster.get("location") == "us-east1", "Unexpected GKE identity")
    require(cluster.get("enable_autopilot") is True and cluster.get("deletion_protection") is True,
            "GKE Autopilot or deletion protection is missing")
    require(cluster.get("network") == VPC_LINK and cluster.get("subnetwork") ==
            f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/regions/us-east1/subnetworks/{SUBNET}",
            "GKE must use the existing Dev VPC and subnet")
    require(cluster.get("networking_mode") == "VPC_NATIVE", "GKE must use alias IP networking")
    ranges = only_item(cluster.get("ip_allocation_policy"), "Missing GKE secondary ranges")
    require(ranges.get("cluster_secondary_range_name") == "helpdeskcloud-dev-pods"
            and ranges.get("services_secondary_range_name") == "helpdeskcloud-dev-services",
            "GKE secondary ranges do not match the existing subnet")
    private_config = only_item(cluster.get("private_cluster_config"), "Missing private node config")
    require(private_config.get("enable_private_nodes") is True, "GKE nodes must be private")
    require(private_config.get("enable_private_endpoint") is True,
            "GKE private endpoint setting must preserve the existing cluster configuration")
    endpoints = only_item(cluster.get("control_plane_endpoints_config"), "Missing control plane endpoints")
    require(only_item(endpoints.get("dns_endpoint_config"), "Missing DNS endpoint")
            .get("allow_external_traffic") is True, "Cloud Shell DNS endpoint is missing")
    require(only_item(endpoints.get("ip_endpoints_config"), "Missing IP endpoint config")
            .get("enabled") is False, "Direct control plane IP access must be disabled")
    require(only_item(cluster.get("workload_identity_config"), "Missing GKE workload pool")
            .get("workload_pool") == f"{PROJECT}.svc.id.goog", "Unexpected GKE workload pool")
    require(only_item(cluster.get("secret_manager_config"), "Missing managed Secret Manager add-on")
            .get("enabled") is True, "Managed Secret Manager add-on must be enabled")
    require(only_item(cluster.get("release_channel"), "Missing GKE release channel")
            .get("channel") == "REGULAR", "Unexpected GKE release channel")
    node = only_item(only_item(cluster.get("cluster_autoscaling"), "Missing node identity defaults")
                     .get("auto_provisioning_defaults"), "Missing node identity defaults")
    expected_or_unknown(cluster, "google_container_cluster.dev[0]",
                        ("cluster_autoscaling", 0, "auto_provisioning_defaults", 0, "service_account"),
                        f"helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com", changes, creates,
                        "GKE node identity")

    for address, account_id in (
        ("google_service_account.dev_gke_nodes[0]", "helpdesk-gke-node-dev"),
        ("google_service_account.dev_app[0]", "helpdesk-app-dev"),
        ("google_service_account.dev_migration[0]", "helpdesk-migrate-dev"),
    ):
        require(item(address).get("project") == PROJECT and item(address).get("account_id") == account_id,
                f"Unexpected service account: {address}")
        email = f"{account_id}@{PROJECT}.iam.gserviceaccount.com"
        for field, expected in (("email", email), ("member", f"serviceAccount:{email}"),
                                ("name", f"projects/{PROJECT}/serviceAccounts/{email}")):
            expected_or_unknown(item(address), address, (field,), expected, changes, creates,
                                f"service-account {field}: {address}")

    for address, role, email in (
        ("google_project_iam_member.dev_gke_node_runtime[0]", "roles/container.defaultNodeServiceAccount", "helpdesk-gke-node-dev"),
        ("google_project_iam_member.dev_app_cloudsql[0]", "roles/cloudsql.client", "helpdesk-app-dev"),
        ("google_project_iam_member.dev_migration_cloudsql[0]", "roles/cloudsql.client", "helpdesk-migrate-dev"),
    ):
        grant = item(address)
        require(grant.get("project") == PROJECT and grant.get("role") == role,
                f"Unexpected project IAM grant: {address}")
        expected_or_unknown(grant, address, ("member",),
                            f"serviceAccount:{email}@{PROJECT}.iam.gserviceaccount.com",
                            changes, creates, f"project IAM member: {address}")

    reader = item("google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]")
    require(reader.get("project") == PROJECT and reader.get("location") == "us-east1"
            and reader.get("repository") in (REGISTRY_REPOSITORY_ID, REGISTRY_REPOSITORY_PATH)
            and reader.get("role") == "roles/artifactregistry.reader",
            "Node image access must be repository-scoped Reader")
    expected_or_unknown(reader, "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]",
                        ("member",), f"serviceAccount:helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com",
                        changes, creates, "node repository IAM member")

    for address, name in (
        ("google_service_account_iam_member.dev_app_workload_identity[0]", "helpdesk-dev-app"),
        ("google_service_account_iam_member.dev_migration_workload_identity[0]", "helpdesk-dev-migrate"),
    ):
        grant = item(address)
        require(grant.get("role") == "roles/iam.workloadIdentityUser"
                and grant.get("member") == f"serviceAccount:{PROJECT}.svc.id.goog[helpdesk-dev/{name}]",
                f"Unexpected workload identity binding: {address}")
        account = "dev_app" if name == "helpdesk-dev-app" else "dev_migration"
        expected_or_unknown(grant, address, ("service_account_id",),
                            f"projects/{PROJECT}/serviceAccounts/"
                            f"{'helpdesk-app-dev' if account == 'dev_app' else 'helpdesk-migrate-dev'}@{PROJECT}.iam.gserviceaccount.com",
                            changes, creates, f"Workload Identity target: {address}")

    for address, secret_name in (
        ("google_secret_manager_secret.dev_app_connection[0]", "helpdesk-dev-db-connection"),
        ("google_secret_manager_secret.dev_admin_password[0]", "helpdesk-dev-db-admin-password"),
    ):
        secret = item(address)
        require(secret.get("project") == PROJECT and secret.get("secret_id") == secret_name
                and secret.get("deletion_protection") is True,
                f"Unexpected secret metadata: {address}")
        require(bool(only_item(secret.get("replication"), "Missing secret replication").get("auto")),
                "Secret must use Google-managed automatic replication")

    for address, name in (
        ("google_secret_manager_secret_iam_member.dev_app_secret_access[0]", "helpdesk-dev-app"),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access[0]", "helpdesk-dev-migrate"),
    ):
        grant = item(address)
        expected = (f"principal://iam.googleapis.com/projects/260283083469/locations/global/"
                    f"workloadIdentityPools/{PROJECT}.svc.id.goog/subject/ns/helpdesk-dev/sa/{name}")
        require(grant.get("role") == "roles/secretmanager.secretAccessor" and grant.get("member") == expected,
                f"Unexpected Secret Manager principal: {address}")
        secret_id = ("helpdesk-dev-db-connection" if name == "helpdesk-dev-app"
                     else "helpdesk-dev-db-admin-password")
        expected_or_unknown(grant, address, ("secret_id",),
                            f"projects/{PROJECT}/secrets/{secret_id}", changes, creates,
                            f"Secret Manager target: {address}")


def permitted_drift(entry):
    """Accept only exact provider readbacks, with every other field identical."""
    address = entry.get("address")
    expected_type = {
        PSA_ADDRESS: NETWORK[PSA_ADDRESS],
        SUBNET_ADDRESS: NETWORK[SUBNET_ADDRESS],
        REGISTRY_ADDRESS: PHASE6[REGISTRY_ADDRESS],
        SQL_ADDRESS: PHASE6[SQL_ADDRESS],
        CLUSTER_ADDRESS: PHASE7[CLUSTER_ADDRESS],
        **{address: "google_project_iam_member" for address in PROJECT_IAM_READBACKS},
        **{secret: PHASE7[secret] for secret in SECRET_READBACK_NAMES},
    }.get(address)
    if entry.get("mode") != "managed" or expected_type is None or entry.get("type") != expected_type:
        return False
    change = entry.get("change", {})
    before, after = change.get("before"), change.get("after")
    if change.get("actions") != ["update"] or not isinstance(before, dict) or not isinstance(after, dict):
        return False

    if address in SECRET_READBACK_NAMES:
        secret_id = SECRET_READBACK_NAMES[address]
        expected_id = f"projects/{PROJECT}/secrets/{secret_id}"
        if any(snapshot.get("project") != PROJECT or snapshot.get("secret_id") != secret_id
               or snapshot.get("id") != expected_id or snapshot.get("deletion_protection") is not True
               for snapshot in (before, after)):
            return False
        if any(before.get(field, MISSING) is not None or after.get(field, MISSING) != {}
               for field in SECRET_EMPTY_MAP_FIELDS):
            return False
        # Admit only null -> empty map for each unset optional field. The
        # diagnostic classifies the live snapshots without exposing contents.
        return ({key: value for key, value in before.items() if key not in SECRET_EMPTY_MAP_FIELDS}
                == {key: value for key, value in after.items() if key not in SECRET_EMPTY_MAP_FIELDS})

    if address == CLUSTER_ADDRESS:
        expected_identity = (PROJECT, "helpdeskcloud-dev-gke", "us-east1")
        if (tuple(before.get(key) for key in ("project", "name", "location")) != expected_identity
                or tuple(after.get(key) for key in ("project", "name", "location")) != expected_identity
                or before.get("deletion_protection") is not True
                or after.get("deletion_protection") is not True
                or before.get("network") != VPC_LINK or after.get("network") != VPC_LINK
                or before.get("subnetwork") != f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/regions/us-east1/subnetworks/{SUBNET}"
                or after.get("subnetwork") != f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/regions/us-east1/subnetworks/{SUBNET}"
                or before.get("networking_mode") != "VPC_NATIVE"
                or after.get("networking_mode") != "VPC_NATIVE"
                or before.get("enable_autopilot") is not True
                or after.get("enable_autopilot") is not True):
            return False
        for snapshot in (before, after):
            private = snapshot.get("private_cluster_config")
            endpoints = snapshot.get("control_plane_endpoints_config")
            workload_identity = snapshot.get("workload_identity_config")
            if (not isinstance(private, list) or len(private) != 1
                    or not isinstance(private[0], dict)
                    or private[0].get("enable_private_nodes") is not True
                    or private[0].get("enable_private_endpoint") is not True
                    or not isinstance(endpoints, list) or len(endpoints) != 1
                    or not isinstance(endpoints[0], dict)
                    or endpoints[0].get("ip_endpoints_config") != [{"enabled": False}]
                    or not isinstance(workload_identity, list) or len(workload_identity) != 1
                    or not isinstance(workload_identity[0], dict)
                    or workload_identity[0].get("workload_pool") != f"{PROJECT}.svc.id.goog"):
                return False
        # GKE's resourceLabels readback may normalize an absent map to the
        # provider's single attribution label. No user label is accepted here.
        before_labels = before.get("resource_labels", MISSING)
        after_labels = after.get("resource_labels", MISSING)
        empty_representations = (MISSING, None, {})
        empty_map_normalization = (
            before_labels in empty_representations
            and after_labels in empty_representations
            and before_labels != after_labels
        )
        exact_normalization = (
            before_labels == ATTRIBUTION_LABEL and after_labels in empty_representations
        ) or (
            after_labels == ATTRIBUTION_LABEL and before_labels in empty_representations
        )
        if not (exact_normalization or empty_map_normalization):
            return False
        return ({key: value for key, value in before.items() if key != "resource_labels"}
                == {key: value for key, value in after.items() if key != "resource_labels"})

    if address in PROJECT_IAM_READBACKS:
        expected_role, expected_member = PROJECT_IAM_READBACKS[address]
        if any(snapshot.get("project") != PROJECT or snapshot.get("role") != expected_role
               or snapshot.get("member") != expected_member
               for snapshot in (before, after)):
            return False
        before_etag, after_etag = before.get("etag", MISSING), after.get("etag", MISSING)
        empty_etags = (MISSING, None, "")

        def valid_etag(value):
            return value in empty_etags or (isinstance(value, str) and bool(value))

        if (not valid_etag(before_etag) or not valid_etag(after_etag)
                or before_etag == after_etag
                or (before_etag in empty_etags and after_etag in empty_etags)):
            return False
        # Project policy etags are concurrency metadata. Require every grant
        # field and all other provider values to remain identical.
        return ({key: value for key, value in before.items() if key != "etag"}
                == {key: value for key, value in after.items() if key != "etag"})

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

    if address == REGISTRY_ADDRESS:
        expected_identity = (PROJECT, "us-east1", "helpdeskcloud-dev-images")
        if (tuple(before.get(key) for key in ("project", "location", "repository_id")) != expected_identity
                or tuple(after.get(key) for key in ("project", "location", "repository_id")) != expected_identity
                or before.get("labels", MISSING) is not None or after.get("labels", MISSING) != {}
                or before.get("terraform_labels", MISSING) != ATTRIBUTION_LABEL
                or after.get("terraform_labels", MISSING) != ATTRIBUTION_LABEL
                or before.get("effective_labels", MISSING) != ATTRIBUTION_LABEL
                or after.get("effective_labels", MISSING) != ATTRIBUTION_LABEL):
            return False
        return {k: v for k, v in before.items() if k != "labels"} == {
            k: v for k, v in after.items() if k != "labels"}

    if address == SQL_ADDRESS:
        identity = (PROJECT, "helpdeskcloud-dev-postgres", "us-east1", "POSTGRES_17")
        if (tuple(before.get(key) for key in ("project", "name", "region", "database_version")) != identity
                or tuple(after.get(key) for key in ("project", "name", "region", "database_version")) != identity):
            return False
        before_settings, after_settings = before.get("settings"), after.get("settings")
        if (not isinstance(before_settings, list) or len(before_settings) != 1
                or not isinstance(after_settings, list) or len(after_settings) != 1
                or not isinstance(before_settings[0], dict) or not isinstance(after_settings[0], dict)):
            return False
        before_config = before_settings[0].get("ip_configuration")
        after_config = after_settings[0].get("ip_configuration")
        if (type(before_settings[0].get("version")) is not int or before_settings[0]["version"] != 1
                or type(after_settings[0].get("version")) is not int or after_settings[0]["version"] != 3
                or not isinstance(before_config, list) or len(before_config) != 1
                or not isinstance(after_config, list) or len(after_config) != 1
                or not isinstance(before_config[0], dict) or not isinstance(after_config[0], dict)
                or before_config[0].get("server_ca_mode") != "GOOGLE_MANAGED_INTERNAL_CA"
                or after_config[0].get("server_ca_mode") != "GOOGLE_MANAGED_INTERNAL_CA"
                or before_config[0].get("custom_subject_alternative_names", MISSING) is not None
                or after_config[0].get("custom_subject_alternative_names", MISSING) != []):
            return False
        # settings.version is Cloud SQL's concurrency generation. Remove only the two
        # observed normalization fields before comparing the complete snapshots.
        before_copy, after_copy = deepcopy(before), deepcopy(after)
        before_copy["settings"][0].pop("version")
        after_copy["settings"][0].pop("version")
        before_copy["settings"][0]["ip_configuration"][0].pop("custom_subject_alternative_names")
        after_copy["settings"][0]["ip_configuration"][0].pop("custom_subject_alternative_names")
        return before_copy == after_copy

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
        requested = [change for change in plan.get("resource_changes", [])
                     if change.get("address") == entry.get("address")]
        require(all(change.get("change", {}).get("actions") == ["no-op"] for change in requested),
                "Provider drift is readback only; a proposed resource change requires review")


def check_plan(plan):
    for name, expected in {"project_id": PROJECT, "region": "us-east1", "environment": "dev"}.items():
        require(plan.get("variables", {}).get(name, {}).get("value") == expected, f"Unexpected {name}")
    # Drift is separate from requested actions; only exact, tested readbacks are allowed.
    check_drift(plan)
    planned = planned_resources(plan.get("planned_values", {}).get("root_module", {}))
    managed = [r for r in planned if r.get("mode") == "managed"]
    require(len(managed) == len(EXPECTED) and {r.get("address") for r in managed} == set(EXPECTED),
            "Planned Dev infrastructure must contain exactly the approved addresses")
    require(all(r.get("type") == EXPECTED[r["address"]] for r in managed),
            "Unexpected planned resource type")
    changes = [c for c in plan.get("resource_changes", []) if c.get("mode") == "managed"]
    require(len({c.get("address") for c in changes}) == len(changes), "Duplicate resource change")
    require(all(c.get("address") in EXPECTED and c.get("type") == EXPECTED[c["address"]] for c in changes),
            "Unexpected resource address or type")
    actions = {c["address"]: c.get("change", {}).get("actions") for c in changes}
    require(all(actions.get(address, ["no-op"]) == ["no-op"] for address in BASE),
            "Existing Phase 5-6 resource change, replacement, or deletion requires review")
    creates = {address for address in PHASE7 if actions.get(address) == ["create"]}
    require(all(actions.get(address, ["no-op"]) in (["create"], ["no-op"]) for address in PHASE7),
            "Phase 7 update, replacement, or deletion requires review")
    prior_state = plan.get("prior_state")
    require(isinstance(prior_state, dict), "Terraform prior state is required to classify the Dev plan")
    prior = prior_state.get("values", {}).get("root_module")
    require(isinstance(prior, dict), "Terraform prior state is required to classify the Dev plan")
    prior_managed = [r for r in state_resources(prior) if r.get("mode") == "managed"]
    prior_addresses = [r.get("address") for r in prior_managed]
    require(len(set(prior_addresses)) == len(prior_addresses), "Duplicate Terraform prior-state resource")
    require(all(address in EXPECTED for address in prior_addresses),
            "Terraform prior state contains an unexpected managed resource")
    prior_types = {r["address"]: r.get("type") for r in prior_managed}
    require(all(prior_types.get(address) == kind for address, kind in EXPECTED.items()
                if address in prior_types), "Terraform prior state has an unexpected resource type")
    prior_addresses = set(prior_addresses)
    require(set(BASE) <= prior_addresses,
            "Terraform prior state is missing an existing Phase 5-6 resource")
    prior_phase7 = prior_addresses & set(PHASE7)
    full_initial_create = creates == set(PHASE7) and not prior_phase7
    exact_apply12_recovery = creates == APPLY12_REMAINING and prior_phase7 == APPLY12_COMPLETED
    complete_no_changes = not creates and prior_phase7 == set(PHASE7)
    require(full_initial_create or exact_apply12_recovery or complete_no_changes,
            "Partial or inconsistent Phase 7 state/creation batch requires review")
    # Check the complete planned values, including no-op resources omitted from resource_changes.
    by_address = {r["address"]: r.get("values", {}) for r in managed}
    by_type = {r["type"]: r.get("values", {}) for r in managed if r["address"] in BASE}
    check_network(by_type)
    check_phase6(by_type)
    check_phase7(by_address, plan, creates)
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


def safe_drift_path(path, secret=False):
    """Do not expose user-defined map keys or unknown secret paths in logs."""
    if secret:
        for field in SECRET_EMPTY_MAP_FIELDS:
            if path == field:
                return field
            if path.startswith(field + "."):
                return field + ".<key withheld>"
        return "<other secret path withheld>"
    for field in ("labels", "terraform_labels", "effective_labels", "annotations",
                  "effective_annotations", "version_aliases"):
        if path.startswith(field + "."):
            return field + ".<key withheld>"
    return path


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


def empty_map_status(value):
    """Classify optional Secret Manager maps without exposing keys or values."""
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if value == {}:
        return "empty map"
    return "<unexpected value withheld>"


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


def empty_set_status(value):
    """Classify optional API lists without printing any configured names."""
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if value == []:
        return "[]"
    return "<unexpected value withheld>"


def settings_version_status(value):
    """The Cloud SQL settings generation is non-secret; reject other value types."""
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if type(value) is int and 0 <= value < 10**18:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 18:
        return value
    return "<unexpected value withheld>"


def single_block(value):
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return {}


def ca_mode_status(value):
    if value in ("GOOGLE_MANAGED_INTERNAL_CA", "GOOGLE_MANAGED_CAS_CA", "CUSTOMER_MANAGED_CAS_CA"):
        return value
    return known_value(value)


def diagnose_drift(plan):
    drift = plan.get("resource_drift", [])
    if not drift:
        return ["No resource_drift entries in this plan; this does not prove the earlier drift is resolved."]
    lines = [f"Terraform reported drift for {len(drift)} resource(s). Only approved non-secret fields are classified."]
    for entry in drift:
        change = entry.get("change", {})
        secret = entry.get("address") in SECRET_READBACK_NAMES
        paths = list(dict.fromkeys(safe_drift_path(path, secret=secret)
                                   for path in changed_paths(change.get("before"), change.get("after"))))
        paths = paths or ["<unknown>"]
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
        if entry.get("address") == REGISTRY_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            identity = all(snapshot.get("project") == PROJECT
                           and snapshot.get("location") == "us-east1"
                           and snapshot.get("repository_id") == "helpdeskcloud-dev-images"
                           for snapshot in (before, after))
            lines.append("  repository identity: " + ("expected" if identity else "unexpected (values withheld)"))
            lines.append("  labels: before=" + classify_address_labels(before.get("labels", MISSING))
                         + "; after=" + classify_address_labels(after.get("labels", MISSING)))
            for field in ("terraform_labels", "effective_labels"):
                first, second = before.get(field, MISSING), after.get(field, MISSING)
                lines.append("  " + field + ": before=" + attribution_status(first)
                             + "; after=" + attribution_status(second)
                             + "; exact attribution only=" + str(first == second == ATTRIBUTION_LABEL).lower()
                             + "; unchanged=" + str(first == second).lower())
        if entry.get("address") == SQL_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            identity = all(snapshot.get("project") == PROJECT
                           and snapshot.get("name") == "helpdeskcloud-dev-postgres"
                           and snapshot.get("region") == "us-east1"
                           and snapshot.get("database_version") == "POSTGRES_17"
                           for snapshot in (before, after))
            lines.append("  Cloud SQL identity and PostgreSQL 17: "
                         + ("expected" if identity else "unexpected (values withheld)"))
            first_settings, second_settings = single_block(before.get("settings")), single_block(after.get("settings"))
            lines.append("  settings[0].version: before="
                         + settings_version_status(first_settings.get("version", MISSING))
                         + "; after=" + settings_version_status(second_settings.get("version", MISSING)))
            first_ip = single_block(first_settings.get("ip_configuration"))
            second_ip = single_block(second_settings.get("ip_configuration"))
            for field in ("server_ca_mode", "custom_subject_alternative_names"):
                classify = ca_mode_status if field == "server_ca_mode" else empty_set_status
                lines.append("  settings[0].ip_configuration[0]." + field + ": before="
                             + classify(first_ip.get(field, MISSING))
                             + "; after=" + classify(second_ip.get(field, MISSING)))
        if entry.get("address") in SECRET_READBACK_NAMES and isinstance(before, dict) and isinstance(after, dict):
            for field in SECRET_EMPTY_MAP_FIELDS:
                lines.append("  " + field + ": before=" + empty_map_status(before.get(field, MISSING))
                             + "; after=" + empty_map_status(after.get(field, MISSING)))
    lines.append("Only exact documented normalization patterns may pass; all other drift remains blocked.")
    return lines


def verify_deployment(paths):
    require(len(paths) == 22, "Expected read-only Phase 7 evidence, Terraform state, and addresses")
    network, subnet, address, connections, registry, registry_iam, project_iam, sql, databases, outputs = [read_json(p) for p in paths[:10]]
    state_addresses = set(Path(paths[-1]).read_text(encoding="utf-8").splitlines())
    require(state_addresses == set(EXPECTED), "Dev state does not contain exactly the approved resources")
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

    verify_phase7(*[read_json(path) for path in paths[10:20]], registry_iam, project_iam, outputs)
    state = read_json(paths[20])
    resources = state.get("values", {}).get("root_module", {}).get("resources", [])
    protected = {
        "google_container_cluster.dev[0]": "GKE",
        "google_secret_manager_secret.dev_app_connection[0]": "application secret",
        "google_secret_manager_secret.dev_admin_password[0]": "migration secret",
    }
    for resource_address, label in protected.items():
        matching = [r for r in resources if r.get("address") == resource_address]
        require(len(matching) == 1 and matching[0].get("values", {}).get("deletion_protection") is True,
                f"Terraform {label} deletion protection is missing")


def has_binding(policy, role, member):
    return any(binding.get("role") == role and member in binding.get("members", [])
               for binding in policy.get("bindings", []))


def verify_phase7(cluster, node_sa, app_sa, migration_sa, app_secret, admin_secret,
                  app_sa_iam, migration_sa_iam, app_secret_iam, admin_secret_iam,
                  registry_iam, project_iam, outputs):
    """Use documented GKE and Secret Manager API fields; do not read secret versions."""
    require(cluster.get("name") == "helpdeskcloud-dev-gke" and cluster.get("location") == "us-east1"
            and cluster.get("status") == "RUNNING", "GKE identity or status verification failed")
    require(cluster.get("autopilot", {}).get("enabled") is True, "GKE Autopilot is not enabled")
    require(cluster.get("network") in (VPC, VPC_PATH, VPC_LINK), "GKE is attached to a different VPC")
    subnet_path = f"projects/{PROJECT}/regions/us-east1/subnetworks/{SUBNET}"
    subnet_link = f"https://www.googleapis.com/compute/v1/{subnet_path}"
    require(cluster.get("subnetwork") in (SUBNET, subnet_path, subnet_link), "GKE is attached to a different subnet")
    # The API's networkConfig reports project-qualified paths even if the top-level name is short.
    require(cluster.get("networkConfig", {}).get("network") == VPC_PATH
            and cluster.get("networkConfig", {}).get("subnetwork") == subnet_path,
            "GKE networkConfig does not identify the intended project and subnet")
    ranges = cluster.get("ipAllocationPolicy", {})
    require(ranges.get("useIpAliases") is True
            and ranges.get("clusterSecondaryRangeName") == "helpdeskcloud-dev-pods"
            and ranges.get("servicesSecondaryRangeName") == "helpdeskcloud-dev-services",
            "GKE alias IP mode or secondary ranges do not match the existing subnet")
    require(cluster.get("privateClusterConfig", {}).get("enablePrivateNodes") is True
            or cluster.get("networkConfig", {}).get("defaultEnablePrivateNodes") is True,
            "GKE nodes are not confirmed private")
    endpoints = cluster.get("controlPlaneEndpointsConfig", {})
    require(endpoints.get("ipEndpointsConfig", {}).get("enabled") is False
            and endpoints.get("dnsEndpointConfig", {}).get("allowExternalTraffic") is True,
            "GKE control plane endpoints are not the reviewed DNS-only design")
    require(cluster.get("workloadIdentityConfig", {}).get("workloadPool") == f"{PROJECT}.svc.id.goog",
            "GKE Workload Identity pool mismatch")
    require(cluster.get("secretManagerConfig", {}).get("enabled") is True,
            "Managed Secret Manager add-on is missing")
    require(cluster.get("releaseChannel", {}).get("channel") == "REGULAR", "GKE release channel mismatch")
    node_email = f"helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com"
    app_email = f"helpdesk-app-dev@{PROJECT}.iam.gserviceaccount.com"
    migration_email = f"helpdesk-migrate-dev@{PROJECT}.iam.gserviceaccount.com"
    node_config = cluster.get("autoscaling", {}).get("autoprovisioningNodePoolDefaults", {})
    require(node_config.get("serviceAccount") == node_email, "GKE node identity mismatch")

    for account, email in ((node_sa, node_email), (app_sa, app_email), (migration_sa, migration_email)):
        require(account.get("email") == email and account.get("disabled") is not True,
                "GKE service account identity or status mismatch")

    require(has_binding(project_iam, "roles/container.defaultNodeServiceAccount", f"serviceAccount:{node_email}"),
            "GKE node runtime role is missing")
    require(has_binding(registry_iam, "roles/artifactregistry.reader", f"serviceAccount:{node_email}"),
            "GKE node repository Reader grant is missing")
    for email in (app_email, migration_email):
        require(has_binding(project_iam, "roles/cloudsql.client", f"serviceAccount:{email}"),
                "Cloud SQL Client grant is missing")
    for policy, members in ((project_iam, {f"serviceAccount:{node_email}",
                                           f"serviceAccount:{app_email}", f"serviceAccount:{migration_email}"}),
                            (registry_iam, {f"serviceAccount:{node_email}"})):
        forbidden = {"roles/owner", "roles/editor", "roles/compute.admin", "roles/container.admin",
                     "roles/cloudsql.admin", "roles/artifactregistry.admin", "roles/secretmanager.admin"}
        require(not any(binding.get("role") in forbidden and members.intersection(binding.get("members", []))
                        for binding in policy.get("bindings", [])),
                "A Phase 7 runtime identity has an unapproved administrative role")

    for policy, email, ksa in ((app_sa_iam, app_email, "helpdesk-dev-app"),
                               (migration_sa_iam, migration_email, "helpdesk-dev-migrate")):
        check_iam(policy, email)
        member = f"serviceAccount:{PROJECT}.svc.id.goog[helpdesk-dev/{ksa}]"
        bindings = [set(b.get("members", [])) for b in policy.get("bindings", [])
                    if b.get("role") == "roles/iam.workloadIdentityUser"]
        require(bindings == [{member}], "Workload Identity binding differs from the intended KSA")
        require(len(policy.get("bindings", [])) == 1, "Unexpected service account IAM binding")

    for secret, policy, name, ksa in (
        (app_secret, app_secret_iam, "helpdesk-dev-db-connection", "helpdesk-dev-app"),
        (admin_secret, admin_secret_iam, "helpdesk-dev-db-admin-password", "helpdesk-dev-migrate"),
    ):
        # Secret Manager can return the canonical resource name with the
        # project's numeric ID even when the request used its project ID.
        expected_names = {
            f"projects/{PROJECT}/secrets/{name}",
            f"projects/{PROJECT_NUMBER}/secrets/{name}",
        }
        require(secret.get("name") in expected_names
                and isinstance(secret.get("replication", {}).get("automatic"), dict),
                "Secret Manager metadata or replication mismatch")
        check_iam(policy, name)
        member = (f"principal://iam.googleapis.com/projects/260283083469/locations/global/"
                  f"workloadIdentityPools/{PROJECT}.svc.id.goog/subject/ns/helpdesk-dev/sa/{ksa}")
        bindings = [set(b.get("members", [])) for b in policy.get("bindings", [])
                    if b.get("role") == "roles/secretmanager.secretAccessor"]
        require(bindings == [{member}], "Secret access is not limited to the intended KSA")
        require(len(policy.get("bindings", [])) == 1, "Unexpected direct secret IAM binding")

    for key, expected in {
        "gke_cluster_name": "helpdeskcloud-dev-gke", "gke_cluster_location": "us-east1",
        "gke_mode": "AUTOPILOT", "gke_workload_pool": f"{PROJECT}.svc.id.goog",
        "gke_node_service_account": node_email, "app_service_account": app_email,
        "migration_service_account": migration_email,
        "app_connection_secret": f"projects/{PROJECT}/secrets/helpdesk-dev-db-connection",
        "migration_admin_secret": f"projects/{PROJECT}/secrets/helpdesk-dev-db-admin-password",
    }.items():
        require(outputs.get(key, {}).get("value") == expected, f"Terraform output {key} mismatch")


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
        elif len(sys.argv) == 24 and sys.argv[1] == "verify-deployment":
            verify_deployment(sys.argv[2:])
            print("Approved Dev resources, IAM, outputs, and deletion protection verified")
        else:
            raise ValueError("Usage: dev_infra_guard.py check-plan PLAN_JSON | diagnose-drift PLAN_JSON | "
                             "check-project-iam PROJECT_IAM_JSON | "
                             "verify-deployment VPC SUBNET ADDRESS CONNECTIONS REGISTRY REGISTRY_IAM PROJECT_IAM SQL DATABASES OUTPUTS "
                             "CLUSTER NODE_SA APP_SA MIGRATION_SA APP_SECRET ADMIN_SECRET APP_SA_IAM MIGRATION_SA_IAM "
                             "APP_SECRET_IAM ADMIN_SECRET_IAM STATE_JSON STATE_LIST")
    except (ValueError, KeyError, IndexError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"Dev infrastructure guard stopped: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
