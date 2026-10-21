#!/usr/bin/env python3
"""Discover only the IAP backend serving the approved HelpDesk HTTPRoute."""

import json
import re
import sys
from pathlib import Path


PROJECT = "helpdeskcloud-capstone-511905"
PROJECT_NUMBER = "260283083469"
GATEWAY_NAME = "helpdesk-dev-https"
HTTPROUTE_NAME = "helpdesk-dev-https"
SERVICE_NAME = "helpdesk-helpdesk"
SERVICE_PORT = 80
NAMESPACE = "helpdesk-dev"
BACKEND_ANNOTATION = "networking.gke.io/backend-services"
NEG_STATUS_ANNOTATION = "cloud.google.com/neg-status"
BACKEND_NAME = re.compile(r"^gkegw1?-[a-z0-9-]{1,56}$")
BACKEND_RESOURCE_PATH = re.compile(
    r"^(?:https?://[^/]+(?:/compute/(?:v[0-9]+|beta|alpha))?)?"
    r"/projects/([^/]+)/global/backendServices/([^/]+)$"
)


class NotReady(ValueError):
    """The Gateway's dependent resources have not finished provisioning."""


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def approved_kubernetes_object(obj, name):
    metadata = obj.get("metadata", {})
    if metadata.get("name") != name or metadata.get("namespace") != NAMESPACE:
        raise ValueError(f"Kubernetes object is not the approved {name}")
    if not metadata.get("uid"):
        raise ValueError(f"Kubernetes {name} object has no UID")
    return metadata


def backend_names(gateway):
    metadata = approved_kubernetes_object(gateway, GATEWAY_NAME)
    annotation = metadata.get("annotations", {}).get(BACKEND_ANNOTATION, "")
    entries = [entry.strip() for entry in annotation.split(",") if entry.strip()]
    if not entries:
        raise NotReady("GKE has not published the Gateway backend-services annotation")

    names = []
    for entry in entries:
        if BACKEND_NAME.fullmatch(entry):
            names.append(entry)
            continue
        resource_path = BACKEND_RESOURCE_PATH.fullmatch(entry)
        if not resource_path:
            raise ValueError("Gateway backend-services annotation contains a malformed backend")
        project, name = resource_path.groups()
        if project not in (PROJECT, PROJECT_NUMBER) or not BACKEND_NAME.fullmatch(name):
            raise ValueError("Gateway backend-services annotation contains a backend outside the approved project")
        names.append(name)
    if len(names) != len(set(names)):
        raise ValueError("Gateway backend-services annotation contains duplicate backends")
    return names


def route_service(route):
    metadata = approved_kubernetes_object(route, HTTPROUTE_NAME)
    parent_refs = route.get("spec", {}).get("parentRefs", [])
    matching_parents = [
        parent for parent in parent_refs
        if parent.get("name") == GATEWAY_NAME
        and parent.get("kind", "Gateway") == "Gateway"
        and parent.get("group", "gateway.networking.k8s.io") == "gateway.networking.k8s.io"
        and parent.get("namespace", NAMESPACE) == NAMESPACE
    ]
    if len(parent_refs) != 1 or len(matching_parents) != 1:
        raise ValueError("HTTPRoute must reference only the approved HelpDesk Gateway")
    parent_statuses = [
        parent_status for parent_status in route.get("status", {}).get("parents", [])
        if parent_status.get("parentRef", {}).get("name") == GATEWAY_NAME
        and parent_status.get("parentRef", {}).get("namespace") in (None, NAMESPACE)
    ]
    if len(parent_statuses) != 1:
        raise NotReady("GKE has not published status for the approved HelpDesk HTTPRoute parent")
    route_conditions = {
        condition.get("type"): condition.get("status")
        for condition in parent_statuses[0].get("conditions", [])
    }
    if route_conditions.get("Accepted") != "True" or route_conditions.get("ResolvedRefs") != "True":
        raise NotReady("HelpDesk HTTPRoute is not accepted with resolved Service references")

    rules = route.get("spec", {}).get("rules", [])
    if len(rules) != 1:
        raise ValueError("HelpDesk HTTPRoute must have exactly one routing rule")
    backend_refs = rules[0].get("backendRefs", [])
    if len(backend_refs) != 1:
        raise ValueError("HelpDesk HTTPRoute must reference exactly one Service backend")
    backend_ref = backend_refs[0]
    if (backend_ref.get("group", "") not in ("", None)
            or backend_ref.get("kind", "Service") != "Service"
            or backend_ref.get("name") != SERVICE_NAME
            or backend_ref.get("port") != SERVICE_PORT):
        raise ValueError("HTTPRoute backend is not the approved HelpDesk Service on port 80")
    return metadata


