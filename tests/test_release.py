from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from app import APP_VERSION
from release_self_test import run_self_test


class ReleaseTests(unittest.TestCase):
    def test_windows_metadata_matches_app_version(self):
        metadata = (Path(__file__).resolve().parents[1] / "version_info.txt").read_text(encoding="utf-8")
        self.assertRegex(APP_VERSION, r"^\d+\.\d+\.\d+$")
        for field in ("FileVersion", "ProductVersion"):
            self.assertIn(f"StringStruct('{field}', '{APP_VERSION}')", metadata)
        expected = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
        for field in ("filevers", "prodvers"):
            match = re.search(field + r"=\(([^)]+)\)", metadata)
            actual = tuple(int(part.strip()) for part in match.group(1).split(","))
            self.assertEqual(actual, expected)

    def test_success_report_is_written(self):
        with tempfile.TemporaryDirectory() as directory, patch("release_self_test.run_checks", return_value={"synthetic": True}):
            output = Path(directory) / "self-test.json"
            self.assertEqual(run_self_test(str(output), APP_VERSION), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(result["ok"])
            self.assertEqual(result["version"], APP_VERSION)
            self.assertEqual(result["checks"], {"synthetic": True})
            self.assertFalse(result["frozen"])

    def test_failed_checks_return_nonzero_and_preserve_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory, patch("release_self_test.run_checks", side_effect=RuntimeError("missing model")):
            output = Path(directory) / "self-test.json"
            self.assertEqual(run_self_test(str(output), APP_VERSION), 1)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(result["ok"])
            self.assertIn("missing model", result["error"])


if __name__ == "__main__":
    unittest.main()
