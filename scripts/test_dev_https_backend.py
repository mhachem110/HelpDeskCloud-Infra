import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dev_https_backend", ROOT / "scripts/dev_https_backend.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def gateway_fixture():
    return {
        "metadata": {
            "name": backend.GATEWAY_NAME,
            "namespace": backend.NAMESPACE,
            "uid": "f6ab8d12-708b-4ad0-9b41-43a116760312",
            "annotations": {backend.BACKEND_ANNOTATION: "gkegw-helpdesk-service"},
        },
        "status": {"conditions": [
            {"type": "Accepted", "status": "True"},
            {"type": "Programmed", "status": "True"},
        ]},
    }


def cloud_backend_fixture():
    return {
        "name": "gkegw-helpdesk-service",
        "id": "1234567890",
        "selfLink": "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/global/backendServices/gkegw-helpdesk-service",
        "backends": [{
            "group": "https://www.googleapis.com/compute/v1/projects/helpdeskcloud-capstone-511905/zones/us-east1-b/networkEndpointGroups/gkegw1-helpdesk",
        }],
    }


class DevHttpsBackendTests(unittest.TestCase):
    def test_exact_programmed_gateway_backend_in_project_is_discovered(self):
        self.assertEqual(backend.gateway_backend(gateway_fixture()), "gkegw-helpdesk-service")
        self.assertEqual(backend.validate_backend(gateway_fixture(), cloud_backend_fixture()),
                         "gkegw-helpdesk-service")

    def test_unprogrammed_gateway_is_reported_not_ready(self):
        gateway = gateway_fixture()
        gateway["status"]["conditions"][1]["status"] = "False"
        with self.assertRaises(backend.NotReady):
            backend.gateway_backend(gateway)

    def test_wrong_gateway_or_backend_annotation_is_rejected(self):
        gateway = gateway_fixture()
        gateway["metadata"]["name"] = "other-gateway"
        with self.assertRaisesRegex(ValueError, "not the approved"):
            backend.gateway_backend(gateway)
        gateway = gateway_fixture()
        gateway["metadata"]["annotations"][backend.BACKEND_ANNOTATION] = "arbitrary-backend"
        with self.assertRaisesRegex(ValueError, "annotation"):
            backend.gateway_backend(gateway)

    def test_arbitrary_cloud_backend_project_or_non_gke_group_is_rejected(self):
        gateway = gateway_fixture()
        for key, value in (
            ("name", "gkegw-unrelated"),
            ("selfLink", "https://www.googleapis.com/compute/v1/projects/other/global/backendServices/gkegw-helpdesk-service"),
        ):
            candidate = cloud_backend_fixture()
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                backend.validate_backend(gateway, candidate)
        candidate = cloud_backend_fixture()
        candidate["backends"][0]["group"] = "https://example.invalid/arbitrary"
        with self.assertRaisesRegex(ValueError, "network endpoint groups"):
            backend.validate_backend(gateway, candidate)


if __name__ == "__main__":
    unittest.main()