def service_neg(service):
    metadata = approved_kubernetes_object(service, SERVICE_NAME)
    ports = service.get("spec", {}).get("ports", [])
    if not any(port.get("port") == SERVICE_PORT and port.get("protocol", "TCP") == "TCP" for port in ports):
        raise ValueError("HelpDesk Service does not expose the approved TCP port 80")
    raw_neg_status = metadata.get("annotations", {}).get(NEG_STATUS_ANNOTATION)
    if not raw_neg_status:
        raise NotReady("GKE has not published the HelpDesk Service NEG annotation")
    try:
        neg_status = json.loads(raw_neg_status)
    except json.JSONDecodeError as error:
        raise ValueError("HelpDesk Service NEG annotation is malformed") from error
    neg_name = neg_status.get("network_endpoint_groups", {}).get(str(SERVICE_PORT))
    if not isinstance(neg_name, str) or not re.fullmatch(r"k8s1-[a-z0-9-]{1,58}", neg_name):
        raise NotReady("GKE has not published the expected HelpDesk port 80 network endpoint group")
    return neg_name


def gateway_backend(gateway, route, service):
    metadata = approved_kubernetes_object(gateway, GATEWAY_NAME)
    conditions = gateway.get("status", {}).get("conditions", [])
    state = {condition.get("type"): condition.get("status") for condition in conditions}
    if state.get("Accepted") != "True" or state.get("Programmed") != "True":
        raise NotReady("HelpDesk HTTPS Gateway is not accepted and programmed")

    route_service(route)
    expected_neg = service_neg(service)
    # GKE's annotation also lists its empty default 404 backend. Restrict
    # selection to the generated backend whose name encodes this exact route
    # Service and port; validate its actual NEG membership before trusting it.
    route_token = f"-{NAMESPACE}-{SERVICE_NAME}-{SERVICE_PORT}-"
    candidates = [name for name in backend_names(gateway) if route_token in name]
    if len(candidates) != 1:
        raise ValueError("Gateway annotation must identify exactly one backend for the HelpDesk Service route")
    return candidates[0], expected_neg


def validate_backend(gateway, route, service, backend_resource):
    expected_name, expected_neg = gateway_backend(gateway, route, service)
    if backend_resource.get("name") != expected_name:
        raise ValueError("Cloud backend name does not match the HelpDesk route Service")
    if not str(backend_resource.get("id", "")).isdigit():
        raise ValueError("Cloud backend has no numeric resource ID")
    project_path = f"/projects/{PROJECT}/global/backendServices/{expected_name}"
    if project_path not in backend_resource.get("selfLink", ""):
        raise ValueError("Cloud backend resource is outside the approved GCP project")
    groups = [backend.get("group", "") for backend in backend_resource.get("backends", [])]
    if not groups:
        raise ValueError("HelpDesk route backend has no GKE network endpoint groups")
    for group in groups:
        match = re.search(
            rf"/projects/{re.escape(PROJECT)}/zones/(us-east1-[^/]+)/networkEndpointGroups/([^/]+)$",
            group,
        )
        if not match or match.group(2) != expected_neg:
            raise ValueError("Cloud backend is not attached only to the HelpDesk Service's regional GKE NEG")
    return expected_name


def main():
    if len(sys.argv) not in (5, 6) or sys.argv[1] not in ("gateway-backend", "validate"):
        raise SystemExit(
            "Usage: dev_https_backend.py gateway-backend GATEWAY_JSON HTTPROUTE_JSON SERVICE_JSON "
            "| validate GATEWAY_JSON HTTPROUTE_JSON SERVICE_JSON BACKEND_JSON"
        )
    try:
        gateway, route, service = map(read_json, sys.argv[2:5])
        if sys.argv[1] == "gateway-backend":
            if len(sys.argv) != 5:
                raise ValueError("gateway-backend requires Gateway, HTTPRoute and Service JSON files")
            print(gateway_backend(gateway, route, service)[0])
        else:
            if len(sys.argv) != 6:
                raise ValueError("validate requires Gateway, HTTPRoute, Service and Cloud backend JSON files")
            print(validate_backend(gateway, route, service, read_json(sys.argv[5])))
    except NotReady as error:
        print(f"HTTPS access target is not ready: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"HTTPS backend validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
