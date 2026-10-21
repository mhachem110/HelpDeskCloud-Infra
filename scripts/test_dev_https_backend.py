import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dev_https_backend", ROOT / "scripts/dev_https_backend.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)

APP_BACKEND = "gkegw1-q0h0-helpdesk-dev-helpdesk-helpdesk-80-3xnr96g2yybt"
DEFAULT_BACKEND = "gkegw1-q0h0-helpdesk-dev-gw-serve404-80-yvk48okmns1e"
APP_NEG = "k8s1-65fa85fd-helpdesk-dev-helpdesk-helpdesk-80-82b50f3a"


def gateway_fixture():
    return {
        "metadata": {
            "name": backend.GATEWAY_NAME,
            "namespace": backend.NAMESPACE,
            "uid": "f6ab8d12-708b-4ad0-9b41-43a116760312",
            "annotations": {
                backend.BACKEND_ANNOTATION: f"{DEFAULT_BACKEND}, {APP_BACKEND}",
            },
        },
        "status": {"conditions": [
            {"type": "Accepted", "status": "True"},
            {"type": "Programmed", "status": "True"},
        ]},
    }


def route_fixture():
    return {
        "metadata": {
            "name": backend.HTTPROUTE_NAME,
            "namespace": backend.NAMESPACE,
            "uid": "e1ab8d12-708b-4ad0-9b41-43a116760312",
        },
        "spec": {
            "parentRefs": [{"name": backend.GATEWAY_NAME}],
            "rules": [{"backendRefs": [{"name": backend.SERVICE_NAME, "port": backend.SERVICE_PORT}]}],
        },
        "status": {"parents": [{
            "parentRef": {"name": backend.GATEWAY_NAME},
            "conditions": [
                {"type": "Accepted", "status": "True"},
                {"type": "ResolvedRefs", "status": "True"},
            ],
        }]},
    }


def service_fixture():
    return {
        "metadata": {
            "name": backend.SERVICE_NAME,
            "namespace": backend.NAMESPACE,
            "uid": "a2ab8d12-708b-4ad0-9b41-43a116760312",
            "annotations": {backend.NEG_STATUS_ANNOTATION: json.dumps({
                "network_endpoint_groups": {"80": APP_NEG},
                "zones": ["us-east1-c"],
            })},
        },
        "spec": {"ports": [{"port": 80, "protocol": "TCP", "targetPort": 8080}]},
    }


def cloud_backend_fixture():
    return {
        "name": APP_BACKEND,
        "id": "1234567890",
        "selfLink": (
            "https://www.googleapis.com/compute/v1/projects/"
            f"{backend.PROJECT}/global/backendServices/{APP_BACKEND}"
        ),
        "backends": [{
            "group": (
                f"https://www.googleapis.com/compute/v1/projects/{backend.PROJECT}/"
                f"zones/us-east1-c/networkEndpointGroups/{APP_NEG}"
            ),
        }],
    }


