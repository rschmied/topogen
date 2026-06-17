#!/usr/bin/env python3
"""DMVPN day-0 vs NaC gap audit helper (offline).

Generates audit lab profiles (optional), scans offline CML YAML day-0 stanzas and
nac.yaml configuration.* per device, and prints a feature coverage summary.

Usage (from repo root):
  python scripts/audit-dmvpn-day0-nac-gap.py --scan-existing
  python scripts/audit-dmvpn-day0-nac-gap.py --generate --overwrite
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# Day-0 CLI signatures (regex on per-router configuration block)
DAY0_FEATURES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("NBMA underlay IPv4", re.compile(r"interface GigabitEthernet\d+.*\n(?:.*\n)*? ip address ", re.M)),
    ("Pair link IPv4", re.compile(r"interface GigabitEthernet2\b", re.M)),
    ("Loopback0 IPv4", re.compile(r"interface Loopback0\b", re.M)),
    ("Tunnel0 IPv4", re.compile(r"interface Tunnel0\b", re.M)),
    ("tunnel source", re.compile(r"tunnel source GigabitEthernet", re.M)),
    ("no ip redirects", re.compile(r"no ip redirects", re.M)),
    ("GRE mGRE mode", re.compile(r"tunnel mode gre multipoint", re.M)),
    ("tunnel key", re.compile(r"tunnel key \d+", re.M)),
    ("tunnel vrf (fvrf)", re.compile(r"tunnel vrf \S+", re.M)),
    ("ip tcp adjust-mss", re.compile(r"ip tcp adjust-mss \d+", re.M)),
    ("tunnel protection ipsec", re.compile(r"tunnel protection ipsec profile", re.M)),
    ("NHRP (any)", re.compile(r"ip nhrp ", re.M)),
    ("NHRP hub multicast dynamic", re.compile(r"ip nhrp map multicast dynamic", re.M)),
    ("NHRP spoke NHS", re.compile(r"ip nhrp nhs ", re.M)),
    ("EIGRP over tunnel", re.compile(r"router eigrp", re.M)),
    ("Overlay/pair VRF", re.compile(r"vrf definition \S+|vrf forwarding \S+", re.M)),
    ("IKEv2 proposal/policy/profile", re.compile(r"crypto ikev2 (proposal|policy|profile)", re.M)),
    ("IKEv2-PSK keyring", re.compile(r"crypto ikev2 keyring", re.M)),
    ("IKEv2 rsa-sig (PKI)", re.compile(r"authentication (local|remote) rsa-sig", re.M)),
    ("IPsec transform/profile", re.compile(r"crypto ipsec (transform-set|profile)", re.M)),
    ("PKI trustpoint/enrollment", re.compile(r"crypto pki trustpoint", re.M)),
    ("OOB mgmt Gi5 DHCP", re.compile(r"interface GigabitEthernet5\b.*\n(?:.*\n)*? ip address dhcp", re.M)),
)

NAC_TUNNEL_KEYS = (
    "tunnel_source",
    "tunnel_vrf",
    "ip_mtu",
    "tunnel_protection_ipsec_profile",
    "vrf_forwarding",
)
NAC_IPV4_TUNNEL_KEYS = ("redirects",)


@dataclass(frozen=True)
class AuditProfile:
    profile_id: str
    argv: tuple[str, ...]
    offline_rel: str


PROFILES: tuple[AuditProfile, ...] = (
    AuditProfile("P1", ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1", "-T", "csr-dmvpn", "--device-template", "csr1000v"), "out/TG-GAP-AUDIT-P1-baseline-1hub"),
    AuditProfile("P2", ("6", "--mode", "dmvpn", "--dmvpn-hubs", "1,3,5", "-T", "csr-dmvpn", "--device-template", "csr1000v"), "out/TG-GAP-AUDIT-P2-3hub"),
    AuditProfile("P3", ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1", "-T", "csr-dmvpn", "--device-template", "csr1000v", "--dmvpn-security", "ikev2-psk", "--dmvpn-psk", "TopogenDummyPsk123!"), "out/TG-GAP-AUDIT-P3-psk"),
    AuditProfile("P4", ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1", "-T", "csr-dmvpn", "--device-template", "csr1000v", "--dmvpn-security", "ikev2-pki", "--pki"), "out/TG-GAP-AUDIT-P4-pki"),
    AuditProfile("P5", ("4", "--mode", "dmvpn", "--dmvpn-underlay", "flat-pair", "--vrf", "--pair-vrf", "tenant", "-T", "csr-dmvpn", "--device-template", "csr1000v"), "out/TG-GAP-AUDIT-P5-pair-vrf"),
    AuditProfile("P6", ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1", "-T", "csr-dmvpn", "--device-template", "csr1000v", "--dmvpn-fvrf", "WAN-VRF"), "out/TG-GAP-AUDIT-P6-fvrf"),
    AuditProfile("P7", ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1", "-T", "csr-dmvpn", "--device-template", "csr1000v", "--mgmt", "--mgmt-bridge"), "out/TG-GAP-AUDIT-P7-mgmt"),
    AuditProfile("P8", ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1", "-T", "iosv-dmvpn", "--device-template", "iosv"), "out/TG-GAP-AUDIT-P8-iosv"),
)


def _lab_dir(profile: AuditProfile) -> Path:
    return ROOT / profile.offline_rel


def _offline_yaml(profile: AuditProfile) -> Path:
    base = _lab_dir(profile)
    return base / f"{base.name}.yaml"


def _nac_yaml(profile: AuditProfile) -> Path:
    return _lab_dir(profile) / "nac" / "nac.yaml"


def generate_profiles(overwrite: bool) -> None:
    for profile in PROFILES:
        argv = ["python", "-m", "topogen", *profile.argv, "--offline-yaml", profile.offline_rel, "--nac"]
        if overwrite:
            argv.append("--overwrite")
        print(" ".join(argv))
        subprocess.run(argv, cwd=ROOT, check=True)


def _router_day0_blocks(offline_path: Path) -> dict[str, str]:
    data = yaml.safe_load(offline_path.read_text(encoding="utf-8"))
    blocks: dict[str, str] = {}
    for node in data.get("nodes", []):
        label = str(node.get("label", ""))
        if not re.fullmatch(r"R\d+", label):
            continue
        cfg = node.get("configuration", "")
        if isinstance(cfg, list):
            cfg = "\n".join(
                item.get("content", "") for item in cfg if isinstance(item, dict)
            )
        blocks[label] = str(cfg)
    return blocks


def _nac_devices(nac_path: Path) -> dict[str, dict]:
    model = yaml.safe_load(nac_path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for device in model.get("iosxe", {}).get("devices", []):
        hostname = device.get("configuration", {}).get("system", {}).get("hostname")
        if hostname:
            out[str(hostname)] = device.get("configuration", {})
    return out


def _nac_has_tunnel_attr(config: dict, key: str) -> bool:
    tunnels = config.get("interfaces", {}).get("tunnels", [])
    return any(key in t for t in tunnels)


def _nac_has_crypto_psk(config: dict) -> bool:
    crypto = config.get("crypto", {})
    ikev2 = crypto.get("ikev2", {})
    return bool(ikev2.get("keyrings"))


def _nac_has_crypto_pki_body(config: dict) -> bool:
    crypto = config.get("crypto", {})
    profiles = crypto.get("ikev2", {}).get("profiles", [])
    return any(p.get("pki_trustpoint") or p.get("authentication_local_rsa_sig") for p in profiles)


def _day0_roles(blocks: dict[str, str]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for host, cfg in blocks.items():
        if "ip nhrp map multicast dynamic" in cfg:
            roles[host] = "hub"
        elif "ip nhrp nhs " in cfg:
            roles[host] = "spoke"
        else:
            roles[host] = "unknown"
    return roles


def scan_profile(profile: AuditProfile) -> None:
    offline = _offline_yaml(profile)
    nac = _nac_yaml(profile)
    if not offline.is_file() or not nac.is_file():
        print(f"[{profile.profile_id}] SKIP missing artifacts ({offline} / {nac})")
        return

    day0 = _router_day0_blocks(offline)
    nac_by_host = _nac_devices(nac)
    roles = _day0_roles(day0)

    print(f"\n=== {profile.profile_id} ({profile.offline_rel}) ===")
    print(f"Routers: {', '.join(sorted(day0))} | roles: {roles}")

    present_day0: list[str] = []
    for name, pattern in DAY0_FEATURES:
        if any(pattern.search(cfg) for cfg in day0.values()):
            present_day0.append(name)

    print(f"Day-0 features present ({len(present_day0)}):")
    for feat in present_day0:
        routers = [h for h, cfg in day0.items() if dict(DAY0_FEATURES)[feat].search(cfg)]
        print(f"  - {feat}: {','.join(routers)}")

    sample = next(iter(nac_by_host.values()), {})
    nac_signals = []
    if sample.get("interfaces", {}).get("ethernets"):
        nac_signals.append("ethernets")
    if sample.get("interfaces", {}).get("tunnels"):
        nac_signals.append("tunnels+ipv4")
    if _nac_has_tunnel_attr(sample, "tunnel_source"):
        nac_signals.append("tunnel_source")
    if _nac_has_tunnel_attr(sample, "tunnel_protection_ipsec_profile"):
        nac_signals.append("tunnel_protection_ipsec_profile")
    if _nac_has_tunnel_attr(sample, "tunnel_vrf"):
        nac_signals.append("tunnel_vrf")
    if _nac_has_tunnel_attr(sample, "ip_mtu"):
        nac_signals.append("ip_mtu")
    if sample.get("vrfs"):
        nac_signals.append("vrfs[]")
    if _nac_has_crypto_psk(sample):
        nac_signals.append("crypto IKEv2-PSK")
    if _nac_has_crypto_pki_body(sample):
        nac_signals.append("crypto IKEv2-PKI body")
    elif _nac_has_tunnel_attr(sample, "tunnel_protection_ipsec_profile") and not _nac_has_crypto_psk(sample):
        nac_signals.append("tunnel_protection WITHOUT crypto body (PKI gap)")

    print(f"NaC configuration.* signals: {', '.join(nac_signals) or '(minimal)'}")

    def _tunnel_shape(tunnels: list) -> str:
        if not tunnels:
            return ""
        t = dict(tunnels[0])
        t.pop("ipv4", None)
        return yaml.dump(t, default_flow_style=True)

    tunnel_shapes = {
        host: _tunnel_shape(nac_by_host.get(host, {}).get("interfaces", {}).get("tunnels") or [])
        for host in day0
    }
    unique_shapes = {s for s in tunnel_shapes.values() if s}
    if len(unique_shapes) > 1:
        print("  NaC tunnel attribute shape differs by router (e.g. flat-pair evens omit tunnel).")
    elif len(day0) > 1 and any(roles.get(h) == "hub" for h in day0) and any(roles.get(h) == "spoke" for h in day0):
        print("  WARN: hub and spoke share identical NaC tunnel shape (NHRP hub/spoke not projected).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Run topogen for all audit profiles")
    parser.add_argument("--overwrite", action="store_true", help="Pass --overwrite to topogen")
    parser.add_argument("--scan-existing", action="store_true", help="Scan generated out/TG-GAP-AUDIT-* trees")
    parser.add_argument("--profile", action="append", help="Limit to profile id (P1..P8)")
    args = parser.parse_args()

    if not args.generate and not args.scan_existing:
        parser.error("Specify --generate and/or --scan-existing")

    selected = PROFILES
    if args.profile:
        wanted = {p.upper() for p in args.profile}
        selected = tuple(p for p in PROFILES if p.profile_id in wanted)

    if args.generate:
        generate_profiles(args.overwrite)

    if args.scan_existing:
        for profile in selected:
            scan_profile(profile)

    return 0


if __name__ == "__main__":
    sys.exit(main())
