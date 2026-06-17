# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-06-13
#
# Purpose: TG-195 unit tests for FF10 static IPv6 OOB addressing helpers.

import sys
import unittest
from ipaddress import IPv4Address, IPv6Network
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.mgmt_addressing import (  # pylint: disable=wrong-import-position
    mgmt_ipv4_static_host,
    mgmt_ipv6_default_route_vrf,
    mgmt_ipv6_static_address,
    mgmt_ipv6_static_link_local,
    parse_static_ipv6_anchor,
    slaac_global_from_loopback,
)

DOC_PREFIX = "2001:db8:1:2::/64"
FD80_PREFIX = "fd80::/64"
DEFAULT_MGMT_CIDR = "10.254.0.0/16"


class TestMgmtAddressing(unittest.TestCase):
    def test_global_fd80_r1(self):
        host = mgmt_ipv4_static_host(DEFAULT_MGMT_CIDR, 1)
        anchor = parse_static_ipv6_anchor(FD80_PREFIX)
        addr = mgmt_ipv6_static_address(host, anchor, DEFAULT_MGMT_CIDR)
        self.assertEqual(addr, "fd80::FF10:254:0:1/64")

    def test_global_fd80_r2(self):
        host = mgmt_ipv4_static_host(DEFAULT_MGMT_CIDR, 2)
        anchor = parse_static_ipv6_anchor(FD80_PREFIX)
        addr = mgmt_ipv6_static_address(host, anchor, DEFAULT_MGMT_CIDR)
        self.assertEqual(addr, "fd80::FF10:254:0:2/64")

    def test_global_doc_prefix_r1(self):
        host = mgmt_ipv4_static_host(DEFAULT_MGMT_CIDR, 1)
        anchor = parse_static_ipv6_anchor(DOC_PREFIX)
        addr = mgmt_ipv6_static_address(host, anchor, DEFAULT_MGMT_CIDR)
        self.assertEqual(addr, "2001:db8:1:2:FF10:254:0:1/64")

    def test_global_third_octet(self):
        host = IPv4Address("10.254.2.1")
        anchor = parse_static_ipv6_anchor(DOC_PREFIX)
        addr = mgmt_ipv6_static_address(host, anchor, DEFAULT_MGMT_CIDR)
        self.assertEqual(addr, "2001:db8:1:2:FF10:254:2:1/64")

    def test_link_local_default_loopback_r1(self):
        ll = mgmt_ipv6_static_link_local(IPv4Address("10.20.0.1"))
        self.assertEqual(ll, "fe80::FF10:20:0:1")

    def test_link_local_default_loopback_r3(self):
        ll = mgmt_ipv6_static_link_local(IPv4Address("10.20.0.3"))
        self.assertEqual(ll, "fe80::FF10:20:0:3")

    def test_link_local_loopback_255_r1(self):
        ll = mgmt_ipv6_static_link_local(IPv4Address("10.255.0.1"))
        self.assertEqual(ll, "fe80::FF10:255:0:1")

    def test_slaac_global_from_loopback(self):
        predicted = slaac_global_from_loopback(FD80_PREFIX, IPv4Address("10.20.0.1"))
        self.assertEqual(predicted, "fd80::FF10:20:0:1/64")

    def test_parse_anchor_normalizes_slash64(self):
        for prefix in ("2001:db8:1:2::/48", "2001:db8:1:2::/56"):
            net = parse_static_ipv6_anchor(prefix)
            self.assertEqual(net.prefixlen, 64)
            self.assertEqual(str(net.network_address), "2001:db8:1:2::")

    def test_no_real_prefix_in_fixtures(self):
        for value in (DOC_PREFIX, FD80_PREFIX, DEFAULT_MGMT_CIDR):
            self.assertNotIn("2001:db8:", value)

    def test_default_route_vrf_explicit(self):
        class Args:
            mgmt_ipv6_gw_vrf = "Custom-vrf"
            mgmt_vrf = "Mgmt-vrf"

        self.assertEqual(mgmt_ipv6_default_route_vrf(Args()), "Custom-vrf")

    def test_default_route_vrf_falls_back_to_mgmt_vrf(self):
        class Args:
            mgmt_ipv6_gw_vrf = None
            mgmt_vrf = "Mgmt-vrf"

        self.assertEqual(mgmt_ipv6_default_route_vrf(Args()), "Mgmt-vrf")

    def test_default_route_vrf_global(self):
        class Args:
            mgmt_ipv6_gw_vrf = "global"
            mgmt_vrf = "Mgmt-vrf"

        self.assertIsNone(mgmt_ipv6_default_route_vrf(Args()))


if __name__ == "__main__":
    unittest.main()
