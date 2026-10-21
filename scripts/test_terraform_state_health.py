"""Offline tests for exact Terraform state-backend and recovery metadata checks."""

import tempfile
import unittest
from pathlib import Path

from terraform_state_health import (
    ROOTS,
    STATE_BUCKET,
    validate_backend_files,
    validate_bucket_metadata,
)


def valid_bucket():
    return {
        "name": STATE_BUCKET,
        "versioning": {"enabled": True},
        "iamConfiguration": {
            "uniformBucketLevelAccess": {"enabled": True},
            "publicAccessPrevention": "enforced",
        },
        "retentionPolicy": {"retentionPeriod": "2592000"},
        "lifecycle": {"rule": []},
    }


def valid_versions():
    return {
        root: [
            {"name": f"{prefix}/default.tfstate", "generation": "101", "size": "200", "crc32c": "x"},
            {"name": f"{prefix}/default.tfstate", "generation": "102", "size": "210", "crc32c": "y"},
        ]
        for root, (_, prefix) in ROOTS.items()
    }


def valid_current_objects():
    return {
        root: {"name": f"{prefix}/default.tfstate", "generation": "102"}
        for root, (_, prefix) in ROOTS.items()
    }


class TerraformStateHealthTests(unittest.TestCase):
    def test_all_checked_in_dev_backends_use_exact_bucket_and_unique_prefixes(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue(validate_backend_files(root))

    def test_backend_file_with_unknown_project_prefix_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, (relative, prefix) in ROOTS.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f'bucket = "{STATE_BUCKET}"\nprefix = "{prefix}"\n', encoding="utf-8")
            path = root / ROOTS["https-access"][0]
            path.write_text(f'bucket = "{STATE_BUCKET}"\nprefix = "helpdeskcloud/prod"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_backend_files(root)

    def test_versioning_access_and_two_generations_are_reported_without_state_contents(self):
        report = validate_bucket_metadata(valid_bucket(), valid_versions(), valid_current_objects())
        self.assertIn("Object versioning: enabled", report)
        for root in ROOTS:
            self.assertIn(f"`{root}`", report)
        self.assertIn("Only object metadata was listed", report)
        self.assertNotIn("private", report)

    def test_missing_versioning_is_reported_as_unsafe(self):
        bucket = valid_bucket()
        bucket["versioning"]["enabled"] = False
        with self.assertRaises(ValueError):
            validate_bucket_metadata(bucket, valid_versions())

    def test_missing_uniform_access_or_public_access_prevention_is_rejected(self):
        for key, value in (("uniformBucketLevelAccess", {"enabled": False}),
                           ("publicAccessPrevention", "inherited_disabled")):
            bucket = valid_bucket()
            bucket["iamConfiguration"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_bucket_metadata(bucket, valid_versions(), valid_current_objects())

    def test_lifecycle_delete_rule_must_not_cover_state_prefixes(self):
        bucket = valid_bucket()
        bucket["lifecycle"]["rule"] = [{
            "action": {"type": "Delete"},
            "condition": {"matchesPrefix": ["helpdeskcloud/"]},
        }]
        with self.assertRaises(ValueError):
            validate_bucket_metadata(bucket, valid_versions(), valid_current_objects())

    def test_unrelated_lifecycle_rule_is_reported_and_retained(self):
        bucket = valid_bucket()
        bucket["lifecycle"]["rule"] = [{
            "action": {"type": "Delete"},
            "condition": {"matchesPrefix": ["unrelated-cache/"]},
        }]
        report = validate_bucket_metadata(bucket, valid_versions(), valid_current_objects())
        self.assertIn("1 lifecycle rule(s)", report)

    def test_missing_state_history_or_unexpected_object_name_is_rejected(self):
        versions = valid_versions()
        versions["core"] = versions["core"][:1]
        with self.assertRaises(ValueError):
            validate_bucket_metadata(valid_bucket(), versions, valid_current_objects())

    def test_missing_or_wrong_current_state_metadata_is_rejected(self):
        current = valid_current_objects()
        current["https-access"] = {"name": "helpdeskcloud/prod/default.tfstate", "generation": "102"}
        with self.assertRaises(ValueError):
            validate_bucket_metadata(valid_bucket(), valid_versions(), current)
        versions = valid_versions()
        versions["core"][0]["name"] = "helpdeskcloud/prod/default.tfstate"
        with self.assertRaises(ValueError):
            validate_bucket_metadata(valid_bucket(), versions, valid_current_objects())


if __name__ == "__main__":
    unittest.main()
