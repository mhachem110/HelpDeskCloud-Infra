"""Offline policy tests for the future-only infrastructure destroy workflow."""

import shutil
import tempfile
import unittest
from pathlib import Path

from dev_destroy_guard import (
    ACCESS,
    BACKENDS,
    ENVIRONMENT,
    PROJECT_ID,
    REPOSITORY,
    STATE_BUCKET,
    validate_backend,
    validate_backup_evidence,
    validate_backup_uri,
    validate_destroy_plan,
    validate_environment,
    validate_protection_configuration,
    validate_selection,
)


FINGERPRINT = "a" * 64


def valid_environment():
    return {
        "name": ENVIRONMENT,
        "deployment_branch_policy": {"custom_branch_policies": True},
        "protection_rules": [{
            "type": "required_reviewers",
            "reviewers": [{"type": "User", "reviewer": {"id": 10}}],
            "prevent_self_review": True,
        }],
    }


def valid_branch_policy():
    return {"total_count": 1, "branch_policies": [{"name": "dev"}]}


def selection(**changes):
    values = {
        "mode": "destroy",
        "repository": REPOSITORY,
        "ref": "refs/heads/dev",
        "project_id": PROJECT_ID,
        "root": "https-access",
        "confirmation": "DESTROY dev helpdeskcloud-capstone-511905 https-access",
        "opt_in": "true",
        "reviewed_fingerprint": FINGERPRINT,
    }
    values.update(changes)
    return values


def access_destroy_plan(address=None, actions=None):
    address = address or next(iter(ACCESS))
    return {"resource_changes": [{
        "address": address,
        "mode": "managed",
        "type": ACCESS.get(address, "google_iap_web_backend_service_iam_member"),
        "change": {"actions": actions or ["delete"], "before": {"email": "private"}, "after": None},
    }]}


