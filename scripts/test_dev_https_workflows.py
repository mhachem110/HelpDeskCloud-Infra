import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_workflow(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class DevHttpsWorkflowTests(unittest.TestCase):
    def test_existing_dev_workflow_defaults_to_core_and_keeps_https_opt_in(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-plan.yml")
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(triggers["workflow_dispatch"]["inputs"]["component"]["default"], "core")
        self.assertEqual(workflow["jobs"]["dev-plan"]["if"].split("&&")[-1].strip(), "inputs.component == 'core'")
        edge = workflow["jobs"]["https-plan"]
        self.assertIn("inputs.component != 'core'", edge["if"])
        self.assertIn("providers/github-infra-dev", str(edge["steps"]))
        self.assertIn("dev_https_guard.py check-foundation", str(edge["steps"]))
        self.assertIn("dev_https_guard.py check-access", str(edge["steps"]))

    def test_apply_uses_existing_protected_dev_environment_and_a_fresh_checked_plan(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-apply.yml")
        triggers = workflow.get("on", workflow.get(True))
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["component"]["default"], "core")
        self.assertEqual(workflow["jobs"]["approved-https-apply"]["environment"], "dev-network-apply")
        steps = workflow["jobs"]["approved-https-apply"]["steps"]
        guard = next(index for index, step in enumerate(steps)
                     if "dev_https_guard.py check-foundation" in step.get("run", "") or
                     "dev_https_guard.py check-access" in step.get("run", ""))
        apply = next(index for index, step in enumerate(steps)
                     if "terraform -chdir=\"$COMPONENT\" apply" in step.get("run", ""))
        self.assertLess(guard, apply)
        self.assertIn("dev-https-${COMPONENT}-apply.tfplan", steps[apply]["run"])
        self.assertIn("required_reviewers", str(steps))
        self.assertIn("deployment_branch_policy", str(steps))
        self.assertNotIn("gcloud dns record-sets transaction", str(workflow))

    def test_https_terraform_roots_use_distinct_retained_state_prefixes(self):
        foundation = (ROOT / "terraform/https-foundation/environments/dev.gcs.tfbackend").read_text()
        access = (ROOT / "terraform/https-access/environments/dev.gcs.tfbackend").read_text()
        self.assertIn('prefix = "helpdeskcloud/dev-https"', foundation)
        self.assertIn('prefix = "helpdeskcloud/dev-https-access"', access)
        self.assertNotEqual(foundation, access)


if __name__ == "__main__":
    unittest.main()
