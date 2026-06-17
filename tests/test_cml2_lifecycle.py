# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-04
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py, src/topogen/cml2.py
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main, topogen.cml2.write_cml2_lifecycle_scaffold
#
# Purpose: Verify TG-150 CML2 Terraform lifecycle scaffold output and layout.
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.cml2 import write_cml2_lifecycle_scaffold  # pylint: disable=wrong-import-position
from topogen.main import main  # pylint: disable=wrong-import-position


class TestCml2LifecycleScaffold(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def test_writer_emits_pinned_secret_free_lifecycle_scaffold(self):
        with tempfile.TemporaryDirectory() as tmp:
            cml2_root = Path(tmp) / "lab" / "cml2"
            written = write_cml2_lifecycle_scaffold(
                cml2_root,
                topology_file="lab.yaml",
                overwrite=True,
            )

            self.assertEqual(
                [path.name for path in written],
                ["main.tf", "versions.tf", "variables.tf", "outputs.tf", ".gitignore"],
            )
            main_tf = (cml2_root / "main.tf").read_text(encoding="utf-8")
            versions_tf = (cml2_root / "versions.tf").read_text(encoding="utf-8")
            variables_tf = (cml2_root / "variables.tf").read_text(encoding="utf-8")
            outputs_tf = (cml2_root / "outputs.tf").read_text(encoding="utf-8")

            self.assertIn('resource "cml2_lifecycle" "lab"', main_tf)
            self.assertIn("topology = file(var.topology_file)", main_tf)
            self.assertIn("state    = var.lab_state", main_tf)
            self.assertIn("wait     = var.wait", main_tf)
            self.assertIn('source  = "CiscoDevNet/cml2"', versions_tf)
            self.assertIn('version = "~> 0.8"', versions_tf)
            self.assertIn('default     = "../lab.yaml"', variables_tf)
            self.assertIn('variable "address"', variables_tf)
            self.assertIn('variable "username"', variables_tf)
            self.assertIn('variable "password"', variables_tf)
            self.assertIn('variable "token"', variables_tf)
            self.assertIn("sensitive   = true", variables_tf)
            self.assertIn('output "lab_id"', outputs_tf)
            self.assertIn('output "nodes"', outputs_tf)
            self.assertEqual(
                (cml2_root / ".gitignore").read_text(encoding="utf-8").splitlines(),
                [".terraform/", "*.tfstate*", "terraform.tfvars"],
            )

            for content in (main_tf, versions_tf, variables_tf, outputs_tf):
                self.assertNotIn(str(Path(tmp)), content)
                self.assertNotIn("10.", content)
                self.assertNotIn("172.", content)
                self.assertNotIn("192.168.", content)
                self.assertNotIn("admin", content.lower())
                self.assertNotIn("cisco123", content.lower())

    def test_cml2_cli_writes_lifecycle_directory_without_nac(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "cml2-simple.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--terraform-cml2",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "cml2-simple"
            cml_yaml = lab_root / "cml2-simple.yaml"
            cml2_root = lab_root / "cml2"
            self.assertTrue(cml_yaml.exists())
            self.assertTrue((cml2_root / "main.tf").exists())
            self.assertTrue((cml2_root / "variables.tf").exists())
            self.assertTrue((cml2_root / "outputs.tf").exists())
            self.assertFalse((lab_root / "nac").exists())
            self.assertFalse(out_file.exists())

            variables_tf = (cml2_root / "variables.tf").read_text(encoding="utf-8")
            self.assertIn('default     = "../cml2-simple.yaml"', variables_tf)

    def test_cml2_and_nac_outputs_are_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "cml2-nac.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--terraform-cml2",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "cml2-nac"
            self.assertTrue((lab_root / "cml2-nac.yaml").exists())
            self.assertTrue((lab_root / "nac" / "nac.yaml").exists())
            self.assertTrue((lab_root / "nac" / "main.tf").exists())
            self.assertTrue((lab_root / "cml2" / "main.tf").exists())
            self.assertTrue((lab_root / "cml2" / "variables.tf").exists())
            self.assertTrue((lab_root / "cml2" / "outputs.tf").exists())
            self.assertFalse((lab_root / "main.tf").exists())
            self.assertFalse((lab_root / "nac" / "outputs.tf").exists())

            cml2_main = (lab_root / "cml2" / "main.tf").read_text(encoding="utf-8")
            nac_main = (lab_root / "nac" / "main.tf").read_text(encoding="utf-8")
            self.assertIn('resource "cml2_lifecycle" "lab"', cml2_main)
            self.assertIn('module "iosxe"', nac_main)

    def test_cml2_alias_still_writes_lifecycle_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "alias-cml2.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--cml2",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / "out" / "alias-cml2" / "cml2" / "main.tf").exists())


if __name__ == "__main__":
    unittest.main()
