"""Offline tests for the protected Dev Apply decision and read-only verification."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from dev_infra_guard import (APPLY12_COMPLETED, APPLY12_REMAINING, ATTRIBUTION_LABEL, BASE, EXPECTED,
                             NETWORK, PHASE6, PHASE7, PSA_ADDRESS, REGISTRY_ADDRESS, SQL_ADDRESS,
                             SUBNET_ADDRESS, SUBNET_PATHS, VPC_LINK, VPC_PATH, VPC_PATHS,
                             check_plan, diagnose_drift, permitted_drift, verify_deployment)


def terraform_references(attribute_reference):
    """Terraform JSON includes indexed attribute, instance, and collection traversals."""
    resource_address = attribute_reference.rsplit(".", 1)[0]
    if "[" in resource_address:
        return [attribute_reference, resource_address, resource_address.split("[", 1)[0]]
    return [attribute_reference]


def strict_reference_cases(plan):
    """Every exact identity and atomic project reference checked by the guard."""
    resources = {item["address"]: item["expressions"]
                 for item in plan["configuration"]["root_module"]["resources"]}
    cluster = resources["google_container_cluster.dev"]
    cases = [("GKE node identity", cluster["cluster_autoscaling"][0]["auto_provisioning_defaults"][0][
        "service_account"], "google_service_account.dev_gke_nodes[0].email")]
    for address, field, expected in (
        ("google_artifact_registry_repository_iam_member.dev_gke_image_pull", "member", "google_service_account.dev_gke_nodes[0].member"),
        ("google_service_account_iam_member.dev_app_workload_identity", "service_account_id", "google_service_account.dev_app[0].name"),
        ("google_service_account_iam_member.dev_migration_workload_identity", "service_account_id", "google_service_account.dev_migration[0].name"),
        ("google_secret_manager_secret_iam_member.dev_app_secret_access", "secret_id", "google_secret_manager_secret.dev_app_connection[0].id"),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access", "secret_id", "google_secret_manager_secret.dev_admin_password[0].id"),
        ("google_project_iam_member.dev_gke_node_runtime", "member", "google_service_account.dev_gke_nodes[0].member"),
        ("google_project_iam_member.dev_app_cloudsql", "member", "google_service_account.dev_app[0].member"),
        ("google_project_iam_member.dev_migration_cloudsql", "member", "google_service_account.dev_migration[0].member"),
    ):
        cases.append((f"{address}.{field}", resources[address][field], expected))
    for address in ("google_service_account.dev_gke_nodes", "google_service_account.dev_app",
                    "google_service_account.dev_migration"):
        cases.append((f"{address}.project", resources[address]["project"], "var.project_id"))
    return cases


def fixture():
    network = {
        "google_compute_network": {"name": "helpdeskcloud-dev-vpc", "auto_create_subnetworks": False,
                                   "routing_mode": "REGIONAL"},
        "google_compute_subnetwork": {"name": "helpdeskcloud-dev-subnet", "region": "us-east1",
                                      "ip_cidr_range": "10.20.0.0/20", "private_ip_google_access": True,
                                      "secondary_ip_range": [
                                          {"range_name": "helpdeskcloud-dev-pods", "ip_cidr_range": "10.24.0.0/16"},
                                          {"range_name": "helpdeskcloud-dev-services", "ip_cidr_range": "10.25.0.0/20"}]},
        "google_compute_global_address": {"name": "helpdeskcloud-dev-psa", "address": "10.30.0.0",
                                          "prefix_length": 16, "purpose": "VPC_PEERING", "address_type": "INTERNAL"},
        "google_service_networking_connection": {"service": "servicenetworking.googleapis.com",
                                                 "reserved_peering_ranges": ["helpdeskcloud-dev-psa"]},
    }
    phase6 = {
        "google_artifact_registry_repository": {
            "project": "helpdeskcloud-capstone-511905", "location": "us-east1", "repository_id": "helpdeskcloud-dev-images",
            "format": "DOCKER", "docker_config": [{"immutable_tags": True}]},
        "google_sql_database_instance": {
            "project": "helpdeskcloud-capstone-511905", "name": "helpdeskcloud-dev-postgres", "region": "us-east1",
            "database_version": "POSTGRES_17", "deletion_protection": True,
            "settings": [{"edition": "ENTERPRISE", "tier": "db-f1-micro", "availability_type": "ZONAL",
                          "disk_type": "PD_SSD", "disk_size": 10, "disk_autoresize": False,
                          "deletion_protection_enabled": True,
                          "backup_configuration": [{"enabled": True, "point_in_time_recovery_enabled": False,
                                                    "backup_retention_settings": [{"retained_backups": 7, "retention_unit": "COUNT"}]}],
                          "ip_configuration": [{"ipv4_enabled": False, "private_network": VPC_LINK,
                                                "allocated_ip_range": "helpdeskcloud-dev-psa", "ssl_mode": "ENCRYPTED_ONLY"}]}]},
        "google_sql_database": {"project": "helpdeskcloud-capstone-511905", "name": "helpdesk",
                                "instance": "helpdeskcloud-dev-postgres"},
    }
    project = "helpdeskcloud-capstone-511905"
    node = f"helpdesk-gke-node-dev@{project}.iam.gserviceaccount.com"
    app = f"helpdesk-app-dev@{project}.iam.gserviceaccount.com"
    migration = f"helpdesk-migrate-dev@{project}.iam.gserviceaccount.com"
    principal = f"principal://iam.googleapis.com/projects/260283083469/locations/global/workloadIdentityPools/{project}.svc.id.goog/subject/ns/helpdesk-dev/sa/"
    phase7 = {
        "google_container_cluster.dev[0]": {
            "project": project, "name": "helpdeskcloud-dev-gke", "location": "us-east1",
            "enable_autopilot": True, "deletion_protection": True,
            "network": VPC_LINK,
            "subnetwork": f"https://www.googleapis.com/compute/v1/projects/{project}/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet",
            "networking_mode": "VPC_NATIVE",
            "ip_allocation_policy": [{"cluster_secondary_range_name": "helpdeskcloud-dev-pods",
                                      "services_secondary_range_name": "helpdeskcloud-dev-services"}],
            "private_cluster_config": [{"enable_private_nodes": True, "enable_private_endpoint": True}],
            "control_plane_endpoints_config": [{"dns_endpoint_config": [{"allow_external_traffic": True}],
                                                "ip_endpoints_config": [{"enabled": False}]}],
            "workload_identity_config": [{"workload_pool": f"{project}.svc.id.goog"}],
            "secret_manager_config": [{"enabled": True}], "release_channel": [{"channel": "REGULAR"}],
            "cluster_autoscaling": [{"auto_provisioning_defaults": [{"service_account": node}]}],
        },
        "google_service_account.dev_gke_nodes[0]": {"project": project, "account_id": "helpdesk-gke-node-dev",
            "email": node, "member": f"serviceAccount:{node}",
            "name": f"projects/{project}/serviceAccounts/{node}"},
        "google_service_account.dev_app[0]": {"project": project, "account_id": "helpdesk-app-dev",
            "email": app, "member": f"serviceAccount:{app}",
            "name": f"projects/{project}/serviceAccounts/{app}"},
        "google_service_account.dev_migration[0]": {"project": project, "account_id": "helpdesk-migrate-dev",
            "email": migration, "member": f"serviceAccount:{migration}",
            "name": f"projects/{project}/serviceAccounts/{migration}"},
        "google_project_iam_member.dev_gke_node_runtime[0]": {"project": project, "role": "roles/container.defaultNodeServiceAccount", "member": f"serviceAccount:{node}"},
        "google_project_iam_member.dev_app_cloudsql[0]": {"project": project, "role": "roles/cloudsql.client", "member": f"serviceAccount:{app}"},
        "google_project_iam_member.dev_migration_cloudsql[0]": {"project": project, "role": "roles/cloudsql.client", "member": f"serviceAccount:{migration}"},
        "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]": {
            "project": project, "location": "us-east1", "repository": "helpdeskcloud-dev-images",
            "role": "roles/artifactregistry.reader", "member": f"serviceAccount:{node}"},
        "google_service_account_iam_member.dev_app_workload_identity[0]": {
            "role": "roles/iam.workloadIdentityUser", "service_account_id": f"projects/{project}/serviceAccounts/{app}",
            "member": f"serviceAccount:{project}.svc.id.goog[helpdesk-dev/helpdesk-dev-app]"},
        "google_service_account_iam_member.dev_migration_workload_identity[0]": {
            "role": "roles/iam.workloadIdentityUser", "service_account_id": f"projects/{project}/serviceAccounts/{migration}",
            "member": f"serviceAccount:{project}.svc.id.goog[helpdesk-dev/helpdesk-dev-migrate]"},
        "google_secret_manager_secret.dev_app_connection[0]": {
            "project": project, "secret_id": "helpdesk-dev-db-connection", "deletion_protection": True,
            "replication": [{"auto": [{}]}]},
        "google_secret_manager_secret.dev_admin_password[0]": {
            "project": project, "secret_id": "helpdesk-dev-db-admin-password", "deletion_protection": True,
            "replication": [{"auto": [{}]}]},
        "google_secret_manager_secret_iam_member.dev_app_secret_access[0]": {
            "role": "roles/secretmanager.secretAccessor",
            "secret_id": f"projects/{project}/secrets/helpdesk-dev-db-connection",
            "member": principal + "helpdesk-dev-app"},
        "google_secret_manager_secret_iam_member.dev_admin_secret_access[0]": {
            "role": "roles/secretmanager.secretAccessor",
            "secret_id": f"projects/{project}/secrets/helpdesk-dev-db-admin-password",
            "member": principal + "helpdesk-dev-migrate"},
    }
    config = {
        "root_module": {
            "resources": [
                {"address": "google_sql_database_instance.dev_postgres", "depends_on": ["module.dev_network"],
                 "expressions": {"settings": [{"ip_configuration": [{
                     "private_network": {"references": ["module.dev_network[0].vpc_self_link"]},
                     "allocated_ip_range": {"references": ["module.dev_network[0].private_services_range_name"]}}]}]}},
                {"address": "google_sql_database.dev_helpdesk", "expressions": {
                    "instance": {"references": ["google_sql_database_instance.dev_postgres[0].name"]}}},
                {"address": "google_container_cluster.dev",
                 "depends_on": ["google_project_iam_member.dev_gke_node_runtime",
                                "google_artifact_registry_repository_iam_member.dev_gke_image_pull"],
                 "expressions": {
                     "network": {"references": ["module.dev_network[0].vpc_self_link"]},
                     "subnetwork": {"references": ["module.dev_network[0].subnet_self_link"]},
                     "ip_allocation_policy": [{
                         "cluster_secondary_range_name": {"references": ["module.dev_network[0].pods_range_name"]},
                         "services_secondary_range_name": {"references": ["module.dev_network[0].services_range_name"]}}],
                     "cluster_autoscaling": [{"auto_provisioning_defaults": [{
                         "service_account": {"references": terraform_references("google_service_account.dev_gke_nodes[0].email")}}]}]}},
                {"address": "google_artifact_registry_repository_iam_member.dev_gke_image_pull",
                 "expressions": {"role": {"constant_value": "roles/artifactregistry.reader"},
                                 "member": {"references": terraform_references("google_service_account.dev_gke_nodes[0].member")}}},
                {"address": "google_service_account_iam_member.dev_app_workload_identity",
                 "depends_on": ["google_container_cluster.dev"],
                 "expressions": {"role": {"constant_value": "roles/iam.workloadIdentityUser"},
                                 "service_account_id": {"references": terraform_references("google_service_account.dev_app[0].name")}}},
                {"address": "google_service_account_iam_member.dev_migration_workload_identity",
                 "depends_on": ["google_container_cluster.dev"],
                 "expressions": {"role": {"constant_value": "roles/iam.workloadIdentityUser"},
                                 "service_account_id": {"references": terraform_references("google_service_account.dev_migration[0].name")}}},
                {"address": "google_secret_manager_secret_iam_member.dev_app_secret_access",
                 "depends_on": ["google_container_cluster.dev"],
                 "expressions": {"role": {"constant_value": "roles/secretmanager.secretAccessor"},
                                 "secret_id": {"references": terraform_references("google_secret_manager_secret.dev_app_connection[0].id")}}},
                {"address": "google_secret_manager_secret_iam_member.dev_admin_secret_access",
                 "depends_on": ["google_container_cluster.dev"],
                 "expressions": {"role": {"constant_value": "roles/secretmanager.secretAccessor"},
                                 "secret_id": {"references": terraform_references("google_secret_manager_secret.dev_admin_password[0].id")}}},
                {"address": "google_service_account.dev_gke_nodes", "expressions": {
                    "account_id": {"constant_value": "helpdesk-gke-node-dev"},
                    "project": {"references": ["var.project_id"]}}},
                {"address": "google_service_account.dev_app", "expressions": {
                    "account_id": {"constant_value": "helpdesk-app-dev"},
                    "project": {"references": ["var.project_id"]}}},
                {"address": "google_service_account.dev_migration", "expressions": {
                    "account_id": {"constant_value": "helpdesk-migrate-dev"},
                    "project": {"references": ["var.project_id"]}}},
                {"address": "google_project_iam_member.dev_gke_node_runtime", "expressions": {
                    "role": {"constant_value": "roles/container.defaultNodeServiceAccount"},
                    "member": {"references": terraform_references("google_service_account.dev_gke_nodes[0].member")}}},
                {"address": "google_project_iam_member.dev_app_cloudsql", "expressions": {
                    "role": {"constant_value": "roles/cloudsql.client"},
                    "member": {"references": terraform_references("google_service_account.dev_app[0].member")}}},
                {"address": "google_project_iam_member.dev_migration_cloudsql", "expressions": {
                    "role": {"constant_value": "roles/cloudsql.client"},
                    "member": {"references": terraform_references("google_service_account.dev_migration[0].member")}}},
            ],
            "module_calls": {"dev_network": {"module": {"resources": [
                {"address": "google_compute_subnetwork.this", "expressions": {
                    "network": {"references": ["google_compute_network.this.id"]}}},
                {"address": "google_compute_global_address.private_services", "expressions": {
                    "network": {"references": ["google_compute_network.this.id"]}}},
                {"address": "google_service_networking_connection.private_services", "expressions": {
                    "network": {"references": ["google_compute_network.this.id"]},
                    "reserved_peering_ranges": {"references": ["google_compute_global_address.private_services.name"]}}},
            ]}}},
        }
    }
    planned = [{"mode": "managed", "address": address, "type": kind,
                "values": phase7[address] if address in PHASE7 else (network | phase6)[kind]}
               for address, kind in EXPECTED.items()]
    changes = [{"mode": "managed", "address": address, "type": kind,
                "change": {"actions": ["no-op"] if address in BASE else ["create"]}}
               for address, kind in EXPECTED.items()]
    prior_state = [copy.deepcopy(resource) for resource in planned if resource["address"] in BASE]
    return {
        "variables": {key: {"value": value} for key, value in {
            "project_id": "helpdeskcloud-capstone-511905", "region": "us-east1", "environment": "dev"}.items()},
        "prior_state": {"values": {"root_module": {"resources": prior_state}}},
        "planned_values": {"root_module": {"resources": planned}},
        "resource_changes": changes,
        "configuration": config,
    }


def resource(plan, address):
    return next(r for r in plan["planned_values"]["root_module"]["resources"]
                if r["address"] == address)


def set_prior_phase7(plan, addresses):
    """Set the prior state to the fixture's baseline plus selected Phase 7 addresses."""
    allowed = set(BASE) | set(addresses)
    plan["prior_state"]["values"]["root_module"]["resources"] = [
        copy.deepcopy(item) for item in plan["planned_values"]["root_module"]["resources"]
        if item["address"] in allowed
    ]


