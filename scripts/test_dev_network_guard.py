"""Offline safety tests for the Dev Apply gate; no cloud access required."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from dev_network_guard import EXPECTED, check_plan, verify_deployment


def expected_plan():
    addresses = list(EXPECTED)
    after = [
        {"name": "helpdeskcloud-dev-vpc", "auto_create_subnetworks": False, "routing_mode": "REGIONAL"},
        {"name": "helpdeskcloud-dev-subnet", "region": "us-east1", "ip_cidr_range": "10.20.0.0/20",
         "private_ip_google_access": True, "secondary_ip_range": [
             {"range_name": "helpdeskcloud-dev-pods", "ip_cidr_range": "10.24.0.0/16"},
             {"range_name": "helpdeskcloud-dev-services", "ip_cidr_range": "10.25.0.0/20"}]},
        {"name": "helpdeskcloud-dev-psa", "address": "10.30.0.0", "prefix_length": 16,
         "purpose": "VPC_PEERING", "address_type": "INTERNAL"},
        {"service": "servicenetworking.googleapis.com", "reserved_peering_ranges": ["helpdeskcloud-dev-psa"]},
    ]
    resources = [
        {"address": "google_compute_subnetwork.this", "expressions": {"network": {"references": ["google_compute_network.this.id"]}}},
        {"address": "google_compute_global_address.private_services", "expressions": {"network": {"references": ["google_compute_network.this.id"]}}},
        {"address": "google_service_networking_connection.private_services", "expressions": {
            "network": {"references": ["google_compute_network.this.id"]},
            "reserved_peering_ranges": {"references": ["google_compute_global_address.private_services.name"]}}},
    ]
    return {
        "variables": {k: {"value": v} for k, v in {
            "project_id": "helpdeskcloud-capstone-511905", "region": "us-east1", "environment": "dev"}.items()},
        "resource_changes": [
            {"mode": "managed", "address": address, "type": EXPECTED[address],
             "change": {"actions": ["create"], "after": attributes}}
            for address, attributes in zip(addresses, after)
        ],
        "configuration": {"root_module": {"module_calls": {"dev_network": {"module": {"resources": resources}}}}},
    }


class DevPlanGuardTests(unittest.TestCase):
    def setUp(self):
        self.plan = expected_plan()

    def test_expected_four_creations(self):
        self.assertEqual(check_plan(self.plan), "apply")

    def test_no_change_plan_skips_apply(self):
        for change in self.plan["resource_changes"]:
            change["change"]["actions"] = ["no-op"]
        self.assertEqual(check_plan(self.plan), "no_changes")
        self.plan["resource_changes"] = []
        self.assertEqual(check_plan(self.plan), "no_changes")

    def test_replacement_and_delete_are_rejected(self):
        for actions in (["delete", "create"], ["delete"], ["update"]):
            plan = copy.deepcopy(self.plan)
            plan["resource_changes"][0]["change"]["actions"] = actions
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                check_plan(plan)

    def test_extra_resource_is_rejected(self):
        self.plan["resource_changes"].append(copy.deepcopy(self.plan["resource_changes"][0]))
        with self.assertRaises(ValueError):
            check_plan(self.plan)

    def test_wrong_cidr_and_identity_are_rejected(self):
        for index, field, value in ((1, "ip_cidr_range", "10.21.0.0/20"), (2, "name", "other-psa")):
            plan = copy.deepcopy(self.plan)
            plan["resource_changes"][index]["change"]["after"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_plan(plan)

    def test_missing_resource_reference_is_rejected(self):
        self.plan["configuration"]["root_module"]["module_calls"]["dev_network"]["module"]["resources"][2]["expressions"]["reserved_peering_ranges"]["references"] = []
        with self.assertRaises(ValueError):
            check_plan(self.plan)

    def test_drift_is_rejected(self):
        self.plan["resource_drift"] = [{"address": "unexpected"}]
        with self.assertRaises(ValueError):
            check_plan(self.plan)

    def test_post_apply_evidence(self):
        vpc_url = "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/global/networks/helpdeskcloud-dev-vpc"
        subnet_url = "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/regions/us-east1/subnetworks/helpdeskcloud-dev-subnet"
        evidence = [
            {"name": "helpdeskcloud-dev-vpc", "selfLink": vpc_url, "autoCreateSubnetworks": False,
             "routingConfig": {"routingMode": "REGIONAL"},
             "peerings": [{"name": "servicenetworking-googleapis-com", "state": "ACTIVE"}]},
            {"name": "helpdeskcloud-dev-subnet", "selfLink": subnet_url,
             "network": vpc_url, "region": "projects/helpdeskcloud-capstone-511905/regions/us-east1",
             "ipCidrRange": "10.20.0.0/20", "privateIpGoogleAccess": True,
             "secondaryIpRanges": [{"rangeName": "helpdeskcloud-dev-pods", "ipCidrRange": "10.24.0.0/16"},
                                   {"rangeName": "helpdeskcloud-dev-services", "ipCidrRange": "10.25.0.0/20"}]},
            {"name": "helpdeskcloud-dev-psa", "network": vpc_url, "purpose": "VPC_PEERING",
             "addressType": "INTERNAL", "address": "10.30.0.0", "prefixLength": 16},
            [{"network": "projects/260283083469/global/networks/helpdeskcloud-dev-vpc",
              "reservedPeeringRanges": ["helpdeskcloud-dev-psa"],
              "service": "services/servicenetworking.googleapis.com", "peering": "servicenetworking-googleapis-com"}],
            {k: {"value": v} for k, v in {
                "environment": "dev", "project_id": "helpdeskcloud-capstone-511905", "region": "us-east1",
                "vpc_name": "helpdeskcloud-dev-vpc", "vpc_self_link": vpc_url,
                "subnet_name": "helpdeskcloud-dev-subnet", "subnet_self_link": subnet_url,
                "subnet_cidr": "10.20.0.0/20", "pods_range_name": "helpdeskcloud-dev-pods",
                "pods_cidr": "10.24.0.0/16", "services_range_name": "helpdeskcloud-dev-services",
                "services_cidr": "10.25.0.0/20", "private_services_range_name": "helpdeskcloud-dev-psa",
                "private_services_connection_id": "connection-id"}.items()},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            paths = [Path(temporary) / f"evidence-{i}.json" for i in range(5)]
            for path, value in zip(paths, evidence):
                path.write_text(json.dumps(value), encoding="utf-8")
            state_path = Path(temporary) / "state-addresses.txt"
            state_path.write_text("\n".join(EXPECTED), encoding="utf-8")
            path_names = [str(p) for p in paths] + [str(state_path)]
            verify_deployment(path_names)
            evidence[0]["peerings"][0]["state"] = "INACTIVE"
            paths[0].write_text(json.dumps(evidence[0]), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_deployment(path_names)


if __name__ == "__main__":
    unittest.main()
