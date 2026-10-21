"""Static safety checks for the manually operated Terraform workflows."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow(name):
    value = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return value.get("on", value.get(True)), value


def run_text(job):
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


class TerraformOpsWorkflowTests(unittest.TestCase):
    def test_destroy_is_manual_plan_first_and_separately_protected(self):
        triggers, config = workflow("terraform-dev-destroy.yml")
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertEqual(triggers["workflow_dispatch"]["inputs"]["mode"]["default"], "plan-only")
        self.assertEqual(config["concurrency"]["group"], "terraform-dev-network-apply")
        self.assertEqual(config["jobs"]["destroy"]["environment"], "dev-infra-destroy")
        self.assertIn("inputs.mode == 'destroy'", config["jobs"]["destroy"]["if"])
        self.assertIn("needs.plan.outputs.fingerprint", str(config["jobs"]["destroy"]["env"]))
        self.assertIn("--mode destroy", run_text(config["jobs"]["destroy"]))
        self.assertIn(" apply -input=false", run_text(config["jobs"]["destroy"]))
        text = (WORKFLOWS / "terraform-dev-destroy.yml").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?i)\b-auto-approve\b|\b-target\s*[= ]")
        self.assertNotIn("upload-artifact", text)

    def test_destroy_inventory_preserves_protected_roots_and_uses_access_variables(self):
        _, config = workflow("terraform-dev-destroy.yml")
        jobs = config["jobs"]
        protected = jobs["plan"]["steps"]
        inventory = next(step for step in protected
                         if step.get("name") == "Create inventory-only preview for protected roots")
        access_plan = next(step for step in protected
                           if step.get("name") == "Create a local Identity & Access destroy plan")
        self.assertIn("inputs.root == 'core' || inputs.root == 'https-foundation'", inventory["if"])
        self.assertIn("inputs.root == 'https-access'", access_plan["if"])
        self.assertIn("state pull >", Path(ROOT / "scripts/capture_terraform_state_evidence.sh").read_text())
        self.assertIn("--state-generation", inventory["run"])
        self.assertIn('-var="backend_service_name=$BACKEND_SERVICE_NAME"', access_plan["run"])
        self.assertIn('-var="allowed_email=$ALLOWED_EMAIL"', access_plan["run"])
        self.assertNotIn("-var-file=environments/dev.tfvars", (WORKFLOWS / "terraform-dev-destroy.yml").read_text())
        self.assertIn("This root contains retained deletion protections",
                      Path(ROOT / "scripts/dev_destroy_guard.py").read_text())

    def test_plan_and_apply_show_friendly_names_for_existing_root_ids(self):
        for name in ("terraform-dev-plan.yml", "terraform-dev-apply.yml"):
            _, config = workflow(name)
            triggers = config.get("on", config.get(True))
            description = triggers["workflow_dispatch"]["inputs"]["target"]["description"]
            for label in ("Platform Infrastructure (core)",
                          "HTTPS & Certificates (https-foundation)",
                          "Identity & Access (https-access)"):
                self.assertIn(label, description)
            text = (WORKFLOWS / name).read_text(encoding="utf-8")
            self.assertIn("terraform_target_summary.sh", text)

    def test_drift_is_scheduled_or_manual_and_has_no_mutating_command(self):
        triggers, config = workflow("terraform-drift.yml")
        self.assertEqual(set(triggers), {"workflow_dispatch", "schedule"})
        self.assertEqual(triggers["schedule"][0]["cron"], "0 14 * * 1")
        self.assertEqual(config["jobs"]["drift"]["strategy"]["matrix"],
                         "${{ fromJSON(needs.preflight.outputs.matrix) }}")
        self.assertIn('matrix={"root":["core","https-foundation","https-access"]}',
                      run_text(config["jobs"]["preflight"]))
        text = run_text(config["jobs"]["drift"])
        self.assertIn("-detailed-exitcode", text)
        self.assertIn("terraform_plan_summary.py", text)
        self.assertNotRegex(text, r"(?im)^\s*(terraform\s+(?:apply|destroy)|kubectl\s+(?:apply|delete|patch)|helm\s+(?:upgrade|install|uninstall))\b")

    def test_state_health_is_manual_and_metadata_only(self):
        triggers, config = workflow("terraform-state-health.yml")
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        text = run_text(config["jobs"]["state-health"])
        self.assertIn("gcloud storage buckets describe", text)
        self.assertIn("gcloud storage ls --all-versions --json", text)
        self.assertIn("terraform_state_health.py inspect", text)
        self.assertNotRegex(text, r"(?i)terraform\s+(?:init|state\s+pull)|gcloud\s+storage\s+(?:cp|rsync|buckets\s+(?:update|create))|set-iam-policy")

    def test_apply_uses_shared_environment_check_before_each_oidc_auth(self):
        _, config = workflow("terraform-dev-apply.yml")
        protected_jobs = [job for job in config["jobs"].values()
                          if job.get("environment") == "dev-network-apply"]
        self.assertEqual(len(protected_jobs), 2)
        for job in protected_jobs:
            steps = job["steps"]
            check = next(i for i, step in enumerate(steps)
                         if step.get("run") == "bash ../scripts/verify_dev_environment.sh")
            auth = next(i for i, step in enumerate(steps)
                        if step.get("uses", "").startswith("google-github-actions/auth@"))
            self.assertLess(check, auth)

    def test_all_workflow_yaml_files_parse(self):
        for path in WORKFLOWS.glob("*.yml"):
            with self.subTest(path=path.name):
                yaml.safe_load(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