def apply12_recovery_plan():
    """Model a refreshed plan after Apply #12 created exactly its six successful resources."""
    plan = fixture()
    for change in plan["resource_changes"]:
        if change["address"] in APPLY12_COMPLETED:
            change["change"]["actions"] = ["no-op"]
    set_prior_phase7(plan, APPLY12_COMPLETED)
    return plan


def set_nested(document, path, value):
    current = document
    for index, part in enumerate(path[:-1]):
        next_part = path[index + 1]
        if isinstance(part, int):
            while len(current) <= part:
                current.append({} if not isinstance(next_part, int) else [])
            current = current[part]
        else:
            current = current.setdefault(part, [] if isinstance(next_part, int) else {})
    last = path[-1]
    if isinstance(last, int):
        while len(current) <= last:
            current.append(None)
        current[last] = value
    else:
        current[last] = value


def remove_nested(document, path):
    current = document
    for part in path[:-1]:
        current = current[part]
    last = path[-1]
    if isinstance(current, dict):
        current.pop(last, None)
    else:
        del current[last]


def mark_unknown(plan, address, field_path, omit_value=False):
    """Model Terraform plan JSON's null or omitted unknown value and marker."""
    planned = resource(plan, address)["values"]
    if omit_value:
        remove_nested(planned, field_path)
    else:
        set_nested(planned, field_path, None)
    change = next(c for c in plan["resource_changes"] if c["address"] == address)["change"]
    set_nested(change.setdefault("after_unknown", {}), field_path, True)


def unknown_identity_plan():
    plan = fixture()
    computed_fields = [
        ("google_service_account.dev_gke_nodes[0]", ("email",)),
        ("google_service_account.dev_gke_nodes[0]", ("member",)),
        ("google_service_account.dev_gke_nodes[0]", ("name",)),
        ("google_service_account.dev_app[0]", ("email",)),
        ("google_service_account.dev_app[0]", ("member",)),
        ("google_service_account.dev_app[0]", ("name",)),
        ("google_service_account.dev_migration[0]", ("email",)),
        ("google_service_account.dev_migration[0]", ("member",)),
        ("google_service_account.dev_migration[0]", ("name",)),
        ("google_container_cluster.dev[0]",
         ("cluster_autoscaling", 0, "auto_provisioning_defaults", 0, "service_account")),
        ("google_project_iam_member.dev_gke_node_runtime[0]", ("member",)),
        ("google_project_iam_member.dev_app_cloudsql[0]", ("member",)),
        ("google_project_iam_member.dev_migration_cloudsql[0]", ("member",)),
        ("google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]", ("member",)),
        ("google_service_account_iam_member.dev_app_workload_identity[0]", ("service_account_id",)),
        ("google_service_account_iam_member.dev_migration_workload_identity[0]", ("service_account_id",)),
        ("google_secret_manager_secret_iam_member.dev_app_secret_access[0]", ("secret_id",)),
        ("google_secret_manager_secret_iam_member.dev_admin_secret_access[0]", ("secret_id",)),
    ]
    for address, field_path in computed_fields:
        mark_unknown(plan, address, field_path)
    return plan


def label_drift():
    before = {"name": "helpdeskcloud-dev-psa", "address": "10.30.0.0", "labels": None,
              "terraform_labels": ATTRIBUTION_LABEL, "effective_labels": ATTRIBUTION_LABEL}
    after = copy.deepcopy(before)
    after["labels"] = {}
    return {"mode": "managed", "address": PSA_ADDRESS, "type": "google_compute_global_address",
            "change": {"actions": ["update"], "before": before, "after": after}}


def metadata_drift(after_fields=None, omit_after=False):
    before = {"name": "helpdeskcloud-dev-subnet", "ip_cidr_range": "10.20.0.0/20",
              "log_config": [{"metadata": "EXCLUDE_ALL_METADATA", "metadata_fields": None}]}
    after = copy.deepcopy(before)
    if omit_after:
        del after["log_config"][0]["metadata_fields"]
    else:
        after["log_config"][0]["metadata_fields"] = [] if after_fields is None else after_fields
    return {"mode": "managed", "address": SUBNET_ADDRESS, "type": "google_compute_subnetwork",
            "change": {"actions": ["update"], "before": before, "after": after}}


def registry_drift():
    before = {"project": "helpdeskcloud-capstone-511905", "location": "us-east1",
              "repository_id": "helpdeskcloud-dev-images", "format": "DOCKER",
              "docker_config": [{"immutable_tags": True}], "labels": None,
              "terraform_labels": ATTRIBUTION_LABEL, "effective_labels": ATTRIBUTION_LABEL}
    after = copy.deepcopy(before)
    after["labels"] = {}
    return {"mode": "managed", "address": REGISTRY_ADDRESS, "type": "google_artifact_registry_repository",
            "change": {"actions": ["update"], "before": before, "after": after}}


def sql_readback_drift():
    before = {"project": "helpdeskcloud-capstone-511905", "name": "helpdeskcloud-dev-postgres",
              "region": "us-east1", "database_version": "POSTGRES_17",
              "deletion_protection": True,
              "settings": [{"version": 1, "edition": "ENTERPRISE", "tier": "db-f1-micro",
                            "availability_type": "ZONAL", "disk_type": "PD_SSD", "disk_size": 10,
                            "disk_autoresize": False, "deletion_protection_enabled": True,
                            "backup_configuration": [{"enabled": True,
                                                      "point_in_time_recovery_enabled": False,
                                                      "backup_retention_settings": [{"retained_backups": 7,
                                                                                     "retention_unit": "COUNT"}]}],
                            "ip_configuration": [{"ipv4_enabled": False, "private_network": VPC_LINK,
                                                  "allocated_ip_range": "helpdeskcloud-dev-psa",
                                                  "ssl_mode": "ENCRYPTED_ONLY",
                                                  "server_ca_mode": "GOOGLE_MANAGED_INTERNAL_CA",
                                                  "custom_subject_alternative_names": None}]}]}
    after = copy.deepcopy(before)
    after["settings"][0]["version"] = 3
    after["settings"][0]["ip_configuration"][0]["custom_subject_alternative_names"] = []
    return {"mode": "managed", "address": SQL_ADDRESS, "type": "google_sql_database_instance",
            "change": {"actions": ["update"], "before": before, "after": after}}


