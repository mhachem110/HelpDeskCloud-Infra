import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dev_https_config", ROOT / "scripts/dev_https_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)


class DevHttpsConfigTests(unittest.TestCase):
    def test_tracked_dev_hostname_is_valid(self):
        self.assertEqual(
            config.load_hostname(ROOT / "terraform/https-foundation/environments/dev.tfvars"),
            "helpdeskcloud.chickenkiller.com",
        )

    def test_missing_or_duplicate_hostname_is_rejected(self):
        for contents in ("", 'hostname = "one.example.test"\nhostname = "two.example.test"\n'):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "dev.tfvars"
                path.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaisesRegex(ValueError, "exactly one"):
                    config.load_hostname(path)

    def test_bad_or_unquoted_hostname_is_rejected(self):
        for contents in ('hostname = var.hostname\n', 'hostname = "UPPER.example.test"\n',
                         'hostname = "*.example.test"\n'):
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "dev.tfvars"
                path.write_text(contents, encoding="utf-8")
                with self.subTest(contents=contents), self.assertRaises(ValueError):
                    config.load_hostname(path)


if __name__ == "__main__":
    unittest.main()
