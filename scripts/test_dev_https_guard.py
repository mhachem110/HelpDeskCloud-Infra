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
                {"address": "google_compute_global_address.https", "expressions": {
                    "address_type": {"constant_value": "EXTERNAL"},
                    "ip_version": {"constant_value": "IPV4"}}},
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


def partial_foundation_plan():
    """Model the failed Apply: retained IP and TLS policy, with four resources still to add."""
    plan = foundation_plan()
    retained = {"google_compute_global_address.https", "google_compute_ssl_policy.https"}
    resources = plan["planned_values"]["root_module"]["resources"]
    for change in plan["resource_changes"]:
        if change["address"] in retained:
            change["change"]["actions"] = ["no-op"]
    plan["prior_state"]["values"]["root_module"]["resources"] = [
        deepcopy(resource) for resource in resources if resource["address"] in retained
    ]
    return plan


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

    def test_partial_apply_state_preserves_ip_and_tls_and_creates_only_remaining_certificates(self):
        plan = partial_foundation_plan()
        guard.check_foundation(plan, HOST)
        actions = {change["address"]: change["change"]["actions"]
                   for change in plan["resource_changes"]}
        self.assertEqual(actions["google_compute_global_address.https"], ["no-op"])
        self.assertEqual(actions["google_compute_ssl_policy.https"], ["no-op"])
        self.assertEqual(sum(action == ["create"] for action in actions.values()), 4)
        self.assertEqual(sum(action == ["no-op"] for action in actions.values()), 2)

    def test_foundation_rejects_project_api_enablement_resources(self):
        plan = foundation_plan()
        plan["planned_values"]["root_module"]["resources"].append({
            "address": "google_project_service.iap", "mode": "managed",
            "type": "google_project_service", "values": {"service": "iap.googleapis.com"}})
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_provider_omitted_global_address_defaults_are_checked_live_after_apply(self):
        plan = foundation_plan()
        address = plan["resource_changes"][0]["change"]["after"]
        address.update(address_type="", ip_version="", address="34.8.56.208")
        plan["planned_values"]["root_module"]["resources"][0]["values"].update(
            address_type="", ip_version="", address="34.8.56.208")
        guard.check_foundation(plan, HOST)
        address["ip_version"] = "IPV6"
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_ipv4_provider_default_without_explicit_configuration(self):
        plan = foundation_plan()
        del plan["configuration"]["root_module"]["resources"][0]["expressions"]["ip_version"]
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_non_ipv4_existing_reservation(self):
        plan = foundation_plan()
        plan["resource_changes"][0]["change"]["after"].update(address="2001:db8::1", ip_version="")
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

    def test_partial_state_accepts_only_confirmed_null_to_empty_provider_readback(self):
        plan = partial_foundation_plan()
        plan["resource_drift"] = [
            {
                "address": "google_compute_global_address.https", "mode": "managed",
                "type": "google_compute_global_address",
                "change": {"actions": ["update"], "before": {"labels": None}, "after": {"labels": {}}},
            },
            {
                "address": "google_compute_ssl_policy.https", "mode": "managed",
                "type": "google_compute_ssl_policy",
                "change": {"actions": ["update"], "before": {"custom_features": None},
                           "after": {"custom_features": []}},
            },
        ]
        guard.check_foundation(plan, HOST)

    def test_foundation_rejects_any_additional_or_material_provider_drift(self):
        mutations = (
            ("google_compute_global_address.https", "labels", None, {"unexpected": "label"}),
            ("google_compute_global_address.https", "address", "34.8.56.208", "34.8.56.209"),
            ("google_compute_ssl_policy.https", "custom_features", None, ["TLS_RSA_WITH_AES_128_CBC_SHA"]),
        )
        for address, field, before_value, after_value in mutations:
            plan = partial_foundation_plan()
            plan["resource_drift"] = [{
                "address": address, "mode": "managed", "type": guard.PROVIDER_READBACK_DRIFT[address][0],
                "change": {"actions": ["update"], "before": {field: before_value}, "after": {field: after_value}},
            }]
            with self.subTest(address=address, field=field), self.assertRaises(ValueError):
                guard.check_foundation(plan, HOST)

    def test_unapproved_drift_reports_resource_fields_and_redacts_sensitive_values(self):
        plan = partial_foundation_plan()
        plan["resource_drift"] = [{
            "address": "google_certificate_manager_certificate.https",
            "mode": "managed",
            "type": "google_certificate_manager_certificate",
            "change": {
                "actions": ["update"],
                "before": {"managed": [{"domains": [HOST]}],
                           "oauth_client_secret": "sensitive-before", "owner_email": "before@example.test"},
                "after": {"managed": [{"domains": ["changed.example.test"]}],
                          "oauth_client_secret": "sensitive-after", "owner_email": "after@example.test"},
            },
        }]

        with self.assertRaises(ValueError) as error:
            guard.check_foundation(plan, HOST)

        message = str(error.exception)
        self.assertIn("google_certificate_manager_certificate.https", message)
        self.assertIn("managed[0].domains[0]", message)
        self.assertIn('"dev.example.test" -> "changed.example.test"', message)
        self.assertIn("oauth_client_secret: <redacted> -> <redacted>", message)
        self.assertIn("owner_email: <redacted> -> <redacted>", message)
        self.assertNotIn("sensitive-before", message)
        self.assertNotIn("sensitive-after", message)
        self.assertNotIn("before@example.test", message)
        self.assertNotIn("after@example.test", message)

    def test_unexpected_field_drift_on_an_allowlisted_resource_reports_actual_transition(self):
        plan = partial_foundation_plan()
        plan["resource_drift"] = [{
            "address": "google_compute_global_address.https", "mode": "managed",
            "type": "google_compute_global_address",
            "change": {"actions": ["update"],
                       "before": {"address": "34.8.56.208"},
                       "after": {"address": "34.8.56.209"}},
        }]

        with self.assertRaises(ValueError) as error:
            guard.check_foundation(plan, HOST)

        message = str(error.exception)
        self.assertIn("expected only labels=None->{}", message)
        self.assertIn('address: "34.8.56.208" -> "34.8.56.209"', message)

    def test_foundation_rejects_readback_drift_if_retained_resource_would_change(self):
        plan = partial_foundation_plan()
        plan["resource_changes"][0]["change"]["actions"] = ["update"]
        plan["resource_drift"] = [{
            "address": "google_compute_global_address.https", "mode": "managed",
            "type": "google_compute_global_address",
            "change": {"actions": ["update"], "before": {"labels": None}, "after": {"labels": {}}},
        }]
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_hostname_change(self):
        with self.assertRaises(ValueError):
            guard.check_foundation(foundation_plan(), "other.example.test")

    def test_foundation_rejects_weaker_tls(self):
        plan = foundation_plan()
        plan["resource_changes"][1]["change"]["after"]["min_tls_version"] = "TLS_1_0"
        with self.assertRaises(ValueError):
            guard.check_foundation(plan, HOST)

    def test_foundation_rejects_broad_certificate(self):
        plan = foundation_plan()
        plan["resource_changes"][3]["change"]["after"]["managed"][0]["domains"] = ["*.example.test"]
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
