# File Chain (see DEVELOPER.md):
# Doc Version: v1.7.1
# Date Modified: 2026-06-13
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py parser and validation helpers
# - Writes to: Temporary test directories only
# - Calls into: topogen.main (main, create_argparser, validate_nodes_for_mode, validate_nac_mvp_guardrails)
#
# Purpose: Validate NaC CLI guardrails and preserve non-NaC node behavior.
# Blast Radius: Test-only; no runtime behavior changes.

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import (  # pylint: disable=wrong-import-position
    MGMT_IPV4_OOB_NODE_LIMIT,
    create_argparser,
    finalize_mgmt_addressing_args,
    main,
    normalize_template_inputs,
    validate_bootstrap_guardrails,
    validate_cml2_lifecycle_guardrails,
    validate_mgmt_ipv6_guardrails,
    validate_nac_mvp_guardrails,
    validate_nodes_for_mode,
)


class TestNacCliGuardrails(unittest.TestCase):
    def setUp(self):
        self.parser = create_argparser()

    def _parse_and_validate(self, argv):
        args = self.parser.parse_args(argv)
        normalize_template_inputs(args)
        validate_nodes_for_mode(args, self.parser)
        validate_nac_mvp_guardrails(args, self.parser)
        validate_bootstrap_guardrails(args, self.parser)
        validate_cml2_lifecycle_guardrails(args, self.parser)
        if getattr(args, "enable_mgmt", False) and args.mgmt_vrf and args.mgmt_vrf.lower() == "global":
            args.mgmt_vrf = None
        finalize_mgmt_addressing_args(args, self.parser)
        validate_mgmt_ipv6_guardrails(args, self.parser)
        return args

    def _run_main_exit(self, argv):
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["topogen", *argv]), redirect_stderr(stderr):
            try:
                return main(), stderr.getvalue()
            except SystemExit as exc:
                return exc.code, stderr.getvalue()

    def test_valid_nac_simple_one_router_command_shape(self):
        args = self._parse_and_validate(
            ["1", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 1)
        self.assertEqual(args.mode, "simple")
        self.assertEqual(args.offline_yaml, "out/iosv-test.yaml")

    def test_valid_nac_flat_one_router_command_shape(self):
        args = self._parse_and_validate(
            ["1", "--mode", "flat", "--offline-yaml", "out/one-router-flat.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 1)
        self.assertEqual(args.mode, "flat")
        self.assertEqual(args.offline_yaml, "out/one-router-flat.yaml")

    def test_valid_nac_two_router_nx_command_shape(self):
        args = self._parse_and_validate(
            ["2", "--mode", "nx", "--offline-yaml", "out/two-router-nx.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 2)
        self.assertEqual(args.mode, "nx")
        self.assertEqual(args.offline_yaml, "out/two-router-nx.yaml")

    def test_valid_nac_two_router_simple_command_shape(self):
        args = self._parse_and_validate(
            ["2", "--mode", "simple", "--offline-yaml", "out/two-router-simple.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 2)
        self.assertEqual(args.mode, "simple")
        self.assertEqual(args.offline_yaml, "out/two-router-simple.yaml")

    def test_valid_nac_two_router_flat_command_shape(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat", "--offline-yaml", "out/two-router-flat.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 2)
        self.assertEqual(args.mode, "flat")
        self.assertEqual(args.offline_yaml, "out/two-router-flat.yaml")

    def test_valid_nac_two_router_flat_pair_command_shape(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat-pair", "--offline-yaml", "out/two-router-flat-pair.yaml", "--nac"]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 2)
        self.assertEqual(args.mode, "flat-pair")
        self.assertEqual(args.offline_yaml, "out/two-router-flat-pair.yaml")

    def test_valid_nac_dmvpn_flat_command_shape(self):
        args = self._parse_and_validate(
            [
                "3",
                "--mode",
                "dmvpn",
                "--dmvpn-hubs",
                "1",
                "--offline-yaml",
                "out/dmvpn-flat.yaml",
                "--nac",
            ]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 3)
        self.assertEqual(args.mode, "dmvpn")
        self.assertEqual(getattr(args, "dmvpn_underlay", "flat"), "flat")
        self.assertEqual(args.dmvpn_hubs, "1")
        self.assertEqual(args.offline_yaml, "out/dmvpn-flat.yaml")

    def test_valid_nac_dmvpn_flat_pair_command_shape(self):
        args = self._parse_and_validate(
            [
                "4",
                "--mode",
                "dmvpn",
                "--dmvpn-underlay",
                "flat-pair",
                "--template",
                "iosv-dmvpn",
                "--offline-yaml",
                "out/dmvpn-flat-pair.yaml",
                "--nac",
            ]
        )
        self.assertTrue(args.nac)
        self.assertEqual(args.nodes, 4)
        self.assertEqual(args.mode, "dmvpn")
        self.assertEqual(args.dmvpn_underlay, "flat-pair")
        self.assertEqual(args.template, "iosv-dmvpn")
        self.assertEqual(args.offline_yaml, "out/dmvpn-flat-pair.yaml")

    def test_bootstrap_requires_nac(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "nx",
                        "--offline-yaml",
                        "out/two-router-nx.yaml",
                        "--mgmt",
                        "--bootstrap",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--bootstrap requires --nac", stderr.getvalue())

    def test_bootstrap_requires_mgmt(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "nx",
                        "--offline-yaml",
                        "out/two-router-nx.yaml",
                        "--nac",
                        "--bootstrap",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--bootstrap requires --mgmt", stderr.getvalue())

    def test_bootstrap_rejects_blank(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "nx",
                        "--offline-yaml",
                        "out/two-router-nx.yaml",
                        "--nac",
                        "--mgmt",
                        "--bootstrap",
                        "--blank",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        stderr_text = stderr.getvalue()
        self.assertTrue(
            "--bootstrap cannot be combined with --blank" in stderr_text
            or "--nac cannot be combined with --blank" in stderr_text
        )

    def test_valid_nac_bootstrap_command_shape(self):
        args = self._parse_and_validate(
            [
                "2",
                "--mode",
                "nx",
                "--offline-yaml",
                "out/two-router-nx.yaml",
                "--nac",
                "--mgmt",
                "--mgmt-bridge",
                "--bootstrap",
            ]
        )
        self.assertTrue(args.nac)
        self.assertTrue(args.bootstrap)
        self.assertTrue(args.enable_mgmt)

    def test_nac_rejects_blank(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "nx",
                        "--offline-yaml",
                        "out/two-router-nx.yaml",
                        "--nac",
                        "--blank",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--nac cannot be combined with --blank", stderr.getvalue())

    def test_nac_requires_offline_yaml(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(["1", "--mode", "simple", "--nac"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--nac requires --offline-yaml FILE", stderr.getvalue())

    def test_nac_without_offline_yaml_exits_nonzero_and_creates_no_nac(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, stderr = self._run_main_exit(["1", "--mode", "simple", "--nac"])
            self.assertNotEqual(code, 0)
            self.assertIn("--nac requires --offline-yaml FILE", stderr)
            self.assertFalse((Path(tmp) / "nac").exists())

    def test_nac_rejects_import_workflow_flags(self):
        cases = [
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--import", "--nac"],
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--import-yaml", "in.yaml", "--nac"],
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--up", "in.yaml", "--nac"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as cm:
                    with redirect_stderr(io.StringIO()) as stderr:
                        self._parse_and_validate(argv)
                self.assertNotEqual(cm.exception.code, 0)
                self.assertIn("import workflow flags are not supported", stderr.getvalue())

    def test_nac_rejects_online_yaml_export(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "simple",
                        "--yaml",
                        "online.yaml",
                        "--offline-yaml",
                        "out.yaml",
                        "--nac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("use --offline-yaml instead of --yaml online export", stderr.getvalue())

    def test_terraform_cml2_requires_offline_yaml(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(["2", "--mode", "simple", "--terraform-cml2"])
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--terraform-cml2 requires --offline-yaml FILE", stderr.getvalue())

    def test_terraform_cml2_rejects_import_workflow_flags(self):
        cases = [
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--import", "--terraform-cml2"],
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--import-yaml", "in.yaml", "--terraform-cml2"],
            ["2", "--mode", "simple", "--offline-yaml", "out/iosv-test.yaml", "--up", "in.yaml", "--terraform-cml2"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as cm:
                    with redirect_stderr(io.StringIO()) as stderr:
                        self._parse_and_validate(argv)
                self.assertNotEqual(cm.exception.code, 0)
                self.assertIn("import workflow flags are not supported", stderr.getvalue())

    def test_nac_rejects_unsupported_platform_family(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "1",
                        "--mode",
                        "simple",
                        "--offline-yaml",
                        "out/iosv-test.yaml",
                        "--device-template",
                        "iol",
                        "--nac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("R1", stderr.getvalue())
        self.assertIn("IOL is not in the supported IOS-XE template set", stderr.getvalue())

    def test_nac_rejects_non_iosxe_node_before_nac_tree_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "lxc-test.yaml"
            code, stderr = self._run_main_exit(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--device-template",
                    "lxc",
                    "--nac",
                ]
            )
            self.assertNotEqual(code, 0)
            self.assertIn("R1", stderr)
            self.assertIn("FRR/LXC/Linux containers are not IOS-XE devices", stderr)
            self.assertFalse((Path(tmp) / "out" / "lxc-test" / "nac").exists())

    def test_valid_all_iosxe_nac_cli_succeeds_with_composed_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-pair-csr-mgmt-vrf.yaml"
            code, stderr = self._run_main_exit(
                [
                    "2",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--device-template",
                    "csr1000v",
                    "--mgmt",
                    "--vrf",
                    "--pair-vrf",
                    "tenant-a",
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(code, 0, stderr)
            nac_yaml = Path(tmp) / "out" / "flat-pair-csr-mgmt-vrf" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())

    def test_non_nac_still_rejects_one_node(self):
        with self.assertRaises(SystemExit):
            self._parse_and_validate(["1", "--mode", "simple", "--offline-yaml", "out/non-nac.yaml"])

    def test_template_csr1000v_sets_device_template_for_nac(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat", "--template", "csr1000v", "--offline-yaml", "out/two-router-csr.yaml", "--nac"]
        )
        self.assertEqual(args.template, "csr1000v")
        self.assertEqual(args.dev_template, "csr1000v")

    def test_template_crsv_alias_normalizes_to_csr1000v(self):
        args = self._parse_and_validate(
            ["2", "--mode", "flat", "--template", "CRSv", "--offline-yaml", "out/two-router-csr.yaml", "--nac"]
        )
        self.assertEqual(args.template, "csr1000v")
        self.assertEqual(args.dev_template, "csr1000v")

    def test_mgmt_ipv6_mode_requires_mgmt(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "simple",
                        "--offline-yaml",
                        "out/iosv-test.yaml",
                        "--mgmt-ipv6-mode",
                        "slaac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("IPv6 OOB flags", stderr.getvalue())

    def test_mgmt_ipv6_mode_rejects_global_vrf(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                args = self.parser.parse_args(
                    [
                        "2",
                        "--mode",
                        "simple",
                        "--offline-yaml",
                        "out/iosv-test.yaml",
                        "--mgmt",
                        "--mgmt-vrf",
                        "global",
                        "--mgmt-ipv6-mode",
                        "slaac",
                    ]
                )
                normalize_template_inputs(args)
                if args.mgmt_vrf and args.mgmt_vrf.lower() == "global":
                    args.mgmt_vrf = None
                finalize_mgmt_addressing_args(args, self.parser)
                validate_mgmt_ipv6_guardrails(args, self.parser)
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("named --mgmt-vrf", stderr.getvalue())

    def test_valid_mgmt_ipv6_slaac_with_mgmt_bridge(self):
        args = self._parse_and_validate(
            [
                "2",
                "--mode",
                "flat",
                "--offline-yaml",
                "out/iosv-ipv6-bridge.yaml",
                "--mgmt",
                "--mgmt-bridge",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-mode",
                "slaac",
                "--mgmt-ipv6-cidr",
                "fd00:10:254::/64",
            ]
        )
        self.assertTrue(args.enable_mgmt)
        self.assertTrue(args.mgmt_bridge)
        self.assertEqual(args.mgmt_ipv6_mode, "slaac")

    def test_valid_mgmt_ipv6_slaac_command_shape(self):
        args = self._parse_and_validate(
            [
                "2",
                "--mode",
                "simple",
                "--offline-yaml",
                "out/iosv-ipv6.yaml",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-mode",
                "slaac",
                "--mgmt-ipv6-cidr",
                "fd00:10:254::/64",
            ]
        )
        self.assertTrue(args.enable_mgmt)
        self.assertEqual(args.mgmt_ipv6_mode, "slaac")
        self.assertEqual(args.mgmt_ipv6_cidr, "fd00:10:254::/64")

    def test_mgmt_ipv4_oob_rejected_at_scale_without_ipv6_mode(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "300",
                        "--mode",
                        "flat",
                        "--offline-yaml",
                        "out/large-flat.yaml",
                        "--nac",
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-bridge",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        err = stderr.getvalue()
        self.assertIn("300 nodes", err)
        self.assertIn("--mgmt-ipv6-dhcp", err)
        self.assertIn("IPv4 OOB", err)

    def test_mgmt_ipv4_oob_allowed_below_scale_threshold(self):
        below = str(MGMT_IPV4_OOB_NODE_LIMIT - 1)
        args = self._parse_and_validate(
            [
                below,
                "--mode",
                "flat",
                "--offline-yaml",
                "out/medium-flat.yaml",
                "--nac",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
            ]
        )
        self.assertTrue(args.enable_mgmt)
        self.assertIsNone(args.mgmt_ipv6_mode)

    def test_mgmt_ipv4_oob_at_threshold_requires_ipv6_mode(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        str(MGMT_IPV4_OOB_NODE_LIMIT),
                        "--mode",
                        "flat",
                        "--offline-yaml",
                        "out/at-threshold-flat.yaml",
                        "--nac",
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--mgmt-ipv6-dhcp", stderr.getvalue())

    def _static_base_argv(self):
        return [
            "2",
            "--mode",
            "flat",
            "-T",
            "iosv",
            "--device-template",
            "iosv",
            "--offline-yaml",
            "out/iosv-static.yaml",
        ]

    def test_static_requires_mgmt(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        "2",
                        "--mode",
                        "flat",
                        "--offline-yaml",
                        "out/iosv-static.yaml",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "fd80::/64",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        err = stderr.getvalue()
        self.assertTrue("IPv6 OOB" in err or "require --mgmt" in err)

    def test_static_accepts_default_mgmt_vrf(self):
        args = self._parse_and_validate(
            [
                *self._static_base_argv(),
                "--mgmt",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
            ]
        )
        self.assertEqual(args.mgmt_vrf, "Mgmt-vrf")
        self.assertEqual(args.mgmt_ipv6_mode, "static")

    def test_static_requires_named_mgmt_vrf_when_global(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "global",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "fd80::/64",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("named --mgmt-vrf", stderr.getvalue())

    def test_static_requires_ipv6_cidr(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("--mgmt-ipv6-cidr", stderr.getvalue())

    def test_static_rejects_invalid_cidr(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "not-an-address",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("Invalid --mgmt-ipv6-cidr", stderr.getvalue())

    def test_link_local_requires_ipv6_mode(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static-link-local",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("IPv6 OOB mode", stderr.getvalue())

    def test_static_rejects_slaac_flag(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "fd80::/64",
                        "--mgmt-ipv6-slaac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        err = stderr.getvalue().lower()
        self.assertTrue("mutually exclusive" in err or "conflicts" in err)

    def test_static_rejects_dhcp_flag(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "fd80::/64",
                        "--mgmt-ipv6-dhcp",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        err = stderr.getvalue().lower()
        self.assertTrue("mutually exclusive" in err or "conflicts" in err)

    def test_static_rejects_legacy_mode_slaac(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "fd80::/64",
                        "--mgmt-ipv6-mode",
                        "slaac",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("conflicts", stderr.getvalue().lower())

    def test_static_rejects_legacy_mode_dhcpv6(self):
        with self.assertRaises(SystemExit) as cm:
            with redirect_stderr(io.StringIO()) as stderr:
                self._parse_and_validate(
                    [
                        *self._static_base_argv(),
                        "--mgmt",
                        "--mgmt-vrf",
                        "Mgmt-vrf",
                        "--mgmt-ipv6-static",
                        "--mgmt-ipv6-cidr",
                        "fd80::/64",
                        "--mgmt-ipv6-mode",
                        "dhcpv6",
                    ]
                )
        self.assertNotEqual(cm.exception.code, 0)
        self.assertIn("conflicts", stderr.getvalue().lower())

    def test_valid_static_minimal(self):
        args = self._parse_and_validate(
            [
                *self._static_base_argv(),
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
            ]
        )
        self.assertEqual(args.mgmt_ipv6_mode, "static")
        self.assertEqual(args.mgmt_ipv6_cidr, "fd80::/64")

    def test_valid_slaac_with_link_local(self):
        args = self._parse_and_validate(
            [
                *self._static_base_argv(),
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-slaac",
                "--mgmt-ipv6-static-link-local",
            ]
        )
        self.assertEqual(args.mgmt_ipv6_mode, "slaac")
        self.assertTrue(args.mgmt_ipv6_static_link_local)

    def test_valid_static_with_link_local(self):
        args = self._parse_and_validate(
            [
                *self._static_base_argv(),
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
                "--mgmt-ipv6-static-link-local",
            ]
        )
        self.assertTrue(args.mgmt_ipv6_static_link_local)

    def test_cidr_without_static_unchanged(self):
        args = self._parse_and_validate(
            [
                *self._static_base_argv(),
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-slaac",
                "--mgmt-ipv6-cidr",
                "fd00:10:254::/64",
            ]
        )
        self.assertEqual(args.mgmt_ipv6_mode, "slaac")
        self.assertFalse(getattr(args, "mgmt_ipv6_static", False))

    def test_static_doc_prefix_cidr(self):
        args = self._parse_and_validate(
            [
                *self._static_base_argv(),
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "2001:db8:1:2::/64",
            ]
        )
        self.assertEqual(args.mgmt_ipv6_mode, "static")


if __name__ == "__main__":
    unittest.main()
