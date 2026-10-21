"""Keep runtime/private files ignored without hiding controlled source fixtures."""
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GitIgnoreTests(unittest.TestCase):
    def assert_ignored(self, paths, expected):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--stdin", "-z"],
            input="\0".join(paths) + "\0",
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        ignored = set(result.stdout.split("\0")) - {""}
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(path in ignored, expected)

    def test_runtime_roots_remain_ignored(self):
        self.assert_ignored([
            "data/datasets/samples.csv",
            "data/campaigns/trials.json",
            "data/syringe_programs/registry.json",
            "logs/devices/serial.log",
            "reports/samples.csv",
            "reports/run.json",
            "output/experiment_logs/run.json",
            "output/yaml_runs/recovery.lock",
            "output/desktop/release/Heat-Setup.exe",
        ], True)

    def test_controlled_fixtures_and_manufacturer_sources_are_visible(self):
        self.assert_ignored([
            "tests/fixtures/data/samples.csv",
            "tests/fixtures/logs/serial.log",
            "tests/fixtures/reports/sample.json",
            "tests/fixtures/output/run.json",
            "tests/fixtures/characterization.xlsx",
            "tests/fixtures/legacy.xls",
            "docs/device_materials/vendor_protocol.xlsx",
            "docs/device_materials/vendor_protocol.xls",
            "docs/device_materials/registers.csv",
        ], False)

    def test_private_configurations_are_ignored(self):
        self.assert_ignored([
            ".env",
            ".env.production",
            "frontend/.env.local",
            "config/local_config.yaml",
            "config/local_config.yml",
        ], True)

    def test_examples_and_packaging_source_are_visible(self):
        self.assert_ignored([
            ".env.example",
            ".env.production.example",
            "frontend/.env.example",
            "config/local_config.example.yaml",
            "config/system_config.yaml",
            "packaging/desktop/heat.spec",
        ], False)
        self.assert_ignored([
            "packaging/desktop/generated.spec",
            "frontend/node_modules/dependency/package.json",
            "src/web/static/index.html",
        ], True)


if __name__ == "__main__":
    unittest.main()
