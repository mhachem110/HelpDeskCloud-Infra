import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path


SCRIPT = Path(__file__).with_name("dev_https_guard.py")
spec = importlib.util.spec_from_file_location("dev_https_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

HOST = guard.DYNV6_HOSTNAME
LEGACY_HOST = guard.LEGACY_HOSTNAME
EMAIL = "owner@example.test"
BACKEND = "gkegw1-q0h0-helpdesk-dev-helpdesk-helpdesk-80-3xnr96g2yybt"
TARGET_PROXY = (
    f"//compute.googleapis.com/projects/{guard.PROJECT_NUMBER}/global/targetHttpsProxies/"
    "gkegw1-q0h0-helpdesk-dev-helpdesk-dev-https-abc123xyz789"
)


def foundation_plan(action=("create",)):
    dns_id = "projects/helpdeskcloud-capstone-511905/locations/global/dnsAuthorizations/helpdesk-dev-https-dns-auth"
    cert_id = "projects/helpdeskcloud-capstone-511905/locations/global/certificates/helpdesk-dev-https-certificate"
    dynv6_dns_id = "projects/helpdeskcloud-capstone-511905/locations/global/dnsAuthorizations/helpdesk-dev-https-dynv6-dns-auth"
    dynv6_cert_id = "projects/helpdeskcloud-capstone-511905/locations/global/certificates/helpdesk-dev-https-dynv6-certificate"
    items = {
        "google_compute_global_address.https": ("google_compute_global_address", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-ip", "address_type": "EXTERNAL", "ip_version": "IPV4"}),
        "google_compute_ssl_policy.https": ("google_compute_ssl_policy", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-tls", "profile": "MODERN", "min_tls_version": "TLS_1_2"}),
        "google_certificate_manager_dns_authorization.https": ("google_certificate_manager_dns_authorization", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-dns-auth", "location": "global", "domain": LEGACY_HOST}),
        "google_certificate_manager_certificate.https": ("google_certificate_manager_certificate", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-certificate", "location": "global",
            "managed": [{"domains": [LEGACY_HOST], "dns_authorizations": [dns_id]}]}),
        "google_certificate_manager_certificate_map.https": ("google_certificate_manager_certificate_map", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-map"}),
        "google_certificate_manager_certificate_map_entry.https": ("google_certificate_manager_certificate_map_entry", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-host", "map": "helpdesk-dev-https-map",
            "hostname": LEGACY_HOST, "certificates": [cert_id]}),
        "google_certificate_manager_dns_authorization.dynv6": ("google_certificate_manager_dns_authorization", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-dynv6-dns-auth", "location": "global", "domain": HOST}),
        "google_certificate_manager_certificate.dynv6": ("google_certificate_manager_certificate", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-dynv6-certificate", "location": "global",
            "managed": [{"domains": [HOST], "dns_authorizations": [dynv6_dns_id]}]}),
        "google_certificate_manager_certificate_map_entry.dynv6": ("google_certificate_manager_certificate_map_entry", {
            "project": guard.PROJECT, "name": "helpdesk-dev-https-dynv6-host", "map": "helpdesk-dev-https-map",
            "hostname": HOST, "certificates": [dynv6_cert_id]}),
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
                {"address": "google_certificate_manager_certificate.dynv6", "expressions": {
                    "managed": [{"dns_authorizations": {"references": [
                        "google_certificate_manager_dns_authorization.dynv6.id"]}}]}},
                {"address": "google_certificate_manager_certificate_map_entry.https", "expressions": {
                    "certificates": {"references": ["google_certificate_manager_certificate.https.id"]}}},
                {"address": "google_certificate_manager_certificate_map_entry.dynv6", "expressions": {
                    "certificates": {"references": ["google_certificate_manager_certificate.dynv6.id"]}}},
            ]
        }
    }
    return {"planned_values": {"root_module": {"resources": resources}},
            "resource_changes": changes, "resource_drift": [],
            "prior_state": {"values": {"root_module": {"resources": []}}},
            "configuration": configuration}


def partial_foundation_plan():
    """Model the migration: keep six legacy resources and create only the dynv6 resources."""
    plan = foundation_plan()
    retained = {
        "google_compute_global_address.https", "google_compute_ssl_policy.https",
        "google_certificate_manager_dns_authorization.https",
        "google_certificate_manager_certificate.https",
        "google_certificate_manager_certificate_map.https",
        "google_certificate_manager_certificate_map_entry.https",
    }
    resources = plan["planned_values"]["root_module"]["resources"]
    for change in plan["resource_changes"]:
        if change["address"] in retained:
            change["change"]["actions"] = ["no-op"]
    plan["prior_state"]["values"]["root_module"]["resources"] = [
        deepcopy(resource) for resource in resources if resource["address"] in retained
    ]
    return plan


def certificate_status_drift_plan():
    """Model only Google-managed Certificate Manager status changing during refresh."""
    plan = foundation_plan(("no-op",))
    plan["prior_state"]["values"]["root_module"]["resources"] = deepcopy(
        plan["planned_values"]["root_module"]["resources"]
    )
    certificate_change = next(change for change in plan["resource_changes"]
                              if change["address"] == "google_certificate_manager_certificate.https")
    before = deepcopy(certificate_change["change"]["after"])
    after = deepcopy(before)
    before["labels"] = None
    after["labels"] = {}
    before["managed"][0]["state"] = "PROVISIONING"
    after["managed"][0]["state"] = "ACTIVE"
    before["managed"][0]["authorization_attempt_info"] = [{
        "domain": LEGACY_HOST,
        "state": "FAILED",
        "failure_reason": "CONFIG",
        "details": "Expected DNS authorization CNAME is missing.",
    }]
    after["managed"][0]["authorization_attempt_info"] = [{
        "domain": LEGACY_HOST,
        "state": "AUTHORIZING",
        "failure_reason": None,
        "details": "DNS authorization is being checked.",
    }]
    before["managed"][0]["provisioning_issue"] = []
    after["managed"][0]["provisioning_issue"] = [{
        "reason": "AUTHORIZATION_ISSUE",
        "details": "",
    }]
    plan["resource_drift"] = [{
        "address": "google_certificate_manager_certificate.https",
        "mode": "managed",
        "type": "google_certificate_manager_certificate",
        "change": {"actions": ["update"], "before": before, "after": after},
    }]
    return plan


def dynv6_certificate_status_drift_plan():
    """Model Certificate Manager refreshing output-only status for the new hostname."""
    plan = foundation_plan(("no-op",))
    plan["prior_state"]["values"]["root_module"]["resources"] = deepcopy(
        plan["planned_values"]["root_module"]["resources"]
    )
    certificate_change = next(change for change in plan["resource_changes"]
                              if change["address"] == "google_certificate_manager_certificate.dynv6")
    before = deepcopy(certificate_change["change"]["after"])
    after = deepcopy(before)
    before["labels"] = None
    after["labels"] = {}
    before["managed"][0]["state"] = "PROVISIONING"
    after["managed"][0]["state"] = "ACTIVE"
    before["managed"][0]["authorization_attempt_info"] = [{
        "domain": HOST, "state": "AUTHORIZING", "failure_reason": None,
    }]
    before["managed"][0]["provisioning_issue"] = []
    after["managed"][0]["authorization_attempt_info"] = [{
        "domain": HOST, "state": "AUTHORIZED", "failure_reason": None,
    }]
    after["managed"][0]["provisioning_issue"] = [{
        "reason": "AUTHORIZATION_ISSUE",
        "details": "DNS authorization is not published yet.",
    }]
    plan["resource_drift"] = [{
        "address": "google_certificate_manager_certificate.dynv6",
        "mode": "managed",
        "type": "google_certificate_manager_certificate",
        "change": {"actions": ["update"], "before": before, "after": after},
    }]
    return plan


def certificate_map_target_drift_plan():
    """Model Certificate Manager reporting the live HTTPS Gateway attachment."""
    plan = foundation_plan(("no-op",))
    plan["prior_state"]["values"]["root_module"]["resources"] = deepcopy(
        plan["planned_values"]["root_module"]["resources"]
    )
    map_change = next(change for change in plan["resource_changes"]
                      if change["address"] == "google_certificate_manager_certificate_map.https")
    before = deepcopy(map_change["change"]["after"])
    after = deepcopy(before)
    before.update(labels=None, update_time="2026-10-20T23:13:16.622182484Z")
    after.update(
        labels={},
        update_time="2026-10-21T02:22:04.948473077Z",
        gclb_targets=[{
            "ip_configs": [{"ip_address": guard.HTTPS_STATIC_IP, "ports": [443]}],
            "target_https_proxy": TARGET_PROXY,
                "target_ssl_proxy": "",
        }],
    )
    plan["resource_drift"] = [{
        "address": "google_certificate_manager_certificate_map.https",
        "mode": "managed",
        "type": "google_certificate_manager_certificate_map",
        "change": {"actions": ["update"], "before": before, "after": after},
    }]
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
        self.assertEqual(sum(action == ["create"] for action in actions.values()), 3)
        self.assertEqual(sum(action == ["no-op"] for action in actions.values()), 6)

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

    def test_certificate_map_accepts_only_null_to_empty_label_readback(self):
        plan = foundation_plan(("no-op",))
        target = {
            "ip_configs": [{"ip_address": guard.HTTPS_STATIC_IP, "ports": [443]}],
            "target_https_proxy": TARGET_PROXY,
            "target_ssl_proxy": "",
        }
        plan["resource_drift"] = [{
            "address": "google_certificate_manager_certificate_map.https",
            "mode": "managed",
            "type": "google_certificate_manager_certificate_map",
            "change": {
                "actions": ["update"],
                "before": {"project": guard.PROJECT, "name": "helpdesk-dev-https-map",
                           "labels": None, "gclb_targets": [target]},
                "after": {"project": guard.PROJECT, "name": "helpdesk-dev-https-map",
                          "labels": {}, "gclb_targets": [target]},
            },
        }]

        guard.check_foundation(plan, HOST)

    def test_dns_authorization_accepts_only_null_to_empty_label_readback(self):
        for address in ("google_certificate_manager_dns_authorization.https",
                        "google_certificate_manager_dns_authorization.dynv6"):
            with self.subTest(address=address):
                plan = partial_foundation_plan()
                values = deepcopy(next(resource["values"] for resource in
                                       plan["planned_values"]["root_module"]["resources"]
                                       if resource["address"] == address))
                before = deepcopy(values)
                after = deepcopy(values)
                before["labels"] = None
                after["labels"] = {}
                plan["resource_drift"] = [{
                    "address": address,
                    "mode": "managed",
                    "type": "google_certificate_manager_dns_authorization",
                    "change": {"actions": ["update"], "before": before, "after": after},
                }]

                guard.check_foundation(plan, HOST)

    def test_dns_authorization_readback_rejects_any_change_beyond_null_to_empty_labels(self):
        plan = partial_foundation_plan()
        values = deepcopy(next(resource["values"] for resource in
                               plan["planned_values"]["root_module"]["resources"]
                               if resource["address"] ==
                               "google_certificate_manager_dns_authorization.https"))
        before = deepcopy(values)
        after = deepcopy(values)
        before["labels"] = None
        after["labels"] = {}
        after["domain"] = "unreviewed.example.test"
        plan["resource_drift"] = [{
            "address": "google_certificate_manager_dns_authorization.https",
            "mode": "managed",
            "type": "google_certificate_manager_dns_authorization",
            "change": {"actions": ["update"], "before": before, "after": after},
        }]

        with self.assertRaisesRegex(ValueError, "exact confirmed null-to-empty field"):
            guard.check_foundation(plan, HOST)

    def test_legacy_certificate_map_entry_accepts_exact_serving_state_readback(self):
        plan = partial_foundation_plan()
        entry = next(resource for resource in plan["planned_values"]["root_module"]["resources"]
                     if resource["address"] == "google_certificate_manager_certificate_map_entry.https")
        entry_change = next(change for change in plan["resource_changes"]
                            if change["address"] == "google_certificate_manager_certificate_map_entry.https")
        certificate_ref = entry["values"]["certificates"][0]
        canonical_ref = f"//certificatemanager.googleapis.com/{certificate_ref}"
        entry["values"]["certificates"] = [canonical_ref]
        entry_change["change"]["after"]["certificates"] = [canonical_ref]
        values = deepcopy(entry["values"])
        before = deepcopy(values)
        after = deepcopy(values)
        before.update(labels=None, state="PENDING")
        after.update(labels={}, state="ACTIVE")
        plan["resource_drift"] = [{
            "address": "google_certificate_manager_certificate_map_entry.https",
            "mode": "managed",
            "type": "google_certificate_manager_certificate_map_entry",
            "change": {"actions": ["update"], "before": before, "after": after},
        }]

        guard.check_foundation(plan, HOST)

    def test_legacy_certificate_map_entry_readback_rejects_unexpected_transitions(self):
        mutations = (
            ("state", "FAILED", "PENDING-to-ACTIVE"),
            ("labels", {"unexpected": "label"}, "labels readback"),
            ("hostname", "other.example.test", "exact retained legacy entry"),
        )
        for field, value, message in mutations:
            plan = partial_foundation_plan()
            values = deepcopy(next(resource["values"] for resource in
                                   plan["planned_values"]["root_module"]["resources"]
                                   if resource["address"] == "google_certificate_manager_certificate_map_entry.https"))
            before = deepcopy(values)
            after = deepcopy(values)
            before.update(labels=None, state="PENDING")
            after.update(labels={}, state="ACTIVE")
            if field == "hostname":
                before[field] = after[field] = value
            else:
                after[field] = value
            plan["resource_drift"] = [{
                "address": "google_certificate_manager_certificate_map_entry.https",
                "mode": "managed",
                "type": "google_certificate_manager_certificate_map_entry",
                "change": {"actions": ["update"], "before": before, "after": after},
            }]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                guard.check_foundation(plan, HOST)

    def test_legacy_map_entry_readback_does_not_allow_a_resource_update(self):
        plan = partial_foundation_plan()
        entry = next(change for change in plan["resource_changes"]
                     if change["address"] == "google_certificate_manager_certificate_map_entry.https")
        entry["change"]["actions"] = ["update"]

        with self.assertRaisesRegex(ValueError, "only an exact create or no-op is allowed"):
            guard.check_foundation(plan, HOST)

    def test_certificate_map_accepts_exact_live_gateway_target_readback(self):
        guard.check_foundation(certificate_map_target_drift_plan(), HOST)

    def test_certificate_map_readback_rejects_other_targets_or_material_changes(self):
        def mutate_ip(plan):
            plan["resource_drift"][0]["change"]["after"]["gclb_targets"][0][
                "ip_configs"][0]["ip_address"] = "34.8.56.209"

        def mutate_port(plan):
            plan["resource_drift"][0]["change"]["after"]["gclb_targets"][0][
                "ip_configs"][0]["ports"] = [80, 443]

        def mutate_proxy_project(plan):
            plan["resource_drift"][0]["change"]["after"]["gclb_targets"][0][
                "target_https_proxy"] = TARGET_PROXY.replace(guard.PROJECT_NUMBER, "999999999999")

        def mutate_proxy_gateway(plan):
            plan["resource_drift"][0]["change"]["after"]["gclb_targets"][0][
                "target_https_proxy"] = TARGET_PROXY.replace("helpdesk-dev-https", "other-gateway")

        def mutate_ssl_proxy(plan):
            plan["resource_drift"][0]["change"]["after"]["gclb_targets"][0][
                "target_ssl_proxy"] = "//compute.googleapis.com/projects/260283083469/global/targetSslProxies/unreviewed"

        def add_second_target(plan):
            plan["resource_drift"][0]["change"]["after"]["gclb_targets"].append(
                deepcopy(plan["resource_drift"][0]["change"]["after"]["gclb_targets"][0]))

        def change_map_description(plan):
            plan["resource_drift"][0]["change"]["after"]["description"] = "unreviewed"

        for name, mutate in (
            ("IP", mutate_ip), ("port", mutate_port), ("proxy project", mutate_proxy_project),
            ("proxy Gateway", mutate_proxy_gateway), ("SSL proxy", mutate_ssl_proxy),
            ("extra target", add_second_target),
            ("map description", change_map_description),
        ):
            plan = certificate_map_target_drift_plan()
            mutate(plan)
            with self.subTest(name=name), self.assertRaises(ValueError):
                guard.check_foundation(plan, HOST)

    def test_certificate_map_readback_rejects_target_removal_or_backward_timestamp(self):
        for field, value in (("gclb_targets", []), ("update_time", "2026-10-20T20:00:00Z")):
            plan = certificate_map_target_drift_plan()
            plan["resource_drift"][0]["change"]["after"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                guard.check_foundation(plan, HOST)

    def test_certificate_output_only_dns_status_and_labels_readback_are_allowed(self):
        guard.check_foundation(certificate_status_drift_plan(), HOST)

    def test_dynv6_certificate_output_only_status_readback_is_allowed_for_new_hostname(self):
        guard.check_foundation(dynv6_certificate_status_drift_plan(), HOST)

    def test_certificate_output_only_provisioning_issue_readback_is_allowed_for_both_hostnames(self):
        guard.check_foundation(certificate_status_drift_plan(), HOST)
        guard.check_foundation(dynv6_certificate_status_drift_plan(), HOST)

    def test_certificate_provisioning_issue_rejects_unknown_reason_unbounded_details_and_extra_fields(self):
        mutations = (
            ("reason", "UNRECOGNIZED", "unknown reason enum"),
            ("details", "x" * 2049, "bounded provider status string"),
            ("troubleshooting", {"issue": "CNAME_MISMATCH"}, "unreviewed field"),
        )
        for field, value, message in mutations:
            plan = certificate_status_drift_plan()
            plan["resource_drift"][0]["change"]["after"]["managed"][0][
                "provisioning_issue"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_rejects_unknown_enums(self):
        for key, value, expected in (
            ("state", "UNRECOGNIZED", "unknown state enum"),
            ("failure_reason", "UNRECOGNIZED", "unknown failure_reason enum"),
        ):
            plan = certificate_status_drift_plan()
            plan["resource_drift"][0]["change"]["after"]["managed"][0][
                "authorization_attempt_info"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, expected):
                guard.check_foundation(plan, HOST)

    def test_managed_certificate_state_readback_rejects_unknown_enum(self):
        plan = dynv6_certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["after"]["managed"][0]["state"] = "UNRECOGNIZED"

        with self.assertRaisesRegex(ValueError, "unknown state enum"):
            guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_accepts_empty_failure_reason_as_unset(self):
        plan = certificate_status_drift_plan()
        before = plan["resource_drift"][0]["change"]["before"]["managed"][0][
            "authorization_attempt_info"][0]
        after = plan["resource_drift"][0]["change"]["after"]["managed"][0][
            "authorization_attempt_info"][0]
        before["failure_reason"] = ""
        after["failure_reason"] = "CONFIG"

        guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_rejects_malformed_labels_and_unbounded_details(self):
        plan = certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["after"]["labels"] = {"unexpected": "label"}
        with self.assertRaisesRegex(ValueError, "labels readback drift"):
            guard.check_foundation(plan, HOST)

        plan = certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["after"]["managed"][0][
            "authorization_attempt_info"][0]["details"] = "x" * 2049
        with self.assertRaisesRegex(ValueError, "bounded provider status string"):
            guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_rejects_wrong_domain(self):
        plan = certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["after"]["managed"][0][
            "authorization_attempt_info"][0]["domain"] = "unrelated.example.test"
        with self.assertRaisesRegex(ValueError, "configured or unreviewed field"):
            guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_rejects_configured_field_drift(self):
        plan = certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["after"]["name"] = "different-certificate"
        with self.assertRaisesRegex(ValueError, "configured or unreviewed field"):
            guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_rejects_unreviewed_computed_fields(self):
        plan = certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["after"]["managed"][0][
            "authorization_attempt_info"][0]["troubleshooting"] = {"issue": "CNAME_MISMATCH"}
        with self.assertRaisesRegex(ValueError, "configured or unreviewed field"):
            guard.check_foundation(plan, HOST)

    def test_certificate_status_readback_requires_refresh_only_update(self):
        plan = certificate_status_drift_plan()
        plan["resource_drift"][0]["change"]["actions"] = ["delete", "create"]
        with self.assertRaisesRegex(ValueError, "refresh-only update"):
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
        self.assertIn(f'"{HOST}" -> "changed.example.test"', message)
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

    def test_migration_creates_only_new_dynv6_resources_and_preserves_legacy_resources(self):
        plan = partial_foundation_plan()
        guard.check_foundation(plan, HOST)
        actions = {change["address"]: change["change"]["actions"]
                   for change in plan["resource_changes"]}
        legacy = (
            "google_certificate_manager_dns_authorization.https",
            "google_certificate_manager_certificate.https",
            "google_certificate_manager_certificate_map.https",
            "google_certificate_manager_certificate_map_entry.https",
        )
        new = (
            "google_certificate_manager_dns_authorization.dynv6",
            "google_certificate_manager_certificate.dynv6",
            "google_certificate_manager_certificate_map_entry.dynv6",
        )
        self.assertTrue(all(actions[address] == ["no-op"] for address in legacy))
        self.assertTrue(all(actions[address] == ["create"] for address in new))

    def test_migration_rejects_legacy_hostname_reused_by_new_resources(self):
        for address, field in (
            ("google_certificate_manager_dns_authorization.dynv6", "domain"),
            ("google_certificate_manager_certificate_map_entry.dynv6", "hostname"),
        ):
            plan = partial_foundation_plan()
            planned = next(item for item in plan["planned_values"]["root_module"]["resources"]
                           if item["address"] == address)
            changed = next(item for item in plan["resource_changes"] if item["address"] == address)
            planned["values"][field] = LEGACY_HOST
            changed["change"]["after"][field] = LEGACY_HOST
            with self.subTest(address=address), self.assertRaises(ValueError):
                guard.check_foundation(plan, HOST)

    def test_migration_rejects_updates_and_deletes_of_legacy_resources(self):
        for action in (("update",), ("delete",), ("delete", "create")):
            plan = partial_foundation_plan()
            legacy = next(item for item in plan["resource_changes"]
                          if item["address"] == "google_certificate_manager_certificate.https")
            legacy["change"]["actions"] = list(action)
            with self.subTest(action=action), self.assertRaises(ValueError):
                guard.check_foundation(plan, HOST)

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

    def test_access_accepts_exact_canonical_backend_resource_reference(self):
        plan = access_plan(("no-op",))
        canonical = f"projects/{guard.PROJECT}/iap_web/compute/services/{BACKEND}"
        plan["planned_values"]["root_module"]["resources"][0]["values"]["web_backend_service"] = canonical
        plan["resource_changes"][0]["change"]["after"]["web_backend_service"] = canonical

        guard.check_access(plan, BACKEND, EMAIL)

    def test_access_rejects_canonical_reference_for_another_backend_or_project(self):
        for reference in (
            f"projects/{guard.PROJECT}/iap_web/compute/services/other-backend",
            f"projects/other-project/iap_web/compute/services/{BACKEND}",
        ):
            plan = access_plan(("no-op",))
            plan["planned_values"]["root_module"]["resources"][0]["values"]["web_backend_service"] = reference
            plan["resource_changes"][0]["change"]["after"]["web_backend_service"] = reference
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "one exact user"):
                guard.check_access(plan, BACKEND, EMAIL)

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
