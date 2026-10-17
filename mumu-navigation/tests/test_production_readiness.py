import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from production_readiness import collect_diagnostics


class ProductionReadinessTests(unittest.TestCase):
    def test_missing_adb_is_not_ready(self):
        with patch.dict(os.environ, {"ADB_PATH": ""}, clear=False), patch(
            "production_readiness.shutil.which", return_value=None
        ):
            report = collect_diagnostics(runner=Mock())
        self.assertFalse(report["ready"])
        self.assertEqual(report["checks"][0]["name"], "adb")

    def test_online_device_is_ready(self):
        def runner(command, **kwargs):
            if command[-1] == "version":
                return subprocess.CompletedProcess(command, 0, "Android Debug Bridge version 1.0.41\n", "")
            return subprocess.CompletedProcess(command, 0, "List of devices attached\nemulator-5554\tdevice\n", "")

        report = collect_diagnostics("adb", runner=runner)
        self.assertTrue(report["ready"])
        self.assertIn("1 online", report["checks"][1]["summary"])

    def test_unauthorized_device_is_not_ready(self):
        def runner(command, **kwargs):
            if command[-1] == "version":
                return subprocess.CompletedProcess(command, 0, "ADB version", "")
            return subprocess.CompletedProcess(command, 0, "List of devices attached\nemulator-5554\tunauthorized\n", "")

        report = collect_diagnostics("adb", runner=runner)
        self.assertFalse(report["ready"])
        self.assertIn("1 unauthorized", report["checks"][1]["summary"])

    def test_timeout_fails_closed(self):
        def runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, 5)

        report = collect_diagnostics("adb", runner=runner)
        self.assertFalse(report["ready"])
        self.assertIn("adb_execution", [check["name"] for check in report["checks"]])


if __name__ == "__main__":
    unittest.main()
