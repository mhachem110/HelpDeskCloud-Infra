import importlib.util
import io
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock


SCRIPT = Path(__file__).with_name("dev_https_api_preflight.py")
spec = importlib.util.spec_from_file_location("dev_https_api_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def results(*states):
    return [subprocess.CompletedProcess([], 0, f"{state}\n", "") if state is not None else
            subprocess.CompletedProcess([], 1, "", "permission denied") for state in states]


class DevHttpsApiPreflightTests(unittest.TestCase):
    def test_api_probe_is_read_only_and_scoped_to_the_two_required_services(self):
        runner = Mock(side_effect=results("ENABLED", "ENABLED"))
        self.assertEqual(preflight.get_states(runner), {
            "certificatemanager.googleapis.com": "ENABLED",
            "iap.googleapis.com": "ENABLED",
        })
        self.assertEqual(runner.call_count, 2)
        for call, service in zip(runner.call_args_list, preflight.SERVICES):
            self.assertEqual(call.args[0], [
                "gcloud", "services", "describe", service,
                "--project=helpdeskcloud-capstone-511905", "--format=value(state)",
            ])

    def test_plan_reports_disabled_apis_without_stopping_read_only_diagnostics(self):
        out, err = io.StringIO(), io.StringIO()
        runner = Mock(side_effect=results("DISABLED", "DISABLED"))
        self.assertEqual(preflight.main([], runner, out, err), 0)
        self.assertIn("certificatemanager.googleapis.com: DISABLED", out.getvalue())
        self.assertIn("iap.googleapis.com: DISABLED", out.getvalue())
        self.assertIn("gcloud services enable", err.getvalue())

    def test_apply_fails_closed_when_an_api_is_disabled_or_unreadable(self):
        for states in (("DISABLED", "ENABLED"), (None, "ENABLED")):
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(states=states):
                self.assertEqual(preflight.main(["--require-enabled"], Mock(side_effect=results(*states)), out, err), 1)
                self.assertIn("HTTPS Apply requires", err.getvalue())
                self.assertIn("--project=helpdeskcloud-capstone-511905", err.getvalue())


if __name__ == "__main__":
    unittest.main()
