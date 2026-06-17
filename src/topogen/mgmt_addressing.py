# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.2
# Date Modified: 2026-06-13
#
# - Called by: render.py, tests/test_mgmt_addressing.py
# - Purpose: FF10-embedded static IPv6 OOB addressing from mgmt IPv4 carve

from __future__ import annotations

import re

from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Interface, IPv6Network

DEFAULT_MGMT_CIDR = "10.254.0.0/16"
_FF10_UPPER_RE = re.compile(r"(?i)(:|\b)ff10(?=:|$)")


def mgmt_ipv4_static_host(mgmt_cidr: str, router_index: int) -> IPv4Address:
    """Return deterministic mgmt IPv4 host for a router index."""
    net = IPv4Network(str(mgmt_cidr), strict=False)
    return IPv4Address(int(net.network_address) + int(router_index))


def parse_static_ipv6_anchor(cidr: str) -> IPv6Network:
    """Parse operator prefix and normalize to /64 anchor."""
    text = str(cidr).strip()
    if "/" not in text:
        text = f"{text}/64"
    iface = IPv6Interface(text)
    anchor_bytes = iface.ip.packed[:8] + b"\x00" * 8
    return IPv6Network((IPv6Address(anchor_bytes), 64), strict=False)


def _ff10_interface_id(ipv4_host: IPv4Address, mgmt_cidr: str) -> int:
    octets = ipv4_host.packed
    a, b, c, d = octets[0], octets[1], octets[2], octets[3]
    mgmt_net = IPv4Network(str(mgmt_cidr), strict=False)
    default_net = IPv4Network(DEFAULT_MGMT_CIDR, strict=False)
    if (
        mgmt_net.network_address == default_net.network_address
        and mgmt_net.prefixlen == default_net.prefixlen
    ) or (a == 10 and b == 254):
        ab_hextet = 0x254
    else:
        ab_hextet = (a << 8) | b
    return (0xFF10 << 48) | (ab_hextet << 32) | (c << 16) | d


def format_ff10_ipv6_interface(iface: IPv6Interface) -> str:
    """Render IPv6Interface with uppercase FF10 sentinel for IOS/NAC display."""
    text = iface.compressed
    return _FF10_UPPER_RE.sub(lambda m: f"{m.group(1)}FF10", text)


def mgmt_ipv6_static_address(
    ipv4_host: IPv4Address,
    anchor: IPv6Network,
    mgmt_cidr: str,
) -> str:
    """Map mgmt IPv4 carve + /64 anchor to global FF10 OOB address string."""
    iface_id = _ff10_interface_id(ipv4_host, mgmt_cidr)
    full = int(anchor.network_address) | iface_id
    return format_ff10_ipv6_interface(IPv6Interface(f"{IPv6Address(full)}/64"))


def mgmt_ipv6_static_link_local(loopback_host: IPv4Address) -> str:
    """Derive one fe80::FF10:… link-local string from Loopback0 IPv4."""
    a, b, c, d = loopback_host.packed
    if a == 10 and b == 20:
        tail = f"FF10:20:{c}:{d}"
    elif a == 10 and b == 255:
        tail = f"FF10:255:{c}:{d}"
    else:
        ab_hextet = (a << 8) | b
        tail = f"FF10:{ab_hextet}:{c}:{d}"
    return f"fe80::{tail}"


def slaac_global_from_loopback(prefix: str, loopback_host: IPv4Address) -> str:
    """Predict SLAAC global = prefix + IID from static fe80::FF10 link-local."""
    anchor = parse_static_ipv6_anchor(prefix)
    ll_addr = IPv6Address(mgmt_ipv6_static_link_local(loopback_host))
    iid = int(ll_addr) & ((1 << 64) - 1)
    full = int(anchor.network_address) | iid
    return format_ff10_ipv6_interface(IPv6Interface(f"{IPv6Address(full)}/64"))


def mgmt_ipv6_default_route_vrf(args: object) -> str | None:
    """Resolve VRF name for optional static ::/0 (None = global IPv6 table)."""
    explicit = getattr(args, "mgmt_ipv6_gw_vrf", None)
    if explicit is not None:
        if str(explicit).lower() == "global":
            return None
        return str(explicit)
    mgmt_vrf = getattr(args, "mgmt_vrf", None)
    if mgmt_vrf and str(mgmt_vrf).lower() == "global":
        return None
    return mgmt_vrf
