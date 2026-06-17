# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.1
# Date Modified: 2026-06-13
#
# Purpose: TG-190 CP1 — offline render asserts for OOB IPv6 mgmt in VRF.
# Blast Radius: Test-only.

import re
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

from argparse import Namespace

from topogen.main import main  # pylint: disable=wrong-import-position
from topogen.config import Config  # pylint: disable=wrong-import-position
from topogen.models import TopogenInterface, TopogenNode  # pylint: disable=wrong-import-position
from topogen.render import _render_bootstrap_config  # pylint: disable=wrong-import-position


def _extract_router_config(cml_yaml: Path, label: str = "R1") -> str:
    data = yaml.safe_load(cml_yaml.read_text(encoding="utf-8"))
    for node in data.get("nodes", []):
        if node.get("label") == label:
            cfg = node.get("configuration", "")
            if isinstance(cfg, list):
                return cfg[0].get("content", "") if cfg else ""
            return str(cfg)
    raise AssertionError(f"node {label} not found in {cml_yaml}")


def _oob_block(config: str, iface_pattern: str) -> str:
    match = re.search(
        rf"(interface {iface_pattern}\b.*?)(?=\ninterface |\n!|\nend\b)",
        config,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise AssertionError(f"OOB interface {iface_pattern} not found")
    return match.group(1)


class TestMgmtIpv6VrfOfflineRender(unittest.TestCase):
    def _run_offline_config(self, argv: list[str], label: str = "R1") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab.yaml"
            with patch.object(sys, "argv", ["topogen", *argv, "--offline-yaml", str(out_file)]):
                rc = main()
            self.assertEqual(rc, 0, f"topogen failed for argv={argv}")
            return _extract_router_config(out_file, label)

    def test_csr_slaac_renders_ipv6_oob_and_vrf_af(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "simple",
                "-T",
                "csr1000v",
                "--device-template",
                "csr1000v",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-mode",
                "slaac",
            ]
        )
        self.assertIn("address-family ipv6", config)
        self.assertIn("vrf definition Mgmt-vrf", config)
        self.assertRegex(config, r"interface GigabitEthernet5\b")
        oob = _oob_block(config, r"GigabitEthernet5")
        self.assertIn("vrf forwarding Mgmt-vrf", oob)
        self.assertIn("no ip address", oob)
        self.assertIn("ipv6 address autoconfig", oob)
        self.assertNotIn("ip address dhcp", oob)

    def test_csr_ospf_dhcpv6_explicit_flag_renders_ipv6_oob(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "csr-ospf",
                "--device-template",
                "csr1000v",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-dhcp",
                "--mgmt-bridge",
            ]
        )
        oob = _oob_block(config, r"GigabitEthernet5")
        self.assertIn("no ip address", oob)
        self.assertIn("ipv6 address dhcp", oob)
        self.assertNotIn("ip address dhcp", oob)

    def test_dual_stack_oob_renders_ipv4_and_ipv6_dhcp(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-bridge",
                "--mgmt-ipv4-dhcp",
                "--mgmt-ipv6-dhcp",
            ]
        )
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ip address dhcp", oob)
        self.assertIn("ipv6 address dhcp", oob)
        self.assertNotIn("no ip address", oob)

    def test_csr_ospf_dhcpv6_renders_ipv6_oob(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "csr-ospf",
                "--device-template",
                "csr1000v",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-mode",
                "dhcpv6",
                "--mgmt-bridge",
            ]
        )
        self.assertIn("address-family ipv6", config)
        self.assertEqual(config.count("vrf definition Mgmt-vrf"), 1)
        self.assertRegex(config, r"interface GigabitEthernet5\b")
        oob = _oob_block(config, r"GigabitEthernet5")
        self.assertIn("vrf forwarding Mgmt-vrf", oob)
        self.assertIn("no ip address", oob)
        self.assertIn("ipv6 address dhcp", oob)
        self.assertNotIn("ip address dhcp", oob)
        self.assertIn("10.10.0.1", config)

    def test_iosv_dhcpv6_renders_ipv6_oob(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "simple",
                "-T",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-mode",
                "dhcpv6",
            ]
        )
        self.assertIn("vrf definition Mgmt-vrf", config)
        self.assertIn("address-family ipv6", config)
        self.assertRegex(config, r"interface GigabitEthernet0/5\b")
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("vrf forwarding Mgmt-vrf", oob)
        self.assertIn("no ip address", oob)
        self.assertIn("ipv6 address dhcp", oob)
        self.assertNotIn("ip address dhcp", oob)

    def test_flat_slaac_with_mgmt_bridge_renders_ext_conn_and_ipv6_oob(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab.yaml"
            with patch.object(
                sys,
                "argv",
                [
                    "topogen",
                    "2",
                    "--mode",
                    "flat",
                    "-T",
                    "iosv",
                    "--device-template",
                    "iosv",
                    "--mgmt",
                    "--mgmt-vrf",
                    "Mgmt-vrf",
                    "--mgmt-bridge",
                    "--mgmt-ipv6-mode",
                    "slaac",
                    "--mgmt-ipv6-cidr",
                    "fd00:10:254::/64",
                    "--offline-yaml",
                    str(out_file),
                ],
            ):
                rc = main()
            self.assertEqual(rc, 0)
            data = yaml.safe_load(out_file.read_text(encoding="utf-8"))
            labels = {node.get("label") for node in data.get("nodes", [])}
            self.assertIn("ext-conn-mgmt", labels)
            self.assertIn("SWoob0", labels)
            links = data.get("links", [])
            ext_id = next(
                n["id"] for n in data["nodes"] if n.get("label") == "ext-conn-mgmt"
            )
            swoob0_id = next(n["id"] for n in data["nodes"] if n.get("label") == "SWoob0")
            bridge_link = next(
                (
                    link
                    for link in links
                    if {link.get("n1"), link.get("n2")} == {ext_id, swoob0_id}
                ),
                None,
            )
            self.assertIsNotNone(bridge_link, "ext-conn-mgmt must link to SWoob0")
            config = _extract_router_config(out_file, "R1")
            self.assertIn("vrf definition Mgmt-vrf", config)
            oob = _oob_block(config, r"GigabitEthernet0/5")
            self.assertIn("vrf forwarding Mgmt-vrf", oob)
            self.assertIn("ipv6 address autoconfig", oob)
            self.assertNotIn("ip address dhcp", oob)

    def test_default_ipv4_mgmt_unchanged(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "simple",
                "-T",
                "csr1000v",
                "--device-template",
                "csr1000v",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv4-dhcp",
            ]
        )
        oob = _oob_block(config, r"GigabitEthernet5")
        self.assertIn("ip address dhcp", oob)
        self.assertNotIn("ipv6 address autoconfig", oob)
        self.assertNotIn("ipv6 address dhcp", oob)
        self.assertNotIn("address-family ipv6", config)

    def test_flat_ipv4_mgmt_no_duplicate_vrf_blocks(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-bridge",
            ]
        )
        self.assertEqual(config.count("ip vrf Mgmt-vrf"), 1)
        self.assertNotIn("vrf definition Mgmt-vrf", config)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ip vrf forwarding Mgmt-vrf", oob)
        self.assertIn("ip address dhcp", oob)

    def test_flat_ipv6_slaac_no_ip_vrf_conflict(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-bridge",
                "--mgmt-ipv6-mode",
                "slaac",
            ]
        )
        self.assertNotIn("ip vrf Mgmt-vrf", config)
        self.assertEqual(config.count("vrf definition Mgmt-vrf"), 1)
        self.assertIn("address-family ipv6", config)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("vrf forwarding Mgmt-vrf", oob)
        self.assertIn("ipv6 address autoconfig", oob)
        self.assertNotIn("ip address dhcp", oob)

    def test_flat_ipv6_slaac_oob_no_shutdown_single_block(self):
        """OOB Gi must be no shutdown once; NaC iface must not duplicate Gi0/5."""
        config = self._run_offline_config(
            [
                "4",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-bridge",
                "--mgmt-ipv6-mode",
                "slaac",
            ]
        )
        self.assertEqual(len(re.findall(r"interface GigabitEthernet0/5\b", config)), 1)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("no shutdown", oob)
        self.assertNotRegex(oob, r"(?m)^\s+shutdown\s*$")
        after_oob = config.split(oob, 1)[-1]
        self.assertNotRegex(after_oob, r"interface GigabitEthernet0/5\b")

    def test_iosv_bootstrap_ipv6_slaac_uses_vrf_definition(self):
        cfg = Config(
            username="cisco",
            password="cisco",
            domainname="virl.lab",
            nameserver="8.8.8.8",
        )
        node = TopogenNode(
            hostname="R1",
            loopback=None,
            interfaces=[
                TopogenInterface(
                    description="OOB Management",
                    slot=5,
                    vrf="Mgmt-vrf",
                )
            ],
        )
        args = Namespace(
            dev_template="iosv",
            template="iosv",
            enable_mgmt=True,
            mgmt_vrf="Mgmt-vrf",
            mgmt_slot=5,
            mgmt_bridge=True,
            mgmt_gw=None,
            mgmt_ipv6_mode="slaac",
        )
        config = _render_bootstrap_config(cfg, node, args)
        self.assertNotIn("ip vrf Mgmt-vrf", config)
        self.assertEqual(config.count("vrf definition Mgmt-vrf"), 1)
        self.assertIn("address-family ipv6", config)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("vrf forwarding Mgmt-vrf", oob)
        self.assertIn("ipv6 address autoconfig", oob)

    def test_mgmt_global_vrf_omits_vrf_stanzas(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "simple",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "global",
                "--mgmt-bridge",
            ]
        )
        self.assertNotIn("ip vrf ", config)
        self.assertNotIn("vrf definition ", config)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertNotIn("vrf forwarding", oob)
        self.assertNotIn("ip vrf forwarding", oob)
        self.assertIn("ip address dhcp", oob)


