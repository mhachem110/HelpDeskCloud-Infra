"""Offline tests for the protected Dev Apply decision and read-only verification."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from dev_infra_guard import EXPECTED, NETWORK, PHASE6, VPC_LINK, check_plan, diagnose_drift, verify_deployment


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
    config = {
        "root_module": {
            "resources": [
                {"address": "google_sql_database_instance.dev_postgres", "depends_on": ["module.dev_network"],
                 "expressions": {"settings": [{"ip_configuration": [{
                     "private_network": {"references": ["module.dev_network[0].vpc_self_link"]},
                     "allocated_ip_range": {"references": ["module.dev_network[0].private_services_range_name"]}}]}]}},
                {"address": "google_sql_database.dev_helpdesk", "expressions": {
                    "instance": {"references": ["google_sql_database_instance.dev_postgres[0].name"]}}},
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
    planned = [{"mode": "managed", "address": address, "type": kind, "values": (network | phase6)[kind]}
               for address, kind in EXPECTED.items()]
    changes = [{"mode": "managed", "address": address, "type": kind,
                "change": {"actions": ["no-op"] if address in NETWORK else ["create"]}}
               for address, kind in EXPECTED.items()]
    return {
        "variables": {key: {"value": value} for key, value in {
            "project_id": "helpdeskcloud-capstone-511905", "region": "us-east1", "environment": "dev"}.items()},
        "planned_values": {"root_module": {"resources": planned}},
        "resource_changes": changes,
        "configuration": config,
    }


def evidence():
    vpc = VPC_LINK
    subnet_link = "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet"
    sql = {
        "name": "helpdeskcloud-dev-postgres", "region": "us-east1", "databaseVersion": "POSTGRES_17",
        "deletionProtection": True, "connectionName": "helpdeskcloud-capstone-511905:us-east1:helpdeskcloud-dev-postgres",
        "ipAddresses": [{"type": "PRIVATE", "ipAddress": "10.30.0.5"}],
        "settings": {"edition": "ENTERPRISE", "tier": "db-f1-micro", "availabilityType": "ZONAL",
                     "dataDiskType": "PD_SSD", "dataDiskSizeGb": "10", "storageAutoResize": False,
                     "deletionProtectionEnabled": True,
                     "backupConfiguration": {"enabled": True, "pointInTimeRecoveryEnabled": False,
                                             "backupRetentionSettings": {"retainedBackups": 7}},
                     "ipConfiguration": {"ipv4Enabled": False, "privateNetwork": vpc,
                                         "allocatedIpRange": "helpdeskcloud-dev-psa", "sslMode": "ENCRYPTED_ONLY"}},
    }
    outputs = {key: {"value": value} for key, value in {
        "environment": "dev", "project_id": "helpdeskcloud-capstone-511905", "region": "us-east1",
        "vpc_name": "helpdeskcloud-dev-vpc", "vpc_self_link": vpc,
        "subnet_name": "helpdeskcloud-dev-subnet", "subnet_self_link": subnet_link,
        "subnet_cidr": "10.20.0.0/20", "pods_range_name": "helpdeskcloud-dev-pods",
        "pods_cidr": "10.24.0.0/16", "services_range_name": "helpdeskcloud-dev-services",
        "services_cidr": "10.25.0.0/20", "private_services_range_name": "helpdeskcloud-dev-psa",
        "private_services_connection_id": "connection-id",
        "artifact_registry_repository_id": "helpdeskcloud-dev-images", "artifact_registry_location": "us-east1",
        "artifact_registry_resource_name": "projects/helpdeskcloud-capstone-511905/locations/us-east1/repositories/helpdeskcloud-dev-images",
        "cloud_sql_instance_name": "helpdeskcloud-dev-postgres", "cloud_sql_region": "us-east1",
        "cloud_sql_database_version": "POSTGRES_17", "cloud_sql_database_name": "helpdesk",
        "cloud_sql_private_ip": "10.30.0.5", "cloud_sql_connection_name": sql["connectionName"],
        "cloud_sql_vpc_self_link": vpc, "cloud_sql_private_services_range_name": "helpdeskcloud-dev-psa",
    }.items()}
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
        {"bindings": []}, {"bindings": []}, sql,
        [{"name": "helpdesk", "instance": "helpdeskcloud-dev-postgres"}], outputs,
    ]


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.plan = fixture()

    def change(self, address, actions):
        next(c for c in self.plan["resource_changes"] if c["address"] == address)["change"]["actions"] = actions

    def values(self, kind):
        return next(r["values"] for r in self.plan["planned_values"]["root_module"]["resources"] if r["type"] == kind)

    def test_three_approved_creations(self):
        self.assertEqual(check_plan(self.plan), "apply")

    def test_no_changes_even_when_no_op_entries_are_omitted(self):
        for change in self.plan["resource_changes"]:
            change["change"]["actions"] = ["no-op"]
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

    def test_partial_phase6_creation_is_rejected(self):
        self.change("google_sql_database.dev_helpdesk[0]", ["no-op"])
        with self.assertRaisesRegex(ValueError, "Partial"):
            check_plan(self.plan)

    def test_unknown_drift_is_rejected_and_diagnosed_without_values(self):
        self.plan["resource_drift"] = [{"address": next(iter(NETWORK)), "type": "google_compute_network",
                                        "change": {"actions": ["update"], "before": {"routing_mode": "REGIONAL"},
                                                   "after": {"routing_mode": "GLOBAL"}}}]
        with self.assertRaisesRegex(ValueError, "drift"):
            check_plan(self.plan)
        report = "\n".join(diagnose_drift(self.plan))
        self.assertIn("routing_mode", report)
        self.assertIn("security-sensitive paths=yes", report)
        self.assertNotIn("GLOBAL", report)

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

    def test_wrong_sql_tier_or_engine_is_rejected(self):
        for field, value in (("tier", "db-custom-2-7680"), ("database_version", "POSTGRES_16")):
            plan = fixture()
            sql = next(r["values"] for r in plan["planned_values"]["root_module"]["resources"]
                       if r["type"] == "google_sql_database_instance")
            (sql["settings"][0] if field == "tier" else sql)[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan(plan)

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
            with self.assertRaisesRegex(ValueError, "seven"):
                verify_deployment(filenames)
            state.write_text("\n".join(EXPECTED), encoding="utf-8")
            values[8] = []
            paths[8].write_text(json.dumps(values[8]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "database"):
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
