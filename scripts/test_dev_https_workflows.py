import unittest
from pathlib import Path
import importlib.util

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_SPEC = importlib.util.spec_from_file_location("dev_https_config", ROOT / "scripts/dev_https_config.py")
CONFIG = importlib.util.module_from_spec(CONFIG_SPEC)
CONFIG_SPEC.loader.exec_module(CONFIG)


def load_workflow(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class DevHttpsWorkflowTests(unittest.TestCase):
    def test_plan_exposes_only_the_isolated_target_selector(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-plan.yml")
        triggers = workflow.get("on", workflow.get(True))
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"target"})
        self.assertEqual(inputs["target"]["default"], "core")
        self.assertEqual(inputs["target"]["options"], ["core", "https-foundation", "https-access"])
        self.assertEqual(workflow["jobs"]["dev-plan"]["if"].split("&&")[-1].strip(), "inputs.target == 'core'")
        edge = workflow["jobs"]["https-plan"]
        self.assertIn("inputs.target != 'core'", edge["if"])
        self.assertIn("providers/github-infra-dev", str(edge["steps"]))
        self.assertIn("dev_https_guard.py check-foundation", str(edge["steps"]))
        self.assertIn("dev_https_guard.py check-access", str(edge["steps"]))
        self.assertIn("vars.DEV_IAP_ALLOWED_EMAIL", str(edge))
        self.assertNotIn("inputs.https_hostname", str(workflow))
        self.assertNotIn("inputs.iap_backend_service_name", str(workflow))
        self.assertNotIn("inputs.iap_allowed_email", str(workflow))

    def test_apply_exposes_only_target_and_preserves_the_protected_environment(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-apply.yml")
        triggers = workflow.get("on", workflow.get(True))
        inputs = triggers["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"target"})
        self.assertEqual(inputs["target"]["default"], "core")
        self.assertNotIn("operation", inputs)
        self.assertNotIn("acknowledged_drift_fingerprint", inputs)
        self.assertEqual(workflow["jobs"]["approved-https-apply"]["environment"], "dev-network-apply")
        steps = workflow["jobs"]["approved-https-apply"]["steps"]
        plan = next(index for index, step in enumerate(steps)
                    if step.get("id") == "inspect-https")
        apply = next(index for index, step in enumerate(steps)
                     if "terraform -chdir=\"$COMPONENT\" apply" in step.get("run", ""))
        self.assertLess(plan, apply)
        self.assertIn("plan_file=\"$RUNNER_TEMP/dev-${COMPONENT}-apply.tfplan\"", steps[plan]["run"])
        self.assertIn("steps.inspect-https.outputs.plan_file", steps[apply]["env"]["PLAN_FILE"])
        self.assertEqual(steps[apply]["run"].count("$PLAN_FILE"), 1)
        self.assertNotIn("dev-https-https-foundation-apply.tfplan", str(workflow))
        self.assertNotIn("dev-https-${COMPONENT}-apply.tfplan", str(workflow))
        environment_checks = workflow["jobs"]["approved-https-apply"]["steps"]
        self.assertIn("required_reviewers", str(environment_checks))
        self.assertIn("deployment_branch_policy", str(environment_checks))
        self.assertNotIn("gcloud dns record-sets transaction", str(workflow))
        self.assertNotIn("inputs.operation", str(workflow))
        self.assertNotIn("inputs.acknowledged_drift_fingerprint", str(workflow))

    def test_saved_plan_name_is_exact_for_each_https_state(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-apply.yml")
        steps = workflow["jobs"]["approved-https-apply"]["steps"]
        plan_step = next(step for step in steps if step.get("id") == "inspect-https")
        apply_step = next(step for step in steps if "terraform -chdir=\"$COMPONENT\" apply" in step.get("run", ""))
        self.assertIn('plan_file="$RUNNER_TEMP/dev-${COMPONENT}-apply.tfplan"', plan_step["run"])
        self.assertIn('"$PLAN_FILE"', apply_step["run"])
        path_template = "dev-${COMPONENT}-apply.tfplan"
        for component in ("https-foundation", "https-access"):
            self.assertEqual(path_template.replace("${COMPONENT}", component),
                             f"dev-{component}-apply.tfplan")
        self.assertIn('echo "plan_file=$plan_file" >> "$GITHUB_OUTPUT"', plan_step["run"])
        self.assertIn("-var-file=environments/dev.tfvars", plan_step["run"])

        review_step = next(step for step in workflow["jobs"]["review-https-plan"]["steps"]
                           if step.get("name") == "Display and check review plan")
        self.assertIn("-var-file=environments/dev.tfvars", review_step["run"])

    def test_core_drift_is_reviewed_against_the_protected_apply_and_still_fails_closed(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-apply.yml")
        review = workflow["jobs"]["review-plan"]
        apply = workflow["jobs"]["approved-apply"]
        review_text = str(review["steps"])
        apply_text = str(apply["steps"])
        self.assertIn("review-drift", review_text)
        self.assertIn("REVIEWED_DRIFT_FINGERPRINT", str(apply["env"]))
        self.assertIn("current_fingerprint", apply_text)
        self.assertIn("REVIEWED_DRIFT_FINGERPRINT", apply_text)
        self.assertIn("--acknowledged-drift", apply_text)
        self.assertEqual(apply["environment"], "dev-network-apply")
        self.assertNotIn("inputs.acknowledged_drift_fingerprint", str(workflow))

    def test_https_targets_report_missing_access_configuration_without_applying(self):
        workflow = load_workflow(ROOT / ".github/workflows/terraform-dev-plan.yml")
        edge = workflow["jobs"]["https-plan"]
        steps = edge["steps"]
        prepare = next(step for step in steps if step.get("id") == "prepare-target")
        init = next(step for step in steps if step.get("name") == "Initialize the selected isolated HTTPS state")
        self.assertIn("vars.DEV_IAP_ALLOWED_EMAIL", str(prepare))
        self.assertIn("prepare_dev_https_target.sh", prepare["run"])
        self.assertIn("steps.prepare-target.outputs.ready == 'true'", init["if"])
        self.assertIn("DEV_IAP_ALLOWED_EMAIL", (ROOT / "scripts/prepare_dev_https_access.sh").read_text())
        self.assertIn("--dns-endpoint", (ROOT / "scripts/prepare_dev_https_access.sh").read_text())
        self.assertIn("networking.gke.io/backend-services", (ROOT / "scripts/dev_https_backend.py").read_text())
        apply = load_workflow(ROOT / ".github/workflows/terraform-dev-apply.yml")
        self.assertIn("needs.review-https-plan.outputs.ready == 'true'", apply["jobs"]["approved-https-apply"]["if"])

    def test_https_terraform_roots_use_distinct_retained_state_prefixes(self):
        foundation = (ROOT / "terraform/https-foundation/environments/dev.gcs.tfbackend").read_text()
        access = (ROOT / "terraform/https-access/environments/dev.gcs.tfbackend").read_text()
        self.assertIn('prefix = "helpdeskcloud/dev-https"', foundation)
        self.assertIn('prefix = "helpdeskcloud/dev-https-access"', access)
        self.assertNotEqual(foundation, access)
        self.assertEqual(
            "helpdeskcloud.chickenkiller.com",
            CONFIG.load_hostname(ROOT / "terraform/https-foundation/environments/dev.tfvars"),
        )


if __name__ == "__main__":
    unittest.main()
