"""Sanitized Terraform plan summary regression tests."""

import unittest

from terraform_plan_summary import summarize


class TerraformPlanSummaryTests(unittest.TestCase):
    def test_summary_includes_only_resource_addresses_and_actions(self):
        plan = {
            "resource_changes": [
                {"address": "google_compute_network.dev", "mode": "managed", "type": "google_compute_network",
                 "change": {"actions": ["update"], "before": {"secret": "before-secret"},
                            "after": {"secret": "after-secret"}}},
                {"address": "google_sql_database.dev", "mode": "managed", "type": "google_sql_database",
                 "change": {"actions": ["delete", "create"], "after_sensitive": {"password": True}}},
                {"address": "data.google_client_config.current", "mode": "data", "type": "google_client_config",
                 "change": {"actions": ["no-op"], "after": {"access_token": "never-print"}}},
            ]
        }
        output = summarize(plan, "core")
        self.assertIn("google_compute_network.dev", output)
        self.assertIn("update", output)
        self.assertIn("delete, create", output)
        self.assertNotIn("before-secret", output)
        self.assertNotIn("after-secret", output)
        self.assertNotIn("never-print", output)
        self.assertNotIn("access_token", output)

    def test_malformed_plan_inventory_fails_closed(self):
        for plan in ({}, {"resource_changes": [{"change": {"actions": []}}]}):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                summarize(plan, "core")


if __name__ == "__main__":
    unittest.main()
