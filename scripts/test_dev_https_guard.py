import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPT = Path(__file__).with_name("dev_https_guard.py")
spec = importlib.util.spec_from_file_location("dev_https_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

HOST = "dev.example.test"
EMAIL = "owner@example.test"
BACKEND = "gkegw-helpdesk-helpdesk"


def foundation_plan(action=("create",)):
    dns_id = "projects/helpdeskcloud-capstone-511905/locations/global/dnsAuthorizations/helpdesk-dev-https-dns-auth"
    cert_id = "projects/helpdeskcloud-capstone-511905/locations/global/certificates/helpdesk-dev-https-certificate"
    items = {
        "google_project_service.certificate_manager": ("google_project_service", {
            "project": guard.PROJECT, "service": "certificatemanager.googleapis.com", "disable_on_destroy": False}),
        "google_project_service.iap": ("google_project_service", {
            "project": guard.PROJECT, "service": "iap.googleapis.com", "disable_on_destroy": False}),
        "google_compute_global_address.https": ("google_compute_global_address", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-ip", "address_type": "EXTERNAL", "ip_version": "IPV4"}),
        "google_compute_ssl_policy.https": ("google_compute_ssl_policy", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-tls", "profile": "MODERN", "min_tls_version": "TLS_1_2"}),
        "google_certificate_manager_dns_authorization.https": ("google_certificate_manager_dns_authorization", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-dns-auth", "location": "global", "domain": HOST}),
        "google_certificate_manager_certificate.https": ("google_certificate_manager_certificate", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-certificate", "location": "global",
            "managed": [{"domains": [HOST], "dns_authorizations": [dns_id]}]}),
        "google_certificate_manager_certificate_map.https": ("google_certificate_manager_certificate_map", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-map"}),
        "google_certificate_manager_certificate_map_entry.https": ("google_certificate_manager_certificate_map_entry", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-host", "map": "helpdesk-dev-https-map",
            "hostname": HOST, "certificates": [cert_id]}),
    }
    resources = []
    changes = []
    for address, (resource_type, values) in items.items():
        resources.append({"address": address, "mode": "managed", "type": resource_type, "values": values})
        changes.append({"address": address, "mode": "managed", "type": resource_type,
                        "change": {"actions": list(action), "after": deepcopy(values)}})
    configuration = {
        "root_module": {
            "resources": [
                {"address": "google_certificate_manager_certificate.https", "expressions": {
                    "managed": [{"dns_authorizations": {"references": [
                        "google_certificate_manager_dns_authorization.https.id"]}}]}},
                {"address": "google_certificate_manager_certificate_map_entry.https", "expressions": {
                    "certificates": {"references": ["google_certificate_manager_certificate.https.id"]}}},
            ]
        }
    }
    return {"planned_values": {"root_module": {"resources": resources}},
            "resource_changes": changes, "resource_drift": [],
            "prior_state": {"values": {"root_module": {"resources": []}}},
            "configuration": configuration}


def access_plan(action=("create",)):
    values = {"project": guard.PROJECT, "web_backend_service": BACKEND,
              "role": "roles/iap.httpsResourceAccessor", "member": f"user:{EMAIL}"}
    address = "google_iap_web_backend_service_iam_member.helpdesk_user"
    resource = {"address": address, "mode": "managed", "type": "google_iap_web_backend_service_iam_member",
                "values": deepcopy(values)}
    change = {"address": address, "mode": "managed", "type": "google_iap_web_backend_service_iam_member",
              "change": {"actions": list(action), "after": deepcopy(values)}}
    return {"planned_values": {"root_module": {"resources": [resource]}},
            "resource_changes": [change], "resource_drift": [],
            "prior_state": {"values": {"root_module": {"resources": []}}}}


class DevHttpsGuardTests(unittest.TestCase):
    def test_exact_https_foundation_create_is_allowed(self):
        guard.check_foundation(foundation_plan(), HOST)

    def test_exact_https_foundation_noop_is_allowed(self):
        guard.check_foundation(foundation_plan(("no-op",)), HOST)

    def test_provider_omitted_global_address_defaults_are_checked_live_after_apply(self):
        plan = foundation_plan()
        address = plan["resource_changes"][2]["change"]["after"]
        address["address_type"] = None
        address["ip_version"] = None
        plan["planned_values"]["root_module"]["resources"][2]["values"].update(
            address_type=None, ip_version=None)
        guard.check_foundation(plan, HOST)
        address["address_type"] = "INTERNAL"
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_unrelated_resource(self):
        plan = foundation_plan()
        plan["planned_values"]["root_module"]["resources"].append({
            "address": "google_compute_firewall.unrelated", "mode": "managed",
            "type": "google_compute_firewall", "values": {}})
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_updates_deletes_and_replacements(self):
        for actions in (("update",), ("delete",), ("delete", "create"), ("create", "delete")):
            plan = foundation_plan()
            plan["resource_changes"][0]["change"]["actions"] = list(actions)
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                guard.check_foundation(plan, HOST)

    def test_foundation_rejects_drift(self):
        plan = foundation_plan()
        plan["resource_drift"].append({"address": "google_compute_global_address.unexpected"})
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_hostname_change(self):
        with self.assertRaises(ValueError):
            guard.check_foundation(foundation_plan(), "other.example.test")

    def test_foundation_rejects_weaker_tls(self):
        plan = foundation_plan()
        plan["resource_changes"][3]["change"]["after"]["min_tls_version"] = "TLS_1_0"
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_broad_certificate(self):
        plan = foundation_plan()
        plan["resource_changes"][5]["change"]["after"]["managed"][0]["domains"] = ["*.example.test"]
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_single_user_backend_grant_is_allowed(self):
        guard.check_access(access_plan(), BACKEND, EMAIL)

    def test_access_rejects_arbitrary_backend(self):
        with self.assertRaises(ValueError):
            guard.check_access(access_plan(), "unrelated-backend", EMAIL)

    def test_access_rejects_wrong_member_or_role(self):
        for key, value in (("member", "allUsers"), ("member", "group:everyone@example.test"),
                           ("role", "roles/iap.admin")):
            plan = access_plan()
            plan["resource_changes"][0]["change"]["after"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                guard.check_access(plan, BACKEND, EMAIL)

    def test_access_rejects_delete_replace_and_drift(self):
        for actions in (("delete",), ("delete", "create")):
            plan = access_plan(actions)
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                guard.check_access(plan, BACKEND, EMAIL)
        plan = access_plan()
        plan["resource_drift"].append({"address": "google_iap_web_backend_service_iam_member.other"})
        with self.assertRaises(ValueError):
            guard.check_access(plan, BACKEND, EMAIL)

    def test_live_iap_policy_must_have_only_the_configured_user(self):
        guard.verify_access_policy({"bindings": [{"role": "roles/iap.httpsResourceAccessor",
                                                   "members": [f"user:{EMAIL}"]}]}, EMAIL)
        for members in (["allUsers"], [f"user:{EMAIL}", "allAuthenticatedUsers"]):
            with self.subTest(members=members), self.assertRaises(ValueError):
                guard.verify_access_policy({"bindings": [{"role": "roles/iap.httpsResourceAccessor",
                                                           "members": members}]}, EMAIL)


if __name__ == "__main__":
    unittest.main()