class DevHttpsBackendTests(unittest.TestCase):
    def test_selects_only_the_helpdesk_route_backend_from_gateway_default_and_app_backends(self):
        gateway, route, service = gateway_fixture(), route_fixture(), service_fixture()
        self.assertEqual(backend.gateway_backend(gateway, route, service), (APP_BACKEND, APP_NEG))
        self.assertEqual(
            backend.validate_backend(gateway, route, service, cloud_backend_fixture()), APP_BACKEND
        )

    def test_actual_gke_backend_name_generation_is_accepted(self):
        self.assertRegex(APP_BACKEND, backend.BACKEND_NAME)
        self.assertRegex(DEFAULT_BACKEND, backend.BACKEND_NAME)
        self.assertFalse(backend.BACKEND_NAME.fullmatch("arbitrary-backend"))

    def test_unprogrammed_gateway_is_reported_not_ready(self):
        gateway = gateway_fixture()
        gateway["status"]["conditions"][1]["status"] = "False"
        with self.assertRaises(backend.NotReady):
            backend.gateway_backend(gateway, route_fixture(), service_fixture())

    def test_wrong_gateway_identity_or_malformed_annotation_is_rejected(self):
        gateway = gateway_fixture()
        gateway["metadata"]["name"] = "other-gateway"
        with self.assertRaisesRegex(ValueError, "not the approved"):
            backend.gateway_backend(gateway, route_fixture(), service_fixture())

        gateway = gateway_fixture()
        gateway["metadata"]["annotations"][backend.BACKEND_ANNOTATION] = "arbitrary-backend"
        with self.assertRaisesRegex(ValueError, "malformed"):
            backend.gateway_backend(gateway, route_fixture(), service_fixture())

    def test_backend_annotation_accepts_resource_paths_but_rejects_untrusted_or_ambiguous_entries(self):
        gateway, route, service = gateway_fixture(), route_fixture(), service_fixture()
        gateway["metadata"]["annotations"][backend.BACKEND_ANNOTATION] = (
            f"/projects/{backend.PROJECT_NUMBER}/global/backendServices/{APP_BACKEND}"
        )
        self.assertEqual(backend.gateway_backend(gateway, route, service)[0], APP_BACKEND)

        gateway["metadata"]["annotations"][backend.BACKEND_ANNOTATION] = (
            f"/projects/other/global/backendServices/{APP_BACKEND}"
        )
        with self.assertRaisesRegex(ValueError, "outside the approved project"):
            backend.gateway_backend(gateway, route, service)

        gateway["metadata"]["annotations"][backend.BACKEND_ANNOTATION] = (
            f"{APP_BACKEND}, gkegw1-q0h0-helpdesk-dev-helpdesk-helpdesk-80-another"
        )
        with self.assertRaisesRegex(ValueError, "exactly one backend for the HelpDesk Service"):
            backend.gateway_backend(gateway, route, service)

        gateway["metadata"]["annotations"][backend.BACKEND_ANNOTATION] = DEFAULT_BACKEND
        with self.assertRaisesRegex(ValueError, "exactly one backend for the HelpDesk Service"):
            backend.gateway_backend(gateway, route, service)

    def test_route_must_target_only_the_approved_gateway_service_and_port(self):
        gateway, route, service = gateway_fixture(), route_fixture(), service_fixture()
        for edit in (
            lambda item: item["spec"]["parentRefs"][0].update(name="another-gateway"),
            lambda item: item["spec"]["rules"][0]["backendRefs"][0].update(name="another-service"),
            lambda item: item["spec"]["rules"][0]["backendRefs"][0].update(port=443),
            lambda item: item["spec"]["rules"][0]["backendRefs"].append(
                {"name": backend.SERVICE_NAME, "port": backend.SERVICE_PORT}
            ),
        ):
            candidate = route_fixture()
            edit(candidate)
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                backend.gateway_backend(gateway, candidate, service)

    def test_unaccepted_or_unresolved_route_is_not_ready(self):
        route = route_fixture()
        route["status"]["parents"][0]["conditions"][0]["status"] = "False"
        with self.assertRaises(backend.NotReady):
            backend.gateway_backend(gateway_fixture(), route, service_fixture())

    def test_service_neg_annotation_and_port_must_be_present(self):
        gateway, route, service = gateway_fixture(), route_fixture(), service_fixture()
        service["metadata"]["annotations"].pop(backend.NEG_STATUS_ANNOTATION)
        with self.assertRaises(backend.NotReady):
            backend.gateway_backend(gateway, route, service)

        service = service_fixture()
        service["spec"]["ports"][0]["port"] = 8080
        with self.assertRaisesRegex(ValueError, "does not expose"):
            backend.gateway_backend(gateway, route, service)

    def test_cloud_backend_must_match_exact_name_project_and_service_neg(self):
        gateway, route, service = gateway_fixture(), route_fixture(), service_fixture()
        for key, value in (
            ("name", DEFAULT_BACKEND),
            ("selfLink", f"https://www.googleapis.com/compute/v1/projects/other/global/backendServices/{APP_BACKEND}"),
        ):
            candidate = cloud_backend_fixture()
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                backend.validate_backend(gateway, route, service, candidate)

        candidate = cloud_backend_fixture()
        candidate["backends"][0]["group"] = (
            f"https://www.googleapis.com/compute/v1/projects/{backend.PROJECT}/"
            "zones/us-east1-c/networkEndpointGroups/a-different-neg"
        )
        with self.assertRaisesRegex(ValueError, "HelpDesk Service's regional GKE NEG"):
            backend.validate_backend(gateway, route, service, candidate)

        candidate = cloud_backend_fixture()
        candidate["backends"] = []
        with self.assertRaisesRegex(ValueError, "no GKE network endpoint groups"):
            backend.validate_backend(gateway, route, service, candidate)


if __name__ == "__main__":
    unittest.main()
