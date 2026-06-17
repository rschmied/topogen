#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-13
#
# - Called by: emitted nac/sync-nac-mgmt.py, topogen sync-nac-mgmt subcommand
# - Reads from: CML virl2_client, controller pyATS, nac host_vars/devices.yaml
# - Writes to: host_vars/*.yaml, devices.yaml, mgmt_sync.json
# - Calls into: virl2_client, optional pyATS on CML controller
"""NaC OOB management host sync from live CML labs (DHCP IPv4 or SLAAC IPv6)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import Literal

import yaml

SyncMode = Literal["dhcp", "slaac"]

ROUTER_NODE_DEFINITIONS = frozenset({"csr1000v", "iosv"})
BRIDGE_PREFIX = "192.168.1."
IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
IPV6_CANDIDATE_RE = re.compile(
    r"(?<![0-9A-Fa-f:])(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,7}:|"
    r":(?::[0-9A-Fa-f]{1,4}){1,7}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}|"
    r"(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}|"
    r"[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}|"
    r":(?::[0-9A-Fa-f]{1,4}){1,7}|"
    r"fe80::[0-9A-Fa-f:]+|"
    r"FE80::[0-9A-Fa-f:]+"
    r")(?![0-9A-Fa-f:])",
    re.IGNORECASE,
)

REPORT_FILENAME = "mgmt_sync.json"


def mgmt_interface_name(node_definition: str, mgmt_slot: int) -> str:
    if node_definition == "iosv":
        return f"GigabitEthernet0/{mgmt_slot}"
    return f"GigabitEthernet{mgmt_slot}"


def canonical_name(index: int) -> str:
    return f"iosv-{index:02d}"


def default_sync_mode_from_args(args) -> SyncMode:
    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None) if args else None
    if ipv6_mode == "static":
        return "dhcp"
    if ipv6_mode in ("slaac", "dhcpv6"):
        return "slaac"
    return "dhcp"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def dump_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def format_nac_device_host(addr: str) -> str:
    """Bracket IPv6 for nac.yaml device host (Terraform/NETCONF); leave IPv4 unchanged."""
    raw = str(addr).strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    try:
        parsed = ip_address(raw)
    except ValueError:
        return addr
    if isinstance(parsed, IPv6Address):
        return f"[{parsed}]"
    if isinstance(parsed, IPv4Address):
        return str(parsed)
    return addr


def patch_nac_files(
    nac_root: Path,
    mapping: dict[str, str],
    mapping_ipv4: dict[str, str] | None = None,
) -> None:
    nac_yaml = nac_root / "nac.yaml"
    inventory_yaml = nac_root / "inventory.yaml"
    devices_yaml = nac_root / "devices.yaml"

    nac_data = load_yaml(nac_yaml)
    for device in nac_data.get("iosxe", {}).get("devices", []):
        name = device.get("name", "")
        if name in mapping:
            device["host"] = format_nac_device_host(mapping[name])
    dump_yaml(nac_yaml, nac_data)

    inv_data = load_yaml(inventory_yaml)
    host_groups: list[dict] = []
    all_block = inv_data.get("all", {})
    if isinstance(all_block.get("hosts"), dict):
        host_groups.append(all_block["hosts"])
    for group in all_block.get("children", {}).values():
        if isinstance(group, dict) and isinstance(group.get("hosts"), dict):
            host_groups.append(group["hosts"])
    for hosts in host_groups:
        for host_name, host_vars in hosts.items():
            if host_name in mapping and isinstance(host_vars, dict):
                host_vars["ansible_host"] = mapping[host_name]
    dump_yaml(inventory_yaml, inv_data)

    dev_data = load_yaml(devices_yaml)
    mapping_ipv4 = mapping_ipv4 or {}
    for device in dev_data.get("devices", []):
        name = device.get("name", "")
        if name in mapping:
            device["mgmt_ip"] = mapping[name]
        if name in mapping_ipv4:
            device["mgmt_ipv4"] = mapping_ipv4[name]
    dump_yaml(devices_yaml, dev_data)


def write_sync_report(nac_root: Path, report: dict) -> Path:
    report_path = nac_root / REPORT_FILENAME
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def resolve_sync_mode(
    mode: str,
    *,
    nac_root: Path | None = None,
    default_mode: SyncMode = "dhcp",
) -> SyncMode:
    if mode == "auto":
        if nac_root is not None:
            metadata_path = nac_root / "nac_metadata.yaml"
            if metadata_path.is_file():
                metadata = load_yaml(metadata_path)
                mgmt_ipv6_mode = str(metadata.get("mgmt_ipv6_mode", "")).lower()
                if mgmt_ipv6_mode == "static":
                    return "dhcp"
                if mgmt_ipv6_mode in ("slaac", "dhcpv6"):
                    return "slaac"
                mgmt_mode = str(metadata.get("mgmt_mode", "")).lower()
                if mgmt_mode in ("dhcp", "slaac"):
                    return mgmt_mode  # type: ignore[return-value]
        return default_mode
    if mode not in ("dhcp", "slaac"):
        raise ValueError(f"unsupported sync mode: {mode}")
    return mode  # type: ignore[return-value]


def _collect_router_nodes(lab):
    routers = []
    for node in lab.nodes():
        if node.node_definition not in ROUTER_NODE_DEFINITIONS:
            continue
        label = node.label
        if not label.startswith("R") or not label[1:].isdigit():
            continue
        routers.append((int(label[1:]), node))
    routers.sort(key=lambda item: item[0])
    return routers


def _cml_client():
    try:
        from virl2_client import ClientLibrary
    except ImportError as exc:
        raise RuntimeError("virl2_client is required") from exc
    url = os.environ.get("VIRL2_URL", "https://192.168.1.183")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    return ClientLibrary(url, user, password, ssl_verify=False)


# --- DHCP (IPv4) ---


def _dhcp_fix_commands(iface_name: str) -> str:
    return (
        f"interface {iface_name}\n"
        "no ip address\n"
        "ip address dhcp\n"
        "no shutdown"
    )


def _bridge_ip_from_addresses(addresses: object) -> str | None:
    if not addresses:
        return None
    candidates = [addresses] if isinstance(addresses, str) else list(addresses)
    for candidate in candidates:
        try:
            ip = ip_address(str(candidate))
        except ValueError:
            continue
        if str(ip).startswith(BRIDGE_PREFIX):
            return str(ip)
    return None


def _mgmt_ip_from_cml_interface(node, iface_name: str) -> str | None:
    for iface in node.interfaces():
        if iface.label != iface_name:
            continue
        mgmt_ip = _bridge_ip_from_addresses(getattr(iface, "discovered_ipv4", None))
        if mgmt_ip:
            return mgmt_ip
        snooped = getattr(iface, "ip_snooped_info", None) or {}
        return _bridge_ip_from_addresses(snooped.get("ipv4"))
    return None


def _parse_mgmt_ipv4(output: str, iface_name: str) -> str | None:
    for line in output.splitlines():
        if iface_name not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        candidate = parts[1]
        if candidate == "unassigned":
            continue
        try:
            ip = ip_address(candidate)
        except ValueError:
            continue
        if str(ip).startswith(BRIDGE_PREFIX):
            return str(ip)
    return None


def sync_dhcp_from_lab(
    lab,
    *,
    nac_root: Path,
    mgmt_slot: int,
    device_template: str,
    fix_dhcp: bool = False,
    lab_id: str | None = None,
) -> tuple[dict[str, str], dict]:
    iface_name = mgmt_interface_name(device_template, mgmt_slot)
    mapping: dict[str, str] = {}
    report: dict[str, object] = {
        "mode": "dhcp",
        "lab_id": lab_id,
        "nac_root": str(nac_root),
        "mgmt_interface": iface_name,
        "routers": {},
    }

    for node in lab.nodes():
        if node.node_definition not in ROUTER_NODE_DEFINITIONS:
            continue
        label = node.label
        if not label.startswith("R") or not label[1:].isdigit():
            continue
        index = int(label[1:])
        canonical = canonical_name(index)
        entry: dict[str, str | None] = {
            "state": str(node.state),
            "mgmt_ip": None,
            "source": None,
            "error": None,
        }

        if str(node.state) != "BOOTED":
            report["routers"][label] = entry
            continue

        node_iface = mgmt_interface_name(node.node_definition, mgmt_slot)
        mgmt_ip: str | None = None
        try:
            if fix_dhcp:
                node.run_pyats_config_command(_dhcp_fix_commands(node_iface))
            show_cmd = f"show ip interface brief | include {node_iface}"
            output = node.run_pyats_command(show_cmd, config=False)
            mgmt_ip = _parse_mgmt_ipv4(str(output), node_iface)
            if mgmt_ip:
                entry["source"] = "pyats"
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc) or type(exc).__name__

        if not mgmt_ip:
            mgmt_ip = _mgmt_ip_from_cml_interface(node, node_iface)
            if mgmt_ip:
                entry["source"] = "cml_snooped"
                entry["error"] = None

        entry["mgmt_ip"] = mgmt_ip
        if mgmt_ip:
            mapping[canonical] = mgmt_ip
        report["routers"][label] = entry

    return mapping, report


# --- SLAAC (IPv6) ---


def _is_global_unicast(ip: IPv6Address) -> bool:
    return (
        not ip.is_link_local
        and not ip.is_loopback
        and not ip.is_multicast
        and not ip.is_unspecified
    )


def _normalize_ipv6(raw: str) -> str | None:
    candidate = raw.strip().strip("[]").split("/")[0].split("%")[0]
    try:
        ip = ip_address(candidate)
    except ValueError:
        return None
    if ip.version != 6:
        return None
    return str(ip)


def _extract_ipv6_candidates(text: str) -> list[str]:
    found: list[str] = []
    for match in IPV6_CANDIDATE_RE.finditer(text):
        normalized = _normalize_ipv6(match.group(0))
        if normalized and normalized not in found:
            found.append(normalized)
    return found


def pick_preferred_global(addresses: list[str]) -> str | None:
    globals_: list[str] = []
    for addr in addresses:
        ip = ip_address(addr)
        if isinstance(ip, IPv6Address) and _is_global_unicast(ip):
            globals_.append(addr)
    if not globals_:
        return None
    for prefix in ("2001:db8:", "fd00:"):
        for addr in globals_:
            if addr.lower().startswith(prefix):
                return addr
    return globals_[0]


def _iface_section(output: str, iface_name: str) -> str:
    lines = output.splitlines()
    section: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if not in_section:
            if iface_name in line and (
                stripped.startswith("GigabitEthernet") or stripped.startswith("Gi")
            ):
                in_section = True
                section = [line]
            continue
        if stripped.startswith("GigabitEthernet") and iface_name not in line:
            break
        if stripped.startswith("Gi") and iface_name not in line and "Ethernet" not in iface_name:
            break
        section.append(line)
    return "\n".join(section)


def parse_mgmt_ipv6(output: str, iface_name: str) -> str | None:
    """Parse global SLAAC IPv6 for iface from show ipv6 interface* output."""
    section = _iface_section(output, iface_name)
    if not section:
        for line in output.splitlines():
            if iface_name not in line:
                continue
            if "unassigned" in line.lower():
                continue
            addrs = _extract_ipv6_candidates(line)
            picked = pick_preferred_global(addrs)
            if picked:
                return picked
        return None
    addrs = _extract_ipv6_candidates(section)
    return pick_preferred_global(addrs)


def mgmt_ipv6_from_cml_interface(node, iface_name: str) -> str | None:
    for iface in node.interfaces():
        if iface.label != iface_name:
            continue
        candidates: list[str] = []
        for source in (
            getattr(iface, "discovered_ipv6", None),
            (getattr(iface, "ip_snooped_info", None) or {}).get("ipv6"),
        ):
            if not source:
                continue
            if isinstance(source, str):
                candidates.append(source)
            else:
                candidates.extend(str(item) for item in source)
        normalized: list[str] = []
        for candidate in candidates:
            normalized_addr = _normalize_ipv6(str(candidate))
            if normalized_addr:
                normalized.append(normalized_addr)
        return pick_preferred_global(normalized)
    return None


def sync_slaac_from_lab(
    lab,
    *,
    nac_root: Path,
    mgmt_slot: int,
    device_template: str,
    cml_snoop_only: bool = False,
    set_pyats_creds: bool = False,
    progress_every: int = 25,
    lab_id: str | None = None,
) -> tuple[dict[str, str], dict]:
    lab.sync_l3_addresses_if_outdated()
    iface_name = mgmt_interface_name(device_template, mgmt_slot)
    mapping: dict[str, str] = {}
    mapping_ipv4: dict[str, str] = {}
    report: dict[str, object] = {
        "mode": "slaac",
        "lab_id": lab_id,
        "nac_root": str(nac_root),
        "mgmt_interface": iface_name,
        "routers": {},
    }

    routers = _collect_router_nodes(lab)
    total = len(routers)
    processed = 0

    pyats_creds = {
        "username": os.environ.get("IOSXE_USERNAME", "cisco"),
        "password": os.environ.get("IOSXE_PASSWORD", "cisco"),
        "enable_password": os.environ.get("IOSXE_ENABLE_PASSWORD", "cisco"),
    }

    for index, node in routers:
        label = node.label
        canonical = canonical_name(index)
        entry: dict[str, str | None] = {
            "state": str(node.state),
            "mgmt_ipv6": None,
            "mgmt_ipv4": None,
            "source": None,
            "ipv4_source": None,
            "error": None,
        }

        if str(node.state) != "BOOTED":
            report["routers"][label] = entry
            processed += 1
            continue

        node_iface = mgmt_interface_name(node.node_definition, mgmt_slot)
        mgmt_ipv6: str | None = None
        if not cml_snoop_only:
            try:
                if set_pyats_creds:
                    node.update({"pyats": pyats_creds}, exclude_configurations=True)

                brief_out = str(node.run_pyats_command("show ipv6 interface brief", config=False))
                mgmt_ipv6 = parse_mgmt_ipv6(brief_out, node_iface)
                if mgmt_ipv6:
                    entry["source"] = "pyats_brief"
                else:
                    detail_out = str(
                        node.run_pyats_command(f"show ipv6 interface {node_iface}", config=False)
                    )
                    mgmt_ipv6 = parse_mgmt_ipv6(detail_out, node_iface)
                    if mgmt_ipv6:
                        entry["source"] = "pyats_detail"
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc) or type(exc).__name__

        if not mgmt_ipv6:
            mgmt_ipv6 = mgmt_ipv6_from_cml_interface(node, node_iface)
            if mgmt_ipv6:
                entry["source"] = "cml_snooped"
                entry["error"] = None

        entry["mgmt_ipv6"] = mgmt_ipv6
        if mgmt_ipv6:
            mapping[canonical] = mgmt_ipv6

        mgmt_ipv4: str | None = None
        if not cml_snoop_only:
            try:
                ip_brief = str(
                    node.run_pyats_command(
                        f"show ip interface brief | include {node_iface}",
                        config=False,
                    )
                )
                mgmt_ipv4 = _parse_mgmt_ipv4(ip_brief, node_iface)
                if mgmt_ipv4:
                    entry["ipv4_source"] = "pyats"
            except Exception:  # noqa: BLE001
                pass
        if not mgmt_ipv4:
            mgmt_ipv4 = _mgmt_ip_from_cml_interface(node, node_iface)
            if mgmt_ipv4:
                entry["ipv4_source"] = "cml_snooped"
        entry["mgmt_ipv4"] = mgmt_ipv4
        if mgmt_ipv4:
            mapping_ipv4[canonical] = mgmt_ipv4

        report["routers"][label] = entry

        processed += 1
        if progress_every and processed % progress_every == 0:
            print(
                f"progress: {processed}/{total} routers polled, {len(mapping)} IPv6 synced",
                file=sys.stderr,
            )

    report["total_routers"] = total
    if mapping_ipv4:
        report["mapping_ipv4"] = mapping_ipv4
    return mapping, report


def sync_nac_mgmt(
    *,
    mode: SyncMode,
    nac_root: Path,
    lab_id: str | None = None,
    mapping_file: Path | None = None,
    mgmt_slot: int = 5,
    device_template: str = "iosv",
    fix_dhcp: bool = False,
    cml_snoop_only: bool = False,
    set_pyats_creds: bool = False,
    progress_every: int = 25,
) -> int:
    if mapping_file:
        mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
        patch_nac_files(nac_root, mapping)
        report = {"mode": mode, "synced": len(mapping), "mapping": mapping}
        report_path = write_sync_report(nac_root, report)
        print(json.dumps({"synced": len(mapping), "report": str(report_path)}, indent=2))
        return 0

    metadata_path = nac_root / "nac_metadata.yaml"
    if metadata_path.is_file():
        metadata = load_yaml(metadata_path)
        if str(metadata.get("mgmt_ipv6_mode", "")).lower() == "static":
            report = {
                "mode": "static",
                "skipped": True,
                "reason": "static IPv6 OOB inventory complete at generate time",
            }
            report_path = write_sync_report(nac_root, report)
            print(
                "INFO: static IPv6 OOB — inventory complete at generate time; "
                "skipping live sync.",
                file=sys.stderr,
            )
            print(json.dumps({"skipped": True, "report": str(report_path)}, indent=2))
            return 0

    if not lab_id:
        print("--lab-id is required unless --mapping-file is provided", file=sys.stderr)
        return 1

    client = _cml_client()
    lab = client.join_existing_lab(lab_id)

    if mode == "dhcp":
        mapping, report = sync_dhcp_from_lab(
            lab,
            nac_root=nac_root,
            mgmt_slot=mgmt_slot,
            device_template=device_template,
            fix_dhcp=fix_dhcp,
            lab_id=lab_id,
        )
        exit_code = 0
    else:
        mapping, report = sync_slaac_from_lab(
            lab,
            nac_root=nac_root,
            mgmt_slot=mgmt_slot,
            device_template=device_template,
            cml_snoop_only=cml_snoop_only,
            set_pyats_creds=set_pyats_creds,
            progress_every=progress_every,
            lab_id=lab_id,
        )
        exit_code = 0 if mapping else 1

    if mapping:
        patch_nac_files(nac_root, mapping, report.get("mapping_ipv4"))

    report["synced"] = len(mapping)
    report["mapping"] = mapping
    if report.get("mapping_ipv4"):
        report["synced_ipv4"] = len(report["mapping_ipv4"])
    report_path = write_sync_report(nac_root, report)
    print(json.dumps({"synced": len(mapping), "report": str(report_path)}, indent=2))
    return exit_code


def build_argparser(default_mode: SyncMode = "dhcp") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync NaC mgmt hosts from live CML OOB addresses (DHCP or SLAAC)."
    )
    parser.add_argument("--lab-id", help="CML lab UUID (required unless --mapping-file)")
    parser.add_argument("--nac-root", required=True, type=Path, help="Path to nac/ output tree")
    parser.add_argument(
        "--mode",
        choices=("dhcp", "slaac", "auto"),
        default=default_mode,
        help=f"Address discovery mode (default: {default_mode}; auto reads nac_metadata.yaml)",
    )
    parser.add_argument(
        "--mapping-file",
        type=Path,
        help="JSON map of iosv-NN -> mgmt address (skip CML polling)",
    )
    parser.add_argument(
        "--device-template",
        choices=("iosv", "csr1000v"),
        default="iosv",
        help="Router image family for mgmt interface naming",
    )
    parser.add_argument(
        "--mgmt-slot",
        type=int,
        default=5,
        help="Mgmt interface slot (default 5)",
    )
    parser.add_argument(
        "--fix-dhcp",
        action="store_true",
        help="(dhcp) Push Gi DHCP remediation on BOOTED routers before reading addresses",
    )
    parser.add_argument(
        "--cml-snoop-only",
        action="store_true",
        help="(slaac) Use CML L3 address snooping only (no local pyATS)",
    )
    parser.add_argument(
        "--set-pyats-creds",
        action="store_true",
        help="(slaac) Set pyATS credentials from IOSXE_* env vars before polling",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="(slaac) Print progress every N routers (0 disables)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)
    try:
        mode = resolve_sync_mode(args.mode, nac_root=args.nac_root)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return sync_nac_mgmt(
        mode=mode,
        nac_root=args.nac_root,
        lab_id=args.lab_id,
        mapping_file=args.mapping_file,
        mgmt_slot=args.mgmt_slot,
        device_template=args.device_template,
        fix_dhcp=args.fix_dhcp,
        cml_snoop_only=args.cml_snoop_only,
        set_pyats_creds=args.set_pyats_creds,
        progress_every=args.progress_every,
    )


if __name__ == "__main__":
    raise SystemExit(main())