class TestMgmtIpv6StaticOfflineRender(unittest.TestCase):
    _STATIC_BASE = [
        "2",
        "--mode",
        "flat",
        "-T",
        "iosv",
        "--device-template",
        "iosv",
        "--mgmt",
        "--mgmt-vrf",
        "Mgmt-vrf",
        "--mgmt-ipv6-static",
        "--mgmt-ipv6-cidr",
        "fd80::/64",
    ]

    def _run_offline_config(self, argv: list[str], label: str = "R1") -> str:
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab.yaml"
            with patch.object(sys, "argv", ["topogen", *argv, "--offline-yaml", str(out_file)]):
                rc = main()
            self.assertEqual(rc, 0, f"topogen failed for argv={argv}")
            return _extract_router_config(out_file, label)

    def _run_offline_yaml(self, argv: list[str]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab.yaml"
            with patch.object(sys, "argv", ["topogen", *argv, "--offline-yaml", str(out_file)]):
                rc = main()
            self.assertEqual(rc, 0)
            return yaml.safe_load(out_file.read_text(encoding="utf-8"))

    def test_iosv_static_global_fd80_r1(self):
        config = self._run_offline_config(self._STATIC_BASE)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 enable", oob)
        self.assertIn("vrf forwarding Mgmt-vrf", oob)
        self.assertIn("ipv6 address fd80::FF10:254:0:1/64", oob)
        self.assertNotIn("ipv6 unicast-routing", config)

    def test_iosv_static_global_r2(self):
        config = self._run_offline_config(self._STATIC_BASE, label="R2")
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 address fd80::FF10:254:0:2/64", oob)

    def test_iosv_static_doc_prefix(self):
        argv = [*self._STATIC_BASE[:-1], "2001:db8:1:2::/64"]
        config = self._run_offline_config(argv)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 address 2001:db8:1:2:FF10:254:0:1/64", oob)

    def test_csr_static_global(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "csr1000v",
                "--device-template",
                "csr1000v",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
            ]
        )
        self.assertIn("address-family ipv6", config)
        oob = _oob_block(config, r"GigabitEthernet5")
        self.assertIn("ipv6 address fd80::FF10:254:0:1/64", oob)

    def test_iosv_slaac_with_link_local(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-slaac",
                "--mgmt-ipv6-static-link-local",
            ]
        )
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 address autoconfig", oob)
        self.assertIn("ipv6 address fe80::FF10:20:0:1 link-local", oob)
        self.assertNotIn("ipv6 address fd80::FF10:254:0:1/64", oob)
        self.assertNotIn("FF10:254", oob)
        self.assertIn(
            "alias exec topogen-test show ipv6 interface GigabitEthernet0/5",
            config,
        )

    def test_iosv_static_with_link_local(self):
        argv = [
            *self._STATIC_BASE[:-1],
            "2001:db8:1:2::/64",
            "--mgmt-ipv6-static-link-local",
        ]
        config = self._run_offline_config(argv)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 address 2001:db8:1:2:FF10:254:0:1/64", oob)
        self.assertIn("ipv6 address fe80::FF10:20:0:1 link-local", oob)

    def test_iosv_static_link_local_loopback_255(self):
        argv = [
            "2",
            "--mode",
            "flat",
            "-T",
            "iosv",
            "--device-template",
            "iosv",
            "--mgmt",
            "--mgmt-vrf",
            "Mgmt-vrf",
            "--loopback-255",
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "fd80::/64",
            "--mgmt-ipv6-static-link-local",
        ]
        config = self._run_offline_config(argv)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 address fe80::FF10:255:0:1 link-local", oob)

    def test_iosv_static_no_slaac_stanzas(self):
        config = self._run_offline_config(self._STATIC_BASE)
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertNotIn("autoconfig", oob)
        self.assertNotIn("ipv6 address dhcp", oob)

    def test_iosv_bootstrap_static_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab" / "lab.yaml"
            argv = [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
                "--nac",
                "--bootstrap",
                "--offline-yaml",
                str(out_file),
            ]
            with patch.object(sys, "argv", ["topogen", *argv]):
                rc = main()
            self.assertEqual(rc, 0)
            config = _extract_router_config(out_file, "R1")
            oob = _oob_block(config, r"GigabitEthernet0/5")
            self.assertIn("ipv6 address fd80::FF10:254:0:1/64", oob)
            self.assertNotIn("ipv6 unicast-routing", config)

    def test_iosv_bootstrap_static_link_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab" / "lab.yaml"
            argv = [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-static-link-local",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
                "--nac",
                "--bootstrap",
                "--offline-yaml",
                str(out_file),
            ]
            with patch.object(sys, "argv", ["topogen", *argv]):
                rc = main()
            self.assertEqual(rc, 0)
            config = _extract_router_config(out_file, "R1")
            oob = _oob_block(config, r"GigabitEthernet0/5")
            self.assertIn("link-local", oob)

    def test_static_metadata_cidr_only_no_render(self):
        config = self._run_offline_config(
            [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-slaac",
                "--mgmt-ipv6-cidr",
                "fd00:10:254::/64",
            ]
        )
        oob = _oob_block(config, r"GigabitEthernet0/5")
        self.assertIn("ipv6 address autoconfig", oob)

    def test_loopback_unchanged_with_static(self):
        config = self._run_offline_config(self._STATIC_BASE)
        self.assertIn("int Loopback0", config)
        self.assertIn("10.20.0.1", config)

    def test_provenance_args_bits(self):
        data = self._run_offline_yaml(
            [
                *self._STATIC_BASE[:-1],
                "2001:db8:1:2::/64",
                "--mgmt-ipv6-static-link-local",
            ]
        )
        desc = data.get("lab", {}).get("description", "")
        self.assertIn("--mgmt-ipv6-static", desc)
        self.assertIn("--mgmt-ipv6-cidr", desc)
        self.assertIn("--mgmt-ipv6-static-link-local", desc)

    def test_static_without_cidr_exits(self):
        with self.assertRaises(SystemExit) as cm:
            with patch.object(
                sys,
                "argv",
                [
                    "topogen",
                    "2",
                    "--mode",
                    "flat",
                    "--mgmt",
                    "--mgmt-vrf",
                    "Mgmt-vrf",
                    "--mgmt-ipv6-static",
                    "--offline-yaml",
                    "out/x.yaml",
                ],
            ):
                main()
        self.assertNotEqual(cm.exception.code, 0)

    def test_static_plus_slaac_exits(self):
        with self.assertRaises(SystemExit) as cm:
            with patch.object(
                sys,
                "argv",
                [
                    "topogen",
                    *self._STATIC_BASE,
                    "--mgmt-ipv6-slaac",
                    "--offline-yaml",
                    "out/x.yaml",
                ],
            ):
                main()
        self.assertNotEqual(cm.exception.code, 0)

    def test_iosv_static_ipv6_gw_renders_default_route(self):
        argv = [
            *self._STATIC_BASE,
            "--mgmt-ipv6-gw",
            "2001:db8:1:2::1",
        ]
        config = self._run_offline_config(argv)
        self.assertIn("ipv6 route vrf Mgmt-vrf ::/0 2001:db8:1:2::1", config)
        self.assertNotIn("ip route vrf Mgmt-vrf 0.0.0.0", config)

    def test_iosv_static_ipv6_gw_vrf_override(self):
        argv = [
            *self._STATIC_BASE,
            "--mgmt-ipv6-gw",
            "2001:db8:1:2::1",
            "--mgmt-ipv6-gw-vrf",
            "Custom-vrf",
        ]
        config = self._run_offline_config(argv)
        self.assertIn("ipv6 route vrf Custom-vrf ::/0 2001:db8:1:2::1", config)
        self.assertNotIn("ipv6 route vrf Mgmt-vrf ::/0", config)

    def test_iosv_static_ipv6_gw_global_route_table(self):
        argv = [
            *self._STATIC_BASE,
            "--mgmt-ipv6-gw",
            "2001:db8:1:2::1",
            "--mgmt-ipv6-gw-vrf",
            "global",
        ]
        config = self._run_offline_config(argv)
        self.assertIn("ipv6 route ::/0 2001:db8:1:2::1", config)
        self.assertNotIn("ipv6 route vrf", config)

    def test_iosv_static_without_ipv6_gw_no_default_route(self):
        config = self._run_offline_config(self._STATIC_BASE)
        self.assertNotIn("ipv6 route", config)

    def test_iosv_bootstrap_static_ipv6_gw(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "lab" / "lab.yaml"
            argv = [
                "2",
                "--mode",
                "flat",
                "-T",
                "iosv",
                "--device-template",
                "iosv",
                "--mgmt",
                "--mgmt-vrf",
                "Mgmt-vrf",
                "--mgmt-ipv6-static",
                "--mgmt-ipv6-cidr",
                "fd80::/64",
                "--mgmt-ipv6-gw",
                "fd80::1",
                "--nac",
                "--bootstrap",
                "--offline-yaml",
                str(out_file),
            ]
            with patch.object(sys, "argv", ["topogen", *argv]):
                rc = main()
            self.assertEqual(rc, 0)
            config = _extract_router_config(out_file, "R1")
            self.assertIn("ipv6 route vrf Mgmt-vrf ::/0 fd80::1", config)

    def test_static_ipv6_gw_without_static_exits(self):
        with self.assertRaises(SystemExit) as cm:
            with patch.object(
                sys,
                "argv",
                [
                    "topogen",
                    "2",
                    "--mode",
                    "flat",
                    "-T",
                    "iosv",
                    "--mgmt",
                    "--mgmt-vrf",
                    "Mgmt-vrf",
                    "--mgmt-ipv6-gw",
                    "fd80::1",
                    "--offline-yaml",
                    "out/x.yaml",
                ],
            ):
                main()
        self.assertNotEqual(cm.exception.code, 0)

    def test_static_ipv6_gw_vrf_without_gw_exits(self):
        with self.assertRaises(SystemExit) as cm:
            with patch.object(
                sys,
                "argv",
                [
                    "topogen",
                    *self._STATIC_BASE,
                    "--mgmt-ipv6-gw-vrf",
                    "Other-vrf",
                    "--offline-yaml",
                    "out/x.yaml",
                ],
            ):
                main()
        self.assertNotEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
