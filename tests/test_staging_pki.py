# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-06
#
# Purpose: TG-165 — auto-enable node staging when --pki is used.
# Blast Radius: Test-only.

import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import (  # pylint: disable=wrong-import-position
    create_argparser,
    main,
    normalize_template_inputs,
    resolve_staging_flags,
    validate_cml2_lifecycle_guardrails,
    validate_nac_mvp_guardrails,
    validate_nodes_for_mode,
)
from topogen.render import STAGING_PRIORITY_CA_ROOT  # pylint: disable=wrong-import-position


class TestResolveStagingFlags(unittest.TestCase):
    def setUp(self):
        self.parser = create_argparser()

    def _resolve(self, argv):
        args = self.parser.parse_args(argv)
        normalize_template_inputs(args)
        validate_nodes_for_mode(args, self.parser)
        validate_nac_mvp_guardrails(args, self.parser)
        validate_cml2_lifecycle_guardrails(args, self.parser)
        resolve_staging_flags(args)
        return args

    def test_pki_auto_enables_staging_with_cml_031(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/pki.yaml",
                "--pki",
                "--cml-version",
                "0.3.1",
            ]
        )
        self.assertTrue(args.pki_enabled)
        self.assertTrue(args.staging)

    def test_no_staging_opt_out(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/pki.yaml",
                "--pki",
                "--no-staging",
                "--cml-version",
                "0.3.1",
            ]
        )
        self.assertFalse(args.staging)

    def test_non_pki_does_not_auto_enable_staging(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/plain.yaml",
                "--cml-version",
                "0.3.1",
            ]
        )
        self.assertFalse(args.staging)

    def test_explicit_staging_without_pki(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/staged.yaml",
                "--staging",
                "--cml-version",
                "0.3.1",
            ]
        )
        self.assertTrue(args.staging)

    def test_pki_old_cml_version_disables_staging(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/pki-old.yaml",
                "--pki",
                "--cml-version",
                "0.3.0",
            ]
        )
        self.assertFalse(args.staging)

    def test_no_staging_overrides_explicit_staging(self):
        args = self._resolve(
            [
                "3",
                "--mode",
                "dmvpn",
                "--offline-yaml",
                "out/pki.yaml",
                "--pki",
                "--staging",
                "--no-staging",
                "--cml-version",
                "0.3.1",
            ]
        )
        self.assertFalse(args.staging)


class TestPkiStagingYamlOutput(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def test_pki_lab_emits_node_staging_and_ca_root_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "pki-dmvpn.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--device-template",
                    "csr1000v",
                    "--offline-yaml",
                    str(out_file),
                    "--pki",
                    "--cml-version",
                    "0.3.1",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            lab_yaml = out_file.read_text(encoding="utf-8")
            self.assertIn("node_staging:", lab_yaml)
            self.assertIn("enabled: true", lab_yaml)
            self.assertIn("label: CA-ROOT", lab_yaml)
            self.assertIn(f"priority: {STAGING_PRIORITY_CA_ROOT}", lab_yaml)

    def test_pki_no_staging_omits_node_staging_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "pki-no-staging.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--device-template",
                    "csr1000v",
                    "--offline-yaml",
                    str(out_file),
                    "--pki",
                    "--no-staging",
                    "--cml-version",
                    "0.3.1",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            lab_yaml = out_file.read_text(encoding="utf-8")
            self.assertNotIn("node_staging:", lab_yaml)
            self.assertNotIn(f"priority: {STAGING_PRIORITY_CA_ROOT}", lab_yaml)


if __name__ == "__main__":
    unittest.main()