def secret_empty_map_drift(address):
    names = {
        "google_secret_manager_secret.dev_app_connection[0]": "helpdesk-dev-db-connection",
        "google_secret_manager_secret.dev_admin_password[0]": "helpdesk-dev-db-admin-password",
    }
    project = "helpdeskcloud-capstone-511905"
    secret_id = names[address]
    before = {
        "project": project, "secret_id": secret_id,
        "id": f"projects/{project}/secrets/{secret_id}",
        "deletion_protection": True, "replication": [{"auto": [{}]}],
        "annotations": None, "labels": None, "version_aliases": None,
        "terraform_labels": ATTRIBUTION_LABEL, "effective_labels": ATTRIBUTION_LABEL,
        "effective_annotations": {},
    }
    after = copy.deepcopy(before)
    for field in ("annotations", "labels", "version_aliases"):
        after[field] = {}
    return {"mode": "managed", "address": address, "type": "google_secret_manager_secret",
            "change": {"actions": ["update"], "before": before, "after": after}}


def gke_resource_labels_drift():
    before = {
        "project": "helpdeskcloud-capstone-511905", "name": "helpdeskcloud-dev-gke",
        "location": "us-east1", "deletion_protection": True, "enable_autopilot": True,
        "network": "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/global/networks/helpdeskcloud-dev-vpc",
        "subnetwork": "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet",
        "networking_mode": "VPC_NATIVE",
        "resource_labels": None,
        "private_cluster_config": [{"enable_private_nodes": True, "enable_private_endpoint": True}],
        "control_plane_endpoints_config": [{"ip_endpoints_config": [{"enabled": False}]}],
        "workload_identity_config": [{"workload_pool": "helpdeskcloud-capstone-511905.svc.id.goog"}],
    }
    after = copy.deepcopy(before)
    after["resource_labels"] = {"goog-terraform-provisioned": "true"}
    return {"mode": "managed", "address": "google_container_cluster.dev[0]",
            "type": "google_container_cluster",
            "change": {"actions": ["update"], "before": before, "after": after}}


def project_iam_etag_drift(address, before_etag="etag-before", after_etag="etag-after"):
    project = "helpdeskcloud-capstone-511905"
    identities = {
        "google_project_iam_member.dev_gke_node_runtime[0]": (
            "roles/container.defaultNodeServiceAccount", "helpdesk-gke-node-dev"),
        "google_project_iam_member.dev_app_cloudsql[0]": (
            "roles/cloudsql.client", "helpdesk-app-dev"),
        "google_project_iam_member.dev_migration_cloudsql[0]": (
            "roles/cloudsql.client", "helpdesk-migrate-dev"),
    }
    role, account = identities[address]
    base = {"project": project, "role": role,
            "member": f"serviceAccount:{account}@{project}.iam.gserviceaccount.com",
            "etag": before_etag}
    after = copy.deepcopy(base)
    after["etag"] = after_etag
    return {"mode": "managed", "address": address, "type": "google_project_iam_member",
            "change": {"actions": ["update"], "before": base, "after": after}}


