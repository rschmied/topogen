# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-13
#
# Purpose: TG-190 — unit tests for IPv6 SLAAC/DHCPv6 NaC mgmt sync parse/patch logic.
# Blast Radius: Test-only.

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from argparse import Namespace

from topogen.nac_mgmt_sync import (  # noqa: E402
    default_sync_mode_from_args,
    format_nac_device_host,
    parse_mgmt_ipv6,
    patch_nac_files,
    resolve_sync_mode,
)

IFACE = "GigabitEthernet0/5"

BRIEF_GLOBAL_SLAAC = """
Interface              IPv6-Address                  Status
GigabitEthernet0/0     unassigned                    [down/down]
GigabitEthernet0/5     [up/up]
    FE80::5054:FF:FE58:4AA4
    2001:db8:1700:21F8:7EC0:5054:FF:FE58:4AA4
GigabitEthernet0/1     unassigned                    [down/down]
"""

BRIEF_FD00_ONLY = """
GigabitEthernet0/5     [up/up]
    FE80::1
    fd00:10:254:0:5054:ff:fe12:3456
"""

BRIEF_LINK_LOCAL_ONLY = """
GigabitEthernet0/5     [up/up]
    FE80::5054:FF:FE58:4AA4
"""

DETAIL_GLOBAL = """
GigabitEthernet0/5 is up, line protocol is up
  IPv6 is enabled, link-local address is FE80::5054:FF:FE58:4AA4
  Global unicast address(es):
    2001:db8:1700:21F8:7EC0:5054:FF:FE58:4AA4, subnet is 2001:db8:1700:21F8:7EC0::/64 [VALID]
  Joined group address(es):
    FF02::1
  MTU is 1500 bytes
"""

BRIEF_COMPACT_LINE = """
GigabitEthernet0/5     2001:db8:1700:21F8:7EC0:5054:FF:FE58:4AA4
GigabitEthernet0/1     unassigned
"""


def _write_min_nac_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "nac.yaml").write_text(
        yaml.safe_dump(
            {
                "iosxe": {
                    "devices": [
                        {"name": "iosv-01", "configuration": {"system": {"hostname": "R1"}}},
                        {"name": "iosv-02", "configuration": {"system": {"hostname": "R2"}}},
                    ]
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "inventory.yaml").write_text(
        yaml.safe_dump(
            {
                "all": {
                    "hosts": {
                        "iosv-01": {"ansible_host": "", "platform": "iosxe"},
                        "iosv-02": {"ansible_host": "", "platform": "iosxe"},
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (root / "devices.yaml").write_text(
        yaml.safe_dump(
            {
                "devices": [
                    {"name": "iosv-01", "hostname": "R1", "mgmt_ip": ""},
                    {"name": "iosv-02", "hostname": "R2", "mgmt_ip": ""},
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


class TestDefaultSyncModeFromArgs(unittest.TestCase):
    def test_slaac_maps_to_ipv6_sync(self):
        args = Namespace(mgmt_ipv6_mode="slaac")
        self.assertEqual(default_sync_mode_from_args(args), "slaac")

    def test_dhcpv6_maps_to_ipv6_sync(self):
        args = Namespace(mgmt_ipv6_mode="dhcpv6")
        self.assertEqual(default_sync_mode_from_args(args), "slaac")

    def test_no_ipv6_mode_maps_to_dhcp(self):
        args = Namespace(mgmt_ipv6_mode=None)
        self.assertEqual(default_sync_mode_from_args(args), "dhcp")


class TestResolveSyncModeAuto(unittest.TestCase):
    def test_auto_prefers_mgmt_ipv6_mode_dhcpv6_over_mgmt_mode_dhcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            nac_root = Path(tmp)
            (nac_root / "nac_metadata.yaml").write_text(
                yaml.safe_dump(
                    {"mgmt_mode": "dhcp", "mgmt_ipv6_mode": "dhcpv6"},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                resolve_sync_mode("auto", nac_root=nac_root, default_mode="dhcp"),
                "slaac",
            )


class TestParseMgmtIpv6(unittest.TestCase):
    def test_parses_global_slaac_from_brief(self):
        got = parse_mgmt_ipv6(BRIEF_GLOBAL_SLAAC, IFACE)
        self.assertEqual(got, "2001:db8:1700:21f8:7ec0:5054:ff:fe58:4aa4")

    def test_prefers_global_over_link_local(self):
        got = parse_mgmt_ipv6(BRIEF_FD00_ONLY, IFACE)
        self.assertEqual(got, "fd00:10:254:0:5054:ff:fe12:3456")

    def test_link_local_only_returns_none(self):
        self.assertIsNone(parse_mgmt_ipv6(BRIEF_LINK_LOCAL_ONLY, IFACE))

    def test_parses_detail_output(self):
        got = parse_mgmt_ipv6(DETAIL_GLOBAL, IFACE)
        self.assertEqual(got, "2001:db8:1700:21f8:7ec0:5054:ff:fe58:4aa4")

    def test_parses_compact_single_line(self):
        got = parse_mgmt_ipv6(BRIEF_COMPACT_LINE, IFACE)
        self.assertEqual(got, "2001:db8:1700:21f8:7ec0:5054:ff:fe58:4aa4")

    def test_missing_interface_returns_none(self):
        self.assertIsNone(parse_mgmt_ipv6(BRIEF_COMPACT_LINE, "GigabitEthernet0/99"))


class TestPatchNacFilesIpv6(unittest.TestCase):
    def test_patches_host_inventory_and_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            nac_root = Path(tmp)
            _write_min_nac_tree(nac_root)
            mapping = {
                "iosv-01": "2001:db8:1700:21f8:7ec0:5054:ff:fe58:4aa4",
                "iosv-02": "fd00:10:254:0:5054:ff:fe12:3456",
            }
            patch_nac_files(nac_root, mapping)

            nac = yaml.safe_load((nac_root / "nac.yaml").read_text(encoding="utf-8"))
            by_name = {d["name"]: d for d in nac["iosxe"]["devices"]}
            self.assertEqual(
                by_name["iosv-01"]["host"],
                "[2001:db8:1700:21f8:7ec0:5054:ff:fe58:4aa4]",
            )
            self.assertEqual(
                format_nac_device_host("10.254.0.5"),
                "10.254.0.5",
            )

            inv = yaml.safe_load((nac_root / "inventory.yaml").read_text(encoding="utf-8"))
            self.assertEqual(
                inv["all"]["hosts"]["iosv-02"]["ansible_host"],
                mapping["iosv-02"],
            )

            dev = yaml.safe_load((nac_root / "devices.yaml").read_text(encoding="utf-8"))
            by_dev = {d["name"]: d for d in dev["devices"]}
            self.assertEqual(by_dev["iosv-01"]["mgmt_ip"], mapping["iosv-01"])

            mapping_ipv4 = {"iosv-01": "192.168.1.10"}
            patch_nac_files(nac_root, mapping, mapping_ipv4)
            dev = yaml.safe_load((nac_root / "devices.yaml").read_text(encoding="utf-8"))
            by_dev = {d["name"]: d for d in dev["devices"]}
            self.assertEqual(by_dev["iosv-01"]["mgmt_ipv4"], "192.168.1.10")
            self.assertNotIn("mgmt_ipv4", by_dev["iosv-02"])

            report = {
                "mode": "slaac",
                "synced": len(mapping),
                "mapping": mapping,
            }
            report_path = nac_root / "mgmt_sync.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["synced"], 2)
            self.assertEqual(loaded["mode"], "slaac")


if __name__ == "__main__":
    unittest.main()
