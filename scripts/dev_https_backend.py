#!/usr/bin/env python3
"""Validate that an IAP backend is owned by the intended programmed GKE Gateway."""

import json
import re
import sys
from pathlib import Path


PROJECT = "helpdeskcloud-capstone-511905"
PROJECT_NUMBER = "260283083469"
GATEWAY_NAME = "helpdesk-dev-https"
NAMESPACE = "helpdesk-dev"
BACKEND_ANNOTATION = "networking.gke.io/backend-services"
BACKEND_NAME = re.compile(r"^gkegw-[a-z0-9-]{1,50}$")
BACKEND_RESOURCE_PATH = re.compile(
    r"^(?:https?://[^/]+(?:/compute/(?:v[0-9]+|beta|alpha))?)?"
    r"/projects/([^/]+)/global/backendServices/([^/]+)$"
)


class NotReady(ValueError):
    pass


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def gateway_backend(gateway):
    metadata = gateway.get("metadata", {})
    if metadata.get("name") != GATEWAY_NAME or metadata.get("namespace") != NAMESPACE:
        raise ValueError("Kubernetes object is not the approved HelpDesk HTTPS Gateway")
    if not metadata.get("uid"):
        raise ValueError("Gateway object has no Kubernetes UID")
    conditions = gateway.get("status", {}).get("conditions", [])
    state = {condition.get("type"): condition.get("status") for condition in conditions}
    if state.get("Accepted") != "True" or state.get("Programmed") != "True":
        raise NotReady("HelpDesk HTTPS Gateway is not accepted and programmed")
    annotation = metadata.get("annotations", {}).get(BACKEND_ANNOTATION, "")
    entries = [entry.strip() for entry in annotation.split(",") if entry.strip()]
    if len(entries) != 1:
        raise ValueError("Gateway backend-services annotation must identify exactly one backend")
    backend = entries[0]
    if BACKEND_NAME.fullmatch(backend):
        return backend
    resource_path = BACKEND_RESOURCE_PATH.fullmatch(backend)
    if not resource_path:
        raise ValueError("Gateway backend-services annotation is missing or malformed")
    project, name = resource_path.groups()
    if project not in (PROJECT, PROJECT_NUMBER) or not BACKEND_NAME.fullmatch(name):
        raise ValueError("Gateway backend-services annotation is outside the approved project")
    return name


def validate_backend(gateway, backend_resource):
    expected_name = gateway_backend(gateway)
    if backend_resource.get("name") != expected_name:
        raise ValueError("Cloud backend name does not match the HelpDesk Gateway annotation")
    if not str(backend_resource.get("id", "")).isdigit():
        raise ValueError("Cloud backend has no numeric resource ID")
    project_path = f"/projects/{PROJECT}/global/backendServices/{expected_name}"
    if project_path not in backend_resource.get("selfLink", ""):
        raise ValueError("Cloud backend resource is outside the approved GCP project")
    groups = [backend.get("group", "") for backend in backend_resource.get("backends", [])]
    if not groups or any(
        f"/projects/{PROJECT}/zones/" not in group
        or "/networkEndpointGroups/" not in group
        for group in groups
    ):
        raise ValueError("Cloud backend is not attached only to this project's GKE network endpoint groups")
    return expected_name


def main():
    if len(sys.argv) not in (3, 4) or sys.argv[1] not in ("gateway-backend", "validate"):
        raise SystemExit("Usage: dev_https_backend.py gateway-backend GATEWAY_JSON | validate GATEWAY_JSON BACKEND_JSON")
    try:
        gateway = read_json(sys.argv[2])
        if sys.argv[1] == "gateway-backend":
            if len(sys.argv) != 3:
                raise ValueError("gateway-backend accepts one JSON file")
            print(gateway_backend(gateway))
        else:
            if len(sys.argv) != 4:
                raise ValueError("validate requires Gateway and Cloud backend JSON files")
            print(validate_backend(gateway, read_json(sys.argv[3])))
    except NotReady as error:
        print(f"HTTPS access target is not ready: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"HTTPS backend validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