def evidence():
    vpc = VPC_LINK
    subnet_link = "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet"
    sql = {
        "name": "helpdeskcloud-dev-postgres", "region": "us-east1", "databaseVersion": "POSTGRES_17",
        "state": "RUNNABLE", "connectionName": "helpdeskcloud-capstone-511905:us-east1:helpdeskcloud-dev-postgres",
        "ipAddresses": [{"type": "PRIVATE", "ipAddress": "10.30.0.3"}],
        "settings": {"edition": "ENTERPRISE", "tier": "db-f1-micro", "availabilityType": "ZONAL",
                     "dataDiskType": "PD_SSD", "dataDiskSizeGb": "10", "storageAutoResize": False,
                     "deletionProtectionEnabled": True,
                     "backupConfiguration": {"enabled": True, "pointInTimeRecoveryEnabled": False,
                                             "backupRetentionSettings": {"retainedBackups": 7}},
                     "ipConfiguration": {"ipv4Enabled": False, "privateNetwork": VPC_PATH,
                                         "allocatedIpRange": "helpdeskcloud-dev-psa", "sslMode": "ENCRYPTED_ONLY"}},
    }
    outputs = {key: {"value": value} for key, value in {
        "environment": "dev", "project_id": "helpdeskcloud-capstone-511905", "region": "us-east1",
        "vpc_name": "helpdeskcloud-dev-vpc", "vpc_self_link": vpc,
        "subnet_name": "helpdeskcloud-dev-subnet", "subnet_self_link": subnet_link,
        "subnet_cidr": "10.20.0.0/20", "pods_range_name": "helpdeskcloud-dev-pods",
        "pods_cidr": "10.24.0.0/16", "services_range_name": "helpdeskcloud-dev-services",
        "services_cidr": "10.25.0.0/20", "private_services_range_name": "helpdeskcloud-dev-psa",
        "private_services_connection_id": "projects%2Fhelpdeskcloud-capstone-511905%2Fglobal%2Fnetworks%2Fhelpdeskcloud-dev-vpc:servicenetworking.googleapis.com",
        "artifact_registry_repository_id": "helpdeskcloud-dev-images", "artifact_registry_location": "us-east1",
        "artifact_registry_resource_name": "helpdeskcloud-dev-images",
        "docker_image_repository": "us-east1-docker.pkg.dev/helpdeskcloud-capstone-511905/helpdeskcloud-dev-images/helpdeskcloud",
        "cloud_sql_instance_name": "helpdeskcloud-dev-postgres", "cloud_sql_region": "us-east1",
        "cloud_sql_database_version": "POSTGRES_17", "cloud_sql_database_name": "helpdesk",
        "cloud_sql_private_ip": "10.30.0.3", "cloud_sql_connection_name": sql["connectionName"],
        "cloud_sql_vpc_self_link": vpc, "cloud_sql_private_services_range_name": "helpdeskcloud-dev-psa",
        "gke_cluster_name": "helpdeskcloud-dev-gke", "gke_cluster_location": "us-east1",
        "gke_mode": "AUTOPILOT", "gke_workload_pool": "helpdeskcloud-capstone-511905.svc.id.goog",
        "gke_node_service_account": "helpdesk-gke-node-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com",
        "app_service_account": "helpdesk-app-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com",
        "migration_service_account": "helpdesk-migrate-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com",
        "app_connection_secret": "projects/helpdeskcloud-capstone-511905/secrets/helpdesk-dev-db-connection",
        "migration_admin_secret": "projects/helpdeskcloud-capstone-511905/secrets/helpdesk-dev-db-admin-password",
    }.items()}
    project = "helpdeskcloud-capstone-511905"
    node_email = f"helpdesk-gke-node-dev@{project}.iam.gserviceaccount.com"
    app_email = f"helpdesk-app-dev@{project}.iam.gserviceaccount.com"
    migration_email = f"helpdesk-migrate-dev@{project}.iam.gserviceaccount.com"
    node_member = f"serviceAccount:{node_email}"
    app_member = f"serviceAccount:{app_email}"
    migration_member = f"serviceAccount:{migration_email}"
    app_ksa = f"serviceAccount:{project}.svc.id.goog[helpdesk-dev/helpdesk-dev-app]"
    migration_ksa = f"serviceAccount:{project}.svc.id.goog[helpdesk-dev/helpdesk-dev-migrate]"
    principal = (f"principal://iam.googleapis.com/projects/260283083469/locations/global/"
                 f"workloadIdentityPools/{project}.svc.id.goog/subject/ns/helpdesk-dev/sa/")
    cluster = {
        "name": "helpdeskcloud-dev-gke", "location": "us-east1", "status": "RUNNING",
        "autopilot": {"enabled": True}, "network": VPC_PATH,
        "subnetwork": f"projects/{project}/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet",
        "networkConfig": {"network": VPC_PATH,
                          "subnetwork": f"projects/{project}/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet"},
        "ipAllocationPolicy": {"useIpAliases": True, "clusterSecondaryRangeName": "helpdeskcloud-dev-pods",
                               "servicesSecondaryRangeName": "helpdeskcloud-dev-services"},
        "privateClusterConfig": {"enablePrivateNodes": True},
        "controlPlaneEndpointsConfig": {"ipEndpointsConfig": {"enabled": False},
                                        "dnsEndpointConfig": {"allowExternalTraffic": True}},
        "workloadIdentityConfig": {"workloadPool": f"{project}.svc.id.goog"},
        "secretManagerConfig": {"enabled": True}, "releaseChannel": {"channel": "REGULAR"},
        "autoscaling": {"autoprovisioningNodePoolDefaults": {"serviceAccount": node_email}},
    }
    state = {"values": {"root_module": {"resources": [
        {"address": address, "values": {"deletion_protection": True}} for address in (
            "google_container_cluster.dev[0]",
            "google_secret_manager_secret.dev_app_connection[0]",
            "google_secret_manager_secret.dev_admin_password[0]",
        )
    ]}}}
    return [
        {"name": "helpdeskcloud-dev-vpc", "selfLink": vpc, "autoCreateSubnetworks": False,
         "routingConfig": {"routingMode": "REGIONAL"},
         "peerings": [{"name": "servicenetworking-googleapis-com", "state": "ACTIVE"}]},
        {"name": "helpdeskcloud-dev-subnet", "selfLink": subnet_link, "network": vpc,
         "region": "projects/helpdeskcloud-capstone-511905/regions/us-east1", "ipCidrRange": "10.20.0.0/20",
         "privateIpGoogleAccess": True, "secondaryIpRanges": [
             {"rangeName": "helpdeskcloud-dev-pods", "ipCidrRange": "10.24.0.0/16"},
             {"rangeName": "helpdeskcloud-dev-services", "ipCidrRange": "10.25.0.0/20"}]},
        {"name": "helpdeskcloud-dev-psa", "network": vpc, "purpose": "VPC_PEERING",
         "addressType": "INTERNAL", "address": "10.30.0.0", "prefixLength": 16},
        [{"network": "projects/260283083469/global/networks/helpdeskcloud-dev-vpc",
          "reservedPeeringRanges": ["helpdeskcloud-dev-psa"], "service": "services/servicenetworking.googleapis.com",
          "peering": "servicenetworking-googleapis-com"}],
        {"name": "projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/helpdeskcloud-dev-images",
         "format": "DOCKER", "dockerConfig": {"immutableTags": True}},
        {"bindings": [{"role": "roles/artifactregistry.reader", "members": [node_member]}]},
        {"bindings": [{"role": "roles/container.defaultNodeServiceAccount", "members": [node_member]},
                      {"role": "roles/cloudsql.client", "members": [app_member, migration_member]}]}, sql,
        [{"name": "helpdesk", "instance": "helpdeskcloud-dev-postgres"}], outputs,
        cluster,
        {"email": node_email}, {"email": app_email}, {"email": migration_email},
        {"name": f"projects/{project}/secrets/helpdesk-dev-db-connection", "replication": {"automatic": {}}},
        {"name": f"projects/{project}/secrets/helpdesk-dev-db-admin-password", "replication": {"automatic": {}}},
        {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [app_ksa]}]},
        {"bindings": [{"role": "roles/iam.workloadIdentityUser", "members": [migration_ksa]}]},
        {"bindings": [{"role": "roles/secretmanager.secretAccessor", "members": [principal + "helpdesk-dev-app"]}]},
        {"bindings": [{"role": "roles/secretmanager.secretAccessor", "members": [principal + "helpdesk-dev-migrate"]}]},
        state,
    ]


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture()

    def change(self, address, actions):
        next(c for c in self.plan["resource_changes"] if c["address"] == address)["change"]["actions"] = actions

    def values(self, kind):
        return next(r["values"] for r in self.plan["planned_values"]["root_module"]["resources"] if r["type"] == kind)

    def test_exact_phase7_creations(self):
        self.assertEqual(check_plan(self.plan), "apply")

    def test_exact_apply12_partial_state_allows_only_the_verified_remainder(self):
        plan = apply12_recovery_plan()
        self.assertEqual(check_plan(plan), "apply")
        creates = {change["address"] for change in plan["resource_changes"]
                   if change["change"]["actions"] == ["create"]}
        self.assertEqual(creates, APPLY12_REMAINING)

    def test_apply12_recovery_allows_only_both_secret_empty_map_readbacks(self):
        plan = apply12_recovery_plan()
        secrets = ("google_secret_manager_secret.dev_app_connection[0]",
                   "google_secret_manager_secret.dev_admin_password[0]")
        plan["resource_drift"] = [secret_empty_map_drift(address) for address in secrets]
        self.assertEqual(check_plan(plan), "apply")
        report = "\n".join(diagnose_drift(plan))
        for field in ("annotations", "labels", "version_aliases"):
            self.assertEqual(report.count(f"{field}: before=null; after=empty map"), 2)

    def test_apply12_recovery_accepts_exact_provider_repository_path_readback(self):
        plan = apply12_recovery_plan()
        address = "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]"
        repository_path = (
            "projects/helpdeskcloud-capstone-511905/locations/us-east1/"
            "repositories/helpdeskcloud-dev-images"
        )
        resource(plan, address)["values"]["repository"] = repository_path
        prior = next(item for item in plan["prior_state"]["values"]["root_module"]["resources"]
                     if item["address"] == address)
        prior["values"]["repository"] = repository_path
        secrets = ("google_secret_manager_secret.dev_app_connection[0]",
                   "google_secret_manager_secret.dev_admin_password[0]")
        plan["resource_drift"] = [secret_empty_map_drift(secret) for secret in secrets]
        self.assertEqual(check_plan(plan), "apply")

    def test_repository_path_readback_rejects_wrong_scope_role_or_member(self):
        address = "google_artifact_registry_repository_iam_member.dev_gke_image_pull[0]"
        mutations = (
            ("repository", "projects/another-project/locations/us-east1/repositories/helpdeskcloud-dev-images"),
            ("repository", "projects/helpdeskcloud-capstone-511905/locations/us-central1/repositories/helpdeskcloud-dev-images"),
            ("repository", "projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/another-repository"),
            ("role", "roles/artifactregistry.admin"),
            ("member", "allUsers"),
            ("project", "another-project"),
            ("location", "us-central1"),
        )
        for field, value in mutations:
            plan = apply12_recovery_plan()
            resource(plan, address)["values"][field] = value
            expected_error = ("Unexpected node repository IAM member" if field == "member"
                              else "repository-scoped Reader")
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                    ValueError, expected_error):
                check_plan(plan)

    def test_secret_readback_rejects_other_maps_identities_and_security_changes(self):
        address = "google_secret_manager_secret.dev_app_connection[0]"
        mutations = (
            lambda d: d["change"]["before"].update(annotations={}),
            lambda d: d["change"]["before"].pop("labels"),
            lambda d: d["change"]["after"].update(version_aliases={"live": "1"}),
            lambda d: d["change"]["after"].update(labels={"owner": "private-value"}),
            lambda d: d["change"]["after"].update(annotations={"owner": "private-value"}),
            lambda d: d["change"]["after"].pop("version_aliases"),
            lambda d: d["change"]["after"].update(project="wrong-project"),
            lambda d: d["change"]["after"].update(secret_id="wrong-secret"),
            lambda d: d["change"]["after"].update(id="projects/wrong/secrets/wrong"),
            lambda d: d["change"]["after"].update(deletion_protection=False),
            lambda d: d["change"]["after"].update(replication=[{"user_managed": []}]),
            lambda d: d["change"]["after"].update(effective_annotations={"owner": "private-value"}),
            lambda d: d["change"].update(actions=["delete", "create"]),
            lambda d: d.update(type="google_secret_manager_secret_version"),
            lambda d: d.update(address="google_secret_manager_secret.other[0]"),
        )
        for mutate in mutations:
            plan = apply12_recovery_plan()
            drift = secret_empty_map_drift(address)
            mutate(drift)
            plan["resource_drift"] = [drift]
            with self.subTest(mutation=mutate), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(plan)

    def test_secret_readback_never_authorizes_a_requested_update_or_new_inventory(self):
        address = "google_secret_manager_secret.dev_admin_password[0]"
        plan = apply12_recovery_plan()
        plan["resource_drift"] = [secret_empty_map_drift(address)]
        next(change for change in plan["resource_changes"] if change["address"] == address)[
            "change"]["actions"] = ["update"]
        with self.assertRaisesRegex(ValueError, "readback only"):
            check_plan(plan)
        plan = apply12_recovery_plan()
        plan["resource_drift"] = [secret_empty_map_drift(address)]
        set_prior_phase7(plan, APPLY12_COMPLETED - {address})
        with self.assertRaisesRegex(ValueError, "Partial or inconsistent"):
            check_plan(plan)

    def test_secret_diagnostic_withholds_annotation_label_and_alias_contents(self):
        plan = apply12_recovery_plan()
        drift = secret_empty_map_drift("google_secret_manager_secret.dev_app_connection[0]")
        for field in ("annotations", "labels", "version_aliases"):
            drift["change"]["before"][field] = {"private-key": "private-before"}
            drift["change"]["after"][field] = {"private-key": "private-after"}
        drift["change"]["after"]["private-field"] = "private-after"
        plan["resource_drift"] = [drift]
        report = "\n".join(diagnose_drift(plan))
        self.assertIn("annotations.<key withheld>", report)
        self.assertIn("version_aliases.<key withheld>", report)
        self.assertIn("<other secret path withheld>", report)
        self.assertIn("<unexpected value withheld>", report)
        for value in ("private-key", "private-before", "private-after", "private-field"):
            self.assertNotIn(value, report)
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(plan)

    def test_apply12_recovery_rejects_a_different_created_inventory(self):
        plan = apply12_recovery_plan()
        completed = sorted(APPLY12_COMPLETED)[0]
        remaining = sorted(APPLY12_REMAINING)[0]
        next(c for c in plan["resource_changes"] if c["address"] == completed)["change"]["actions"] = ["create"]
        next(c for c in plan["resource_changes"] if c["address"] == remaining)["change"]["actions"] = ["no-op"]
        with self.assertRaisesRegex(ValueError, "Partial or inconsistent"):
            check_plan(plan)

    def test_apply12_recovery_requires_matching_prior_state(self):
        plan = apply12_recovery_plan()
        set_prior_phase7(plan, APPLY12_COMPLETED - {sorted(APPLY12_COMPLETED)[0]})
        with self.assertRaisesRegex(ValueError, "Partial or inconsistent"):
            check_plan(plan)

    def test_apply12_recovery_rejects_unexpected_iam_or_resource_changes(self):
        for actions in (["update"], ["delete"], ["delete", "create"]):
            plan = apply12_recovery_plan()
            next(c for c in plan["resource_changes"]
                 if c["address"] == "google_project_iam_member.dev_app_cloudsql[0]")["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaisesRegex(ValueError, "Phase 7"):
                check_plan(plan)

    def test_workload_and_secret_bindings_wait_for_gke_pool(self):
        protected = (
            "google_service_account_iam_member.dev_app_workload_identity",
            "google_service_account_iam_member.dev_migration_workload_identity",
            "google_secret_manager_secret_iam_member.dev_app_secret_access",
            "google_secret_manager_secret_iam_member.dev_admin_secret_access",
        )
        for address in protected:
            plan = fixture()
            resource_config = next(item for item in plan["configuration"]["root_module"]["resources"]
                                   if item["address"] == address)
            resource_config["depends_on"] = []
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "wait for the GKE"):
                check_plan(plan)

    def test_exact_after_unknown_computed_identity_values_allow_initial_creation(self):
        self.assertEqual(check_plan(unknown_identity_plan()), "apply")

    def test_omitted_computed_service_account_name_with_unknown_marker_is_allowed(self):
        plan = unknown_identity_plan()
        mark_unknown(plan, "google_service_account.dev_gke_nodes[0]", ("name",), omit_value=True)
        self.assertEqual(check_plan(plan), "apply")

    def test_omitted_computed_service_account_name_without_unknown_marker_is_rejected(self):
        plan = unknown_identity_plan()
        address = "google_service_account.dev_gke_nodes[0]"
        remove_nested(resource(plan, address)["values"], ("name",))
        change = next(c for c in plan["resource_changes"] if c["address"] == address)["change"]
        change["after_unknown"].pop("name")
        with self.assertRaisesRegex(ValueError, "service-account name"):
            check_plan(plan)

    def test_unknown_marker_does_not_allow_an_unexpected_known_value(self):
        plan = unknown_identity_plan()
        address = "google_service_account.dev_gke_nodes[0]"
        resource(plan, address)["values"]["name"] = "projects/wrong-project/serviceAccounts/wrong"
        with self.assertRaisesRegex(ValueError, "Unexpected unknown value for service-account name"):
            check_plan(plan)

    def test_null_computed_identity_without_after_unknown_marker_is_rejected(self):
        plan = unknown_identity_plan()
        address = "google_project_iam_member.dev_app_cloudsql[0]"
        change = next(c for c in plan["resource_changes"] if c["address"] == address)["change"]
        del change["after_unknown"]["member"]
        with self.assertRaisesRegex(ValueError, "project IAM member"):
            check_plan(plan)

    def test_unknown_iam_identity_requires_the_exact_service_account_reference(self):
        plan = unknown_identity_plan()
        expression = next(r for r in plan["configuration"]["root_module"]["resources"]
                          if r["address"] == "google_project_iam_member.dev_app_cloudsql")
        expression["expressions"]["member"]["references"] = ["google_service_account.dev_migration[0].member"]
        with self.assertRaisesRegex(ValueError, "unexpected Terraform reference"):
            check_plan(plan)

    def test_unknown_gke_node_identity_requires_the_exact_node_account_reference(self):
        plan = unknown_identity_plan()
        cluster = next(r for r in plan["configuration"]["root_module"]["resources"]
                       if r["address"] == "google_container_cluster.dev")
        cluster["expressions"]["cluster_autoscaling"][0]["auto_provisioning_defaults"][0]["service_account"][
            "references"] = ["google_service_account.dev_app[0].email"]
        with self.assertRaisesRegex(ValueError, "GKE node identity"):
            check_plan(plan)

    def test_gke_node_identity_rejects_an_unapproved_additional_reference(self):
        plan = fixture()
        cluster = next(r for r in plan["configuration"]["root_module"]["resources"]
                       if r["address"] == "google_container_cluster.dev")
        reference = cluster["expressions"]["cluster_autoscaling"][0]["auto_provisioning_defaults"][0][
            "service_account"]["references"]
        reference.append("google_service_account.dev_migration[0].email")
        with self.assertRaisesRegex(ValueError, "GKE node identity"):
            check_plan(plan)

    def test_strict_references_accept_full_and_approved_parent_traversals(self):
        # The old guard's actual == [expected] check rejected the three-entry
        # Terraform 1.16.2 array, even though the approved full path is present.
        cases = strict_reference_cases(fixture())
        for index, (label, expression, expected) in enumerate(cases):
            if expected != "var.project_id":
                self.assertNotEqual(expression["references"], [expected])
            for references in ([expected], terraform_references(expected),
                               list(reversed(terraform_references(expected))),
                               terraform_references(expected)[:2]):
                plan = fixture()
                strict_reference_cases(plan)[index][1]["references"] = references
                with self.subTest(label=label, references=references):
                    self.assertEqual(check_plan(plan), "apply")

    def test_strict_references_reject_missing_wrong_or_extra_paths(self):
        replacements = {
            "google_service_account.dev_gke_nodes[0].email": "google_service_account.dev_app[0].email",
            "google_service_account.dev_gke_nodes[0].member": "google_service_account.dev_app[0].member",
            "google_service_account.dev_app[0].name": "google_service_account.dev_migration[0].name",
            "google_service_account.dev_app[0].member": "google_service_account.dev_migration[0].member",
            "google_service_account.dev_migration[0].name": "google_service_account.dev_app[0].name",
            "google_service_account.dev_migration[0].member": "google_service_account.dev_app[0].member",
            "google_secret_manager_secret.dev_app_connection[0].id": "google_secret_manager_secret.dev_admin_password[0].id",
            "google_secret_manager_secret.dev_admin_password[0].id": "google_secret_manager_secret.dev_app_connection[0].id",
            "var.project_id": "var.other_project",
        }
        for index, (label, _, expected) in enumerate(strict_reference_cases(fixture())):
            parent = terraform_references(expected)[-1]
            bad_arrays = ([parent] if parent != expected else [],
                          [replacements[expected]],
                          [expected, replacements[expected]],
                          [expected.replace("[0]", "[1]") if "[0]" in expected else "var.project_id[0]"],
                          [expected.rsplit(".", 1)[0] + ".other"],
                          [expected, expected])
            for references in bad_arrays:
                plan = fixture()
                strict_reference_cases(plan)[index][1]["references"] = references
                with self.subTest(label=label, references=references), self.assertRaises(ValueError):
                    check_plan(plan)

    def test_strict_references_reject_malformed_structures(self):
        for malformed in (None, "google_service_account.dev_gke_nodes[0].email", {},
                          ["google_service_account.dev_gke_nodes[0].email", None],
                          ["google_service_account.dev_gke_nodes[0].email", 1], [""]):
            plan = fixture()
            strict_reference_cases(plan)[0][1]["references"] = malformed
            with self.subTest(malformed=malformed), self.assertRaisesRegex(ValueError, "Malformed Terraform references"):
                check_plan(plan)
        plan = fixture()
        cluster = next(r for r in plan["configuration"]["root_module"]["resources"]
                       if r["address"] == "google_container_cluster.dev")
        cluster["expressions"]["cluster_autoscaling"][0]["auto_provisioning_defaults"][0]["service_account"] = []
        with self.assertRaisesRegex(ValueError, "Malformed Terraform references"):
            check_plan(plan)
        plan = fixture()
        strict_reference_cases(plan)[0][1]["constant_value"] = "unexpected"
        with self.assertRaisesRegex(ValueError, "Malformed Terraform references"):
            check_plan(plan)

    def test_invalid_iam_role_or_identity_is_rejected(self):
        for field, bad in (("role", "roles/editor"),
                           ("member", "serviceAccount:wrong@wrong-project.iam.gserviceaccount.com")):
            plan = fixture()
            planned = resource(plan, "google_project_iam_member.dev_app_cloudsql[0]")
            planned["values"][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan(plan)

    def test_no_changes_even_when_no_op_entries_are_omitted(self):
        for change in self.plan["resource_changes"]:
            change["change"]["actions"] = ["no-op"]
        set_prior_phase7(self.plan, PHASE7)
        self.assertEqual(check_plan(self.plan), "no_changes")
        self.plan["resource_changes"] = []
        self.assertEqual(check_plan(self.plan), "no_changes")

    def test_network_change_is_rejected(self):
        for actions in (["update"], ["delete"], ["delete", "create"]):
            plan = fixture()
            plan["resource_changes"][0]["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                check_plan(plan)

    def test_unexpected_network_cidr_is_rejected_even_without_a_change_entry(self):
        self.plan["resource_changes"] = []
        set_prior_phase7(self.plan, PHASE7)
        self.values("google_compute_subnetwork")["ip_cidr_range"] = "10.21.0.0/20"
        with self.assertRaisesRegex(ValueError, "CIDR"):
            check_plan(self.plan)

    def test_unexpected_resource_is_rejected(self):
        self.plan["resource_changes"].append({"mode": "managed", "address": "google_compute_instance.other",
                                              "type": "google_compute_instance", "change": {"actions": ["create"]}})
        with self.assertRaises(ValueError):
            check_plan(self.plan)

    def test_phase6_update_destroy_and_replace_are_rejected(self):
        for actions in (["update"], ["delete"], ["delete", "create"]):
            plan = fixture()
            next(c for c in plan["resource_changes"] if c["address"] in PHASE6)["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                check_plan(plan)

    def test_phase6_creation_is_rejected(self):
        self.change("google_sql_database.dev_helpdesk[0]", ["create"])
        with self.assertRaisesRegex(ValueError, "Existing Phase 5-6"):
            check_plan(self.plan)

    def test_partial_phase7_creation_is_rejected(self):
        self.change("google_secret_manager_secret.dev_admin_password[0]", ["no-op"])
        with self.assertRaisesRegex(ValueError, "Partial"):
            check_plan(self.plan)

    def test_phase7_update_destroy_and_replace_are_rejected(self):
        for actions in (["update"], ["delete"], ["delete", "create"]):
            plan = fixture()
            next(c for c in plan["resource_changes"] if c["address"] in PHASE7)["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaisesRegex(ValueError, "Phase 7"):
                check_plan(plan)

    def test_wrong_gke_network_ranges_or_project_are_rejected(self):
        cluster = self.values("google_container_cluster")
        for field, bad in (("project", "wrong-project"), ("network", "projects/wrong-project/global/networks/helpdeskcloud-dev-vpc"),
                           ("subnetwork", "wrong-subnet")):
            original = cluster[field]
            cluster[field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan(self.plan)
            cluster[field] = original
        cluster["ip_allocation_policy"][0]["cluster_secondary_range_name"] = "wrong-pods"
        with self.assertRaisesRegex(ValueError, "secondary ranges"):
            check_plan(self.plan)

    def test_missing_private_nodes_or_workload_identity_is_rejected(self):
        cluster = self.values("google_container_cluster")
        cluster["private_cluster_config"][0]["enable_private_nodes"] = False
        with self.assertRaisesRegex(ValueError, "private"):
            check_plan(self.plan)
        cluster["private_cluster_config"][0]["enable_private_nodes"] = True
        cluster["workload_identity_config"][0]["workload_pool"] = "wrong.svc.id.goog"
        with self.assertRaisesRegex(ValueError, "workload pool"):
            check_plan(self.plan)

    def test_public_ip_endpoint_or_wrong_identity_is_rejected(self):
        cluster = self.values("google_container_cluster")
        cluster["control_plane_endpoints_config"][0]["ip_endpoints_config"][0]["enabled"] = True
        with self.assertRaisesRegex(ValueError, "IP access"):
            check_plan(self.plan)
        cluster["control_plane_endpoints_config"][0]["ip_endpoints_config"][0]["enabled"] = False
        cluster["cluster_autoscaling"][0]["auto_provisioning_defaults"][0]["service_account"] = "default@developer.gserviceaccount.com"
        with self.assertRaisesRegex(ValueError, "node identity"):
            check_plan(self.plan)

    def test_secret_and_iam_scope_are_rejected_when_broadened(self):
        grant = next(r["values"] for r in self.plan["planned_values"]["root_module"]["resources"]
                     if r["address"] == "google_secret_manager_secret_iam_member.dev_app_secret_access[0]")
        grant["member"] = "allUsers"
        with self.assertRaisesRegex(ValueError, "Secret Manager principal"):
            check_plan(self.plan)

    def test_unknown_drift_is_rejected_and_diagnosed_without_values(self):
        self.plan["resource_drift"] = [{"mode": "managed", "address": next(iter(NETWORK)), "type": "google_compute_network",
                                        "change": {"actions": ["update"], "before": {"routing_mode": "REGIONAL"},
                                                   "after": {"routing_mode": "GLOBAL"}}}]
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("routing_mode", report)
        self.assertIn("security-sensitive paths=yes", report)
        self.assertNotIn("GLOBAL", report)

    def test_two_exact_normalization_differences_are_permitted(self):
        self.plan["resource_drift"] = [label_drift(), metadata_drift()]
        self.assertEqual(check_plan(self.plan), "apply")
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("labels: before=null; after=empty map", report)
        self.assertIn("metadata_fields: before=null; after=[]", report)
        self.plan["resource_drift"][1] = metadata_drift(omit_after=True)
        self.assertEqual(check_plan(self.plan), "apply")
        self.assertIn("metadata_fields: before=null; after=missing", "\n".join(diagnose_drift(self.plan)))
        self.plan["resource_drift"] = [label_drift()]
        self.assertEqual(check_plan(self.plan), "apply")
        self.plan["resource_drift"] = [metadata_drift()]
        self.assertEqual(check_plan(self.plan), "apply")

    def test_phase6_readback_diagnostic_classifies_only_non_secret_values(self):
        self.plan["resource_drift"] = [registry_drift(), sql_readback_drift()]
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("repository identity: expected", report)
        self.assertIn("labels: before=null; after=empty map", report)
        self.assertIn("exact attribution only=true; unchanged=true", report)
        self.assertIn("Cloud SQL identity and PostgreSQL 17: expected", report)
        self.assertIn("settings[0].version: before=1; after=3", report)
        self.assertIn("custom_subject_alternative_names: before=null; after=[]", report)
        self.assertIn("server_ca_mode: before=GOOGLE_MANAGED_INTERNAL_CA; "
                      "after=GOOGLE_MANAGED_INTERNAL_CA", report)
        self.assertEqual(check_plan(self.plan), "apply")

    def test_exact_phase6_registry_and_sql_normalizations_are_allowed(self):
        self.plan["resource_drift"] = [registry_drift(), sql_readback_drift()]
        self.assertEqual(check_plan(self.plan), "apply")

    def test_registry_normalization_rejects_wrong_identity_labels_or_other_changes(self):
        mutations = (
            lambda d: d["change"]["after"].update(project="another-project"),
            lambda d: d["change"]["after"].update(repository_id="another-repository"),
            lambda d: d["change"]["after"].update(format="MAVEN"),
            lambda d: d["change"]["after"].update(labels={"owner": "private-value"}),
            lambda d: d["change"]["after"]["terraform_labels"].update({"owner": "private-value"}),
            lambda d: d["change"]["after"]["effective_labels"].update({"owner": "private-value"}),
            lambda d: d["change"]["after"]["docker_config"][0].update(immutable_tags=False),
        )
        for mutate in mutations:
            drift = registry_drift()
            mutate(drift)
            self.plan["resource_drift"] = [drift]
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(self.plan)

        drift = registry_drift()
        change = next(c for c in self.plan["resource_changes"] if c["address"] == REGISTRY_ADDRESS)
        change["change"]["actions"] = ["update"]
        self.plan["resource_drift"] = [drift]
        with self.assertRaisesRegex(ValueError, "readback only"):
            check_plan(self.plan)

    def test_sql_readback_normalization_rejects_other_versions_and_configuration_changes(self):
        mutations = (
            lambda d: d["change"]["after"]["settings"][0].update(version=4),
            lambda d: d["change"]["after"]["settings"][0]["ip_configuration"][0].update(
                custom_subject_alternative_names=["unexpected.example"]),
            lambda d: d["change"]["after"]["settings"][0]["ip_configuration"][0].update(
                server_ca_mode="CUSTOMER_MANAGED_CAS_CA"),
            lambda d: d["change"]["after"]["settings"][0].update(tier="db-custom-2-7680"),
            lambda d: d["change"]["after"]["settings"][0]["ip_configuration"][0].update(
                private_network="projects/other-project/global/networks/other-vpc"),
            lambda d: d["change"]["after"].update(database_version="POSTGRES_16"),
            lambda d: d["change"]["after"]["settings"][0].update(deletion_protection_enabled=False),
        )
        for mutate in mutations:
            drift = sql_readback_drift()
            mutate(drift)
            self.plan["resource_drift"] = [drift]
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(self.plan)

        drift = sql_readback_drift()
        drift["change"]["actions"] = ["delete", "create"]
        self.plan["resource_drift"] = [drift]
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)

    def test_phase6_diagnostic_withholds_unexpected_values_and_keeps_guard_closed(self):
        registry = registry_drift()
        registry["change"]["after"]["labels"] = {"owner": "private-value"}
        registry["change"]["after"]["project"] = "wrong-project"
        sql = sql_readback_drift()
        sql["change"]["after"]["settings"][0]["version"] = "private-value"
        sql["change"]["after"]["settings"][0]["ip_configuration"][0][
            "custom_subject_alternative_names"] = ["private-value"]
        sql["change"]["after"]["database_version"] = "POSTGRES_16"
        self.plan["resource_drift"] = [registry, sql]
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("repository identity: unexpected (values withheld)", report)
        self.assertIn("labels: before=null; after=unexpected map (contents withheld)", report)
        self.assertIn("Cloud SQL identity and PostgreSQL 17: unexpected (values withheld)", report)
        self.assertIn("settings[0].version: before=1; after=<unexpected value withheld>", report)
        self.assertIn("custom_subject_alternative_names: before=null; "
                      "after=<unexpected value withheld>", report)
        self.assertNotIn("private-value", report)
        self.assertNotIn("wrong-project", report)
        self.assertNotIn("POSTGRES_16", report)
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)

    def test_exact_drift_is_permitted_with_zero_change_plan(self):
        self.plan["resource_changes"] = []
        set_prior_phase7(self.plan, PHASE7)
        self.plan["resource_drift"] = [label_drift(), metadata_drift()]
        self.assertEqual(check_plan(self.plan), "no_changes")

    def test_gke_and_project_iam_project_number_readbacks_are_permitted(self):
        set_prior_phase7(self.plan, PHASE7)
        for change in self.plan["resource_changes"]:
            change["change"]["actions"] = ["no-op"]
        cluster_drift = gke_resource_labels_drift()
        for snapshot in (cluster_drift["change"]["before"], cluster_drift["change"]["after"]):
            snapshot["project"] = "260283083469"
            snapshot["network"] = (
                "https://www.googleapis.com/compute/v1/projects/260283083469/global/networks/"
                "helpdeskcloud-dev-vpc")
            snapshot["subnetwork"] = (
                "https://www.googleapis.com/compute/v1/projects/260283083469/regions/us-east1/subnetworks/"
                "helpdeskcloud-dev-subnet")
        cluster_planned = resource(self.plan, "google_container_cluster.dev[0]")["values"]
        cluster_planned["project"] = "260283083469"
        cluster_planned["network"] = (
            "https://www.googleapis.com/compute/v1/projects/260283083469/global/networks/"
            "helpdeskcloud-dev-vpc")
        cluster_planned["subnetwork"] = (
            "https://www.googleapis.com/compute/v1/projects/260283083469/regions/us-east1/subnetworks/"
            "helpdeskcloud-dev-subnet")
        drift = [cluster_drift]
        iam_drift = [project_iam_etag_drift(address) for address in (
            "google_project_iam_member.dev_app_cloudsql[0]",
            "google_project_iam_member.dev_gke_node_runtime[0]",
            "google_project_iam_member.dev_migration_cloudsql[0]",
        )]
        for entry in iam_drift:
            entry["change"]["before"]["project"] = "260283083469"
            entry["change"]["after"]["project"] = "260283083469"
            resource(self.plan, entry["address"])["values"]["project"] = "260283083469"
        drift.extend(iam_drift)
        self.plan["resource_drift"] = drift
        self.assertEqual(check_plan(self.plan), "no_changes")

        for address in ("google_container_cluster.dev[0]",
                        "google_project_iam_member.dev_app_cloudsql[0]"):
            change = next(c for c in self.plan["resource_changes"] if c["address"] == address)
            change["change"]["actions"] = ["update"]
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, "readback only"):
                check_plan(self.plan)
            change["change"]["actions"] = ["no-op"]

    def test_gke_empty_resource_label_representations_are_permitted(self):
        for before_labels, after_labels in ((None, {}), ({}, None)):
            drift = gke_resource_labels_drift()
            drift["change"]["before"]["resource_labels"] = before_labels
            drift["change"]["after"]["resource_labels"] = after_labels
            self.plan["resource_drift"] = [drift]
            with self.subTest(before=before_labels, after=after_labels):
                self.assertTrue(permitted_drift(drift))

    def test_gke_exact_project_number_readbacks_are_permitted(self):
        drift = gke_resource_labels_drift()
        for snapshot in (drift["change"]["before"], drift["change"]["after"]):
            snapshot["project"] = "260283083469"
            snapshot["network"] = (
                "https://www.googleapis.com/compute/v1/projects/260283083469/global/networks/"
                "helpdeskcloud-dev-vpc")
            snapshot["subnetwork"] = (
                "https://www.googleapis.com/compute/v1/projects/260283083469/regions/us-east1/subnetworks/"
                "helpdeskcloud-dev-subnet")
        self.assertTrue(permitted_drift(drift))

    def test_gke_canonical_relative_network_paths_are_permitted(self):
        for network_path, subnet_path in zip(VPC_PATHS, SUBNET_PATHS):
            drift = gke_resource_labels_drift()
            for snapshot in (drift["change"]["before"], drift["change"]["after"]):
                snapshot["network"] = network_path
                snapshot["subnetwork"] = subnet_path
            with self.subTest(network_project=network_path.split("/")[1],
                              subnet_project=subnet_path.split("/")[1]):
                self.assertTrue(permitted_drift(drift))

    def test_gke_canonical_relative_paths_pass_complete_no_change_plan(self):
        cluster = resource(self.plan, "google_container_cluster.dev[0]")["values"]
        cluster["network"] = VPC_PATH
        cluster["subnetwork"] = SUBNET_PATHS[0]
        set_prior_phase7(self.plan, PHASE7)
        for change in self.plan["resource_changes"]:
            change["change"]["actions"] = ["no-op"]
        drift = gke_resource_labels_drift()
        for snapshot in (drift["change"]["before"], drift["change"]["after"]):
            snapshot["network"] = VPC_PATH
            snapshot["subnetwork"] = SUBNET_PATHS[0]
        self.plan["resource_drift"] = [drift]
        self.assertEqual(check_plan(self.plan), "no_changes")

    def test_gke_drift_rejects_unexpected_relative_network_paths(self):
        for field, unexpected in (
            ("network", "projects/another-project/global/networks/helpdeskcloud-dev-vpc"),
            ("network", "projects/helpdeskcloud-capstone-511905/global/networks/another-vpc"),
            ("subnetwork", "projects/helpdeskcloud-capstone-511905/regions/us-west1/subnetworks/helpdeskcloud-dev-subnet"),
            ("subnetwork", "projects/helpdeskcloud-capstone-511905/regions/us-east1/subnetworks/another-subnet"),
        ):
            drift = gke_resource_labels_drift()
            drift["change"]["after"][field] = unexpected
            with self.subTest(field=field, unexpected=unexpected):
                self.assertFalse(permitted_drift(drift))

    def test_project_iam_missing_etag_readback_is_permitted(self):
        address = "google_project_iam_member.dev_app_cloudsql[0]"
        for before_etag, after_etag in ((None, "etag-after"), ("", "etag-after"),
                                        ("etag-before", None), ("etag-before", "")):
            drift = project_iam_etag_drift(address, before_etag, after_etag)
            with self.subTest(before=before_etag, after=after_etag):
                self.assertTrue(permitted_drift(drift))
        for missing_side in ("before", "after"):
            drift = project_iam_etag_drift(address)
            drift["change"][missing_side].pop("etag")
            with self.subTest(missing_side=missing_side):
                self.assertTrue(permitted_drift(drift))

    def test_project_iam_exact_project_number_readback_is_permitted(self):
        drift = project_iam_etag_drift("google_project_iam_member.dev_app_cloudsql[0]")
        drift["change"]["before"]["project"] = "260283083469"
        drift["change"]["after"]["project"] = "260283083469"
        self.assertTrue(permitted_drift(drift))

    def test_gke_and_project_iam_diagnostic_classifies_project_number_without_values(self):
        cluster = gke_resource_labels_drift()
        for snapshot in (cluster["change"]["before"], cluster["change"]["after"]):
            snapshot["project"] = "260283083469"
            snapshot["network"] = (
                "https://www.googleapis.com/compute/v1/projects/260283083469/global/networks/"
                "helpdeskcloud-dev-vpc")
            snapshot["subnetwork"] = (
                "https://www.googleapis.com/compute/v1/projects/260283083469/regions/us-east1/subnetworks/"
                "helpdeskcloud-dev-subnet")
        iam = project_iam_etag_drift("google_project_iam_member.dev_app_cloudsql[0]")
        iam["change"]["before"]["project"] = "260283083469"
        iam["change"]["after"]["project"] = "260283083469"
        plan = {"resource_drift": [cluster, iam]}
        report = "\n".join(diagnose_drift(plan))
        self.assertIn("project representation: before=project number; after=project number", report)
        self.assertIn("network reference: before=Compute self-link; after=Compute self-link", report)
        self.assertIn("subnetwork reference: before=Compute self-link; after=Compute self-link", report)
        self.assertIn("before IAM role and member: expected", report)
        self.assertIn("etag representation: before=non-empty token; after=non-empty token", report)
        self.assertNotIn("etag-before", report)
        self.assertNotIn("etag-after", report)

    def test_gke_diagnostic_classifies_relative_paths_without_printing_them(self):
        drift = gke_resource_labels_drift()
        for snapshot in (drift["change"]["before"], drift["change"]["after"]):
            snapshot["network"] = VPC_PATH
            snapshot["subnetwork"] = SUBNET_PATHS[0]
        report = "\n".join(diagnose_drift({"resource_drift": [drift]}))
        self.assertIn("network reference: before=GKE relative resource path; after=GKE relative resource path", report)
        self.assertIn("subnetwork reference: before=GKE relative resource path; after=GKE relative resource path", report)
        self.assertNotIn(VPC_PATH, report)
        self.assertNotIn(SUBNET_PATHS[0], report)

    def test_gke_label_drift_rejects_unexpected_labels_or_cluster_changes(self):
        for mutate in (
            lambda d: d["change"]["after"].update(resource_labels={"owner": "someone"}),
            lambda d: d["change"]["after"].update(resource_labels={
                "goog-terraform-provisioned": "false"}),
            lambda d: d["change"]["after"].update(name="unexpected-cluster"),
            lambda d: d["change"]["after"].update(deletion_protection=False),
            lambda d: d["change"]["after"].update(network="unexpected-vpc"),
            lambda d: d["change"]["after"]["private_cluster_config"][0].update(
                enable_private_endpoint=False),
            lambda d: d["change"]["after"]["control_plane_endpoints_config"][0][
                "ip_endpoints_config"][0].update(enabled=True),
            lambda d: d["change"]["after"]["workload_identity_config"][0].update(
                workload_pool="unexpected-pool"),
            lambda d: d["change"].update(actions=["delete", "create"]),
        ):
            drift = gke_resource_labels_drift()
            mutate(drift)
            self.plan["resource_drift"] = [drift]
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(self.plan)

    def test_project_iam_etag_drift_rejects_wrong_identity_or_any_other_field_change(self):
        address = "google_project_iam_member.dev_app_cloudsql[0]"
        for mutate in (
            lambda d: d["change"]["after"].update(project="other-project"),
            lambda d: d["change"]["after"].update(role="roles/owner"),
            lambda d: d["change"]["after"].update(member="user:someone@example.com"),
            lambda d: d["change"]["after"].update(etag={"unexpected": "shape"}),
            lambda d: d["change"]["after"].update(extra="unexpected"),
            lambda d: d["change"].update(actions=["delete"]),
        ):
            drift = project_iam_etag_drift(address)
            mutate(drift)
            self.plan["resource_drift"] = [drift]
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(self.plan)

        for before_etag, after_etag in ((None, ""), ("", None), (None, None)):
            drift = project_iam_etag_drift(address, before_etag, after_etag)
            self.plan["resource_drift"] = [drift]
            with self.subTest(before=before_etag, after=after_etag), self.assertRaisesRegex(
                    ValueError, "drift"):
                check_plan(self.plan)

    def test_attribution_drift_rejects_other_labels_and_resource_changes(self):
        for mutate in (
            lambda d: d["change"]["after"]["labels"].update({"owner": "someone"}),
            lambda d: d["change"]["after"]["labels"].update({"goog-terraform-provisioned": "false"}),
            lambda d: d["change"]["after"].update({"address": "10.31.0.0"}),
            lambda d: d["change"]["after"].update({"prefix_length": 15}),
            lambda d: d["change"]["after"].update({"network": "unexpected-vpc"}),
            lambda d: d["change"]["after"].update({"terraform_labels": {}}),
            lambda d: d["change"]["after"].update({"effective_labels": {}}),
            lambda d: d["change"]["after"].update({"name": "unexpected-allocation"}),
            lambda d: d["change"].update({"actions": ["delete", "create"]}),
        ):
            drift = label_drift()
            mutate(drift)
            self.plan["resource_drift"] = [drift]
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(self.plan)

    def test_diagnostic_withholds_unexpected_label_and_metadata_values(self):
        label = label_drift()
        label["change"]["after"]["labels"] = {"unexpected": "private-value"}
        metadata = metadata_drift(after_fields=["private-value"])
        self.plan["resource_drift"] = [label, metadata]
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("<unexpected value withheld>", report)
        self.assertNotIn("private-value", report)

    def test_psa_diagnostic_classifies_label_maps_without_exposing_values(self):
        for labels, expected in (
            ({}, "empty map"),
            ({"goog-terraform-provisioned": "true"}, "goog-terraform-provisioned=true"),
            ({"other": "private-value"}, "unexpected map (contents withheld)"),
            ({"goog-terraform-provisioned": "true", "other": "private-value"},
             "unexpected map (contents withheld)"),
        ):
            drift = label_drift()
            drift["change"]["after"]["labels"] = labels
            self.plan["resource_drift"] = [drift]
            report = "\n".join(diagnose_drift(self.plan))
            with self.subTest(labels=labels):
                self.assertIn("labels: before=null; after=" + expected, report)
                self.assertNotIn("private-value", report)
            if labels == {}:
                self.assertEqual(check_plan(self.plan), "apply")
            else:
                with self.assertRaisesRegex(ValueError, "drift"):
                    check_plan(self.plan)

    def test_psa_drift_requires_readback_without_a_proposed_resource_change(self):
        self.plan["resource_drift"] = [label_drift()]
        change = next(c for c in self.plan["resource_changes"] if c["address"] == PSA_ADDRESS)
        change["change"]["actions"] = ["update"]
        with self.assertRaisesRegex(ValueError, "readback only"):
            check_plan(self.plan)

    def test_psa_diagnostic_reports_attribution_presence_without_map_contents(self):
        drift = label_drift()
        drift["change"]["before"]["effective_labels"] = None
        drift["change"]["after"]["terraform_labels"] = {
            "goog-terraform-provisioned": "true", "other": "private-value"}
        drift["change"]["after"]["effective_labels"] = {
            "goog-terraform-provisioned": "true", "other": "private-value"}
        self.plan["resource_drift"] = [drift]
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("terraform_labels: before=expected attribution label present; "
                      "after=expected attribution label present", report)
        self.assertIn("effective_labels: before=null; after=expected attribution label present", report)
        self.assertNotIn("private-value", report)
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)

        drift["change"]["after"]["terraform_labels"] = {"other": "private-value"}
        drift["change"]["after"]["effective_labels"] = {}
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("terraform_labels: before=expected attribution label present; "
                      "after=expected attribution label absent or different", report)
        self.assertIn("effective_labels: before=null; after=expected attribution label absent or different", report)
        self.assertNotIn("private-value", report)

    def test_metadata_drift_rejects_mode_fields_cidr_and_other_changes(self):
        for mutate in (
            lambda d: d["change"]["after"]["log_config"][0].update({"metadata": "CUSTOM_METADATA"}),
            lambda d: d["change"]["after"]["log_config"][0].update({"metadata_fields": ["src_instance"]}),
            lambda d: d["change"]["after"].update({"ip_cidr_range": "10.21.0.0/20"}),
            lambda d: d["change"]["after"]["log_config"][0].update({"flow_sampling": 1}),
            lambda d: d["change"].update({"actions": ["delete"]}),
        ):
            drift = metadata_drift()
            mutate(drift)
            self.plan["resource_drift"] = [drift]
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, "drift"):
                check_plan(self.plan)

    def test_duplicate_or_unrelated_drift_is_rejected(self):
        self.plan["resource_drift"] = [label_drift(), label_drift()]
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)
        unrelated = label_drift()
        unrelated["address"] = next(iter(NETWORK))
        self.plan["resource_drift"] = [unrelated]
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)

    def test_sql_public_ip_is_rejected(self):
        self.values("google_sql_database_instance")["settings"][0]["ip_configuration"][0]["ipv4_enabled"] = True
        with self.assertRaisesRegex(ValueError, "public IPv4"):
            check_plan(self.plan)

    def test_wrong_sql_vpc_or_allocation_is_rejected(self):
        for field in ("private_network", "allocated_ip_range"):
            plan = fixture()
            next(r["values"] for r in plan["planned_values"]["root_module"]["resources"]
                 if r["type"] == "google_sql_database_instance")["settings"][0]["ip_configuration"][0][field] = "wrong"
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan(plan)

    def test_sql_plan_accepts_exact_project_path_or_compute_self_link(self):
        for network_ref in (VPC_LINK, VPC_PATH):
            plan = fixture()
            next(r["values"] for r in plan["planned_values"]["root_module"]["resources"]
                 if r["type"] == "google_sql_database_instance")["settings"][0]["ip_configuration"][0]["private_network"] = network_ref
            with self.subTest(network_ref=network_ref):
                self.assertEqual(check_plan(plan), "apply")

        for network_ref in (
            "projects/wrong-project/global/networks/helpdeskcloud-dev-vpc",
            "projects/helpdeskcloud-capstone-511905/global/networks/wrong-vpc",
        ):
            plan = fixture()
            next(r["values"] for r in plan["planned_values"]["root_module"]["resources"]
                 if r["type"] == "google_sql_database_instance")["settings"][0]["ip_configuration"][0]["private_network"] = network_ref
            with self.subTest(network_ref=network_ref), self.assertRaisesRegex(ValueError, "intended private VPC"):
                check_plan(plan)

    def test_wrong_sql_tier_or_engine_is_rejected(self):
        for field, value in (("tier", "db-custom-2-7680"), ("database_version", "POSTGRES_16")):
            plan = fixture()
            sql = next(r["values"] for r in plan["planned_values"]["root_module"]["resources"]
                       if r["type"] == "google_sql_database_instance")
            (sql["settings"][0] if field == "tier" else sql)[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan(plan)

    def test_terraform_sql_deletion_protection_is_still_required(self):
        self.values("google_sql_database_instance")["deletion_protection"] = False
        with self.assertRaisesRegex(ValueError, "Terraform SQL deletion protection"):
            check_plan(self.plan)

    def test_invalid_registry_is_rejected(self):
        self.values("google_artifact_registry_repository")["docker_config"][0]["immutable_tags"] = False
        with self.assertRaisesRegex(ValueError, "immutable"):
            check_plan(self.plan)

    def test_missing_sql_network_reference_is_rejected(self):
        sql = self.plan["configuration"]["root_module"]["resources"][0]
        sql["expressions"]["settings"][0]["ip_configuration"][0]["private_network"]["references"] = []
        with self.assertRaisesRegex(ValueError, "private_network"):
            check_plan(self.plan)

    def test_deployment_verification_and_missing_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state)]
            verify_deployment(filenames)
            state.write_text("\n".join(NETWORK), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "approved resources"):
                verify_deployment(filenames)
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            values[8] = []
            paths[8].write_text(json.dumps(values[8]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "database"):
                verify_deployment(filenames)

    def test_phase7_read_only_verification_rejects_unsafe_api_responses(self):
        # The fixture follows GKE, IAM and Secret Manager's documented JSON nesting.
        mutations = (
            (10, lambda v: v["controlPlaneEndpointsConfig"]["ipEndpointsConfig"].update(enabled=True), "endpoints"),
            (10, lambda v: v["workloadIdentityConfig"].update(workloadPool="wrong.svc.id.goog"), "Workload Identity"),
            (10, lambda v: v.update(network="projects/other/global/networks/helpdeskcloud-dev-vpc"), "VPC"),
            (10, lambda v: v["networkConfig"].update(network="projects/other/global/networks/helpdeskcloud-dev-vpc"), "networkConfig"),
            (10, lambda v: v["ipAllocationPolicy"].update(useIpAliases=False), "alias IP"),
            (10, lambda v: v["autoscaling"]["autoprovisioningNodePoolDefaults"].update(serviceAccount="default@developer.gserviceaccount.com"), "node identity"),
            (10, lambda v: v["secretManagerConfig"].update(enabled=False), "Secret Manager"),
            (16, lambda v: v["bindings"][0].update(members=["allUsers"]), "Public"),
            (18, lambda v: v["bindings"][0].update(members=["allUsers"]), "Public"),
            (18, lambda v: v["bindings"].append({"role": "roles/secretmanager.admin", "members": ["user:other@example.com"]}), "Unexpected direct secret IAM"),
            (6, lambda v: v["bindings"].append({"role": "roles/editor", "members": [
                "serviceAccount:helpdesk-app-dev@helpdeskcloud-capstone-511905.iam.gserviceaccount.com"]}),
             "unapproved administrative role"),
            (14, lambda v: v["replication"].update(automatic=None), "replication"),
            (20, lambda v: v["values"]["root_module"]["resources"][0]["values"].update(deletion_protection=False),
             "deletion protection"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(21)]
            state_addresses = Path(temporary) / "state-addresses.txt"
            state_addresses.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state_addresses)]
            for index, mutate, message in mutations:
                values = evidence()
                mutate(values[index])
                for path, value in zip(paths, values):
                    path.write_text(json.dumps(value), encoding="utf-8")
                with self.subTest(index=index, message=message), self.assertRaisesRegex(ValueError, message):
                    verify_deployment(filenames)

    def test_secret_manager_accepts_canonical_project_number_resource_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            values[14]["name"] = (
                "projects/260283083469/secrets/helpdesk-dev-db-connection"
            )
            values[15]["name"] = (
                "projects/260283083469/secrets/helpdesk-dev-db-admin-password"
            )
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            verify_deployment([str(path) for path in paths] + [str(state)])

    def test_secret_manager_rejects_unapproved_project_number_resource_names(self):
        for index, name in (
            (14, "projects/999999999999/secrets/helpdesk-dev-db-connection"),
            (15, "projects/260283083469/secrets/unexpected-secret"),
        ):
            with self.subTest(index=index, name=name), tempfile.TemporaryDirectory() as temporary:
                values = evidence()
                values[index]["name"] = name
                paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
                for path, value in zip(paths, values):
                    path.write_text(json.dumps(value), encoding="utf-8")
                state = Path(temporary) / "state-addresses.txt"
                state.write_text("\n".join(EXPECTED), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "metadata or replication"):
                    verify_deployment([str(path) for path in paths] + [str(state)])

    def test_artifact_registry_outputs_match_apply_log_and_api_formats(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state)]

            # Apply output is the short repository ID; the GCP API name is a full path.
            self.assertEqual(values[4]["name"],
                             "projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/helpdeskcloud-dev-images")
            self.assertEqual(values[9]["artifact_registry_resource_name"]["value"], "helpdeskcloud-dev-images")
            self.assertEqual(values[9]["docker_image_repository"]["value"],
                             "us-east1-docker.pkg.dev/helpdeskcloud-capstone-511905/helpdeskcloud-dev-images/helpdeskcloud")
            verify_deployment(filenames)

            values[9]["artifact_registry_resource_name"]["value"] = values[4]["name"]
            paths[9].write_text(json.dumps(values[9]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact_registry_resource_name"):
                verify_deployment(filenames)

            values[9]["artifact_registry_resource_name"]["value"] = "helpdeskcloud-dev-images"
            values[4]["name"] = "projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/unexpected"
            paths[4].write_text(json.dumps(values[4]), encoding="utf-8")
            paths[9].write_text(json.dumps(values[9]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Artifact Registry identity"):
                verify_deployment(filenames)

            values[4]["name"] = "projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/helpdeskcloud-dev-images"
            values[9]["docker_image_repository"]["value"] = "us-east1-docker.pkg.dev/wrong-project/helpdeskcloud-dev-images/helpdeskcloud"
            paths[4].write_text(json.dumps(values[4]), encoding="utf-8")
            paths[9].write_text(json.dumps(values[9]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "docker_image_repository"):
                verify_deployment(filenames)

    def test_cloud_sql_api_deletion_protection_uses_nested_settings_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state)]

            # The Cloud SQL API response has this flag under settings; no top-level
            # deletionProtection field is required for a valid API response.
            verify_deployment(filenames)

            values[7]["settings"]["deletionProtectionEnabled"] = False
            values[7]["deletionProtection"] = True
            paths[7].write_text(json.dumps(values[7]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "API deletion protection"):
                verify_deployment(filenames)

            del values[7]["settings"]["deletionProtectionEnabled"]
            paths[7].write_text(json.dumps(values[7]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "API deletion protection"):
                verify_deployment(filenames)

    def test_cloud_sql_private_network_accepts_only_exact_project_and_vpc(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state)]

            for network_ref in (VPC_PATH, VPC_LINK):
                with self.subTest(accepted=network_ref):
                    values[7]["settings"]["ipConfiguration"]["privateNetwork"] = network_ref
                    paths[7].write_text(json.dumps(values[7]), encoding="utf-8")
                    verify_deployment(filenames)

            for network_ref in (
                "projects/wrong-project/global/networks/helpdeskcloud-dev-vpc",
                "projects/helpdeskcloud-capstone-511905/global/networks/wrong-vpc",
                "https://www.googleapis.com/compute/v1/projects/wrong-project/global/networks/helpdeskcloud-dev-vpc",
                "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/global/networks/wrong-vpc",
            ):
                with self.subTest(rejected=network_ref):
                    values[7]["settings"]["ipConfiguration"]["privateNetwork"] = network_ref
                    paths[7].write_text(json.dumps(values[7]), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "intended private VPC"):
                        verify_deployment(filenames)

    def test_verification_rejects_other_project_in_vpc_or_peering(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state)]

            values[0]["selfLink"] = VPC_LINK.replace("projects/helpdeskcloud-capstone-511905/", "projects/wrong-project/")
            paths[0].write_text(json.dumps(values[0]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "VPC self-link"):
                verify_deployment(filenames)

            values[0]["selfLink"] = VPC_LINK
            paths[0].write_text(json.dumps(values[0]), encoding="utf-8")
            values[3][0]["network"] = VPC_PATH
            paths[3].write_text(json.dumps(values[3]), encoding="utf-8")
            verify_deployment(filenames)

            values[3][0]["network"] = "projects/wrong-project/global/networks/helpdeskcloud-dev-vpc"
            paths[3].write_text(json.dumps(values[3]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PSA connection"):
                verify_deployment(filenames)

    def test_cloud_sql_api_rejects_non_runnable_or_public_address(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            filenames = [str(path) for path in paths] + [str(state)]

            values[7]["state"] = "FAILED"
            paths[7].write_text(json.dumps(values[7]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not RUNNABLE"):
                verify_deployment(filenames)

            values[7]["state"] = "RUNNABLE"
            values[7]["ipAddresses"].append({"type": "PRIMARY", "ipAddress": "203.0.113.10"})
            paths[7].write_text(json.dumps(values[7]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected public IP"):
                verify_deployment(filenames)

    def test_public_iam_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            values = evidence()
            values[5] = {"bindings": [{"role": "roles/artifactregistry.reader", "members": ["allUsers"]}]}
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(len(values))]
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            state = Path(temporary) / "state-addresses.txt"
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Public"):
                verify_deployment([str(path) for path in paths] + [str(state)])


if __name__ == "__main__":
    unittest.main()
