"""Check the saved Dev plan and read-only post-apply evidence.

The workflow stores JSON in the runner's temporary directory. This script prints
only a decision or a short error, never plan or state contents.
"""

import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import datetime
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
    "google_secret_manager_secret_iam_member.dev_migration_gsa_secret_access[0]": "google_secret_manager_secret_iam_member",
}
MIGRATION_GSA_SECRET_ACCESS_ADDRESS = (
    "google_secret_manager_secret_iam_member.dev_migration_gsa_secret_access[0]"
)
# Phase 8 adds one exact, separately scoped GitHub publisher identity. The plan
# guard accepts this as one complete create batch after Phase 7 is already present.
PHASE8 = {
    "google_service_account.dev_app_support_image_publisher[0]": "google_service_account",
    "google_iam_workload_identity_pool_provider.dev_app_support_images[0]": "google_iam_workload_identity_pool_provider",
    "google_service_account_iam_member.dev_app_support_images_wif[0]": "google_service_account_iam_member",
    "google_artifact_registry_repository_iam_member.dev_app_support_images_writer[0]": "google_artifact_registry_repository_iam_member",
}
PHASE8_PROVIDER_ADDRESS = "google_iam_workload_identity_pool_provider.dev_app_support_images[0]"
PHASE8_COMPLETED = frozenset(PHASE8) - {PHASE8_PROVIDER_ADDRESS}
PHASE9 = {
    "google_service_account.dev_app_migration_runner[0]": "google_service_account",
    "google_iam_workload_identity_pool_provider.dev_app_migration[0]": "google_iam_workload_identity_pool_provider",
    "google_service_account_iam_member.dev_app_migration_runner_wif[0]": "google_service_account_iam_member",
    "google_project_iam_member.dev_app_migration_runner_cluster_viewer[0]": "google_project_iam_member",
}
PHASE10 = {
    "google_service_account.dev_app_publisher[0]": "google_service_account",
    "google_iam_workload_identity_pool_provider.dev_app_publish[0]": "google_iam_workload_identity_pool_provider",
    "google_service_account_iam_member.dev_app_publisher_wif[0]": "google_service_account_iam_member",
    "google_artifact_registry_repository_iam_member.dev_app_publisher_writer[0]": "google_artifact_registry_repository_iam_member",
    "google_service_account.dev_app_deployer[0]": "google_service_account",
    "google_iam_workload_identity_pool_provider.dev_app_deploy[0]": "google_iam_workload_identity_pool_provider",
    "google_service_account_iam_member.dev_app_deployer_wif[0]": "google_service_account_iam_member",
    "google_project_iam_member.dev_app_deployer_cluster_viewer[0]": "google_project_iam_member",
    "google_secret_manager_secret_iam_member.dev_app_gsa_secret_access[0]": "google_secret_manager_secret_iam_member",
}
DEPLOYMENT_EVIDENCE_PATH_COUNT = 34
ARTIFACT_READER_IAM_ADDRESS = "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]"
SUPPORT_PUBLISHER_ACCOUNT_ID = "helpdesk-app-support-pub-dev"
SUPPORT_PUBLISHER_DISPLAY_NAME = "helpdesk-app-support-image-publisher-dev"
SUPPORT_PUBLISHER_EMAIL = f"{SUPPORT_PUBLISHER_ACCOUNT_ID}@{PROJECT}.iam.gserviceaccount.com"
SUPPORT_PUBLISHER_PROVIDER_ID = "github-app-support-images-dev"
SUPPORT_PUBLISHER_SUBJECT = (
    "repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:"
    "environment:dev-supporting-images-publish"
)
SUPPORT_PUBLISHER_WORKFLOW_REF = (
    "mhachem110/HelpDeskCloud-App/.github/workflows/"
    "supporting-images-ci.yml@refs/heads/dev"
)
SUPPORT_PUBLISHER_CONDITION = (
    'attribute.repository == "mhachem110/HelpDeskCloud-App" && '
    'attribute.repository_id == "1423008128" && '
    'attribute.repository_owner_id == "150286776" && '
    'attribute.ref == "refs/heads/dev" && '
    'attribute.environment == "dev-supporting-images-publish" && '
    'attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/'
    'supporting-images-ci.yml@refs/heads/dev"'
)
SUPPORT_PUBLISHER_MAPPING = {
    "google.subject": "assertion.sub",
    "attribute.repository": "assertion.repository",
    "attribute.repository_id": "assertion.repository_id",
    "attribute.repository_owner_id": "assertion.repository_owner_id",
    "attribute.ref": "assertion.ref",
    "attribute.environment": "assertion.environment",
    "attribute.workflow_ref": "assertion.workflow_ref",
}
SUPPORT_PUBLISHER_MEMBER = (
    f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
    f"workloadIdentityPools/helpdesk-github/subject/{SUPPORT_PUBLISHER_SUBJECT}"
)
APP_DELIVERY_MAPPING = SUPPORT_PUBLISHER_MAPPING
APP_PUBLISHER_ACCOUNT_ID = "helpdesk-app-publisher-dev"
APP_PUBLISHER_DISPLAY_NAME = "HelpDesk Dev application image publisher"
APP_PUBLISHER_EMAIL = f"{APP_PUBLISHER_ACCOUNT_ID}@{PROJECT}.iam.gserviceaccount.com"
APP_PUBLISHER_PROVIDER_ID = "github-app-publish-dev"
APP_PUBLISHER_SUBJECT = (
    "repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:"
    "environment:dev-app-publish"
)
APP_PUBLISHER_CONDITION = (
    'attribute.repository == "mhachem110/HelpDeskCloud-App" && '
    'attribute.repository_id == "1423008128" && '
    'attribute.repository_owner_id == "150286776" && '
    'attribute.ref == "refs/heads/dev" && '
    'attribute.environment == "dev-app-publish" && '
    'attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/'
    'app-dev-delivery.yml@refs/heads/dev"'
)
APP_PUBLISHER_MEMBER = (
    f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
    f"workloadIdentityPools/helpdesk-github/subject/{APP_PUBLISHER_SUBJECT}"
)
APP_DEPLOYER_ACCOUNT_ID = "helpdesk-app-deployer-dev"
APP_DEPLOYER_DISPLAY_NAME = "HelpDesk Dev application deployer"
APP_DEPLOYER_EMAIL = f"{APP_DEPLOYER_ACCOUNT_ID}@{PROJECT}.iam.gserviceaccount.com"
APP_DEPLOYER_PROVIDER_ID = "github-app-deploy-dev"
APP_DEPLOYER_SUBJECT = (
    "repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:"
    "environment:dev-app-deploy"
)
APP_DEPLOYER_CONDITION = (
    'attribute.repository == "mhachem110/HelpDeskCloud-App" && '
    'attribute.repository_id == "1423008128" && '
    'attribute.repository_owner_id == "150286776" && '
    'attribute.ref == "refs/heads/dev" && '
    'attribute.environment == "dev-app-deploy" && '
    'attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/'
    'app-dev-delivery.yml@refs/heads/dev"'
)
APP_DEPLOYER_MEMBER = (
    f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
    f"workloadIdentityPools/helpdesk-github/subject/{APP_DEPLOYER_SUBJECT}"
)
APP_DELIVERY_PROVIDER_READBACKS = {
    "google_iam_workload_identity_pool_provider.dev_app_publish[0]": (
        APP_PUBLISHER_PROVIDER_ID, APP_PUBLISHER_CONDITION,
    ),
    "google_iam_workload_identity_pool_provider.dev_app_deploy[0]": (
        APP_DEPLOYER_PROVIDER_ID, APP_DEPLOYER_CONDITION,
    ),
}
MIGRATION_RUNNER_ACCOUNT_ID = "helpdesk-app-migr-runner-dev"
MIGRATION_RUNNER_DISPLAY_NAME = "helpdesk-app-migration-runner-dev"
MIGRATION_RUNNER_EMAIL = f"{MIGRATION_RUNNER_ACCOUNT_ID}@{PROJECT}.iam.gserviceaccount.com"
MIGRATION_RUNNER_PROVIDER_ID = "github-app-migration-dev"
MIGRATION_RUNNER_PROVIDER_ADDRESS = (
    "google_iam_workload_identity_pool_provider.dev_app_migration[0]"
)
MIGRATION_RUNNER_PROVIDER_RESOURCE_ID = (
    f"projects/{PROJECT}/locations/global/workloadIdentityPools/"
    f"helpdesk-github/providers/{MIGRATION_RUNNER_PROVIDER_ID}"
)
MIGRATION_RUNNER_SUBJECT = (
    "repo:mhachem110@150286776/HelpDeskCloud-App@1423008128:"
    "environment:dev-db-migration"
)
MIGRATION_RUNNER_WORKFLOW_REF = (
    "mhachem110/HelpDeskCloud-App/.github/workflows/"
    "dev-db-migration.yml@refs/heads/dev"
)
MIGRATION_RUNNER_CONDITION = (
    'attribute.repository == "mhachem110/HelpDeskCloud-App" && '
    'attribute.repository_id == "1423008128" && '
    'attribute.repository_owner_id == "150286776" && '
    'attribute.ref == "refs/heads/dev" && '
    'attribute.environment == "dev-db-migration" && '
    'attribute.workflow_ref == "mhachem110/HelpDeskCloud-App/.github/workflows/'
    'dev-db-migration.yml@refs/heads/dev"'
)
MIGRATION_RUNNER_MEMBER = (
    f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
    f"workloadIdentityPools/helpdesk-github/subject/{MIGRATION_RUNNER_SUBJECT}"
)
MIGRATION_RUNNER_DNS_ENDPOINT = (
    "gke-2c60f148ddaa41c880bb7713114c59909a1a-260283083469.us-east1.gke.goog"
)
MIGRATION_RUNNER_CLUSTER_VIEWER_ADDRESS = (
    "google_project_iam_member.dev_app_migration_runner_cluster_viewer[0]"
)
MIGRATION_RUNNER_DNS_BINDING_ADDRESS = (
    "google_project_iam_member.dev_app_migration_runner_dns_endpoint[0]"
)
MIGRATION_RUNNER_DNS_BINDING_TITLE = "helpdesk-dev-migration-runner-dns-endpoint"
MIGRATION_RUNNER_DNS_BINDING_DESCRIPTION = (
    "Allow GKE connection only to the existing Dev DNS endpoint"
)
MIGRATION_RUNNER_DNS_BINDING_CONDITION = f'resource.name == "{MIGRATION_RUNNER_DNS_ENDPOINT}"'
MIGRATION_RUNNER_CLUSTER_VIEWER_CONDITION = (
    'resource.type == "container.googleapis.com/Cluster" && '
    f'resource.name == "projects/{PROJECT}/locations/us-east1/clusters/helpdeskcloud-dev-gke"'
)
# Previous Phase 9 applied two conditional bindings, neither of which authorized
# the DNS endpoint connect request. Accept this one legacy address only while
# the plan removes it as part of the exact project-level grant remediation.
LEGACY_PHASE9 = {
    MIGRATION_RUNNER_DNS_BINDING_ADDRESS: "google_project_iam_member",
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
EXPECTED = BASE | PHASE7 | PHASE8 | PHASE9 | PHASE10 | LEGACY_PHASE9
# Legacy addresses may exist in prior state and in the exact IAM remediation
# delete, but never in the final planned configuration.
PLANNED_EXPECTED = {address: resource_type for address, resource_type in EXPECTED.items()
                    if address not in LEGACY_PHASE9}
VPC_LINK = f"https://www.googleapis.com/compute/v1/projects/{PROJECT}/global/networks/{VPC}"
VPC_SELF_LINKS = tuple(
    f"https://www.googleapis.com/compute/v1/projects/{project}/global/networks/{VPC}"
    for project in (PROJECT, PROJECT_NUMBER)
)
VPC_PATH = f"projects/{PROJECT}/global/networks/{VPC}"
VPC_PEERING_PATH = f"projects/{PROJECT_NUMBER}/global/networks/{VPC}"
VPC_PATHS = (VPC_PATH, VPC_PEERING_PATH)
VPC_LINKS = VPC_SELF_LINKS + VPC_PATHS
SUBNET_PATHS = tuple(
    f"projects/{project}/regions/us-east1/subnetworks/{SUBNET}"
    for project in (PROJECT, PROJECT_NUMBER)
)
SUBNET_SELF_LINKS = tuple(
    f"https://www.googleapis.com/compute/v1/projects/{project}/regions/us-east1/subnetworks/{SUBNET}"
    for project in (PROJECT, PROJECT_NUMBER)
)
SUBNET_LINKS = SUBNET_SELF_LINKS + SUBNET_PATHS
GKE_NODE_SERVICE_ACCOUNT = f"helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com"
GKE_NODE_OAUTH_SCOPES = frozenset({
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
})
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
SECRET_IAM_READBACKS = {
    "google_secret_manager_secret_iam_member.dev_app_secret_access[0]": (
        "helpdesk-dev-db-connection",
        f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
        f"workloadIdentityPools/{PROJECT}.svc.id.goog/subject/ns/helpdesk-dev/sa/helpdesk-dev-app",
    ),
    "google_secret_manager_secret_iam_member.dev_app_gsa_secret_access[0]": (
        "helpdesk-dev-db-connection",
        f"serviceAccount:helpdesk-app-dev@{PROJECT}.iam.gserviceaccount.com",
    ),
    "google_secret_manager_secret_iam_member.dev_admin_secret_access[0]": (
        "helpdesk-dev-db-admin-password",
        f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
        f"workloadIdentityPools/{PROJECT}.svc.id.goog/subject/ns/helpdesk-dev/sa/helpdesk-dev-migrate",
    ),
    MIGRATION_GSA_SECRET_ACCESS_ADDRESS: (
        "helpdesk-dev-db-admin-password",
        f"serviceAccount:helpdesk-migrate-dev@{PROJECT}.iam.gserviceaccount.com",
    ),
}
SECRET_ACCESSOR_ROLE = "roles/secretmanager.secretAccessor"
PROJECT_IAM_READBACKS = {
    MIGRATION_RUNNER_CLUSTER_VIEWER_ADDRESS: (
        "roles/container.clusterViewer",
        f"serviceAccount:helpdesk-app-migr-runner-dev@{PROJECT}.iam.gserviceaccount.com",
    ),
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
    "google_project_iam_member.dev_app_deployer_cluster_viewer[0]": (
        "roles/container.clusterViewer",
        f"serviceAccount:{APP_DEPLOYER_EMAIL}",
    ),
}
SECRET_EMPTY_MAP_FIELDS = ("annotations", "labels", "version_aliases")
ATTRIBUTION_LABEL = {"goog-terraform-provisioned": "true"}
MISSING = object()
RFC3339_TIMESTAMP = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Terraform records these counted resource traversals alongside their selected
# attribute. Keep this allowlist literal: another instance, attribute, or
# resource must not become an approved identity reference by prefix matching.
STRICT_REFERENCE_PARENTS = {
    "google_service_account.dev_gke_nodes[0]": "google_service_account.dev_gke_nodes",
    "google_service_account.dev_app[0]": "google_service_account.dev_app",
    "google_service_account.dev_migration[0]": "google_service_account.dev_migration",
    "google_service_account.dev_app_support_image_publisher[0]": "google_service_account.dev_app_support_image_publisher",
    "google_service_account.dev_app_migration_runner[0]": "google_service_account.dev_app_migration_runner",
    "google_service_account.dev_app_publisher[0]": "google_service_account.dev_app_publisher",
    "google_service_account.dev_app_deployer[0]": "google_service_account.dev_app_deployer",
    "google_artifact_registry_repository.dev_images[0]": "google_artifact_registry_repository.dev_images",
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


def normalize_cel(expression):
    """Collapse CEL whitespace outside string literals without changing claims."""
    if not isinstance(expression, str):
        return None

    normalized = []
    in_string = False
    escaped = False
    pending_space = False
    for character in expression:
        if in_string:
            normalized.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character.isspace():
            pending_space = True
        else:
            if pending_space and normalized:
                normalized.append(" ")
            normalized.append(character)
            pending_space = False
            if character == '"':
                in_string = True
    return "".join(normalized).strip()


def check_phase8(values, plan, creates, addresses=None):
    addresses = set(PHASE8) if addresses is None else set(addresses)
    require(addresses <= set(PHASE8), "Unexpected Phase 8 resource validation scope")
    changes = {c.get("address"): c for c in plan.get("resource_changes", [])}
    account_address = "google_service_account.dev_app_support_image_publisher[0]"
    if account_address in addresses:
        account = values[account_address]
        require(account.get("project") == PROJECT
                and account.get("account_id") == SUPPORT_PUBLISHER_ACCOUNT_ID
                and account.get("display_name") == SUPPORT_PUBLISHER_DISPLAY_NAME,
                "Unexpected supporting-image publisher service account")
        for field, expected in (
            ("email", SUPPORT_PUBLISHER_EMAIL),
            ("member", f"serviceAccount:{SUPPORT_PUBLISHER_EMAIL}"),
            ("name", f"projects/{PROJECT}/serviceAccounts/{SUPPORT_PUBLISHER_EMAIL}"),
        ):
            expected_or_unknown(account, account_address, (field,), expected, changes, creates,
                                f"supporting-image service-account {field}")

    if PHASE8_PROVIDER_ADDRESS in addresses:
        provider = values[PHASE8_PROVIDER_ADDRESS]
        require(provider.get("project") == PROJECT
                and provider.get("workload_identity_pool_id") == "helpdesk-github"
                and provider.get("workload_identity_pool_provider_id") == SUPPORT_PUBLISHER_PROVIDER_ID
                and provider.get("disabled") is False,
                "Unexpected supporting-image Workload Identity provider")
        require(provider.get("attribute_mapping") == SUPPORT_PUBLISHER_MAPPING,
                "Unexpected supporting-image provider attribute mapping")
        require(normalize_cel(provider.get("attribute_condition")) == SUPPORT_PUBLISHER_CONDITION,
                "Supporting-image provider trust condition is not exact")
        oidc = only_item(provider.get("oidc"), "Expected one supporting-image OIDC issuer")
        require(oidc.get("issuer_uri") == "https://token.actions.githubusercontent.com",
                "Unexpected supporting-image OIDC issuer")

    binding_address = "google_service_account_iam_member.dev_app_support_images_wif[0]"
    if binding_address in addresses:
        binding = values[binding_address]
        require(binding.get("role") == "roles/iam.workloadIdentityUser"
                and binding.get("member") == SUPPORT_PUBLISHER_MEMBER,
                "Supporting-image impersonation binding must use the exact verified subject")
        expected_or_unknown(binding, binding_address, ("service_account_id",),
                            f"projects/{PROJECT}/serviceAccounts/{SUPPORT_PUBLISHER_EMAIL}",
                            changes, creates, "supporting-image Workload Identity target")

    writer_address = "google_artifact_registry_repository_iam_member.dev_app_support_images_writer[0]"
    if writer_address in addresses:
        writer = values[writer_address]
        require(writer.get("project") == PROJECT and writer.get("location") == "us-east1"
                # The Google provider canonicalizes this IAM resource's repository
                # field to the full resource path during refresh/import. Accept only
                # that exact path or the repository ID used by the configuration.
                and writer.get("repository") in (REGISTRY_REPOSITORY_ID, REGISTRY_REPOSITORY_PATH)
                and writer.get("role") == "roles/artifactregistry.writer",
                "Supporting-image Writer must target only the existing Dev repository")
        expected_or_unknown(writer, writer_address, ("member",),
                            f"serviceAccount:{SUPPORT_PUBLISHER_EMAIL}",
                            changes, creates, "supporting-image repository writer")


def check_phase9(values, plan, creates):
    """Validate the runner and the project-level GKE DNS endpoint permission."""
    changes = {c.get("address"): c for c in plan.get("resource_changes", [])}
    account_address = "google_service_account.dev_app_migration_runner[0]"
    account = values[account_address]
    require(account.get("project") == PROJECT
            and account.get("account_id") == MIGRATION_RUNNER_ACCOUNT_ID
            and account.get("display_name") == MIGRATION_RUNNER_DISPLAY_NAME,
            "Unexpected Dev migration-runner service account")
    for field, expected in (
        ("email", MIGRATION_RUNNER_EMAIL),
        ("member", f"serviceAccount:{MIGRATION_RUNNER_EMAIL}"),
        ("name", f"projects/{PROJECT}/serviceAccounts/{MIGRATION_RUNNER_EMAIL}"),
    ):
        expected_or_unknown(account, account_address, (field,), expected, changes, creates,
                            f"migration-runner service-account {field}")

    provider_address = "google_iam_workload_identity_pool_provider.dev_app_migration[0]"
    provider = values[provider_address]
    require(provider.get("project") == PROJECT
            and provider.get("workload_identity_pool_id") == "helpdesk-github"
            and provider.get("workload_identity_pool_provider_id") == MIGRATION_RUNNER_PROVIDER_ID
            and provider.get("disabled") is False,
            "Unexpected Dev migration-runner Workload Identity provider")
    require(provider.get("attribute_mapping") == SUPPORT_PUBLISHER_MAPPING,
            "Unexpected Dev migration-runner provider attribute mapping")
    require(normalize_cel(provider.get("attribute_condition")) == MIGRATION_RUNNER_CONDITION,
            "Dev migration-runner provider trust condition is not exact")
    oidc = only_item(provider.get("oidc"), "Expected one Dev migration-runner OIDC issuer")
    require(oidc.get("issuer_uri") == "https://token.actions.githubusercontent.com",
            "Unexpected Dev migration-runner OIDC issuer")

    binding_address = "google_service_account_iam_member.dev_app_migration_runner_wif[0]"
    binding = values[binding_address]
    require(binding.get("role") == "roles/iam.workloadIdentityUser"
            and binding.get("member") == MIGRATION_RUNNER_MEMBER,
            "Migration-runner impersonation binding must use the exact verified Environment subject")
    expected_or_unknown(binding, binding_address, ("service_account_id",),
                        f"projects/{PROJECT}/serviceAccounts/{MIGRATION_RUNNER_EMAIL}",
                        changes, creates, "migration-runner Workload Identity target")

    viewer_address = "google_project_iam_member.dev_app_migration_runner_cluster_viewer[0]"
    viewer = values[viewer_address]
    require(viewer.get("project") in (PROJECT, PROJECT_NUMBER)
            and viewer.get("role") == "roles/container.clusterViewer",
            "Migration runner must receive the reviewed GKE clusterViewer role")
    expected_or_unknown(viewer, viewer_address, ("member",),
                        f"serviceAccount:{MIGRATION_RUNNER_EMAIL}", changes, creates,
                        "migration-runner GKE cluster identity")
    require(viewer.get("condition") in (None, []),
            "GKE DNS endpoint connect grant must be project-level and unconditional")


def check_phase10(values, plan, creates):
    """Validate the dedicated application publisher/deployer identities and runtime secret grant."""
    changes = {c.get("address"): c for c in plan.get("resource_changes", [])}
    account_specs = (
        ("google_service_account.dev_app_publisher[0]", APP_PUBLISHER_ACCOUNT_ID,
         APP_PUBLISHER_DISPLAY_NAME, APP_PUBLISHER_EMAIL, "application publisher"),
        ("google_service_account.dev_app_deployer[0]", APP_DEPLOYER_ACCOUNT_ID,
         APP_DEPLOYER_DISPLAY_NAME, APP_DEPLOYER_EMAIL, "application deployer"),
    )
    for address, account_id, display_name, email, label in account_specs:
        account = values[address]
        require(account.get("project") == PROJECT and account.get("account_id") == account_id
                and account.get("display_name") == display_name,
                f"Unexpected Dev {label} service account")
        for field, expected in (
            ("email", email),
            ("member", f"serviceAccount:{email}"),
            ("name", f"projects/{PROJECT}/serviceAccounts/{email}"),
        ):
            expected_or_unknown(account, address, (field,), expected, changes, creates,
                                f"{label} service-account {field}")

    provider_specs = (
        ("google_iam_workload_identity_pool_provider.dev_app_publish[0]",
         APP_PUBLISHER_PROVIDER_ID, APP_PUBLISHER_CONDITION, "application publisher"),
        ("google_iam_workload_identity_pool_provider.dev_app_deploy[0]",
         APP_DEPLOYER_PROVIDER_ID, APP_DEPLOYER_CONDITION, "application deployer"),
    )
    for address, provider_id, condition, label in provider_specs:
        provider = values[address]
        require(provider.get("project") == PROJECT
                and provider.get("workload_identity_pool_id") == "helpdesk-github"
                and provider.get("workload_identity_pool_provider_id") == provider_id
                and provider.get("disabled") is False,
                f"Unexpected Dev {label} Workload Identity provider")
        require(provider.get("attribute_mapping") == APP_DELIVERY_MAPPING
                and normalize_cel(provider.get("attribute_condition")) == condition,
                f"Dev {label} provider trust condition or mapping is not exact")
        oidc = only_item(provider.get("oidc"), f"Expected one Dev {label} OIDC issuer")
        require(oidc.get("issuer_uri") == "https://token.actions.githubusercontent.com",
                f"Unexpected Dev {label} OIDC issuer")

    for address, member, email, label in (
        ("google_service_account_iam_member.dev_app_publisher_wif[0]",
         APP_PUBLISHER_MEMBER, APP_PUBLISHER_EMAIL, "application publisher"),
        ("google_service_account_iam_member.dev_app_deployer_wif[0]",
         APP_DEPLOYER_MEMBER, APP_DEPLOYER_EMAIL, "application deployer"),
    ):
        binding = values[address]
        require(binding.get("role") == "roles/iam.workloadIdentityUser"
                and binding.get("member") == member,
                f"{label} impersonation binding must use the exact protected Environment subject")
        expected_or_unknown(binding, address, ("service_account_id",),
                            f"projects/{PROJECT}/serviceAccounts/{email}",
                            changes, creates, f"{label} Workload Identity target")

    writer_address = "google_artifact_registry_repository_iam_member.dev_app_publisher_writer[0]"
    writer = values[writer_address]
    require(writer.get("project") == PROJECT and writer.get("location") == "us-east1"
            and writer.get("repository") in (REGISTRY_REPOSITORY_ID, REGISTRY_REPOSITORY_PATH)
            and writer.get("role") == "roles/artifactregistry.writer",
            "Application publisher Writer must target only the existing Dev repository")
    expected_or_unknown(writer, writer_address, ("member",),
                        f"serviceAccount:{APP_PUBLISHER_EMAIL}",
                        changes, creates, "application publisher repository writer")

    viewer_address = "google_project_iam_member.dev_app_deployer_cluster_viewer[0]"
    viewer = values[viewer_address]
    require(viewer.get("project") in (PROJECT, PROJECT_NUMBER)
            and viewer.get("role") == "roles/container.clusterViewer",
            "Application deployer must use the reviewed GKE clusterViewer role")
    expected_or_unknown(viewer, viewer_address, ("member",),
                        f"serviceAccount:{APP_DEPLOYER_EMAIL}",
                        changes, creates, "application deployer GKE connect identity")
    require(viewer.get("condition") in (None, []),
            "GKE DNS endpoint connect grant must be project-level and unconditional")

    secret_address = "google_secret_manager_secret_iam_member.dev_app_gsa_secret_access[0]"
    secret_grant = values[secret_address]
    require(secret_grant.get("role") == "roles/secretmanager.secretAccessor",
            "Application runtime secret role must be Secret Manager Secret Accessor")
    expected_or_unknown(secret_grant, secret_address, ("secret_id",),
                        f"projects/{PROJECT}/secrets/helpdesk-dev-db-connection",
                        changes, creates, "application runtime connection-secret target")
    expected_or_unknown(secret_grant, secret_address, ("member",),
                        f"serviceAccount:helpdesk-app-dev@{PROJECT}.iam.gserviceaccount.com",
                        changes, creates, "application runtime Google service account")


def check_phase9_legacy_bindings(values):
    """Allow removal only of the exact pre-fix conditional Phase 9 IAM grants."""
    member = f"serviceAccount:{MIGRATION_RUNNER_EMAIL}"
    viewer_address = "google_project_iam_member.dev_app_migration_runner_cluster_viewer[0]"
    viewer = values.get(viewer_address, {})
    require(viewer.get("project") in (PROJECT, PROJECT_NUMBER)
            and viewer.get("role") == "roles/container.clusterViewer"
            and viewer.get("member") == member,
            "Legacy migration-runner clusterViewer binding identity is unexpected")
    condition = only_item(viewer.get("condition"), "Expected the legacy clusterViewer condition")
    require(condition.get("title") == "helpdesk-dev-migration-runner-cluster"
            and condition.get("description") == "Allow cluster discovery only for the existing Dev GKE cluster"
            and normalize_cel(condition.get("expression")) == MIGRATION_RUNNER_CLUSTER_VIEWER_CONDITION,
            "Legacy migration-runner clusterViewer condition is unexpected")

    dns_viewer = values.get(MIGRATION_RUNNER_DNS_BINDING_ADDRESS, {})
    require(dns_viewer.get("project") in (PROJECT, PROJECT_NUMBER)
            and dns_viewer.get("role") == "roles/container.clusterViewer"
            and dns_viewer.get("member") == member,
            "Legacy migration-runner DNS binding identity is unexpected")
    dns_condition = only_item(dns_viewer.get("condition"),
                              "Expected the legacy DNS endpoint condition")
    require(dns_condition.get("title") == MIGRATION_RUNNER_DNS_BINDING_TITLE
            and dns_condition.get("description") == MIGRATION_RUNNER_DNS_BINDING_DESCRIPTION
            and normalize_cel(dns_condition.get("expression")) == MIGRATION_RUNNER_DNS_BINDING_CONDITION,
            "Legacy migration-runner DNS condition is unexpected")


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
        ("google_service_account_iam_member.dev_app_support_images_wif", "service_account_id", "google_service_account.dev_app_support_image_publisher[0].name"),
        ("google_service_account_iam_member.dev_app_migration_runner_wif", "service_account_id", "google_service_account.dev_app_migration_runner[0].name"),
        ("google_service_account_iam_member.dev_app_publisher_wif", "service_account_id", "google_service_account.dev_app_publisher[0].name"),
        ("google_service_account_iam_member.dev_app_deployer_wif", "service_account_id", "google_service_account.dev_app_deployer[0].name"),
        ("google_project_iam_member.dev_app_migration_runner_cluster_viewer", "member", "google_service_account.dev_app_migration_runner[0].member"),
        ("google_project_iam_member.dev_app_deployer_cluster_viewer", "member", "google_service_account.dev_app_deployer[0].member"),
        ("google_secret_manager_secret_iam_member.dev_app_secret_access", "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access", "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
        ("google_secret_manager_secret_iam_member.dev_migration_gsa_secret_access", "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
        ("google_secret_manager_secret_iam_member.dev_migration_gsa_secret_access", "member", "google_service_account.dev_migration[0].member"),
        ("google_secret_manager_secret_iam_member.dev_app_gsa_secret_access", "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_app_gsa_secret_access", "member", "google_service_account.dev_app[0].member"),
        ("google_artifact_registry_repository_iam_member.dev_app_publisher_writer", "member", "google_service_account.dev_app_publisher[0].member"),
        ("google_artifact_registry_repository_iam_member.dev_app_publisher_writer", "location", "google_artifact_registry_repository.dev_images[0].location"),
        ("google_artifact_registry_repository_iam_member.dev_app_publisher_writer", "repository", "google_artifact_registry_repository.dev_images[0].repository_id"),
    ):
        references(resources.get(address, {}).get("expressions", {}).get(field, {}), expected, address,
                   exact=True)

    # These account identifiers are the source of computed service-account emails and names.
    for address, account_id in (
        ("google_service_account.dev_gke_nodes", "helpdesk-gke-node-dev"),
        ("google_service_account.dev_app", "helpdesk-app-dev"),
        ("google_service_account.dev_migration", "helpdesk-migrate-dev"),
        ("google_service_account.dev_app_support_image_publisher", SUPPORT_PUBLISHER_ACCOUNT_ID),
        ("google_service_account.dev_app_migration_runner", MIGRATION_RUNNER_ACCOUNT_ID),
        ("google_service_account.dev_app_publisher", APP_PUBLISHER_ACCOUNT_ID),
        ("google_service_account.dev_app_deployer", APP_DEPLOYER_ACCOUNT_ID),
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
        ("google_service_account_iam_member.dev_app_support_images_wif", "roles/iam.workloadIdentityUser",
         "service_account_id", "google_service_account.dev_app_support_image_publisher[0].name"),
        ("google_service_account_iam_member.dev_app_migration_runner_wif", "roles/iam.workloadIdentityUser",
         "service_account_id", "google_service_account.dev_app_migration_runner[0].name"),
        ("google_project_iam_member.dev_app_migration_runner_cluster_viewer", "roles/container.clusterViewer",
         "member", "google_service_account.dev_app_migration_runner[0].member"),
        ("google_project_iam_member.dev_app_deployer_cluster_viewer", "roles/container.clusterViewer",
         "member", "google_service_account.dev_app_deployer[0].member"),
        ("google_artifact_registry_repository_iam_member.dev_app_publisher_writer", "roles/artifactregistry.writer",
         "member", "google_service_account.dev_app_publisher[0].member"),
        ("google_secret_manager_secret_iam_member.dev_app_secret_access", "roles/secretmanager.secretAccessor",
         "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access", "roles/secretmanager.secretAccessor",
         "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
        ("google_secret_manager_secret_iam_member.dev_migration_gsa_secret_access", "roles/secretmanager.secretAccessor",
         "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
        ("google_secret_manager_secret_iam_member.dev_migration_gsa_secret_access", "roles/secretmanager.secretAccessor",
         "member", "google_service_account.dev_migration[0].member"),
        ("google_secret_manager_secret_iam_member.dev_app_gsa_secret_access", "roles/secretmanager.secretAccessor",
         "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_app_gsa_secret_access", "roles/secretmanager.secretAccessor",
         "member", "google_service_account.dev_app[0].member"),
    )
    for address, role, identity_field, identity_reference in role_specs:
        expressions = resources.get(address, {}).get("expressions", {})
        require(expressions.get("role", {}).get("constant_value") == role,
                f"Unexpected IAM role expression: {address}")
        references(expressions.get(identity_field, {}), identity_reference,
                   f"{address}.{identity_field}", exact=True)

    provider = resources.get("google_iam_workload_identity_pool_provider.dev_app_support_images", {})
    provider_expressions = provider.get("expressions", {})
    require(provider_expressions.get("workload_identity_pool_id", {}).get("constant_value") == "helpdesk-github"
            and provider_expressions.get("workload_identity_pool_provider_id", {}).get("constant_value")
            == SUPPORT_PUBLISHER_PROVIDER_ID,
            "Unexpected supporting-image provider identity expression")
    require(normalize_cel(provider_expressions.get("attribute_condition", {}).get("constant_value"))
            == SUPPORT_PUBLISHER_CONDITION,
            "Supporting-image provider trust expression is not exact")
    require(provider_expressions.get("attribute_mapping", {}).get("constant_value")
            == SUPPORT_PUBLISHER_MAPPING,
            "Supporting-image provider mapping expression is not exact")

    migration_provider = resources.get("google_iam_workload_identity_pool_provider.dev_app_migration", {})
    migration_provider_expressions = migration_provider.get("expressions", {})
    require(migration_provider_expressions.get("workload_identity_pool_id", {}).get("constant_value")
            == "helpdesk-github"
            and migration_provider_expressions.get("workload_identity_pool_provider_id", {}).get("constant_value")
            == MIGRATION_RUNNER_PROVIDER_ID,
            "Unexpected migration-runner provider identity expression")
    require(normalize_cel(migration_provider_expressions.get("attribute_condition", {}).get("constant_value"))
            == MIGRATION_RUNNER_CONDITION
            and migration_provider_expressions.get("attribute_mapping", {}).get("constant_value")
            == SUPPORT_PUBLISHER_MAPPING,
            "Migration-runner provider trust expression or mapping is not exact")

    app_provider_specs = (
        ("google_iam_workload_identity_pool_provider.dev_app_publish",
         APP_PUBLISHER_PROVIDER_ID, APP_PUBLISHER_CONDITION, "application publisher"),
        ("google_iam_workload_identity_pool_provider.dev_app_deploy",
         APP_DEPLOYER_PROVIDER_ID, APP_DEPLOYER_CONDITION, "application deployer"),
    )
    for address, provider_id, condition, label in app_provider_specs:
        expressions = resources.get(address, {}).get("expressions", {})
        require(expressions.get("workload_identity_pool_id", {}).get("constant_value") == "helpdesk-github"
                and expressions.get("workload_identity_pool_provider_id", {}).get("constant_value") == provider_id,
                f"Unexpected {label} provider identity expression")
        references(expressions.get("project", {}), "var.project_id", f"{label} provider project", exact=True)
        require(normalize_cel(expressions.get("attribute_condition", {}).get("constant_value")) == condition
                and expressions.get("attribute_mapping", {}).get("constant_value") == APP_DELIVERY_MAPPING,
                f"{label} provider trust condition or mapping expression is not exact")

    migration_binding = resources.get("google_service_account_iam_member.dev_app_migration_runner_wif", {})
    migration_binding_expressions = migration_binding.get("expressions", {})
    require(migration_binding_expressions.get("role", {}).get("constant_value")
            == "roles/iam.workloadIdentityUser"
            and migration_binding_expressions.get("member", {}).get("constant_value")
            == MIGRATION_RUNNER_MEMBER,
            "Migration-runner impersonation role or exact Environment subject is not configured")
    references(migration_binding_expressions.get("service_account_id", {}),
               "google_service_account.dev_app_migration_runner[0].name",
               "migration-runner Workload Identity target", exact=True)

    app_binding_specs = (
        ("google_service_account_iam_member.dev_app_publisher_wif",
         APP_PUBLISHER_MEMBER, "google_service_account.dev_app_publisher[0].name",
         "application publisher"),
        ("google_service_account_iam_member.dev_app_deployer_wif",
         APP_DEPLOYER_MEMBER, "google_service_account.dev_app_deployer[0].name",
         "application deployer"),
    )
    for address, member, target, label in app_binding_specs:
        expressions = resources.get(address, {}).get("expressions", {})
        require(expressions.get("role", {}).get("constant_value") == "roles/iam.workloadIdentityUser"
                and expressions.get("member", {}).get("constant_value") == member,
                f"{label} impersonation role or exact Environment subject is not configured")
        references(expressions.get("service_account_id", {}), target,
                   f"{label} Workload Identity target", exact=True)

    cluster_viewer = resources.get("google_project_iam_member.dev_app_migration_runner_cluster_viewer", {})
    cluster_viewer_expressions = cluster_viewer.get("expressions", {})
    require(cluster_viewer_expressions.get("role", {}).get("constant_value")
            == "roles/container.clusterViewer",
            "Migration-runner GKE clusterViewer role is not exact")
    references(cluster_viewer_expressions.get("project", {}), "var.project_id",
               "migration-runner IAM project", exact=True)
    references(cluster_viewer_expressions.get("member", {}),
               "google_service_account.dev_app_migration_runner[0].member",
               "migration-runner GKE connect identity", exact=True)
    require(not cluster_viewer_expressions.get("condition"),
            "Migration-runner DNS endpoint connect grant must not use an IAM condition")

    app_cluster_viewer = resources.get("google_project_iam_member.dev_app_deployer_cluster_viewer", {})
    app_cluster_viewer_expressions = app_cluster_viewer.get("expressions", {})
    require(app_cluster_viewer_expressions.get("role", {}).get("constant_value")
            == "roles/container.clusterViewer",
            "Application deployer GKE clusterViewer role is not exact")
    references(app_cluster_viewer_expressions.get("project", {}), "var.project_id",
               "application deployer IAM project", exact=True)
    references(app_cluster_viewer_expressions.get("member", {}),
               "google_service_account.dev_app_deployer[0].member",
               "application deployer GKE connect identity", exact=True)
    require(not app_cluster_viewer_expressions.get("condition"),
            "Application deployer DNS endpoint grant must not use an IAM condition")

    support_binding = resources.get("google_service_account_iam_member.dev_app_support_images_wif", {})
    support_binding_expressions = support_binding.get("expressions", {})
    require(support_binding_expressions.get("role", {}).get("constant_value")
            == "roles/iam.workloadIdentityUser"
            and support_binding_expressions.get("member", {}).get("constant_value") == SUPPORT_PUBLISHER_MEMBER,
            "Supporting-image impersonation role or subject expression is not exact")
    references(support_binding_expressions.get("service_account_id", {}),
               "google_service_account.dev_app_support_image_publisher[0].name",
               "supporting-image Workload Identity target", exact=True)

    support_writer = resources.get("google_artifact_registry_repository_iam_member.dev_app_support_images_writer", {})
    support_writer_expressions = support_writer.get("expressions", {})
    require(support_writer_expressions.get("role", {}).get("constant_value")
            == "roles/artifactregistry.writer",
            "Supporting-image repository role is not exact")
    references(support_writer_expressions.get("project", {}), "var.project_id",
               "supporting-image repository project", exact=True)
    references(support_writer_expressions.get("location", {}),
               "google_artifact_registry_repository.dev_images[0].location",
               "supporting-image repository location", exact=True)
    references(support_writer_expressions.get("repository", {}),
               "google_artifact_registry_repository.dev_images[0].repository_id",
               "supporting-image repository ID", exact=True)
    references(support_writer_expressions.get("member", {}),
               "google_service_account.dev_app_support_image_publisher[0].member",
               "supporting-image repository writer", exact=True)

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
    require(cluster.get("project") in (PROJECT, PROJECT_NUMBER)
            and cluster.get("name") == "helpdeskcloud-dev-gke"
            and cluster.get("location") == "us-east1", "Unexpected GKE identity")
    require(cluster.get("enable_autopilot") is True and cluster.get("deletion_protection") is True,
            "GKE Autopilot or deletion protection is missing")
    require(cluster.get("network") in VPC_LINKS and cluster.get("subnetwork") in SUBNET_LINKS,
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
        require(grant.get("project") in (PROJECT, PROJECT_NUMBER) and grant.get("role") == role,
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

    migration_gsa_grant = item(MIGRATION_GSA_SECRET_ACCESS_ADDRESS)
    require(migration_gsa_grant.get("role") == "roles/secretmanager.secretAccessor",
            "Migration Google service account must receive only Secret Manager Secret Accessor")
    expected_or_unknown(
        migration_gsa_grant, MIGRATION_GSA_SECRET_ACCESS_ADDRESS, ("member",),
        f"serviceAccount:helpdesk-migrate-dev@{PROJECT}.iam.gserviceaccount.com",
        changes, creates, "migration Google service-account Secret Manager principal",
    )
    expected_or_unknown(
        migration_gsa_grant, MIGRATION_GSA_SECRET_ACCESS_ADDRESS, ("secret_id",),
        f"projects/{PROJECT}/secrets/helpdesk-dev-db-admin-password",
        changes, creates, "migration Google service-account Secret Manager target",
    )


def valid_rfc3339_timestamp(value):
    """Return whether a provider update_time is a valid timezone-aware RFC3339 value."""
    if not isinstance(value, str) or not RFC3339_TIMESTAMP.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def permitted_drift(entry):
    """Accept only exact provider readbacks, with every other field identical."""
    address = entry.get("address")
    expected_type = {
        PSA_ADDRESS: NETWORK[PSA_ADDRESS],
        SUBNET_ADDRESS: NETWORK[SUBNET_ADDRESS],
        REGISTRY_ADDRESS: PHASE6[REGISTRY_ADDRESS],
        SQL_ADDRESS: PHASE6[SQL_ADDRESS],
        CLUSTER_ADDRESS: PHASE7[CLUSTER_ADDRESS],
        PHASE8_PROVIDER_ADDRESS: PHASE8[PHASE8_PROVIDER_ADDRESS],
        MIGRATION_RUNNER_PROVIDER_ADDRESS: "google_iam_workload_identity_pool_provider",
        **{address: "google_iam_workload_identity_pool_provider"
           for address in APP_DELIVERY_PROVIDER_READBACKS},
        ARTIFACT_READER_IAM_ADDRESS: "google_artifact_registry_repository_iam_member",
        **{address: "google_project_iam_member" for address in PROJECT_IAM_READBACKS},
        **{secret: PHASE7[secret] for secret in SECRET_READBACK_NAMES},
        **{address: "google_secret_manager_secret_iam_member" for address in SECRET_IAM_READBACKS},
    }.get(address)
    if entry.get("mode") != "managed" or expected_type is None or entry.get("type") != expected_type:
        return False
    change = entry.get("change", {})
    before, after = change.get("before"), change.get("after")
    if change.get("actions") != ["update"] or not isinstance(before, dict) or not isinstance(after, dict):
        return False

    if address in APP_DELIVERY_PROVIDER_READBACKS:
        provider_id, condition = APP_DELIVERY_PROVIDER_READBACKS[address]
        if not all(app_delivery_provider_identity_matches(snapshot, provider_id, condition)
                   for snapshot in (before, after)):
            return False

        before_oidc, after_oidc = single_block(before.get("oidc")), single_block(after.get("oidc"))
        before_audiences = before_oidc.get("allowed_audiences", MISSING)
        after_audiences = after_oidc.get("allowed_audiences", MISSING)
        empty_audiences = (MISSING, None, [])
        if (before_audiences not in empty_audiences or after_audiences not in empty_audiences
                or before_audiences == after_audiences):
            return False

        before_copy, after_copy = deepcopy(before), deepcopy(after)
        single_block(before_copy.get("oidc")).pop("allowed_audiences", None)
        single_block(after_copy.get("oidc")).pop("allowed_audiences", None)
        return before_copy == after_copy

    if address == PHASE8_PROVIDER_ADDRESS:
        if not all(support_provider_identity_matches(snapshot) for snapshot in (before, after)):
            return False

        before_oidc, after_oidc = single_block(before.get("oidc")), single_block(after.get("oidc"))
        before_audiences = before_oidc.get("allowed_audiences", MISSING)
        after_audiences = after_oidc.get("allowed_audiences", MISSING)
        empty_audiences = (MISSING, None, [])
        if (before_audiences not in empty_audiences or after_audiences not in empty_audiences
                or before_audiences == after_audiences):
            return False

        # The Google API and provider may represent the unset optional audience
        # list as missing, null, or []. Keep every other provider value exact.
        before_copy, after_copy = deepcopy(before), deepcopy(after)
        single_block(before_copy.get("oidc")).pop("allowed_audiences", None)
        single_block(after_copy.get("oidc")).pop("allowed_audiences", None)
        return before_copy == after_copy

    if address == MIGRATION_RUNNER_PROVIDER_ADDRESS:
        if not all(migration_provider_identity_matches(snapshot) for snapshot in (before, after)):
            return False

        before_oidc, after_oidc = single_block(before.get("oidc")), single_block(after.get("oidc"))
        before_audiences = before_oidc.get("allowed_audiences", MISSING)
        after_audiences = after_oidc.get("allowed_audiences", MISSING)
        empty_audiences = (MISSING, None, [])
        if (before_audiences not in empty_audiences or after_audiences not in empty_audiences
                or before_audiences == after_audiences):
            return False

        # The Google API and provider may represent the unset optional audience
        # list as missing, null, or []. Keep every other migration-provider value exact.
        before_copy, after_copy = deepcopy(before), deepcopy(after)
        single_block(before_copy.get("oidc")).pop("allowed_audiences", None)
        single_block(after_copy.get("oidc")).pop("allowed_audiences", None)
        return before_copy == after_copy

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

    if address in SECRET_IAM_READBACKS:
        secret_id, expected_member = SECRET_IAM_READBACKS[address]
        expected_secret_path = f"projects/{PROJECT}/secrets/{secret_id}"
        if any(
            snapshot.get("secret_id") not in (secret_id, expected_secret_path)
            or snapshot.get("role") != SECRET_ACCESSOR_ROLE
            or snapshot.get("member") != expected_member
            or snapshot.get("project", MISSING) not in (MISSING, PROJECT, PROJECT_NUMBER)
            for snapshot in (before, after)
        ):
            return False
        before_etag, after_etag = before.get("etag"), after.get("etag")
        if (not isinstance(before_etag, str) or not before_etag
                or not isinstance(after_etag, str) or not after_etag
                or before_etag == after_etag):
            return False
        # A Secret Manager IAM member's etag is the shared secret-policy
        # concurrency token. Permit that field alone; check_drift additionally
        # requires a live policy snapshot matching all members in Terraform state.
        return ({key: value for key, value in before.items() if key != "etag"}
                == {key: value for key, value in after.items() if key != "etag"})

    if address == CLUSTER_ADDRESS:
        expected_identity = ("helpdeskcloud-dev-gke", "us-east1")
        if (before.get("project") not in (PROJECT, PROJECT_NUMBER)
                or after.get("project") not in (PROJECT, PROJECT_NUMBER)
                or tuple(before.get(key) for key in ("name", "location")) != expected_identity
                or tuple(after.get(key) for key in ("name", "location")) != expected_identity
                or before.get("deletion_protection") is not True
                or after.get("deletion_protection") is not True
                or before.get("network") not in VPC_LINKS or after.get("network") not in VPC_LINKS
                or before.get("subnetwork") not in SUBNET_LINKS or after.get("subnetwork") not in SUBNET_LINKS
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
        unchanged_known_labels = (
            before_labels == after_labels
            and before_labels in (*empty_representations, ATTRIBUTION_LABEL)
        )
        if not (exact_normalization or empty_map_normalization or unchanged_known_labels):
            return False
        ignored = {"resource_labels"}
        if before.get("node_config") != after.get("node_config") or before.get("node_pool") != after.get("node_pool"):
            # In provider 7.8.0 these cluster fields are Optional+Computed. The
            # Autopilot cluster had no provisioned pool in Terraform state; GKE
            # created its managed pool for the already scheduled migration Pod.
            # Permit this one empty-to-singleton readback only, with the configured
            # node identity, cloud-platform/userinfo scopes, GKE metadata mode,
            # and the private Dev subnet/pod range all checked above.
            if (before.get("node_config") == after.get("node_config")
                    or before.get("node_pool") == after.get("node_pool")
                    or not gke_autopilot_node_readback_matches(before, after)):
                return False
            ignored.update(("node_config", "node_pool"))
        return ({key: value for key, value in before.items() if key not in ignored}
                == {key: value for key, value in after.items() if key not in ignored})

    if address in PROJECT_IAM_READBACKS:
        expected_role, expected_member = PROJECT_IAM_READBACKS[address]
        if any(snapshot.get("project") not in (PROJECT, PROJECT_NUMBER)
               or snapshot.get("role") != expected_role
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

    if address == ARTIFACT_READER_IAM_ADDRESS:
        expected_member = f"serviceAccount:helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com"
        expected_repositories = (REGISTRY_REPOSITORY_ID, REGISTRY_REPOSITORY_PATH)
        if any(snapshot.get("project") not in (PROJECT, PROJECT_NUMBER)
               or snapshot.get("location") != "us-east1"
               or snapshot.get("repository") not in expected_repositories
               or snapshot.get("role") != "roles/artifactregistry.reader"
               or snapshot.get("member") != expected_member
               for snapshot in (before, after)):
            return False
        before_etag, after_etag = before.get("etag"), after.get("etag")
        if (not isinstance(before_etag, str) or not before_etag
                or not isinstance(after_etag, str) or not after_etag
                or before_etag == after_etag):
            return False
        # Adding a repository-scoped member changes the repository policy etag.
        # Permit only that metadata change when the existing reader grant and all
        # other provider values remain identical.
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

        if (
            tuple(before.get(k) for k in ("project", "location", "repository_id"))
            != expected_identity
            or tuple(after.get(k) for k in ("project", "location", "repository_id"))
            != expected_identity
            or before.get("terraform_labels", MISSING) != ATTRIBUTION_LABEL
            or after.get("terraform_labels", MISSING) != ATTRIBUTION_LABEL
            or before.get("effective_labels", MISSING) != ATTRIBUTION_LABEL
            or after.get("effective_labels", MISSING) != ATTRIBUTION_LABEL
        ):
            return False

        # Accept only the known empty-label representations.
        before_labels = before.get("labels", MISSING)
        after_labels = after.get("labels", MISSING)

        if not (
            (before_labels is None and after_labels == {})
            or (before_labels == {} and after_labels == {})
        ):
            return False

        # Publishing images can change repository update_time.
        before_time = before.get("update_time", MISSING)
        after_time = after.get("update_time", MISSING)
        time_changed = before_time != after_time

        if ((before_time is not MISSING or after_time is not MISSING)
                and not (valid_rfc3339_timestamp(before_time)
                         and valid_rfc3339_timestamp(after_time))):
            return False

        if before_labels == after_labels and not time_changed:
            return False

        # Every actual repository configuration field must match.
        ignored = {"labels", "update_time"}
        return (
            {k: v for k, v in before.items() if k not in ignored}
            ==
            {k: v for k, v in after.items() if k not in ignored}
        )


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
        if (not isinstance(before_config, list) or len(before_config) != 1
                or not isinstance(after_config, list) or len(after_config) != 1
                or not isinstance(before_config[0], dict) or not isinstance(after_config[0], dict)
                or before_config[0].get("server_ca_mode") != "GOOGLE_MANAGED_INTERNAL_CA"
                or after_config[0].get("server_ca_mode") != "GOOGLE_MANAGED_INTERNAL_CA"):
            return False

        before_version = before_settings[0].get("version", MISSING)
        after_version = after_settings[0].get("version", MISSING)
        before_sans = before_config[0].get("custom_subject_alternative_names", MISSING)
        after_sans = after_config[0].get("custom_subject_alternative_names", MISSING)

        # Cloud SQL settings.version is an API concurrency generation, not a
        # configured database setting. Permit a forward-only generation change
        # when every other value on the exact Dev instance is exactly equal.
        # Bound values to the API's signed Int64 representation.
        max_settings_version = (1 << 63) - 1
        if (type(before_version) is int and type(after_version) is int
                and 0 < before_version < after_version <= max_settings_version
                and before_sans == [] and after_sans == []):
            before_copy, after_copy = deepcopy(before), deepcopy(after)
            before_copy["settings"][0].pop("version")
            after_copy["settings"][0].pop("version")
            return before_copy == after_copy

        # Preserve the separately observed initial provider normalization:
        # generation 1 -> 3 and unset optional SAN list null -> []. Do not combine
        # this exception with the general generation-only allowance above.
        if (type(before_version) is not int or before_version != 1
                or type(after_version) is not int or after_version != 3
                or before_sans is not None or after_sans != []):
            return False

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


def check_secret_iam_policy(plan, secret_id, policy):
    """Require the live secret policy to contain exactly its Terraform-tracked grants."""
    prior_state = plan.get("prior_state")
    require(isinstance(prior_state, dict), "Missing Terraform prior state for Secret Manager IAM evidence")
    root_module = prior_state.get("values", {}).get("root_module")
    require(isinstance(root_module, dict), "Malformed Terraform prior state for Secret Manager IAM evidence")

    expected_members = []
    seen_addresses = set()
    for resource in state_resources(root_module):
        if not isinstance(resource, dict) or resource.get("mode") != "managed":
            continue
        if resource.get("type") != "google_secret_manager_secret_iam_member":
            continue
        address = resource.get("address")
        require(address in SECRET_IAM_READBACKS,
                "Unrecognized Secret Manager IAM resource in Terraform state requires review")
        require(address not in seen_addresses, "Duplicate Secret Manager IAM resource in Terraform state")
        seen_addresses.add(address)
        expected_secret, expected_member = SECRET_IAM_READBACKS[address]
        if expected_secret != secret_id:
            continue

        values = resource.get("values")
        expected_path = f"projects/{PROJECT}/secrets/{secret_id}"
        require(isinstance(values, dict)
                and values.get("secret_id") in (secret_id, expected_path)
                and values.get("role") == SECRET_ACCESSOR_ROLE
                and values.get("member") == expected_member
                and values.get("project", MISSING) in (MISSING, PROJECT, PROJECT_NUMBER),
                "Terraform state contains an unexpected Secret Manager IAM identity")
        expected_members.append((SECRET_ACCESSOR_ROLE, expected_member))

    require(bool(expected_members), "No Terraform-managed Secret Manager IAM members found for the affected secret")
    require(isinstance(policy, dict) and set(policy).issubset({"bindings", "etag", "version", "auditConfigs"})
            and isinstance(policy.get("bindings"), list),
            "Invalid live Secret Manager IAM policy evidence")
    require(policy.get("version", 1) in (1, 3), "Unexpected live Secret Manager IAM policy version")

    actual_members = []
    for binding in policy["bindings"]:
        require(isinstance(binding, dict)
                and set(binding).issubset({"role", "members", "condition"})
                and binding.get("role") == SECRET_ACCESSOR_ROLE
                and binding.get("condition") in (None, MISSING)
                and isinstance(binding.get("members"), list)
                and all(isinstance(member, str) and member for member in binding["members"]),
                "Live Secret Manager policy contains an unexpected role or condition")
        actual_members.extend((binding["role"], member) for member in binding["members"])

    require(len(actual_members) == len(set(actual_members))
            and set(actual_members) == set(expected_members),
            "Live Secret Manager policy members differ from Terraform-managed identities")


def check_secret_iam_evidence(plan, policies, drift):
    affected_secrets = {
        SECRET_IAM_READBACKS[entry["address"]][0]
        for entry in drift
        if entry.get("address") in SECRET_IAM_READBACKS
    }
    if not affected_secrets:
        return
    require(isinstance(policies, dict),
            "Secret Manager IAM etag drift requires live secret-policy evidence")
    for secret_id in affected_secrets:
        require(secret_id in policies,
                "Secret Manager IAM etag drift requires live secret-policy evidence")
        check_secret_iam_policy(plan, secret_id, policies[secret_id])


def drift_fingerprint(plan):
    """Fingerprint drift addresses, actions and field paths without including values."""
    drift = plan.get("resource_drift", [])
    require(isinstance(drift, list), "Unexpected resource drift format")
    entries = []
    for entry in drift:
        require(isinstance(entry, dict), "Malformed resource drift entry")
        change = entry.get("change", {})
        before, after = change.get("before"), change.get("after")
        secret = entry.get("address") in SECRET_READBACK_NAMES
        paths = sorted(set(safe_drift_path(path, secret=secret)
                           for path in changed_paths(before, after)))
        entries.append({
            "mode": entry.get("mode"),
            "address": entry.get("address"),
            "type": entry.get("type"),
            "actions": change.get("actions"),
            "paths": paths,
        })
    canonical = json.dumps(sorted(entries, key=lambda item: (str(item["address"]), str(item["type"]))),
                           sort_keys=True, separators=(",", ":"))
    return "drift-v1-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def drift_is_acknowledgeable(plan):
    """Permit explicit acknowledgement only for known managed updates, never delete/replace."""
    drift = plan.get("resource_drift", [])
    if not isinstance(drift, list) or not drift:
        return False
    addresses = [entry.get("address") for entry in drift if isinstance(entry, dict)]
    if len(addresses) != len(drift) or len(set(addresses)) != len(addresses):
        return False
    for entry in drift:
        if not isinstance(entry, dict):
            return False
        address = entry.get("address")
        change = entry.get("change", {})
        if (entry.get("mode") != "managed"
                or address not in EXPECTED
                or entry.get("type") != EXPECTED[address]
                or change.get("actions") != ["update"]
                or not isinstance(change.get("before"), dict)
                or not isinstance(change.get("after"), dict)
                or not changed_paths(change.get("before"), change.get("after"))):
            return False
    return True


def check_drift(plan, *, allow_migration_runner_iam_replacement=False, secret_iam_policies=None,
                acknowledged_drift_fingerprint=None, report_only=False):
    drift = plan.get("resource_drift", [])
    require(isinstance(drift, list), "Unexpected resource drift format")
    require(len({entry.get("address") for entry in drift if isinstance(entry, dict)}) == len(drift),
            "Duplicate or malformed resource drift")
    if report_only:
        require(acknowledged_drift_fingerprint is None,
                "A drift acknowledgement is not used by the read-only Dev Plan")
        require(all(isinstance(entry, dict)
                    and isinstance(entry.get("address"), str)
                    and isinstance(entry.get("change"), dict)
                    for entry in drift),
                "Malformed resource drift entry")
        return
    check_secret_iam_evidence(plan, secret_iam_policies, drift)
    permitted = all(isinstance(entry, dict) and permitted_drift(entry) for entry in drift)
    acknowledged = False
    if acknowledged_drift_fingerprint is not None:
        require(bool(drift), "No resource drift remains; rerun Apply without a drift acknowledgement")
        require(acknowledged_drift_fingerprint == drift_fingerprint(plan),
                "Drift fingerprint does not match this plan; inspect the Dev Plan diagnostic and retry")
    if not permitted and acknowledged_drift_fingerprint is not None:
        require(drift_is_acknowledgeable(plan),
                "Drift acknowledgement is limited to known managed updates; deletions, replacements, "
                "unknown resources, and malformed drift remain blocked")
        acknowledged = True
    require(permitted or acknowledged,
            "Unexpected resource drift requires review; run the Dev Plan diagnostic and, for an intentional "
            "managed update, provide its exact drift fingerprint")
    # Without an exact operator fingerprint, observed drift does not authorize a requested operation.
    for entry in drift if not acknowledged else []:
        requested = [change for change in plan.get("resource_changes", [])
                     if change.get("address") == entry.get("address")]
        if (entry.get("address") == MIGRATION_RUNNER_CLUSTER_VIEWER_ADDRESS
                and allow_migration_runner_iam_replacement):
            require(all(change.get("change", {}).get("actions") in (
                ["no-op"], ["update"], ["create", "delete"], ["delete", "create"])
                for change in requested),
                "Migration-runner IAM drift is allowed only with the exact grant remediation")
        else:
            require(all(change.get("change", {}).get("actions") == ["no-op"] for change in requested),
                    "Provider drift is readback only; a proposed resource change requires review")


def migration_runner_iam_remediation_candidate(plan):
    """Recognize only the phase-9 shape that may accompany the reviewed IAM fix.

    The complete plan checks below still validate every address, type, value, and
    transition. This early predicate exists so drift diagnostics retain priority.
    """
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list):
        return False
    actions = {}
    for change in changes:
        if not isinstance(change, dict) or not isinstance(change.get("address"), str):
            return False
        address = change["address"]
        if address in actions:
            return False
        actions[address] = change.get("change", {}).get("actions")

    viewer_actions = actions.get(MIGRATION_RUNNER_CLUSTER_VIEWER_ADDRESS, ["no-op"])
    dns_actions = actions.get(MIGRATION_RUNNER_DNS_BINDING_ADDRESS, ["no-op"])
    if viewer_actions not in (["update"], ["create", "delete"], ["delete", "create"]):
        return False
    if dns_actions != ["delete"]:
        return False
    if any(actions.get(address, ["no-op"]) != ["no-op"]
           for address in set(PHASE7) | set(PHASE8)
           | (set(PHASE9) - {MIGRATION_RUNNER_CLUSTER_VIEWER_ADDRESS,
                             MIGRATION_RUNNER_DNS_BINDING_ADDRESS})):
        return False

    prior_state = plan.get("prior_state")
    if not isinstance(prior_state, dict):
        return False
    prior = prior_state.get("values", {}).get("root_module")
    if not isinstance(prior, dict):
        return False
    prior_managed = [resource for resource in state_resources(prior)
                     if isinstance(resource, dict) and resource.get("mode") == "managed"]
    prior_addresses = {resource.get("address") for resource in prior_managed}
    return (
        set(PHASE7) <= prior_addresses
        and set(PHASE8) <= prior_addresses
        and set(PHASE9) <= prior_addresses
        and MIGRATION_RUNNER_DNS_BINDING_ADDRESS in prior_addresses
    )


def check_plan(plan, *, secret_iam_policies=None, acknowledged_drift_fingerprint=None,
               report_drift_only=False):
    for name, expected in {"project_id": PROJECT, "region": "us-east1", "environment": "dev"}.items():
        require(plan.get("variables", {}).get(name, {}).get("value") == expected, f"Unexpected {name}")
    # Drift checks run first so diagnostics remain actionable. The exception paths
    # are the exact phase-9 remediation or a matching operator fingerprint; the full
    # resource and action constraints below still apply in either case.
    check_drift(
        plan,
        allow_migration_runner_iam_replacement=migration_runner_iam_remediation_candidate(plan),
        secret_iam_policies=secret_iam_policies,
        acknowledged_drift_fingerprint=acknowledged_drift_fingerprint,
        report_only=report_drift_only,
    )
    planned = planned_resources(plan.get("planned_values", {}).get("root_module", {}))
    managed = [r for r in planned if r.get("mode") == "managed"]
    require(len(managed) == len(PLANNED_EXPECTED)
            and {r.get("address") for r in managed} == set(PLANNED_EXPECTED),
            "Planned Dev infrastructure must contain exactly the approved addresses")
    require(all(r.get("type") == PLANNED_EXPECTED[r["address"]] for r in managed),
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
    support_creates = {address for address in PHASE8 if actions.get(address) == ["create"]}
    require(all(actions.get(address, ["no-op"]) in (["create"], ["no-op"]) for address in PHASE8),
            "Phase 8 update, replacement, or deletion requires review")
    migration_runner_creates = {address for address in PHASE9 if actions.get(address) == ["create"]}
    app_delivery_creates = {address for address in PHASE10 if actions.get(address) == ["create"]}
    require(all(actions.get(address, ["no-op"]) in (["create"], ["no-op"])
                for address in PHASE10),
            "Phase 10 update, replacement, or deletion requires review")
    cluster_viewer_address = MIGRATION_RUNNER_CLUSTER_VIEWER_ADDRESS
    cluster_viewer_actions = actions.get(cluster_viewer_address, ["no-op"])
    legacy_dns_actions = actions.get(MIGRATION_RUNNER_DNS_BINDING_ADDRESS, ["no-op"])
    require(all(actions.get(address, ["no-op"]) in (["create"], ["no-op"])
                for address in set(PHASE9) - {cluster_viewer_address}),
            "Phase 9 update, replacement, or deletion requires review")
    require(cluster_viewer_actions in (["create"], ["no-op"], ["update"],
                                       ["create", "delete"], ["delete", "create"]),
            "Phase 9 update, replacement, or deletion requires review")
    require(legacy_dns_actions in (["no-op"], ["delete"]),
            "Legacy migration-runner DNS binding change requires review")
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
    prior_phase8 = prior_addresses & set(PHASE8)
    prior_phase9 = prior_addresses & set(PHASE9)
    prior_phase10 = prior_addresses & set(PHASE10)
    prior_legacy_dns = MIGRATION_RUNNER_DNS_BINDING_ADDRESS in prior_addresses
    full_initial_create = creates == set(PHASE7) and not prior_phase7
    exact_apply12_recovery = creates == APPLY12_REMAINING and prior_phase7 == APPLY12_COMPLETED
    complete_no_changes = not creates and prior_phase7 == set(PHASE7)
    exact_phase8_provider_recovery = (
        not creates
        and prior_phase7 == set(PHASE7)
        and prior_phase8 == PHASE8_COMPLETED
        and support_creates == {PHASE8_PROVIDER_ADDRESS}
    )
    require(not prior_phase8 or prior_phase8 == set(PHASE8) or exact_phase8_provider_recovery,
            "Partial Phase 8 state requires review")
    support_images_initial_create = (
        not creates and prior_phase7 == set(PHASE7)
        and not prior_phase8 and support_creates == set(PHASE8)
    )
    support_images_complete = not support_creates and prior_phase8 == set(PHASE8)
    migration_runner_initial_create = (
        not creates and not support_creates
        and prior_phase7 == set(PHASE7) and prior_phase8 == set(PHASE8)
        and not prior_phase9 and not prior_legacy_dns
        and migration_runner_creates == set(PHASE9)
    )
    migration_runner_iam_remediation = (
        not creates and not support_creates
        and prior_phase7 == set(PHASE7) and prior_phase8 == set(PHASE8)
        and prior_phase9 == set(PHASE9) and prior_legacy_dns
        and not migration_runner_creates
        and cluster_viewer_actions in (["update"], ["create", "delete"], ["delete", "create"])
        and legacy_dns_actions == ["delete"]
        and all(actions.get(address, ["no-op"]) == ["no-op"]
                for address in set(PHASE9) - {cluster_viewer_address})
    )
    migration_runner_complete = (
        not migration_runner_creates and prior_phase9 == set(PHASE9)
        and not prior_legacy_dns and cluster_viewer_actions == ["no-op"]
    )
    app_delivery_initial_create = (
        not creates and not support_creates and not migration_runner_creates
        and prior_phase7 == set(PHASE7) and prior_phase8 == set(PHASE8)
        and prior_phase9 == set(PHASE9) and not prior_phase10
        and app_delivery_creates == set(PHASE10)
    )
    app_delivery_complete = (
        not app_delivery_creates and prior_phase10 == set(PHASE10)
    )
    secret_access_recovery = (
        creates == {MIGRATION_GSA_SECRET_ACCESS_ADDRESS}
        and prior_phase7 == set(PHASE7) - {MIGRATION_GSA_SECRET_ACCESS_ADDRESS}
        and support_images_complete
        and migration_runner_complete
        and app_delivery_complete
    )
    require(not prior_phase9 or prior_phase9 == set(PHASE9)
            or migration_runner_iam_remediation,
            "Partial Phase 9 migration-runner state requires review")
    require(not prior_legacy_dns or migration_runner_iam_remediation,
            "Legacy Phase 9 state requires the exact GKE IAM remediation")
    require(full_initial_create or exact_apply12_recovery or complete_no_changes
            or exact_phase8_provider_recovery or secret_access_recovery,
            "Partial or inconsistent Phase 7 state/creation batch requires review")
    require(support_images_initial_create or support_images_complete or exact_phase8_provider_recovery,
            "Phase 8 must be created as one exact batch after Phase 7, or already be complete")
    require(migration_runner_initial_create or migration_runner_complete
            or migration_runner_iam_remediation,
            "Phase 9 migration-runner resources must be created as one exact batch after Phase 8, or already be complete")
    require(app_delivery_initial_create or app_delivery_complete,
            "Phase 10 application delivery identities must be created as one exact batch after Phase 9, or already be complete")
    if exact_phase8_provider_recovery:
        prior_phase8_values = {
            resource["address"]: resource.get("values", {})
            for resource in prior_managed if resource.get("address") in PHASE8_COMPLETED
        }
        check_phase8(prior_phase8_values, plan, set(), addresses=PHASE8_COMPLETED)
    if migration_runner_iam_remediation:
        prior_phase9_values = {
            resource["address"]: resource.get("values", {})
            for resource in prior_managed
            if resource.get("address") in set(PHASE9)
        }
        prior_legacy_dns_values = {
            resource["address"]: resource.get("values", {})
            for resource in prior_managed
            if resource.get("address") == MIGRATION_RUNNER_DNS_BINDING_ADDRESS
        }
        check_phase9_legacy_bindings(prior_phase9_values | prior_legacy_dns_values)
    # Check the complete planned values, including no-op resources omitted from resource_changes.
    by_address = {r["address"]: r.get("values", {}) for r in managed}
    by_type = {r["type"]: r.get("values", {}) for r in managed if r["address"] in BASE}
    check_network(by_type)
    check_phase6(by_type)
    check_phase7(by_address, plan, creates)
    check_phase8(by_address, plan, support_creates)
    check_phase9(by_address, plan, migration_runner_creates)
    check_phase10(by_address, plan, app_delivery_creates)
    check_references(plan)
    return "apply" if (creates or support_creates or migration_runner_creates or app_delivery_creates
                        or migration_runner_iam_remediation or secret_access_recovery) else "no_changes"


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


def safe_readback_shape(value, *, depth=0, field_name=""):
    """Describe provider readback structure without logging resource values."""
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        # These Terraform fields are arbitrary user maps; never expose their keys.
        if field_name in {"labels", "resource_labels", "terraform_labels", "effective_labels",
                          "metadata", "annotations", "effective_annotations", "tags",
                          "version_aliases"}:
            return "map(contents withheld)"
        if depth >= 4:
            return f"object(field count={len(value)})"
        fields = []
        for key in sorted(value):
            if not isinstance(key, str):
                continue
            fields.append(f"{key}:{safe_readback_shape(value[key], depth=depth + 1, field_name=key)}")
        return "object(" + ", ".join(fields) + ")"
    if isinstance(value, list):
        if depth >= 4:
            return f"list(count={len(value)})"
        # An empty list is useful to distinguish from an omitted/null block;
        # non-empty arrays report structure only, never item values.
        if not value:
            return "empty list"
        if all(isinstance(item, dict) for item in value):
            samples = "; ".join(
                safe_readback_shape(item, depth=depth + 1, field_name=field_name)
                for item in value[:3]
            )
            suffix = "; more items omitted" if len(value) > 3 else ""
            return f"list(count={len(value)}; items={samples}{suffix})"
        return f"list(count={len(value)}; item type={safe_readback_shape(value[0], depth=depth + 1)})"
    return "other type"


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


def project_readback_status(value):
    if value == PROJECT:
        return "project id"
    if value == PROJECT_NUMBER:
        return "project number"
    return "unexpected (value withheld)"


def gke_network_reference_status(value, *, self_links, relative_paths):
    if value in self_links:
        return "Compute self-link"
    if value in relative_paths:
        return "GKE relative resource path"
    return "unexpected (value withheld)"


def etag_readback_status(value):
    if value is MISSING:
        return "missing"
    if value is None:
        return "null"
    if value == "":
        return "empty"
    if isinstance(value, str):
        return "non-empty token"
    return "unexpected type (value withheld)"


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


def support_provider_identity_checks(snapshot):
    expected_provider_id = (
        f"projects/{PROJECT}/locations/global/workloadIdentityPools/helpdesk-github/"
        f"providers/{SUPPORT_PUBLISHER_PROVIDER_ID}"
    )
    oidc = single_block(snapshot.get("oidc"))
    return {
        "project": snapshot.get("project") in (PROJECT, PROJECT_NUMBER),
        "pool": snapshot.get("workload_identity_pool_id") == "helpdesk-github",
        "provider": snapshot.get("workload_identity_pool_provider_id") == SUPPORT_PUBLISHER_PROVIDER_ID,
        "enabled": snapshot.get("disabled") is False,
        "mapping": snapshot.get("attribute_mapping") == SUPPORT_PUBLISHER_MAPPING,
        # Google may read the same CEL expression back with the Terraform heredoc's
        # multiline formatting. normalize_cel ignores only whitespace outside the
        # quoted claim values; repository IDs, branch, Environment, and workflow
        # text inside those literals remain byte-for-byte exact.
        "attribute_condition": normalize_cel(snapshot.get("attribute_condition"))
        == normalize_cel(SUPPORT_PUBLISHER_CONDITION),
        "issuer": oidc.get("issuer_uri") == "https://token.actions.githubusercontent.com",
        # Apply #22's provider output confirmed the canonical path uses project ID.
        "resource_id": snapshot.get("id", expected_provider_id) == expected_provider_id,
    }


def support_provider_identity_matches(snapshot):
    return all(support_provider_identity_checks(snapshot).values())


def migration_provider_identity_checks(snapshot):
    """Validate the exact Phase 9 provider before accepting audience-only drift."""
    oidc = single_block(snapshot.get("oidc"))
    return {
        "project": snapshot.get("project") in (PROJECT, PROJECT_NUMBER),
        "pool": snapshot.get("workload_identity_pool_id") == "helpdesk-github",
        "provider": snapshot.get("workload_identity_pool_provider_id") == MIGRATION_RUNNER_PROVIDER_ID,
        "enabled": snapshot.get("disabled") is False,
        "mapping": snapshot.get("attribute_mapping") == SUPPORT_PUBLISHER_MAPPING,
        "attribute_condition": normalize_cel(snapshot.get("attribute_condition")) == MIGRATION_RUNNER_CONDITION,
        "issuer": oidc.get("issuer_uri") == "https://token.actions.githubusercontent.com",
        # The provider's create/readback logs use the canonical project-ID path.
        "resource_id": snapshot.get("id", MIGRATION_RUNNER_PROVIDER_RESOURCE_ID)
        == MIGRATION_RUNNER_PROVIDER_RESOURCE_ID,
    }


def migration_provider_identity_matches(snapshot):
    return all(migration_provider_identity_checks(snapshot).values())


def app_delivery_provider_identity_checks(snapshot, provider_id, condition):
    expected_resource_id = (
        f"projects/{PROJECT}/locations/global/workloadIdentityPools/"
        f"helpdesk-github/providers/{provider_id}"
    )
    oidc = single_block(snapshot.get("oidc"))
    return {
        "project": snapshot.get("project") in (PROJECT, PROJECT_NUMBER),
        "pool": snapshot.get("workload_identity_pool_id") == "helpdesk-github",
        "provider": snapshot.get("workload_identity_pool_provider_id") == provider_id,
        "enabled": snapshot.get("disabled") is False,
        "mapping": snapshot.get("attribute_mapping") == APP_DELIVERY_MAPPING,
        "attribute_condition": normalize_cel(snapshot.get("attribute_condition"))
        == normalize_cel(condition),
        "issuer": oidc.get("issuer_uri") == "https://token.actions.githubusercontent.com",
        "resource_id": snapshot.get("id", expected_resource_id) == expected_resource_id,
    }


def app_delivery_provider_identity_matches(snapshot, provider_id, condition):
    return all(app_delivery_provider_identity_checks(snapshot, provider_id, condition).values())


def gke_node_config_readback_matches(value):
    """Check the security identity on one GKE-managed Autopilot node config."""
    return all(gke_node_config_readback_checks(value).values())


def gke_node_config_readback_checks(value):
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        return {"service account": False, "OAuth scopes": False, "Workload Identity mode": False}
    config = value[0]
    scopes = config.get("oauth_scopes")
    workload_metadata = config.get("workload_metadata_config")
    return {
        "service account": config.get("service_account") == GKE_NODE_SERVICE_ACCOUNT,
        "OAuth scopes": (isinstance(scopes, list) and len(scopes) == len(GKE_NODE_OAUTH_SCOPES)
                         and all(isinstance(scope, str) for scope in scopes)
                         and frozenset(scopes) == GKE_NODE_OAUTH_SCOPES),
        "Workload Identity mode": (isinstance(workload_metadata, list)
                                   and len(workload_metadata) == 1
                                   and isinstance(workload_metadata[0], dict)
                                   and workload_metadata[0].get("mode") == "GKE_METADATA"),
    }


def gke_autopilot_node_readback_checks(snapshot):
    """Return value-free checks for GKE's computed Autopilot node readback."""
    node_config_checks = gke_node_config_readback_checks(snapshot.get("node_config"))
    pools = snapshot.get("node_pool")
    pool_ok = isinstance(pools, list) and len(pools) == 1 and isinstance(pools[0], dict)
    pool_config_checks = {"service account": False, "OAuth scopes": False,
                          "Workload Identity mode": False}
    private_network_ok = False
    if pool_ok:
        pool = pools[0]
        pool_config_checks = gke_node_config_readback_checks(pool.get("node_config"))
        network = pool.get("network_config")
        private_network_ok = (
            isinstance(network, list)
            and len(network) == 1
            and isinstance(network[0], dict)
            and network[0].get("enable_private_nodes") is True
            and network[0].get("subnetwork") in SUBNET_LINKS
            and network[0].get("pod_range") == "helpdeskcloud-dev-pods"
        )
    return {
        "node service account": node_config_checks["service account"],
        "node OAuth scopes": node_config_checks["OAuth scopes"],
        "node Workload Identity metadata mode": node_config_checks["Workload Identity mode"],
        "Autopilot pool service account": pool_config_checks["service account"],
        "Autopilot pool OAuth scopes": pool_config_checks["OAuth scopes"],
        "Autopilot pool Workload Identity metadata mode": pool_config_checks["Workload Identity mode"],
        "Autopilot pool private subnet and pod range": private_network_ok,
    }


def gke_autopilot_node_readback_matches(before, after):
    """Recognize the exact empty-to-provisioned readback created by Autopilot."""
    return (
        before.get("node_config") == []
        and before.get("node_pool") == []
        and all(gke_autopilot_node_readback_checks(after).values())
    )


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
        if entry.get("address") == CLUSTER_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            lines.append("  project representation: before=" + project_readback_status(before.get("project", MISSING))
                         + "; after=" + project_readback_status(after.get("project", MISSING)))
            lines.append("  network reference: before="
                         + gke_network_reference_status(before.get("network"),
                                                        self_links=VPC_SELF_LINKS,
                                                        relative_paths=VPC_PATHS)
                         + "; after="
                         + gke_network_reference_status(after.get("network"),
                                                        self_links=VPC_SELF_LINKS,
                                                        relative_paths=VPC_PATHS))
            lines.append("  subnetwork reference: before="
                         + gke_network_reference_status(before.get("subnetwork"),
                                                        self_links=SUBNET_SELF_LINKS,
                                                        relative_paths=SUBNET_PATHS)
                         + "; after="
                         + gke_network_reference_status(after.get("subnetwork"),
                                                        self_links=SUBNET_SELF_LINKS,
                                                        relative_paths=SUBNET_PATHS))
            lines.append("  resource_labels: before="
                         + classify_address_labels(before.get("resource_labels", MISSING))
                         + "; after=" + classify_address_labels(after.get("resource_labels", MISSING)))
            for field in ("node_config", "node_pool"):
                if any(path == field or path.startswith(field + "[") or path.startswith(field + ".")
                       for path in paths):
                    lines.append(f"  {field} readback structure: before="
                                 + safe_readback_shape(before.get(field, MISSING), field_name=field)
                                 + "; after="
                                 + safe_readback_shape(after.get(field, MISSING), field_name=field))
            if any(path == "node_config" or path.startswith("node_config[")
                   or path == "node_pool" or path.startswith("node_pool[")
                   for path in paths):
                checks = gke_autopilot_node_readback_checks(after)
                lines.append("  Autopilot node readback security checks: "
                             + ", ".join(f"{name}={'expected' if matches else 'unexpected'}"
                                          for name, matches in checks.items()))
        if entry.get("address") == PHASE8_PROVIDER_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            for snapshot_name, snapshot in (("before", before), ("after", after)):
                oidc = single_block(snapshot.get("oidc"))
                lines.append("  " + snapshot_name + " provider identity: "
                             + ("expected" if support_provider_identity_matches(snapshot)
                                else "unexpected (values withheld)"))
                checks = support_provider_identity_checks(snapshot)
                lines.append("  " + snapshot_name + " provider identity checks: "
                             + ", ".join(f"{name}={'expected' if matches else 'unexpected'}"
                                          for name, matches in checks.items()))
                lines.append("  " + snapshot_name + " oidc[0].allowed_audiences: "
                             + empty_set_status(oidc.get("allowed_audiences", MISSING)))
        if (entry.get("address") == MIGRATION_RUNNER_PROVIDER_ADDRESS
                and isinstance(before, dict) and isinstance(after, dict)):
            for snapshot_name, snapshot in (("before", before), ("after", after)):
                oidc = single_block(snapshot.get("oidc"))
                checks = migration_provider_identity_checks(snapshot)
                lines.append("  " + snapshot_name + " migration provider identity: "
                             + ("expected" if all(checks.values()) else "unexpected (values withheld)"))
                lines.append("  " + snapshot_name + " migration provider identity checks: "
                             + ", ".join(f"{name}={'expected' if matches else 'unexpected'}"
                                          for name, matches in checks.items()))
                lines.append("  " + snapshot_name + " oidc[0].allowed_audiences: "
                             + empty_set_status(oidc.get("allowed_audiences", MISSING)))
        if (entry.get("address") in APP_DELIVERY_PROVIDER_READBACKS
                and isinstance(before, dict) and isinstance(after, dict)):
            provider_id, condition = APP_DELIVERY_PROVIDER_READBACKS[entry["address"]]
            for snapshot_name, snapshot in (("before", before), ("after", after)):
                oidc = single_block(snapshot.get("oidc"))
                checks = app_delivery_provider_identity_checks(snapshot, provider_id, condition)
                lines.append("  " + snapshot_name + " app-delivery provider identity: "
                             + ("expected" if all(checks.values()) else "unexpected (values withheld)"))
                lines.append("  " + snapshot_name + " app-delivery provider identity checks: "
                             + ", ".join(f"{name}={'expected' if matches else 'unexpected'}"
                                          for name, matches in checks.items()))
                lines.append("  " + snapshot_name + " oidc[0].allowed_audiences: "
                             + empty_set_status(oidc.get("allowed_audiences", MISSING)))
        if entry.get("address") in PROJECT_IAM_READBACKS and isinstance(before, dict) and isinstance(after, dict):
            expected_role, expected_member = PROJECT_IAM_READBACKS[entry["address"]]
            lines.append("  project representation: before=" + project_readback_status(before.get("project", MISSING))
                         + "; after=" + project_readback_status(after.get("project", MISSING)))
            for snapshot_name, snapshot in (("before", before), ("after", after)):
                identity_matches = (snapshot.get("role") == expected_role
                                    and snapshot.get("member") == expected_member)
                lines.append("  " + snapshot_name + " IAM role and member: "
                             + ("expected" if identity_matches else "unexpected (values withheld)"))
            lines.append("  etag representation: before="
                         + etag_readback_status(before.get("etag", MISSING))
                         + "; after=" + etag_readback_status(after.get("etag", MISSING)))
        if entry.get("address") == ARTIFACT_READER_IAM_ADDRESS and isinstance(before, dict) and isinstance(after, dict):
            expected_member = f"serviceAccount:helpdesk-gke-node-dev@{PROJECT}.iam.gserviceaccount.com"
            expected_repositories = (REGISTRY_REPOSITORY_ID, REGISTRY_REPOSITORY_PATH)
            for snapshot_name, snapshot in (("before", before), ("after", after)):
                identity_matches = (
                    snapshot.get("project") in (PROJECT, PROJECT_NUMBER)
                    and snapshot.get("location") == "us-east1"
                    and snapshot.get("repository") in expected_repositories
                    and snapshot.get("role") == "roles/artifactregistry.reader"
                    and snapshot.get("member") == expected_member
                )
                lines.append("  " + snapshot_name + " repository reader identity: "
                             + ("expected" if identity_matches else "unexpected (values withheld)"))
            lines.append("  etag representation: before="
                         + etag_readback_status(before.get("etag", MISSING))
                         + "; after=" + etag_readback_status(after.get("etag", MISSING)))
        if entry.get("address") in SECRET_IAM_READBACKS and isinstance(before, dict) and isinstance(after, dict):
            secret_id, expected_member = SECRET_IAM_READBACKS[entry["address"]]
            expected_path = f"projects/{PROJECT}/secrets/{secret_id}"
            for snapshot_name, snapshot in (("before", before), ("after", after)):
                identity_matches = (
                    snapshot.get("secret_id") in (secret_id, expected_path)
                    and snapshot.get("role") == SECRET_ACCESSOR_ROLE
                    and snapshot.get("member") == expected_member
                    and snapshot.get("project", MISSING) in (MISSING, PROJECT, PROJECT_NUMBER)
                )
                lines.append("  " + snapshot_name + " secret IAM role, resource and principal: "
                             + ("expected" if identity_matches else "unexpected (values withheld)"))
            lines.append("  etag representation: before="
                         + etag_readback_status(before.get("etag", MISSING))
                         + "; after=" + etag_readback_status(after.get("etag", MISSING)))
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
    if drift_is_acknowledgeable(plan):
        lines.append("Drift acknowledgement fingerprint (addresses/actions/field paths only; no values): "
                     + drift_fingerprint(plan))
        lines.append("If Apply blocks intentional drift, pass this fingerprint to the protected Terraform Dev Apply.")
    else:
        lines.append("No general acknowledgement is available for this drift; deletions, replacements, "
                     "unknown resources, and malformed drift remain blocked.")
    lines.append("Only exact documented normalization patterns pass automatically.")
    return lines


def verify_deployment(paths):
    require(len(paths) == DEPLOYMENT_EVIDENCE_PATH_COUNT,
            "Expected read-only Phase 7-10 evidence, Terraform state, and addresses")
    network, subnet, address, connections, registry, registry_iam, project_iam, sql, databases, outputs = [read_json(p) for p in paths[:10]]
    state_addresses = set(Path(paths[-1]).read_text(encoding="utf-8").splitlines())
    require(state_addresses == set(PLANNED_EXPECTED), "Dev state does not contain exactly the approved resources")
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

    phase7_evidence = [read_json(path) for path in paths[10:20]]
    app_secret_iam, admin_secret_iam = phase7_evidence[8], phase7_evidence[9]
    verify_phase7(*phase7_evidence, registry_iam, project_iam, outputs)
    state = read_json(paths[20])
    verify_phase8(read_json(paths[21]), read_json(paths[22]), read_json(paths[23]),
                  registry_iam, project_iam)
    verify_phase9(read_json(paths[24]), read_json(paths[25]), read_json(paths[26]),
                  project_iam, app_secret_iam, admin_secret_iam, outputs)
    verify_phase10(
        read_json(paths[27]), read_json(paths[28]), read_json(paths[29]),
        read_json(paths[30]), read_json(paths[31]), read_json(paths[32]),
        registry_iam, project_iam, app_secret_iam, admin_secret_iam,
    )
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


def verify_phase8(publisher_sa, publisher_sa_iam, provider, registry_iam, project_iam):
    """Check the dedicated App publisher identity without broadening project access."""
    require(publisher_sa.get("email") == SUPPORT_PUBLISHER_EMAIL
            and publisher_sa.get("disabled") is not True,
            "Supporting-image publisher service account identity or status mismatch")
    check_iam(publisher_sa_iam, "supporting-image publisher service account")
    wif_bindings = [set(binding.get("members", [])) for binding in publisher_sa_iam.get("bindings", [])
                    if binding.get("role") == "roles/iam.workloadIdentityUser"]
    require(wif_bindings == [{SUPPORT_PUBLISHER_MEMBER}]
            and len(publisher_sa_iam.get("bindings", [])) == 1,
            "Supporting-image impersonation binding differs from the exact verified subject")

    expected_provider_names = {
        f"projects/{PROJECT}/locations/global/workloadIdentityPools/helpdesk-github/providers/"
        f"{SUPPORT_PUBLISHER_PROVIDER_ID}",
        f"projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/helpdesk-github/providers/"
        f"{SUPPORT_PUBLISHER_PROVIDER_ID}",
    }
    require(provider.get("name") in expected_provider_names and provider.get("state") == "ACTIVE",
            "Supporting-image Workload Identity provider identity or status mismatch")
    require(provider.get("attributeMapping") == SUPPORT_PUBLISHER_MAPPING
            and normalize_cel(provider.get("attributeCondition")) == SUPPORT_PUBLISHER_CONDITION
            and provider.get("oidc", {}).get("issuerUri") == "https://token.actions.githubusercontent.com",
            "Supporting-image provider trust configuration mismatch")

    publisher_member = f"serviceAccount:{SUPPORT_PUBLISHER_EMAIL}"
    writer_bindings = [set(binding.get("members", [])) for binding in registry_iam.get("bindings", [])
                       if binding.get("role") == "roles/artifactregistry.writer"]
    allowed_publishers = {
        publisher_member,
        f"serviceAccount:{APP_PUBLISHER_EMAIL}",
    }
    require(len(writer_bindings) == 1 and publisher_member in writer_bindings[0]
            and writer_bindings[0] <= allowed_publishers,
            "Artifact Registry Writer contains an unexpected principal on the Dev repository")
    require(not has_binding(project_iam, "roles/artifactregistry.writer", publisher_member)
            and not has_binding(project_iam, "roles/artifactregistry.admin", publisher_member),
            "Supporting-image publisher has a project-wide Artifact Registry grant")


def verify_phase9(runner_sa, runner_sa_iam, provider, project_iam, app_secret_iam,
                  admin_secret_iam, outputs):
    """Verify that GitHub can only submit the reviewed namespace migration Job."""
    require(runner_sa.get("email") == MIGRATION_RUNNER_EMAIL
            and runner_sa.get("disabled") is not True,
            "Migration-runner service account identity or status mismatch")
    check_iam(runner_sa_iam, "migration-runner service account")
    wif_bindings = [set(binding.get("members", [])) for binding in runner_sa_iam.get("bindings", [])
                    if binding.get("role") == "roles/iam.workloadIdentityUser"]
    require(wif_bindings == [{MIGRATION_RUNNER_MEMBER}]
            and len(runner_sa_iam.get("bindings", [])) == 1,
            "Migration-runner impersonation binding differs from the exact verified Environment subject")

    expected_provider_names = {
        f"projects/{PROJECT}/locations/global/workloadIdentityPools/helpdesk-github/providers/"
        f"{MIGRATION_RUNNER_PROVIDER_ID}",
        f"projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/helpdesk-github/providers/"
        f"{MIGRATION_RUNNER_PROVIDER_ID}",
    }
    require(provider.get("name") in expected_provider_names and provider.get("state") == "ACTIVE",
            "Migration-runner Workload Identity provider identity or status mismatch")
    require(provider.get("attributeMapping") == SUPPORT_PUBLISHER_MAPPING
            and normalize_cel(provider.get("attributeCondition")) == MIGRATION_RUNNER_CONDITION
            and provider.get("oidc", {}).get("issuerUri") == "https://token.actions.githubusercontent.com",
            "Migration-runner provider trust configuration mismatch")

    runner_member = f"serviceAccount:{MIGRATION_RUNNER_EMAIL}"
    runner_project_bindings = [binding for binding in project_iam.get("bindings", [])
                               if runner_member in binding.get("members", [])]
    cluster_viewer_bindings = [binding for binding in runner_project_bindings
                               if binding.get("role") == "roles/container.clusterViewer"]
    require(len(cluster_viewer_bindings) == 1
            and not cluster_viewer_bindings[0].get("condition")
            and len(runner_project_bindings) == 1,
            "Migration runner must have exactly one unconditional project-level GKE clusterViewer grant")

    for policy, label in ((app_secret_iam, "application Secret Manager"),
                          (admin_secret_iam, "migration Secret Manager")):
        require(not any(runner_member in binding.get("members", [])
                        and str(binding.get("role", "")).startswith("roles/secretmanager.")
                        for binding in policy.get("bindings", [])),
                f"Migration runner has direct access to the {label} resource")
    require(not any(runner_member in binding.get("members", [])
                    and str(binding.get("role", "")).startswith(("roles/cloudsql.", "roles/secretmanager."))
                    for binding in project_iam.get("bindings", [])),
            "Migration runner has direct Cloud SQL or Secret Manager project access")
    require(outputs.get("migration_runner_service_account", {}).get("value") == MIGRATION_RUNNER_EMAIL,
            "Terraform migration-runner service-account output mismatch")


def verify_phase10(publisher_sa, publisher_sa_iam, publisher_provider,
                   deployer_sa, deployer_sa_iam, deployer_provider,
                   registry_iam, project_iam, app_secret_iam, admin_secret_iam):
    """Verify only the two exact app-delivery identities and their resource-scoped grants."""
    for account, email, label in (
        (publisher_sa, APP_PUBLISHER_EMAIL, "application publisher"),
        (deployer_sa, APP_DEPLOYER_EMAIL, "application deployer"),
    ):
        expected_display_name = (APP_PUBLISHER_DISPLAY_NAME if label == "application publisher"
                                 else APP_DEPLOYER_DISPLAY_NAME)
        require(account.get("email") == email and account.get("displayName") == expected_display_name
                and account.get("disabled") is not True,
                f"{label} service account identity or status mismatch")

    for policy, member, label in (
        (publisher_sa_iam, APP_PUBLISHER_MEMBER, "application publisher"),
        (deployer_sa_iam, APP_DEPLOYER_MEMBER, "application deployer"),
    ):
        check_iam(policy, label + " service account")
        wif_bindings = [set(binding.get("members", [])) for binding in policy.get("bindings", [])
                        if binding.get("role") == "roles/iam.workloadIdentityUser"]
        require(wif_bindings == [{member}] and len(policy.get("bindings", [])) == 1,
                f"{label} impersonation is not limited to the exact protected Environment subject")

    provider_specs = (
        (publisher_provider, APP_PUBLISHER_PROVIDER_ID, APP_PUBLISHER_CONDITION,
         "application publisher"),
        (deployer_provider, APP_DEPLOYER_PROVIDER_ID, APP_DEPLOYER_CONDITION,
         "application deployer"),
    )
    for provider, provider_id, condition, label in provider_specs:
        expected_names = {
            f"projects/{PROJECT}/locations/global/workloadIdentityPools/helpdesk-github/providers/{provider_id}",
            f"projects/{PROJECT_NUMBER}/locations/global/workloadIdentityPools/helpdesk-github/providers/{provider_id}",
        }
        require(provider.get("name") in expected_names and provider.get("state") == "ACTIVE",
                f"{label} Workload Identity provider identity or status mismatch")
        # gcloud can omit the API's default-false `disabled` field from a GET
        # response. The ACTIVE state was checked above; accept either that
        # omission or an explicit false, while still rejecting true/malformed values.
        require(("disabled" not in provider or provider.get("disabled") is False)
                and provider.get("attributeMapping") == APP_DELIVERY_MAPPING
                and normalize_cel(provider.get("attributeCondition")) == condition
                and provider.get("oidc", {}).get("issuerUri") == "https://token.actions.githubusercontent.com",
                f"{label} provider trust configuration mismatch")

    publisher_member = f"serviceAccount:{APP_PUBLISHER_EMAIL}"
    deployer_member = f"serviceAccount:{APP_DEPLOYER_EMAIL}"
    publisher_project_bindings = [binding for binding in project_iam.get("bindings", [])
                                  if publisher_member in binding.get("members", [])]
    deployer_project_bindings = [binding for binding in project_iam.get("bindings", [])
                                 if deployer_member in binding.get("members", [])]
    require(not publisher_project_bindings,
            "Application publisher has an unapproved project-level IAM grant")
    require(len(deployer_project_bindings) == 1
            and deployer_project_bindings[0].get("role") == "roles/container.clusterViewer"
            and not deployer_project_bindings[0].get("condition"),
            "Application deployer must have only the unconditional GKE DNS endpoint clusterViewer grant")

    writer_members = {
        member
        for binding in registry_iam.get("bindings", [])
        if binding.get("role") == "roles/artifactregistry.writer"
        for member in binding.get("members", [])
    }
    require(writer_members == {
        f"serviceAccount:{SUPPORT_PUBLISHER_EMAIL}",
        publisher_member,
    }, "Dev repository Writer must be limited to the two approved publisher service accounts")
    require(not has_binding(project_iam, "roles/artifactregistry.writer", publisher_member)
            and not has_binding(project_iam, "roles/artifactregistry.admin", publisher_member),
            "Application publisher has a project-wide Artifact Registry grant")

    runtime_member = f"serviceAccount:helpdesk-app-dev@{PROJECT}.iam.gserviceaccount.com"
    app_secret_bindings = [set(binding.get("members", [])) for binding in app_secret_iam.get("bindings", [])
                           if binding.get("role") == "roles/secretmanager.secretAccessor"]
    expected_app_secret_members = {
        f"principal://iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
        f"workloadIdentityPools/{PROJECT}.svc.id.goog/subject/ns/helpdesk-dev/sa/helpdesk-dev-app",
        runtime_member,
    }
    require(app_secret_bindings == [expected_app_secret_members]
            and len(app_secret_iam.get("bindings", [])) == 1,
            "Runtime Google service account must access only the app connection secret")
    require(not any(runtime_member in binding.get("members", [])
                    and binding.get("role") == "roles/secretmanager.secretAccessor"
                    for binding in admin_secret_iam.get("bindings", [])),
            "Runtime application service account has access to the administrator password secret")
    require(not any(runtime_member in binding.get("members", [])
                    and str(binding.get("role", "")).startswith("roles/secretmanager.")
                    for binding in project_iam.get("bindings", [])),
            "Runtime application service account has project-wide Secret Manager access")
    require(not any(deployer_member in binding.get("members", [])
                    and str(binding.get("role", "")).startswith(
                        ("roles/artifactregistry.", "roles/cloudsql.", "roles/secretmanager."))
                    for binding in project_iam.get("bindings", [])),
            "Application deployer has an unapproved project-level data or registry grant")


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
            and endpoints.get("dnsEndpointConfig", {}).get("allowExternalTraffic") is True
            and endpoints.get("dnsEndpointConfig", {}).get("endpoint") == MIGRATION_RUNNER_DNS_ENDPOINT,
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
        expected_members = {member}
        if name == "helpdesk-dev-db-admin-password":
            expected_members.add(
                f"serviceAccount:helpdesk-migrate-dev@{PROJECT}.iam.gserviceaccount.com"
            )
        else:
            expected_members.add(f"serviceAccount:helpdesk-app-dev@{PROJECT}.iam.gserviceaccount.com")
        bindings = [set(b.get("members", [])) for b in policy.get("bindings", [])
                    if b.get("role") == "roles/secretmanager.secretAccessor"]
        require(bindings == [expected_members],
                "Secret access is not limited to the intended workload identities")
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
        if len(sys.argv) >= 3 and sys.argv[1] == "check-plan":
            plan_path = sys.argv[2]
            arguments = sys.argv[3:]
            report_drift_only = "--report-drift" in arguments
            arguments = [argument for argument in arguments if argument != "--report-drift"]
            acknowledged_drift_fingerprint = None
            if "--acknowledged-drift" in arguments:
                index = arguments.index("--acknowledged-drift")
                if index + 1 >= len(arguments):
                    raise ValueError("--acknowledged-drift requires the fingerprint from Dev Plan")
                acknowledged_drift_fingerprint = arguments[index + 1] or None
                del arguments[index:index + 2]
            if arguments and arguments[-1] == "":
                arguments.pop()
            if len(arguments) not in (0, 2):
                raise ValueError("check-plan accepts either zero or two live Secret Manager policy files")
            policies = None
            if arguments:
                policies = {
                    "helpdesk-dev-db-connection": read_json(arguments[0]),
                    "helpdesk-dev-db-admin-password": read_json(arguments[1]),
                }
            print(check_plan(
                read_json(plan_path),
                secret_iam_policies=policies,
                acknowledged_drift_fingerprint=acknowledged_drift_fingerprint,
                report_drift_only=report_drift_only,
            ))
        elif len(sys.argv) == 3 and sys.argv[1] == "diagnose-drift":
            print("\n".join(diagnose_drift(read_json(sys.argv[2]))))
        elif len(sys.argv) == 3 and sys.argv[1] == "check-project-iam":
            check_iam(read_json(sys.argv[2]), "project")
            print("No direct public project IAM binding found")
        elif len(sys.argv) == DEPLOYMENT_EVIDENCE_PATH_COUNT + 2 and sys.argv[1] == "verify-deployment":
            verify_deployment(sys.argv[2:])
            print("Approved Dev resources, IAM, outputs, and deletion protection verified")
        else:
            raise ValueError("Usage: dev_infra_guard.py check-plan PLAN_JSON [APP_SECRET_IAM ADMIN_SECRET_IAM] "
                             "[--report-drift] [--acknowledged-drift FINGERPRINT] | "
                             "diagnose-drift PLAN_JSON | "
                             "check-project-iam PROJECT_IAM_JSON | "
                             "verify-deployment VPC SUBNET ADDRESS CONNECTIONS REGISTRY REGISTRY_IAM PROJECT_IAM "
                             "SQL DATABASES OUTPUTS "
                             "CLUSTER NODE_SA APP_SA MIGRATION_SA APP_SECRET ADMIN_SECRET APP_SA_IAM MIGRATION_SA_IAM "
                             "APP_SECRET_IAM ADMIN_SECRET_IAM STATE_JSON SUPPORT_IMAGE_PUBLISHER_SA "
                             "SUPPORT_IMAGE_PUBLISHER_SA_IAM SUPPORT_IMAGE_PROVIDER MIGRATION_RUNNER_SA "
                             "MIGRATION_RUNNER_SA_IAM MIGRATION_RUNNER_PROVIDER APP_PUBLISHER_SA "
                             "APP_PUBLISHER_SA_IAM APP_PUBLISHER_PROVIDER APP_DEPLOYER_SA "
                             "APP_DEPLOYER_SA_IAM APP_DEPLOYER_PROVIDER STATE_LIST")
    except (ValueError, KeyError, IndexError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"Dev infrastructure guard stopped: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