class DestroyGuardTests(unittest.TestCase):
    def test_plan_only_is_the_default_safe_mode_and_needs_no_destroy_gates(self):
        target = validate_selection(
            mode="plan-only", repository=REPOSITORY, ref="refs/heads/dev",
            project_id=PROJECT_ID, root="core",
        )
        self.assertEqual(target[2], BACKENDS["core"][2])

    def test_typed_confirmation_must_name_environment_project_and_root(self):
        for value in ("", "DESTROY prod helpdeskcloud-capstone-511905 https-access",
                      "DESTROY dev another-project https-access",
                      "DESTROY dev helpdeskcloud-capstone-511905 core"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_selection(**selection(confirmation=value))

    def test_destroy_requires_explicit_opt_in_and_a_prior_plan_fingerprint(self):
        for changes in ({"opt_in": "false"}, {"reviewed_fingerprint": ""},
                        {"reviewed_fingerprint": "not-a-sha256"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_selection(**selection(**changes))

    def test_wrong_project_environment_root_and_untrusted_ref_are_rejected(self):
        for changes in ({"project_id": "other-project"}, {"ref": "refs/heads/feature/x"},
                        {"root": ""}, {"root": "stage"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_selection(**selection(**changes))

    def test_only_exact_backend_bucket_and_prefix_are_accepted(self):
        self.assertTrue(validate_backend("core", STATE_BUCKET, "helpdeskcloud/dev"))
        for bucket, prefix in (("other-bucket", "helpdeskcloud/dev"),
                               (STATE_BUCKET, "helpdeskcloud/prod"),
                               (STATE_BUCKET, "helpdeskcloud/dev/extra")):
            with self.subTest(bucket=bucket, prefix=prefix), self.assertRaises(ValueError):
                validate_backend("core", bucket, prefix)

    def test_missing_or_unprotected_environment_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_environment({}, valid_branch_policy())
        wrong_environment = valid_environment()
        wrong_environment["name"] = "dev-network-apply"
        with self.assertRaises(ValueError):
            validate_environment(wrong_environment, valid_branch_policy())
        unprotected = valid_environment()
        unprotected["protection_rules"] = []
        with self.assertRaises(ValueError):
            validate_environment(unprotected, valid_branch_policy())
        missing_reviewer = valid_environment()
        missing_reviewer["protection_rules"][0]["reviewers"] = []
        with self.assertRaises(ValueError):
            validate_environment(missing_reviewer, valid_branch_policy())
        malformed_reviewer = valid_environment()
        malformed_reviewer["protection_rules"][0]["reviewers"] = [{"type": "Unknown", "id": 10}]
        with self.assertRaises(ValueError):
            validate_environment(malformed_reviewer, valid_branch_policy())

    def test_self_approval_and_non_dev_environment_branch_are_rejected(self):
        environment = valid_environment()
        environment["protection_rules"][0]["prevent_self_review"] = False
        with self.assertRaises(ValueError):
            validate_environment(environment, valid_branch_policy())
        with self.assertRaises(ValueError):
            validate_environment(valid_environment(), {
                "total_count": 1, "branch_policies": [{"name": "main"}],
            })

    def test_backup_manifest_must_be_present_scoped_and_restore_tested(self):
        metadata = {
            "generation": "1234", "size": "80", "crc32c": "abcd",
            "metadata": {
                "project_id": PROJECT_ID,
                "terraform_root": "https-access",
                "terraform_state_generation": "123",
                "recovery_test_id": "drill-2026-01",
            },
        }
        bucket = "helpdeskcloud-dr-recovery"
        uri = f"gs://{bucket}/dr-recovery/{PROJECT_ID}/https-access/manifest.json"
        self.assertEqual(validate_backup_evidence(
            uri=uri, confirmation="BACKUP VERIFIED https-access generation 1234",
            expected_bucket=bucket, expected_state_generation="123",
            root="https-access", metadata=metadata,
        ), "1234")
        for changes in (
            {"uri": "gs://other-bucket/manifest.json"},
            {"confirmation": "BACKUP VERIFIED https-access generation 9999"},
            {"metadata": {"generation": "1234", "size": "80", "crc32c": "abcd"}},
        ):
            args = {
                "uri": uri,
                "confirmation": "BACKUP VERIFIED https-access generation 1234",
                "expected_bucket": bucket,
                "expected_state_generation": "123",
                "root": "https-access",
                "metadata": metadata,
            }
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_backup_evidence(**args)

    def test_backup_uri_is_restricted_before_cloud_metadata_lookup(self):
        bucket = "helpdesk-dr-recovery"
        uri = f"gs://{bucket}/dr-recovery/{PROJECT_ID}/core/state.json"
        self.assertTrue(validate_backup_uri(uri=uri, expected_bucket=bucket, root="core"))
        for value in (
            f"gs://other-bucket/dr-recovery/{PROJECT_ID}/core/state.json",
            f"gs://{bucket}/dr-recovery/{PROJECT_ID}/https-access/state.json",
            f"gs://{bucket}/dr-recovery/{PROJECT_ID}/core/../other/state.json",
        ):
            with self.subTest(uri=value), self.assertRaises(ValueError):
                validate_backup_uri(uri=value, expected_bucket=bucket, root="core")

    def test_core_requires_a_database_backup_reference(self):
        metadata = {
            "generation": "1234", "size": "80", "crc32c": "abcd",
            "metadata": {
                "project_id": PROJECT_ID, "terraform_root": "core",
                "terraform_state_generation": "123", "recovery_test_id": "drill-1",
            },
        }
        with self.assertRaises(ValueError):
            validate_backup_evidence(
                uri=f"gs://backup/dr-recovery/{PROJECT_ID}/core/manifest.json",
                confirmation="BACKUP VERIFIED core generation 1234",
                expected_bucket="backup", expected_state_generation="123",
                root="core", metadata=metadata,
            )

    def test_backup_manifest_must_match_the_current_state_generation(self):
        metadata = {
            "generation": "1234", "size": "80", "crc32c": "abcd",
            "metadata": {
                "project_id": PROJECT_ID, "terraform_root": "https-access",
                "terraform_state_generation": "122", "recovery_test_id": "drill-1",
            },
        }
        with self.assertRaisesRegex(ValueError, "current selected state generation"):
            validate_backup_evidence(
                uri=f"gs://backup/dr-recovery/{PROJECT_ID}/https-access/manifest.json",
                confirmation="BACKUP VERIFIED https-access generation 1234",
                expected_bucket="backup", expected_state_generation="123",
                root="https-access", metadata=metadata,
            )

    def test_recovery_bucket_must_be_separate_from_state_bucket(self):
        with self.assertRaises(ValueError):
            validate_backup_uri(
                uri=f"gs://{STATE_BUCKET}/dr-recovery/{PROJECT_ID}/core/manifest.json",
                expected_bucket=STATE_BUCKET, root="core",
            )

    def test_exact_iap_grant_delete_is_reviewable(self):
        fingerprint, summary = validate_destroy_plan(access_destroy_plan(), "https-access")
        self.assertEqual(len(fingerprint), 64)
        self.assertIn("Planned deletes: 1", summary)
        self.assertIn(next(iter(ACCESS)), summary)

    def test_unknown_resource_wrong_name_and_wrong_type_are_rejected(self):
        cases = [
            access_destroy_plan("google_compute_instance.unexpected"),
            access_destroy_plan("google_iap_web_backend_service_iam_member.other"),
        ]
        wrong_type = access_destroy_plan()
        wrong_type["resource_changes"][0]["type"] = "google_project_iam_member"
        cases.append(wrong_type)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_destroy_plan(plan, "https-access")

    def test_updates_replacements_and_create_actions_are_rejected(self):
        for actions in (["update"], ["delete", "create"], ["create"]):
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                validate_destroy_plan(access_destroy_plan(actions=actions), "https-access")

    def test_protected_sql_and_certificates_cannot_be_destroyed(self):
        for root, address in (
            ("core", "google_sql_database_instance.dev_postgres[0]"),
            ("https-foundation", next(iter(__import__("dev_https_guard").FOUNDATION))),
        ):
            from dev_destroy_guard import RESOURCE_INVENTORY
            plan = {"resource_changes": [{
                "address": address, "mode": "managed",
                "type": RESOURCE_INVENTORY[root][address],
                "change": {"actions": ["delete"], "before": {}, "after": None},
            }]}
            with self.subTest(root=root), self.assertRaises(ValueError):
                validate_destroy_plan(plan, root)

    def test_live_protection_flags_are_present_in_checked_in_configuration(self):
        root = Path(__file__).resolve().parents[1] / "terraform"
        self.assertTrue(validate_protection_configuration("core", root))
        self.assertTrue(validate_protection_configuration("https-foundation", root))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cloud-sql.tf"
            path.write_text('resource "google_sql_database_instance" "dev_postgres" {\n'
                            '  deletion_protection = true\n'
                            '  lifecycle { prevent_destroy = false }\n}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_protection_configuration("core", directory)

    def test_attempts_to_remove_sql_or_certificate_deletion_protection_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sql = root / "cloud-sql.tf"
            sql.write_text(
                'resource "google_sql_database_instance" "dev_postgres" {\n'
                '  deletion_protection = false\n'
                '  deletion_protection_enabled = false\n'
                '  lifecycle { prevent_destroy = true }\n}\n'
                'resource "google_sql_database" "dev_helpdesk" {\n'
                '  lifecycle { prevent_destroy = true }\n}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deletion_protection"):
                validate_protection_configuration("core", root)

            source_root = Path(__file__).resolve().parents[1] / "terraform" / "https-foundation"
            https_root = root / "https"
            shutil.copytree(source_root, https_root)
            cert_source = https_root / "https.tf"
            cert_source.write_text(
                cert_source.read_text(encoding="utf-8").replace(
                    "prevent_destroy = true", "prevent_destroy = false", 1
                ), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_protection_configuration("https-foundation", https_root)


if __name__ == "__main__":
    unittest.main()
