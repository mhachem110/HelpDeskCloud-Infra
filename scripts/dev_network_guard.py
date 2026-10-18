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
EXPECTED = {
    PREFIX + "google_compute_network.this": "google_compute_network",
    PREFIX + "google_compute_subnetwork.this": "google_compute_subnetwork",
    PREFIX + "google_compute_global_address.private_services": "google_compute_global_address",
    PREFIX + "google_service_networking_connection.private_services": "google_service_networking_connection",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_plan(plan):
    variables = plan.get("variables", {})
    for name, expected in {
        "project_id": PROJECT,
        "region": "us-east1",
        "environment": "dev",
    }.items():
        require(variables.get(name, {}).get("value") == expected, f"Unexpected {name}")

    changes = [c for c in plan.get("resource_changes", []) if c.get("mode") == "managed"]
    require(not plan.get("resource_drift"), "Existing resource drift requires review")
    if not changes:
        return "no_changes"
    require(len(changes) == 4, "Plan must contain exactly four managed resources")
    require({c.get("address") for c in changes} == set(EXPECTED), "Unexpected resource address")
    require(all(c.get("type") == EXPECTED[c["address"]] for c in changes), "Unexpected resource type")

    actions = [c["change"]["actions"] for c in changes]
    if all(a == ["no-op"] for a in actions):
        return "no_changes"
    require(all(a == ["create"] for a in actions), "Plan must only create the four expected resources")
    after = {c["type"]: c["change"].get("after", {}) for c in changes}

    network = after["google_compute_network"]
    require(network.get("name") == VPC, "Unexpected VPC name")
    require(network.get("auto_create_subnetworks") is False, "VPC must use custom subnet mode")
    require(network.get("routing_mode") == "REGIONAL", "Unexpected VPC routing mode")

    subnet = after["google_compute_subnetwork"]
    require(subnet.get("name") == SUBNET and subnet.get("region") == "us-east1", "Unexpected subnet identity")
    require(subnet.get("ip_cidr_range") == "10.20.0.0/20", "Unexpected primary subnet CIDR")
    require(subnet.get("private_ip_google_access") is True, "Private Google Access must be enabled")
    ranges = subnet.get("secondary_ip_range", [])
    require(isinstance(ranges, list) and len(ranges) == 2, "Expected two secondary ranges")
    require(
        {r.get("range_name"): r.get("ip_cidr_range") for r in ranges}
        == {"helpdeskcloud-dev-pods": "10.24.0.0/16", "helpdeskcloud-dev-services": "10.25.0.0/20"},
        "Unexpected secondary ranges",
    )

    allocation = after["google_compute_global_address"]
    require(allocation.get("name") == PSA, "Unexpected private allocation name")
    require(allocation.get("address") == "10.30.0.0" and allocation.get("prefix_length") == 16, "Unexpected private allocation CIDR")
    require(allocation.get("purpose") == "VPC_PEERING" and allocation.get("address_type") == "INTERNAL", "Invalid private allocation type")

    connection = after["google_service_networking_connection"]
    require(connection.get("service") == SERVICE, "Unexpected service producer")
    require(connection.get("reserved_peering_ranges") == [PSA], "Connection must use the intended allocation")

    # Network IDs are unknown until creation. Check Terraform's resource references.
    module = plan.get("configuration", {}).get("root_module", {}).get("module_calls", {}).get("dev_network", {}).get("module", {})
    resources = {r.get("address"): r for r in module.get("resources", [])}

    def references(address, field, expected):
        refs = resources.get(address, {}).get("expressions", {}).get(field, {}).get("references", [])
        require(expected in refs, f"Missing Terraform reference: {address}.{field}")

    references("google_compute_subnetwork.this", "network", "google_compute_network.this.id")
    references("google_compute_global_address.private_services", "network", "google_compute_network.this.id")
    references("google_service_networking_connection.private_services", "network", "google_compute_network.this.id")
    references("google_service_networking_connection.private_services", "reserved_peering_ranges", "google_compute_global_address.private_services.name")
    return "apply"


def verify_deployment(paths):
    network, subnet, address, connections, outputs = [read_json(p) for p in paths[:5]]
    state_addresses = set(Path(paths[5]).read_text(encoding="utf-8").splitlines())
    require(state_addresses == set(EXPECTED), "Dev state does not contain exactly the four expected resources")
    require(network.get("name") == VPC and network.get("autoCreateSubnetworks") is False, "VPC verification failed")
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
    matched = [c for c in connections if c.get("network", "").endswith("/global/networks/" + VPC)
               and PSA in c.get("reservedPeeringRanges", []) and c.get("service") in (SERVICE, "services/" + SERVICE)]
    require(len(matched) == 1 and matched[0].get("peering"), "PSA connection verification failed")
    require(any(p.get("name") == matched[0]["peering"] and p.get("state") == "ACTIVE"
                for p in network.get("peerings", [])), "Service Networking peering is not active")

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


def main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "check-plan":
            print(check_plan(read_json(sys.argv[2])))
        elif len(sys.argv) == 8 and sys.argv[1] == "verify-deployment":
            verify_deployment(sys.argv[2:])
            print("Dev network, remote state addresses, and outputs verified")
        else:
            raise ValueError("Usage: dev_network_guard.py check-plan PLAN_JSON | verify-deployment VPC SUBNET ADDRESS CONNECTIONS OUTPUTS STATE_LIST")
    except (ValueError, KeyError, IndexError, TypeError, OSError, json.JSONDecodeError) as error:
        print(f"Dev network guard stopped: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
