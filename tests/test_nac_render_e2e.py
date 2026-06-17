# File Chain (see DEVELOPER.md):
# Doc Version: v1.2.0
# Date Modified: 2026-06-04
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py offline renderer
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main
#
# Purpose: End-to-end regression for offline render.py -> nac.py wiring (universal + DMVPN paths).
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position


class TestNacRenderEndToEnd(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def _assert_provenance_flags(self, cml_yaml: Path, *flags: str) -> None:
        data = yaml.safe_load(cml_yaml.read_text(encoding="utf-8"))
        lab = data["lab"]
        for flag in flags:
            self.assertIn(flag, lab["description"], flag)
            self.assertIn(flag, lab["notes"], flag)
            self.assertTrue(
                any(flag in annotation.get("text_content", "") for annotation in data["annotations"]),
                flag,
            )

    def _assert_full_nac_tree(self, nac_root: Path, host_vars: tuple[str, ...]):
        expected_artifacts = [
            "nac.yaml",
            "main.tf",
            "versions.tf",
            "terraform.tfvars.example",
            ".gitignore",
            "inventory.yaml",
            "ansible.cfg",
            "group_vars/all.yaml",
            "verify_reachability.yaml",
            "devices.yaml",
            "nac_metadata.yaml",
        ]
        expected_artifacts.extend(f"host_vars/{host_var}" for host_var in host_vars)
        for artifact in expected_artifacts:
            self.assertTrue((nac_root / artifact).exists(), artifact)

    def test_flat_and_flat_pair_nac_runs_emit_complete_tree(self):
        for mode in ("flat", "flat-pair"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / "out" / f"{mode}.yaml"
                rc = self._run_main(
                    [
                        "2",
                        "--mode",
                        mode,
                        "--offline-yaml",
                        str(out_file),
                        "--nac",
                        "--overwrite",
                    ]
                )
                self.assertEqual(rc, 0)

                lab_root = Path(tmp) / "out" / mode
                self.assertTrue((lab_root / f"{mode}.yaml").exists())
                self._assert_full_nac_tree(
                    lab_root / "nac",
                    ("iosv-01.yaml", "iosv-02.yaml"),
                )

    def test_flat_nac_provenance_includes_nac_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-nac.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat",
                    "-T",
                    "iosv",
                    "--device-template",
                    "iosv",
                    "-L",
                    "test-nac",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "flat-nac"
            cml_yaml = lab_root / "flat-nac.yaml"
            self.assertTrue(cml_yaml.exists())
            self._assert_full_nac_tree(
                lab_root / "nac",
                ("iosv-01.yaml", "iosv-02.yaml"),
            )

            self._assert_provenance_flags(cml_yaml, "--nac")

    def test_flat_cml2_provenance_includes_cml2_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-cml2.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat",
                    "-T",
                    "iosv",
                    "--device-template",
                    "iosv",
                    "-L",
                    "test-cml2",
                    "--offline-yaml",
                    str(out_file),
                    "--cml2",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "flat-cml2"
            cml_yaml = lab_root / "flat-cml2.yaml"
            self.assertTrue(cml_yaml.exists())
            self.assertTrue((lab_root / "cml2" / "main.tf").exists())
            self.assertFalse((lab_root / "nac").exists())
            self._assert_provenance_flags(cml_yaml, "--terraform-cml2")

    def test_flat_nac_and_cml2_provenance_and_sibling_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-nac-cml2.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat",
                    "-T",
                    "iosv",
                    "--device-template",
                    "iosv",
                    "-L",
                    "test-nac-cml2",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--cml2",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "flat-nac-cml2"
            cml_yaml = lab_root / "flat-nac-cml2.yaml"
            self.assertTrue(cml_yaml.exists())
            self._assert_full_nac_tree(
                lab_root / "nac",
                ("iosv-01.yaml", "iosv-02.yaml"),
            )
            self.assertTrue((lab_root / "cml2" / "main.tf").exists())
            self._assert_provenance_flags(cml_yaml, "--nac", "--terraform-cml2")

    def test_nx_nac_bootstrap_emits_thin_day0_and_full_nac_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "nx-bootstrap.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "nx",
                    "-T",
                    "csr-ospf",
                    "--device-template",
                    "csr1000v",
                    "-L",
                    "test-nx-bootstrap",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--mgmt",
                    "--mgmt-bridge",
                    "--bootstrap",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "nx-bootstrap"
            cml_yaml = lab_root / "nx-bootstrap.yaml"
            self.assertTrue(cml_yaml.exists())
            self._assert_full_nac_tree(
                lab_root / "nac",
                ("iosv-01.yaml", "iosv-02.yaml"),
            )
            self._assert_provenance_flags(cml_yaml, "--nac", "--bootstrap", "--mgmt-bridge")

            cml_text = cml_yaml.read_text(encoding="utf-8")
            self.assertIn("restconf", cml_text)
            self.assertIn("ip address dhcp", cml_text)
            self.assertIn("no cdp enable", cml_text)
            self.assertIn("ip ssh server algorithm authentication password", cml_text)
            self.assertNotIn("router ospf", cml_text)

            nac_text = (lab_root / "nac" / "nac.yaml").read_text(encoding="utf-8")
            self.assertIn("ospf_processes", nac_text)

    def test_flat_and_flat_pair_non_nac_runs_do_not_emit_nac_tree(self):
        for mode in ("flat", "flat-pair"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / "out" / f"{mode}.yaml"
                rc = self._run_main(
                    [
                        "2",
                        "--mode",
                        mode,
                        "--offline-yaml",
                        str(out_file),
                        "--overwrite",
                    ]
                )
                self.assertEqual(rc, 0)

                self.assertTrue(out_file.exists())
                self.assertFalse((Path(tmp) / "out" / mode / "nac").exists())
                self.assertFalse((Path(tmp) / "out" / "nac").exists())

    def test_dmvpn_flat_nac_run_emits_complete_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "dmvpn-flat"
            self.assertTrue((lab_root / "dmvpn-flat.yaml").exists())
            self._assert_full_nac_tree(
                lab_root / "nac",
                ("iosv-01.yaml", "iosv-02.yaml", "iosv-03.yaml"),
            )

    def test_dmvpn_flat_pair_nac_run_emits_complete_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-pair.yaml"
            rc = self._run_main(
                [
                    "4",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-underlay",
                    "flat-pair",
                    "--template",
                    "iosv-dmvpn",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "dmvpn-flat-pair"
            self.assertTrue((lab_root / "dmvpn-flat-pair.yaml").exists())
            self._assert_full_nac_tree(
                lab_root / "nac",
                (
                    "iosv-01.yaml",
                    "iosv-02.yaml",
                    "iosv-03.yaml",
                    "iosv-04.yaml",
                ),
            )

    def test_dmvpn_flat_and_flat_pair_non_nac_runs_keep_flat_output_path(self):
        cases = (
            (
                "dmvpn-flat.yaml",
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--offline-yaml",
                ],
            ),
            (
                "dmvpn-flat-pair.yaml",
                [
                    "4",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-underlay",
                    "flat-pair",
                    "--template",
                    "iosv-dmvpn",
                    "--offline-yaml",
                ],
            ),
        )
        for lab_name, argv_prefix in cases:
            with self.subTest(lab=lab_name), tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / "out" / lab_name
                rc = self._run_main([*argv_prefix, str(out_file), "--overwrite"])
                self.assertEqual(rc, 0)
                self.assertTrue(out_file.exists())
                self.assertFalse((Path(tmp) / "out" / lab_name.removesuffix(".yaml") / "nac").exists())

    def test_dmvpn_flat_nac_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat.yaml"
            argv = [
                "3",
                "--mode",
                "dmvpn",
                "--dmvpn-hubs",
                "1",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            self.assertEqual(self._run_main(argv), 0)
            lab_root = Path(tmp) / "out" / "dmvpn-flat"
            nac_yaml = lab_root / "nac" / "nac.yaml"
            content_a = nac_yaml.read_text(encoding="utf-8")

            self.assertEqual(self._run_main(argv), 0)
            nested_bad = lab_root / "dmvpn-flat" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertFalse(nested_bad.exists())
            content_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(content_a, content_b)


if __name__ == "__main__":
    unittest.main()
