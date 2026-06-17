# File Chain (see DEVELOPER.md):
# Doc Version: v1.5.1
# Date Modified: 2026-06-13
#
# - Called by: src/topogen/main.py
# - Reads from: Packaged templates, Config, env (VIRL2_*), models
# - Writes to: Offline YAML (--offline-yaml), CML controller via virl2_client
# - Calls into: jinja2, virl2_client, dnshost.py, lxcfrr.py, nac.py, models.py
"""
TopoGen Topology Renderer - Core Topology Generation and Rendering Logic

PURPOSE:
    Core rendering engine for all topology modes. Handles both online (CML API) and
    offline (YAML file) generation. Implements the topology creation logic for:
    - Simple/NX mode: Star topology with central switch
    - Flat mode: Hierarchical unmanaged switch fabric (core + access switches)
    - Flat-pair mode: Odd-even router pairing with switch fabric
    - DMVPN mode: Hub-spoke DMVPN with NBMA underlay (flat or flat-pair)

WHO READS ME:
    - main.py: Creates Renderer instances and calls render methods

WHO I READ:
    - config.py: Config class for configuration defaults
    - models.py: TopogenNode, TopogenInterface, TopogenError, CoordsGenerator, DNShost, Point
    - dnshost.py: dnshostconfig() for DNS host configuration
    - lxcfrr.py: lxcfrr_bootconfig() for FRR LXC container configuration
    - templates/: Jinja2 templates (*.jinja2) for router configurations

DEPENDENCIES:
    External packages:
    - virl2_client: CML2 API client (ClientLibrary, Lab, Node, Interface)
    - httpx: HTTP client (ConnectTimeout, HTTPError)
    - jinja2: Template engine (Environment, PackageLoader, Template, select_autoescape)
    - networkx: Graph algorithms (for topology generation)
    - enlighten: Progress bar display

    Standard library:
    - ipaddress: IPv4 address/network calculations
    - pathlib, os: File operations
    - math: Ceiling calculations for switch counts
    - datetime: Timestamps
    - argparse: Namespace for CLI args

KEY EXPORTS:
    - Renderer: Main class containing all rendering methods
    - get_templates(): Returns list of available Jinja2 templates

KEY METHODS (Renderer class):
    Online (CML API) methods:
    - render_simple_network(): Simple/NX star topology (online)
    - render_flat_network(): Flat hierarchical topology (online)
    - render_flat_pair_network(): Flat-pair topology (online)
    - render_dmvpn(): DMVPN hub-spoke (online)

    Offline (YAML) static methods:
    - offline_flat_yaml(): Flat hierarchical topology (offline YAML)
    - offline_nx_yaml(): NX random shell graph topology (offline YAML)
    - offline_simple_yaml(): Simple chain (sequential) topology (offline YAML)
    - offline_flat_pair_yaml(): Flat-pair topology (offline YAML)
    - offline_dmvpn_yaml(): DMVPN with flat underlay (offline YAML)
    - offline_dmvpn_flat_pair_yaml(): DMVPN with flat-pair underlay (offline YAML)

ARCHITECTURE:
    - Online mode: Renderer.render_*() → CML API via virl2_client
    - Offline mode: Renderer.offline_*_yaml() → YAML file generation
    - Templates: Jinja2 templates in templates/ directory render router configs
    - Addressing: Deterministic IPv4 address allocation for all interfaces
    - Layout: Deterministic X/Y coordinates for visual topology in CML

TOPOLOGY MODES:
    1. Simple: Chain (R1-R2-...-Rn) with ext-conn + dns-host + spiral coords
    2. NX: Random shell graph + kamada_kawai layout with ext-conn + dns-host
    3. Flat: Core switch + access switches + N routers (hierarchical)
    4. Flat-pair: Odd routers paired with even routers + switch fabric
    5. DMVPN flat: Hub-spoke DMVPN with flat underlay switches
    6. DMVPN flat-pair: Hub-spoke DMVPN with flat-pair underlay

OOB MANAGEMENT:
    All modes support optional OOB management network (--mgmt):
    - SWoob0: Core OOB switch
    - SWoobN: Access OOB switches (one per group of routers)
    - ext-conn-mgmt: Optional external-connector for bridge mode (--mgmt-bridge)
"""

import html as html_module
import importlib.resources as pkg_resources
import logging
import math
import os
import threading
from pathlib import Path
from argparse import Namespace
from datetime import datetime, timedelta, timezone
from ipaddress import IPV4LENGTH, IPv4Address, IPv4Interface, IPv4Network
from typing import Any, Set, Tuple, Union

import enlighten
import networkx as nx

from httpx import ConnectTimeout, HTTPError
from jinja2 import (
    Environment,
    PackageLoader,
    Template,
    TemplateNotFound,
    select_autoescape,
)
from virl2_client import ClientLibrary, InitializationError
from virl2_client.models import Interface, Lab, Node

from topogen import templates
from topogen.cml2 import write_cml2_lifecycle_scaffold
from topogen.cml_server import append_cml_schema_provenance_args
from topogen.config import Config
from topogen.dnshost import dnshostconfig
from topogen.lxcfrr import lxcfrr_bootconfig
from topogen.mgmt_addressing import (
    mgmt_ipv4_static_host,
    mgmt_ipv6_default_route_vrf,
    mgmt_ipv6_static_address,
    mgmt_ipv6_static_link_local,
    parse_static_ipv6_anchor,
)
from topogen.nac import write_nac_tree
from topogen.models import (
    CoordsGenerator,
    DNShost,
    Point,
    TopogenError,
    TopogenInterface,
    TopogenNode,
)

_LOGGER = logging.getLogger(__name__)

EXT_CON_NAME = "ext-conn-0"
DNS_HOST_NAME = "dns-host"
SUPPORTED_NAC_DEVICE_TEMPLATES = {"iosv", "csr1000v"}


# Determine package version locally to avoid circular import with topogen.__init__
try:  # Python 3.8+
    from importlib.metadata import version as _pkg_version  # type: ignore
except Exception:  # pragma: no cover - very old Python fallback
    _pkg_version = None  # type: ignore

try:
    TOPGEN_VERSION = _pkg_version("topogen") if _pkg_version else "unknown"
except Exception:  # pragma: no cover - best effort
    TOPGEN_VERSION = "unknown"


INTENT_ANNOTATION_PADDING = 1500
CML_COORD_LIMIT = 15000


def _node_coords_from_offline_lines(lines: list[str]) -> list[tuple[int, int]]:
    """Collect node x/y pairs from generated offline YAML lines (nodes: section only)."""
    coords: list[tuple[int, int]] = []
    in_nodes = False
    pending_x: int | None = None
    for line in lines:
        stripped = line.strip()
        if stripped == "nodes:":
            in_nodes = True
            continue
        if in_nodes and stripped == "links:":
            break
        if not in_nodes:
            continue
        if stripped.startswith("x:"):
            pending_x = int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("y:") and pending_x is not None:
            coords.append((pending_x, int(stripped.split(":", 1)[1].strip())))
            pending_x = None
    return coords


def _scaled_intent_annotation_xy(
    node_coords: list[tuple[int, int]],
    padding: int = INTENT_ANNOTATION_PADDING,
) -> tuple[int, int]:
    """Place hidden intent annotation directly below the topology (down only, no x padding)."""
    if not node_coords:
        return 0, padding
    max_x = max(x for x, _ in node_coords)
    max_y = max(y for _, y in node_coords)
    return (
        min(max_x, CML_COORD_LIMIT),
        min(max_y + padding, CML_COORD_LIMIT),
    )


def _intent_annotation_lines(
    intent: str,
    version: str = "0.3.0",
    *,
    offline_lines: list[str] | None = None,
    node_coords: list[tuple[int, int]] | None = None,
) -> list[str]:
    """Return YAML lines for annotations + smart_annotations with one hidden intent annotation.

    Embeds intent at max(node x), max(node y)+padding (below the topology, not offset right).
    Same intent is also in
    lab.notes inside a hidden HTML span (visible in YAML/grep, not in CML guide).

    smart_annotations is omitted for schema versions <= 0.2.2 (CML 2.7 and earlier).
    """
    if node_coords is None and offline_lines is not None:
        node_coords = _node_coords_from_offline_lines(offline_lines)
    x1, y1 = _scaled_intent_annotation_xy(node_coords or [])
    content = intent.replace("'", "''")
    lines = [
        "annotations:",
        "  - border_color: '#FFFFFF'",
        "    border_style: ''",
        "    color: '#FFFFFF'",
        "    rotation: 0",
        "    text_bold: false",
        f"    text_content: '{content}'",
        "    text_font: monospace",
        "    text_italic: false",
        "    text_size: 1",
        "    text_unit: pt",
        "    thickness: 1",
        "    type: text",
        f"    x1: {x1}",
        f"    y1: {y1}",
        "    z_index: 0",
    ]
    if tuple(int(x) for x in version.split(".")) > (0, 2, 2):
        lines.append("smart_annotations: []")
    return lines


INTENT_SPOT_NODE_DEF = "unmanaged_switch"


def _intent_marker_node_lines(x: int, y: int, node_id: str = "n_intent_spot") -> list[str]:
    """Visible marker switch at the hidden intent annotation coordinates (no router license)."""
    return [
        f"  - id: {node_id}",
        "    label: INTENT-SPOT",
        f"    node_definition: {INTENT_SPOT_NODE_DEF}",
        f"    x: {x}",
        f"    y: {y}",
        "    interfaces:",
        "      - id: i0",
        "        slot: 0",
        "        label: port0",
        "        type: physical",
    ]


def _insert_intent_marker_node(lines: list[str], x: int, y: int) -> list[str]:
    """Insert INTENT-SPOT unmanaged_switch node immediately before the links: section."""
    marker = _intent_marker_node_lines(x, y)
    out: list[str] = []
    inserted = False
    for line in lines:
        if not inserted and line.strip() == "links:":
            out.extend(marker)
            inserted = True
        out.append(line)
    if not inserted:
        out.extend(marker)
    return out


def _finalize_offline_yaml_with_intent(
    lines: list[str],
    intent: str,
    version: str,
    args: Namespace,
) -> list[str]:
    """Prepend scaled intent annotation; optional INTENT-SPOT switch when --intent-spot."""
    coords = _node_coords_from_offline_lines(lines)
    x1, y1 = _scaled_intent_annotation_xy(coords)
    if getattr(args, "intent_spot", False):
        lines = _insert_intent_marker_node(lines, x1, y1)
    return _intent_annotation_lines(intent, version, node_coords=coords) + lines


def _intent_notes_html(intent: str) -> str:
    """Hidden HTML span for lab.notes (invisible in CML guide, grep-friendly in YAML/export)."""
    hidden_content = html_module.escape(intent)
    return f'<span style="color: white; font-size: 1pt; opacity: 0;">{hidden_content}</span>'


def _intent_notes_lines(intent: str) -> list[str]:
    """Return YAML lines for lab.notes: all content in white/hidden span so GUIDE shows nothing.

    Entire notes are invisible (color: white; opacity: 0). CI/CD can grep the YAML for the intent.
    """
    return [
        "  notes: |-",
        f"    {_intent_notes_html(intent)}",
    ]


def _node_coords_from_cml_lab(lab: Lab) -> list[tuple[int, int]]:
    """Collect canvas x/y from live CML nodes for scaled intent placement."""
    coords: list[tuple[int, int]] = []
    for node in lab.nodes():
        try:
            coords.append((int(node.x), int(node.y)))
        except (AttributeError, TypeError, ValueError):
            continue
    return coords


def _build_intent_description(args: Namespace, *, context: str) -> str:
    """Build provenance string for lab description (online API and offline YAML)."""
    args_bits: list[str] = [
        f"nodes={args.nodes}",
        f"-m {args.mode}",
        f"-T {args.template}",
    ]
    dev_def = getattr(args, "dev_template", args.template)
    if dev_def != args.template:
        args_bits.append(f"--device-template {dev_def}")
    if getattr(args, "enable_vrf", False):
        args_bits.append("--vrf")
        if getattr(args, "pair_vrf", None):
            args_bits.append(f"--pair-vrf {args.pair_vrf}")
    if str(args.mode).startswith("flat"):
        args_bits.append(f"--flat-group-size {args.flat_group_size}")
        if getattr(args, "loopback_255", False):
            args_bits.append("--loopback-255")
        if getattr(args, "gi0_zero", False):
            args_bits.append("--gi0-zero")
    if getattr(args, "enable_mgmt", False):
        args_bits.append("--mgmt")
        if getattr(args, "mgmt_vrf", None):
            args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
        if getattr(args, "mgmt_bridge", False):
            args_bits.append("--mgmt-bridge")
        _append_mgmt_ipv6_provenance_args(args_bits, args)
    if getattr(args, "ntp_server", None):
        args_bits.append(f"--ntp {args.ntp_server}")
        if getattr(args, "ntp_vrf", None):
            args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
    if getattr(args, "start_lab", False):
        args_bits.append("--start")
    append_cml_schema_provenance_args(args_bits, args)
    if getattr(args, "staging", False):
        args_bits.append("--staging")
    if getattr(args, "yaml_output", None):
        args_bits.append(f"--yaml {str(args.yaml_output).replace(chr(92), '/')}")
    _append_common_offline_args_bits(args_bits, args)
    if getattr(args, "labname", None):
        args_bits.append(f"-L {args.labname}")
    if getattr(args, "offline_yaml", None):
        args_bits.append(
            f"--offline-yaml {str(args.offline_yaml).replace(chr(92), '/')}"
        )
    desc = (
        f"Generated by topogen v{TOPGEN_VERSION} ({context}) | args: "
        + " ".join(args_bits)
    )
    if getattr(args, "remark", None):
        desc += f" | remark: {args.remark}"
    return desc


def _mgmt_test_alias_lines(mgmt_iface: str) -> list[str]:
    """Exec alias that shows OOB IPv6 interface state (no banner, no pipes)."""
    return [
        f"alias exec topogen-test show ipv6 interface {mgmt_iface}",
    ]


def _build_mgmt_context(
    args: object,
    *,
    mgmt_slot: int | None = None,
    router_index: int | None = None,
    loopback: IPv4Interface | None = None,
    hostname: str | None = None,
) -> dict[str, Any] | None:
    """Build Jinja mgmt context dict for OOB fabric plus optional IPv4/IPv6 addressing."""
    if not getattr(args, "enable_mgmt", False):
        return None
    slot = mgmt_slot if mgmt_slot is not None else int(getattr(args, "mgmt_slot", 5))
    ctx: dict[str, Any] = {
        "enabled": True,
        "slot": slot,
        "vrf": getattr(args, "mgmt_vrf", None),
        "gw": getattr(args, "mgmt_gw", None),
        "ipv6_gw": getattr(args, "mgmt_ipv6_gw", None),
        "ipv4_dhcp": bool(getattr(args, "mgmt_ipv4_dhcp", False)),
    }
    if getattr(args, "mgmt_ipv6_gw", None):
        ctx["ipv6_gw_vrf"] = mgmt_ipv6_default_route_vrf(args)
    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    if ipv6_mode == "static" and router_index is None:
        return ctx
    if ipv6_mode:
        ctx["ipv6_mode"] = ipv6_mode
        ctx["ipv6_static_link_local"] = bool(
            getattr(args, "mgmt_ipv6_static_link_local", False)
        )
        ipv6_cidr = getattr(args, "mgmt_ipv6_cidr", None)
        if ipv6_cidr:
            ctx["ipv6_cidr"] = ipv6_cidr
        loopback_ip = loopback.ip if loopback is not None else None
        link_local = None
        if getattr(args, "mgmt_ipv6_static_link_local", False) and loopback_ip is not None:
            link_local = mgmt_ipv6_static_link_local(loopback_ip)
            ctx["router_link_local"] = link_local
        if ipv6_mode == "static" and router_index is not None:
            mgmt_cidr = str(getattr(args, "mgmt_cidr", "10.254.0.0/16"))
            ipv4_host = mgmt_ipv4_static_host(mgmt_cidr, router_index)
            anchor = parse_static_ipv6_anchor(str(ipv6_cidr))
            v6_iface = mgmt_ipv6_static_address(ipv4_host, anchor, mgmt_cidr)
            ctx["ipv6_address"] = v6_iface
            label = hostname or f"R{router_index}"
            log_line = (
                f"mgmt IPv6 static {label}: global={v6_iface} "
                f"loopback={loopback_ip or 'n/a'}"
            )
            if link_local is not None:
                log_line += f" link-local={link_local}"
            _LOGGER.info(log_line)
    return ctx


def _append_mgmt_ipv6_provenance_args(args_bits: list[str], args: object) -> None:
    """Append IPv6 OOB provenance flags to an args_bits list."""
    if getattr(args, "mgmt_ipv4_dhcp", False):
        args_bits.append("--mgmt-ipv4-dhcp")
    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    if ipv6_mode == "dhcpv6":
        args_bits.append("--mgmt-ipv6-dhcp")
    elif ipv6_mode == "slaac":
        args_bits.append("--mgmt-ipv6-slaac")
    elif ipv6_mode == "static":
        args_bits.append("--mgmt-ipv6-static")
    elif ipv6_mode:
        args_bits.append(f"--mgmt-ipv6-mode {ipv6_mode}")
    if getattr(args, "mgmt_ipv6_static_link_local", False):
        args_bits.append("--mgmt-ipv6-static-link-local")
    if getattr(args, "mgmt_ipv6_cidr", None):
        args_bits.append(f"--mgmt-ipv6-cidr {args.mgmt_ipv6_cidr}")
    if getattr(args, "mgmt_ipv6_gw", None):
        args_bits.append(f"--mgmt-ipv6-gw {args.mgmt_ipv6_gw}")
    if getattr(args, "mgmt_ipv6_gw_vrf", None):
        args_bits.append(f"--mgmt-ipv6-gw-vrf {args.mgmt_ipv6_gw_vrf}")


def _append_common_offline_args_bits(args_bits: list[str], args: object) -> None:
    """Append offline artifact flags shared by provenance metadata builders."""
    if getattr(args, "nac", False):
        args_bits.append("--nac")
    if getattr(args, "bootstrap", False):
        args_bits.append("--bootstrap")
    if getattr(args, "terraform_cml2", False):
        args_bits.append("--terraform-cml2")
    cafile = getattr(args, "cafile", None)
    if cafile:
        args_bits.append(f"--ca {cafile}")
    if getattr(args, "pki_enabled", False) and not any(
        b == "--pki" or b.startswith("--pki ") for b in args_bits
    ):
        args_bits.append("--pki")
    if getattr(args, "enable_mgmt", False) and not any(
        b == "--mgmt" or b.startswith("--mgmt") for b in args_bits
    ):
        args_bits.append("--mgmt")
    if getattr(args, "intent_spot", False):
        args_bits.append("--intent-spot")


def _offline_ca_mgmt_scep_url(args: object, total_routers: int) -> str:
    """SCEP URL for CA-ROOT on the OOB mgmt fabric (simple/nx offline)."""
    mgmt_net = IPv4Network(str(getattr(args, "mgmt_cidr", "10.254.0.0/16")), strict=False)
    ca_ip = mgmt_net.network_address + total_routers + 1
    return f"http://{ca_ip}:80"


def _emit_offline_ca_root_mgmt_node(
    env: Environment,
    cfg: Config,
    args: Namespace,
    lines: list[str],
    node_ids: dict[str, str],
    nid: int,
    tpl,
    enable_mgmt: bool,
    mgmt_slot: int,
    staging: bool,
    total_routers: int,
    distance: int,
) -> int:
    """Append CA-ROOT (CSR1000v) for offline simple/nx labs using OOB mgmt reachability."""
    ca_label = "CA-ROOT"
    node_ids[ca_label] = f"n{nid}"
    nid += 1
    ca_scep_url = _offline_ca_mgmt_scep_url(args, total_routers)
    ca_ip = ca_scep_url.split("://", 1)[1].rsplit(":", 1)[0]
    mgmt_net = IPv4Network(str(getattr(args, "mgmt_cidr", "10.254.0.0/16")), strict=False)
    ca_mgmt_addr = IPv4Interface(f"{ca_ip}/{mgmt_net.prefixlen}")

    template_name = getattr(args, "template", "iosv")
    if "ospf" in template_name or template_name == "iosv":
        ca_template_name = "csr-ospf"
    elif "eigrp" in template_name:
        ca_template_name = "csr-eigrp"
    else:
        ca_template_name = "csr-eigrp"
    try:
        ca_base_tpl = env.get_template(f"{ca_template_name}{Renderer.J2SUFFIX}")
    except TemplateNotFound:
        ca_base_tpl = tpl

    ca_node = TopogenNode(
        hostname=ca_label,
        loopback=IPv4Interface(f"{ca_ip}/32"),
        interfaces=[
            TopogenInterface(
                address=ca_mgmt_addr,
                description="=== SCEP Enrollment URL (OOB) ===",
                slot=mgmt_slot - 1,
            )
        ],
    )
    ca_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
    ca_ntp_ctx = None
    if getattr(args, "ntp_server", None):
        ca_ntp_ctx = {"server": args.ntp_server, "vrf": getattr(args, "ntp_vrf", None)}
    ca_ntp_oob_ctx = None
    if getattr(args, "ntp_oob_server", None):
        ca_ntp_oob_ctx = {
            "server": args.ntp_oob_server,
            "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
        }
    ca_base_config = ca_base_tpl.render(
        config=cfg,
        node=ca_node,
        date=datetime.now(timezone.utc),
        origin="",
        mgmt=ca_mgmt_ctx,
        ntp=ca_ntp_ctx,
        ntp_oob=ca_ntp_oob_ctx,
        archive=getattr(args, "archive", False),
    )
    ca_config_lines = ca_base_config.rstrip().split("\n")
    if ca_config_lines and ca_config_lines[-1].strip() == "end":
        ca_config_lines.pop()
    for i, line in enumerate(ca_config_lines):
        if line.strip() == "crypto key generate rsa modulus 2048":
            ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"
            break
    pki_config_lines = [
        "ntp master 6",
        "!",
        "ip http server",
        "!",
        "crypto pki server CA-ROOT",
        " database level complete",
        " no database archive",
        " grant auto",
        " lifetime certificate 7300",
        " lifetime ca-certificate 7300",
        " database url flash:",
        " no shutdown",
        "!",
    ]
    non_eem_block = (
        pki_config_lines
        + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
        + ["alias exec servcerts sh crypto pki server CA-ROOT cer", "!"]
    )
    try:
        eem_idx = next(
            i for i, line in enumerate(ca_config_lines) if line.strip().startswith("event manager")
        )
    except StopIteration:
        eem_idx = len(ca_config_lines)
    ca_config_lines[eem_idx:eem_idx] = non_eem_block
    ca_config_lines.extend(_pki_ca_authenticate_eem_lines())
    ca_config_lines.append("end")
    ca_rendered = "\n".join(ca_config_lines)

    ca_x = -distance * 3
    lines.append(f"  - id: {node_ids[ca_label]}")
    lines.append(f"    label: {ca_label}")
    lines.append("    node_definition: csr1000v")
    if staging:
        lines.append(f"    priority: {STAGING_PRIORITY_CA_ROOT}")
    lines.append(f"    x: {ca_x}")
    lines.append("    y: 0")
    lines.append("    interfaces:")
    csr_slot = mgmt_slot - 1
    lines.append(f"      - id: i{csr_slot}")
    lines.append(f"        slot: {csr_slot}")
    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
    lines.append("        type: physical")
    _emit_config(lines, ca_rendered, getattr(args, "blank", False))
    return nid


STAGING_PRIORITY_EXT_CONN_OOB = 1000
STAGING_PRIORITY_DATA_SWITCH = 950
STAGING_PRIORITY_CA_ROOT = 900
STAGING_PRIORITY_HUB_KS = 800


def _node_staging_lines(abort_on_failure: bool = True) -> list[str]:
    """Return YAML lines for the lab-level node_staging block (CML 2.10 / schema 0.3.1+)."""
    return [
        "  node_staging:",
        "    enabled: true",
        "    start_remaining: true",
        f"    abort_on_failure: {'true' if abort_on_failure else 'false'}",
    ]


def _staging_version_ok(version: str) -> bool:
    """Return True if schema version supports node staging (>= 0.3.1)."""
    return tuple(int(x) for x in version.split(".")) >= (0, 3, 1)


def _emit_config(lines: list[str], rendered: str, blank: bool) -> None:
    """Append configuration YAML lines. If blank, emit empty config for CML Bootstrap Lab."""
    if blank:
        lines.append('    configuration: ""')
    else:
        lines.append("    configuration: |-")
        for ln in rendered.splitlines():
            lines.append(f"      {ln}")


def resolve_offline_artifact_paths(
    offline_yaml: str,
    nac_enabled: bool = False,
    cml2_enabled: bool = False,
) -> tuple[Path, Path | None, Path | None]:
    """Resolve deterministic offline output paths.

    Plain offline behavior is unchanged (returns the original offline YAML path).
    Optional artifact flows normalize output so CML YAML stays at the lab root
    and each scaffold has a separate directory:
      <parent>/<lab>/<lab>.yaml, <parent>/<lab>/nac/, and/or <parent>/<lab>/cml2/
    """
    raw = Path(offline_yaml)
    if not nac_enabled and not cml2_enabled:
        return raw, None, None

    lab_name = raw.stem if raw.suffix else raw.name
    # Avoid duplicate nesting on reruns if caller already passed out/<lab>/<lab>.yaml
    if raw.parent.name == lab_name:
        lab_root = raw.parent
    else:
        lab_root = raw.parent / lab_name
    return (
        lab_root / f"{lab_name}.yaml",
        lab_root / "nac" if nac_enabled else None,
        lab_root / "cml2" if cml2_enabled else None,
    )


def resolve_offline_output_paths(offline_yaml: str, nac_enabled: bool = False) -> tuple[Path, Path | None]:
    """Resolve deterministic offline CML YAML and NaC output paths."""
    outfile, nac_root, _ = resolve_offline_artifact_paths(
        offline_yaml,
        nac_enabled=nac_enabled,
        cml2_enabled=False,
    )
    return outfile, nac_root


def write_cml2_lifecycle_if_enabled(args: Namespace, outfile: Path, cml2_root: Path | None) -> None:
    """Write CML2 Terraform lifecycle scaffold when requested."""
    if cml2_root is None:
        return
    written = write_cml2_lifecycle_scaffold(
        cml2_root,
        topology_file=outfile.name,
        overwrite=bool(getattr(args, "overwrite", False)),
    )
    _LOGGER.warning("CML2 Terraform lifecycle scaffold written to %s", written[0].parent)


def _nac_unsupported_template_reason(device_template: str) -> str:
    reasons = {
        "asa": "ASA is not an IOS-XE device",
        "iol": "IOL is not in the supported IOS-XE template set",
        "lxc": "FRR/LXC/Linux containers are not IOS-XE devices",
        "ubuntu": "Ubuntu/Linux nodes are not IOS-XE devices",
    }
    return reasons.get(
        str(device_template).lower(),
        "device template is not in the supported IOS-XE template set",
    )


def describe_nac_unsupported_nodes(
    nodes: list[TopogenNode] | list[str],
    device_template: str,
) -> list[str]:
    """Return human-readable unsupported-node details for NaC preflight errors."""
    template = str(device_template).lower()
    if template in SUPPORTED_NAC_DEVICE_TEMPLATES:
        return []
    reason = _nac_unsupported_template_reason(template)
    details: list[str] = []
    for node in nodes:
        hostname = node if isinstance(node, str) else getattr(node, "hostname", "unknown")
        details.append(f"{hostname}: {reason} (--device-template {template})")
    return details


def validate_nac_supported_iosxe_nodes(
    nodes: list[TopogenNode],
    device_template: str,
) -> None:
    """Abort NaC generation before any nac/ tree exists for unsupported routers."""
    unsupported = describe_nac_unsupported_nodes(nodes, device_template)
    if unsupported:
        raise TopogenError(
            "--nac supports IOS-XE router nodes only; unsupported node(s): "
            + "; ".join(unsupported)
            + ". Supported IOS-XE device templates: iosv, csr1000v."
        )


def _validate_nac_router_nodes_if_enabled(
    nac_root: Path | None,
    nodes: list[TopogenNode],
    device_template: str,
) -> None:
    """Validate NaC router nodes before writing any offline artifacts."""
    if nac_root is None:
        return
    validate_nac_supported_iosxe_nodes(nodes, device_template)


def _write_nac_tree_if_enabled(
    *,
    nac_root: Path | None,
    nodes: list[TopogenNode],
    device_template: str,
    template: str,
    mode: str,
    args: Namespace,
) -> Path | None:
    """Write a sibling nac/ tree when the offline path requested NaC artifacts."""
    if nac_root is None or not nodes:
        return None
    nac_file = write_nac_tree(
        nac_root=nac_root,
        nodes=nodes,
        device_template=device_template,
        template=template,
        mode=mode,
        args=args,
        overwrite=getattr(args, "overwrite", False),
    )
    _LOGGER.warning("NaC canonical output written to %s", nac_file)
    return nac_file


def _nac_restconf_lines() -> list[str]:
    """RESTCONF/netconf-yang day0 commands required by the NaC MVP."""
    return [
        "ip http secure-server",
        "restconf",
        "netconf-yang",
    ]


def _append_nac_mgmt_interface(node: TopogenNode, args: Namespace, router_index: int) -> None:
    """Expose the CML-only OOB management interface to the NaC data model."""
    if not getattr(args, "enable_mgmt", False):
        return
    mgmt_net = IPv4Network(str(getattr(args, "mgmt_cidr", "10.254.0.0/16")), strict=False)
    mgmt_slot = int(getattr(args, "mgmt_slot", 5))
    dev_def = str(getattr(args, "dev_template", getattr(args, "template", ""))).lower()
    model_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
    mgmt_bridge = bool(getattr(args, "mgmt_bridge", False))
    ipv4_dhcp = bool(getattr(args, "mgmt_ipv4_dhcp", False))
    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    mgmt_address = None
    ipv6_address = None
    ipv6_link_local_address = None
    if not mgmt_bridge and not ipv4_dhcp and not ipv6_mode:
        mgmt_address = IPv4Interface(
            f"{mgmt_net.network_address + router_index}/{mgmt_net.prefixlen}"
        )
    if ipv6_mode == "static" and node.loopback is not None:
        mgmt_cidr = str(getattr(args, "mgmt_cidr", "10.254.0.0/16"))
        ipv4_host = mgmt_ipv4_static_host(mgmt_cidr, router_index)
        anchor = parse_static_ipv6_anchor(str(getattr(args, "mgmt_ipv6_cidr", "")))
        ipv6_address = mgmt_ipv6_static_address(ipv4_host, anchor, mgmt_cidr)
    if (
        getattr(args, "mgmt_ipv6_static_link_local", False)
        and node.loopback is not None
    ):
        ipv6_link_local_address = mgmt_ipv6_static_link_local(node.loopback.ip)
    node.interfaces.append(
        TopogenInterface(
            address=mgmt_address,
            vrf=getattr(args, "mgmt_vrf", None),
            description="OOB Management",
            slot=model_slot,
            ipv6_address=ipv6_address,
            ipv6_link_local_address=ipv6_link_local_address,
        )
    )


def _bootstrap_mgmt_interface_label(args: Namespace) -> str:
    """Return the IOS-XE CLI label for the OOB management interface."""
    dev_def = str(getattr(args, "dev_template", getattr(args, "template", ""))).lower()
    mgmt_slot = int(getattr(args, "mgmt_slot", 5))
    if dev_def == "csr1000v":
        return f"GigabitEthernet{mgmt_slot}"
    return f"GigabitEthernet0/{mgmt_slot}"


def _render_bootstrap_config(cfg: Config, node: TopogenNode, args: Namespace) -> str:
    """Thin day-0 startup config for the NaC path: auth, OOB mgmt, RESTCONF."""
    dev_def = str(getattr(args, "dev_template", getattr(args, "template", ""))).lower()
    csr_style = dev_def == "csr1000v"
    mgmt_vrf = getattr(args, "mgmt_vrf", None)
    mgmt_slot = int(getattr(args, "mgmt_slot", 5))
    mgmt_bridge = bool(getattr(args, "mgmt_bridge", False))
    mgmt_gw = getattr(args, "mgmt_gw", None)
    if_label = _bootstrap_mgmt_interface_label(args)

    lines = [
        f"hostname {node.hostname}",
        "!",
        "no service password-encryption",
        f"enable password {cfg.password}",
        f"username {cfg.username} privilege 15 secret {cfg.password}",
        "crypto key generate rsa modulus 2048",
        f"ip domain name {cfg.domainname}",
        "!",
    ]

    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    ipv4_dhcp = bool(getattr(args, "mgmt_ipv4_dhcp", False))
    if ipv6_mode and ipv6_mode != "static":
        lines.extend(["ipv6 unicast-routing", "!"])

    if mgmt_vrf:
        if csr_style or ipv6_mode:
            vrf_lines = [
                f"vrf definition {mgmt_vrf}",
                f" rd 1:{mgmt_slot}",
                " address-family ipv4",
                " exit-address-family",
            ]
            if ipv6_mode:
                vrf_lines.extend(
                    [
                        " address-family ipv6",
                        " exit-address-family",
                    ]
                )
            vrf_lines.append("!")
            lines.extend(vrf_lines)
        else:
            lines.extend(
                [
                    f"ip vrf {mgmt_vrf}",
                    f" rd 1:{mgmt_slot}",
                    "!",
                ]
            )

    lines.append(f"interface {if_label}")
    lines.append(" description OOB Management")
    if mgmt_vrf:
        fwd = "vrf forwarding" if (csr_style or ipv6_mode) else "ip vrf forwarding"
        lines.append(f" {fwd} {mgmt_vrf}")
    if ipv4_dhcp:
        lines.append(" ip address dhcp")
    if ipv6_mode:
        if not ipv4_dhcp:
            lines.append(" no ip address")
        lines.append(" ipv6 enable")
        ipv6_link_local = None
        if getattr(args, "mgmt_ipv6_static_link_local", False) and node.loopback is not None:
            ipv6_link_local = mgmt_ipv6_static_link_local(node.loopback.ip)
        if ipv6_mode == "slaac":
            if ipv6_link_local:
                lines.append(f" ipv6 address {ipv6_link_local} link-local")
            lines.append(" ipv6 address autoconfig")
        elif ipv6_mode == "dhcpv6":
            if ipv6_link_local:
                lines.append(f" ipv6 address {ipv6_link_local} link-local")
            lines.append(" ipv6 address dhcp")
        elif ipv6_mode == "static":
            mgmt_iface = next(
                (iface for iface in node.interfaces if iface.description == "OOB Management"),
                None,
            )
            if mgmt_iface is None or not mgmt_iface.ipv6_address:
                raise TopogenError(
                    "bootstrap static IPv6 OOB requires mgmt.ipv6_address on OOB interface"
                )
            lines.append(f" ipv6 address {mgmt_iface.ipv6_address}")
            if mgmt_iface.ipv6_link_local_address:
                lines.append(
                    f" ipv6 address {mgmt_iface.ipv6_link_local_address} link-local"
                )
    elif not ipv4_dhcp:
        mgmt_iface = next(
            (iface for iface in node.interfaces if iface.description == "OOB Management"),
            None,
        )
        if mgmt_iface is None or mgmt_iface.address is None:
            raise TopogenError(
                "bootstrap config requires a static OOB management address; "
                "use --mgmt without --mgmt-bridge or verify node metadata"
            )
        lines.append(
            f" ip address {mgmt_iface.address.ip} {mgmt_iface.address.netmask}"
        )
    lines.append(" no cdp enable")
    lines.append(" no shutdown")
    lines.append("!")

    if mgmt_gw:
        if mgmt_vrf:
            lines.append(f"ip route vrf {mgmt_vrf} 0.0.0.0 0.0.0.0 {mgmt_gw}")
        else:
            lines.append(f"ip route 0.0.0.0 0.0.0.0 {mgmt_gw}")
        lines.append("!")
    mgmt_ipv6_gw = getattr(args, "mgmt_ipv6_gw", None)
    if mgmt_ipv6_gw and ipv6_mode == "static":
        route_vrf = mgmt_ipv6_default_route_vrf(args)
        if route_vrf:
            lines.append(f"ipv6 route vrf {route_vrf} ::/0 {mgmt_ipv6_gw}")
        else:
            lines.append(f"ipv6 route ::/0 {mgmt_ipv6_gw}")
        lines.append("!")

    if ipv6_mode:
        lines.extend(
            [
                *_mgmt_test_alias_lines(if_label),
                "!",
            ]
        )

    lines.extend(
        [
            "ip ssh version 2",
            "ip ssh server algorithm authentication password",
            *_nac_restconf_lines(),
            "!",
            "line vty 0 4",
            " login local",
            " transport input ssh",
            "line con 0",
            f" password {cfg.password}",
            "!",
            "end",
        ]
    )
    return "\n".join(lines)


def _finalize_router_day0_config(
    rendered: str,
    cfg: Config,
    node: TopogenNode,
    args: Namespace,
) -> str:
    """Return router day-0 config: bootstrap skin, NaC RESTCONF splice, or unchanged."""
    if getattr(args, "bootstrap", False):
        return _render_bootstrap_config(cfg, node, args)
    if getattr(args, "nac", False):
        return _inject_nac_restconf_day0(rendered)
    return rendered


def _inject_nac_restconf_day0(rendered: str) -> str:
    """Insert NaC management transport before the final IOS-XE ``end`` line."""
    lines = rendered.splitlines()
    has_rsa_key = any(
        line.strip().startswith("crypto key generate rsa")
        for line in lines
    )
    block: list[str] = ["!"]
    if not has_rsa_key:
        # IOS-XE accepts this command in startup/day0 config; the iosv/csr1000v
        # templates and PKI splice already use this exact form before enabling HTTPS.
        block.extend(["crypto key generate rsa modulus 2048", "!"])
    # With --mgmt, the NaC host can be reachable only inside Mgmt-vrf. This helper
    # intentionally enables global services only; VRF reachability stays user-owned.
    block.extend(_nac_restconf_lines())
    try:
        end_idx = next(
            i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "end"
        )
        lines[end_idx:end_idx] = block
    except StopIteration:
        lines.extend(block)
        lines.append("end")
    return "\n".join(lines)


def get_templates() -> list[str]:
    """get all available templates in the package"""
    return [
        t[: -len(Renderer.J2SUFFIX)]
        for t in pkg_resources.contents(templates)
        if t.endswith(Renderer.J2SUFFIX)
    ]


def _init_client_from_args(args: Namespace) -> ClientLibrary:
    """Initialize virl2_client from CLI args (for import path; no Renderer instance)."""
    cainfo: Union[bool, str] = args.cafile
    try:
        os.stat(args.cafile)
    except (FileNotFoundError, TypeError):
        cainfo = not args.insecure
    url = os.environ.get("VIRL2_URL")
    username = os.environ.get("VIRL2_USER")
    password = os.environ.get("VIRL2_PASS")
    if not url or not username or not password:
        raise TopogenError(
            "Online mode requires VIRL2_URL, VIRL2_USER, VIRL2_PASS set in this shell. "
            "Example (PowerShell): $env:VIRL2_URL='https://192.168.1.164'; $env:VIRL2_USER='admin'; $env:VIRL2_PASS='yourpass'; topogen ..."
        )
    try:
        client = ClientLibrary(
            url=url,
            username=username,
            password=password,
            ssl_verify=cainfo,
        )
        if not client.is_system_ready():
            raise TopogenError("system is not ready")
        return client
    except ConnectTimeout as exc:
        raise TopogenError("no connection: " + str(exc)) from None
    except InitializationError as exc:
        raise TopogenError(
            "CML client init failed. Check VIRL2_URL, VIRL2_USER, VIRL2_PASS are set in this shell. Details: " + str(exc)
        ) from exc


def _start_lab_in_background(lab: Lab, args: Namespace) -> None:
    """Start the lab in a background thread; brief delay so the start request reaches CML before process exits."""
    if not getattr(args, "start_lab", False):
        return
    _LOGGER.warning("Starting lab... (running in background; check CML UI for status)")

    def _start() -> None:
        try:
            lab.start()
        except Exception as exc:  # pragma: no cover
            _LOGGER.error("Start failed: %s", exc)

    t = threading.Thread(target=_start, daemon=True)
    t.start()
    # Let the thread send the start request before we exit (daemon dies on process exit)
    import time
    time.sleep(3)


def disable_pcl_loggers():
    """set all virl python client library loggers to WARN, too much output"""
    loggers = [
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict  # pylint disable=E1101
    ]
    for logger in loggers:
        if logger.name.startswith("virl2_client"):
            logger.setLevel(logging.WARN)


def order_iface_pair(iface_pair: dict, this: int) -> Tuple[Any, Any]:
    """order the interface pair so that the first one is the one with the
    given index "this", and the second one is the other one.
    """
    (src_idx, src_iface), (_, dst_iface) = iface_pair.items()
    if this == src_idx:
        return src_iface, dst_iface
    return dst_iface, src_iface


def format_dns_entry(iface_pair: dict, this: int) -> str:
    """format the interface pair labels suitable for a DNS entry"""
    table = {
        ord("/"): "_",
        ord(" "): "-",
    }

    # these must be sorted by key length
    interface_names = {
        "TenGigabitEthernet": "ten",
        "GigabitEthernet": "gi",
        "Ethernet": "e",
    }

    src, dst = order_iface_pair(iface_pair, this)
    desc = f"{src.node.label}-{src.label}--{dst.node.label}-{dst.label}"

    for long, short in interface_names.items():
        if long in desc:
            desc = desc.replace(long, short)
            break

    return desc.translate(table).lower()


def format_interface_description(iface_pair: dict, this: int) -> str:
    """this puts the interface description together which gets inserted
    into the router configuration."""

    _, dst = order_iface_pair(iface_pair, this)
    # return f"from {src.node.label} {src.label} to {dst.node.label} {dst.label}"
    return f"to {dst.node.label} {dst.label}"


# Hardcoded clock set value: "today" at lab generation time (00:01:00 UTC).
# Must be after CA cert notBefore (often 00:00:21) so IKEv2 cert validation succeeds; NTP takes over later.
def _pki_clock_set_today(backdate_days: int = 0) -> str:
    """Return IOS clock set string: 00:01:00 Month Day Year (UTC at generation time).
    backdate_days > 0 shifts the date earlier (CA uses 1 so notBefore precedes client clocks)."""
    dt = datetime.now(timezone.utc) - timedelta(days=backdate_days)
    return f"00:01:00 {dt.strftime('%B %d %Y')}"


def _pki_client_clock_eem_lines() -> list[str]:
    """EEM applet CLIENT-PKI-SET-CLOCK: one-shot 90s after boot.
    If NTP synced, set TIME_DONE and exit. Else: clock set <hardcoded today>, then TIME_DONE.
    On completion (either path), runs 'event manager run CLIENT-PKI-AUTHENTICATE' so PKI
    enrollment runs after clock is set, avoiding the 95s-vs-90s timer race.
    No show clock / regexp (CVAC rejects it); NTP takes over later.
    Environment variable TIME_DONE set to 0 first so run-once guard works."""
    clock_val = _pki_clock_set_today()
    lines = [
        "!",
        "event manager environment TIME_DONE 0",
        "!",
        "event manager applet CLIENT-PKI-SET-CLOCK authorization bypass",
        " event timer countdown time 300",
        " action 0.1 cli command \"enable\"",
        " action 0.2 syslog msg \"EEM CLIENT-PKI-SET-CLOCK: executed [step 0.2]\"",
        " action 0.3 cli command \"terminal length 0\"",
        " action 0.4 cli command \"show event manager environment | include TIME_DONE\"",
        " action 0.5 regexp \"TIME_DONE 1\" \"$_cli_result\" match",
        " action 0.6 if $_regexp_result eq \"1\"",
        "  action 0.7  exit",
        "  action 0.8 end",
        " action 1.0 cli command \"show ntp status\"",
        " action 1.1 regexp \"Clock is synchronized\" \"$_cli_result\" match",
        " action 1.2 if $_regexp_result eq \"1\"",
        "  action 1.3  cli command \"configure terminal\"",
        "  action 1.4  cli command \"event manager environment TIME_DONE 1\"",
        "  action 1.5  cli command \"no event manager applet CLIENT-PKI-SET-CLOCK\"",
        "  action 1.6  cli command \"end\"",
        "  action 1.7  cli command \"write memory\"",
        "  action 1.8  syslog msg \"EEM CLIENT-PKI-SET-CLOCK: TIME_DONE set (NTP synced) [step 1.8]\"",
        "  action 1.9  cli command \"event manager run CLIENT-PKI-AUTHENTICATE\"",
        "  action 1.10 exit",
        "  action 1.11 end",
        "! Hardcoded clock set (no regexp) so CVAC applies; NTP takes over later.",
        " action 2.0 cli command \"configure terminal\"",
        f" action 2.1 cli command \"do clock set {clock_val}\"",
        " action 2.2 cli command \"end\"",
        " action 3.0 cli command \"configure terminal\"",
        " action 3.1 cli command \"event manager environment TIME_DONE 1\"",
        " action 3.2 cli command \"no event manager applet CLIENT-PKI-SET-CLOCK\"",
        " action 3.3 cli command \"end\"",
        " action 3.4 cli command \"write memory\"",
        " action 3.5 syslog msg \"EEM CLIENT-PKI-SET-CLOCK: TIME_DONE set (clock authoritative) [step 3.5]\"",
        " action 3.6 cli command \"event manager run CLIENT-PKI-AUTHENTICATE\"",
        "!",
    ]
    return lines


def _pki_ca_clock_eem_lines() -> list[str]:
    """EEM applet CA-ROOT-SET-CLOCK: one-shot 90s after boot on CA-ROOT.
    If NTP synced, set TIME_DONE and exit. Else: clock set <hardcoded today>, ntp master 6, TIME_DONE.
    No show clock / regexp (CVAC rejects it); NTP takes over later.
    Environment variable TIME_DONE set to 0 first so run-once guard works."""
    clock_val = _pki_clock_set_today()
    return [
        "!",
        "event manager environment TIME_DONE 0",
        "!",
        "event manager applet CA-ROOT-SET-CLOCK authorization bypass",
        " event timer countdown time 90",
        " action 0.1 cli command \"enable\"",
        " action 0.2 syslog msg \"EEM CA-ROOT-SET-CLOCK: executed [step 0.2]\"",
        " action 0.3 cli command \"terminal length 0\"",
        " action 0.4 cli command \"show event manager environment | include TIME_DONE\"",
        " action 0.5 regexp \"TIME_DONE 1\" \"$_cli_result\" match",
        " action 0.6 if $_regexp_result eq \"1\"",
        "  action 0.7  exit",
        "  action 0.8 end",
        " action 1.0 cli command \"show ntp status\"",
        " action 1.1 regexp \"Clock is synchronized\" \"$_cli_result\" match",
        " action 1.2 if $_regexp_result eq \"1\"",
        "  action 1.3  cli command \"configure terminal\"",
        "  action 1.4  cli command \"event manager environment TIME_DONE 1\"",
        "  action 1.5  cli command \"no event manager applet CA-ROOT-SET-CLOCK\"",
        "  action 1.6  cli command \"end\"",
        "  action 1.7  cli command \"write memory\"",
        "  action 1.8  syslog msg \"EEM CA-ROOT-SET-CLOCK: TIME_DONE set (NTP synced) [step 1.8]\"",
        "  action 1.9  exit",
        " action 1.10 end",
        "! Hardcoded clock set (no regexp) so CVAC applies; then ntp master 6.",
        " action 2.0 cli command \"configure terminal\"",
        f" action 2.1 cli command \"do clock set {clock_val}\"",
        " action 2.2 cli command \"end\"",
        " action 3.0 cli command \"configure terminal\"",
        " action 3.1 cli command \"ntp master 6\"",
        " action 3.2 cli command \"end\"",
        " action 4.0 cli command \"configure terminal\"",
        " action 4.1 cli command \"event manager environment TIME_DONE 1\"",
        " action 4.2 cli command \"no event manager applet CA-ROOT-SET-CLOCK\"",
        " action 4.3 cli command \"end\"",
        " action 4.4 cli command \"write memory\"",
        " action 4.5 syslog msg \"EEM CA-ROOT-SET-CLOCK: TIME_DONE set (clock + ntp master 6) [step 4.5]\"",
        "!",
    ]


def _pki_ca_authenticate_eem_lines() -> list[str]:
    """EEM applet CA-ROOT-AUTHENTICATE: CA-ROOT only. Triggers on syslog PKI-6-CS_ENABLED (Certificate server now enabled).
    Only the CA router sees that message; clients use a different trigger (e.g. TIME_DONE set or timer)."""
    return [
        "!",
        "event manager applet CA-ROOT-AUTHENTICATE authorization bypass",
        " event syslog pattern \"Certificate server now enabled\"",
        " action 0.1 cli command \"enable\"",
        " action 0.2 cli command \"terminal length 0\"",
        " action 0.3 cli command \"show crypto pki certificates CA-ROOT-SELF\"",
        " action 0.4 regexp \"CA Certificate\" \"$_cli_result\" match",
        " action 0.5 if $_regexp_result eq \"1\"",
        "  action 0.6  exit",
        "  action 0.7 end",
        " action 0.8 cli command \"configure terminal\"",
        " action 0.9 cli command \"crypto pki authenticate CA-ROOT-SELF\" pattern \"yes/no\"",
        " action 0.91 wait 2",
        " action 0.92 cli command \"yes\" pattern \".*\"",
        " action 0.93 cli command \" \"",
        " action 0.94 cli command \"end\"",
        " action 0.95 cli command \"write memory\"",
        " action 0.96 cli command \"configure terminal\"",
        " action 0.97 cli command \"no event manager applet CA-ROOT-AUTHENTICATE\"",
        " action 0.98 cli command \"end\"",
        " action 0.99 cli command \"write memory\"",
        "!",
    ]


def _pki_client_authenticate_eem_lines() -> list[str]:
    """EEM applet CLIENT-PKI-AUTHENTICATE: PKI clients only. Runs 95s after boot (after
    CLIENT-PKI-SET-CLOCK at 90s). Proceeds only when TIME_DONE is 1 so cert validation
    does not fail on time. Authenticates CA and enrolls; then removes itself.
    Skips if CA cert already present."""
    return [
        "!",
        "event manager applet CLIENT-PKI-AUTHENTICATE authorization bypass",
        " event timer countdown time 305",
        " action 0.1 cli command \"enable\"",
        " action 0.2 cli command \"terminal length 0\"",
        " action 0.3 cli command \"show event manager environment | include TIME_DONE\"",
        " action 0.4 regexp \"TIME_DONE 1\" \"$_cli_result\" match",
        " action 0.5 if $_regexp_result ne \"1\"",
        "  action 0.6  cli command \"configure terminal\"",
        "  action 0.7  cli command \"no event manager applet CLIENT-PKI-AUTHENTICATE\"",
        "  action 0.8  cli command \"end\"",
        "  action 0.9  syslog msg \"EEM CLIENT-PKI-AUTHENTICATE: TIME_DONE not set, skipping\"",
        "  action 0.10 exit",
        "  action 0.11 end",
        " action 1.0 cli command \"show crypto pki certificates CA-ROOT-SELF\"",
        " action 1.1 regexp \"CA Certificate\" \"$_cli_result\" match",
        " action 1.2 if $_regexp_result eq \"1\"",
        "  action 1.3  cli command \"configure terminal\"",
        "  action 1.4  cli command \"no event manager applet CLIENT-PKI-AUTHENTICATE\"",
        "  action 1.5  cli command \"end\"",
        "  action 1.6  cli command \"write memory\"",
        "  action 1.7  exit",
        "  action 1.8  end",
        " action 2.0 cli command \"configure terminal\"",
        " action 2.1 cli command \"crypto pki authenticate CA-ROOT-SELF\" pattern \"yes/no\"",
        " action 2.2 wait 2",
        " action 2.3 cli command \"yes\" pattern \".*\"",
        " action 2.4 cli command \" \"",
        " action 2.5 cli command \"end\"",
        " action 2.6 cli command \"write memory\"",
        " action 2.7 cli command \"configure terminal\"",
        " action 2.8 cli command \"no event manager applet CLIENT-PKI-AUTHENTICATE\"",
        " action 2.9 cli command \"end\"",
        " action 3.0 cli command \"write memory\"",
        "!",
    ]


def _pki_client_wait_for_ca_eem_lines() -> list[str]:
    """EEM applets for PKI clients: WAIT-FOR-CA (ping CA until reachable, then send syslog)
    and CA-ROOT-AUTHENTICATE (triggered by that syslog; runs crypto pki authenticate).
    On ping success WAIT-FOR-CA removes itself and writes memory so it does not keep running.
    Must be injected at the end of config (before final 'end')."""
    return [
        "!",
        "event manager environment TIME_DONE 0",
        "event manager applet WAIT-FOR-CA",
        " event timer watchdog time 300",
        " action 0.1 cli command \"enable\"",
        " action 0.2 cli command \"terminal length 0\"",
        " action 1.0 cli command \"ping 10.10.255.254 repeat 10 timeout 2\"",
        " action 1.1 regexp \"10/10\" \"$_cli_result\" match",
        " action 1.2 if $_regexp_result eq \"1\"",
        " action 1.3  cli command \"send log Certificate server now enabled\"",
        " action 1.31 cli command \"configure terminal\"",
        " action 1.32 cli command \"no event manager applet WAIT-FOR-CA\"",
        " action 1.33 cli command \"end\"",
        " action 1.34 cli command \"write memory\"",
        " action 1.4  exit",
        " action 1.5 end",
        " action 2.0 wait 60",
        " action 2.1 cli command \"ping 10.10.255.254 repeat 10 timeout 2\"",
        " action 2.2 regexp \"10/10\" \"$_cli_result\" match",
        " action 2.3 if $_regexp_result eq \"1\"",
        " action 2.4  cli command \"send log Certificate server now enabled\"",
        " action 2.41 cli command \"configure terminal\"",
        " action 2.42 cli command \"no event manager applet WAIT-FOR-CA\"",
        " action 2.43 cli command \"end\"",
        " action 2.44 cli command \"write memory\"",
        " action 2.5  exit",
        " action 2.6 end",
        " action 3.0 wait 60",
        " action 3.1 cli command \"ping 10.10.255.254 repeat 10 timeout 2\"",
        " action 3.2 regexp \"10/10\" \"$_cli_result\" match",
        " action 3.3 if $_regexp_result eq \"1\"",
        " action 3.4  cli command \"send log Certificate server now enabled\"",
        " action 3.41 cli command \"configure terminal\"",
        " action 3.42 cli command \"no event manager applet WAIT-FOR-CA\"",
        " action 3.43 cli command \"end\"",
        " action 3.44 cli command \"write memory\"",
        " action 3.5  exit",
        " action 3.6 end",
        "event manager applet CA-ROOT-AUTHENTICATE authorization bypass",
        " event syslog pattern \"Certificate server now enabled\"",
        " action 0.1  cli command \"enable\"",
        " action 0.2  cli command \"terminal length 0\"",
        " action 0.3  cli command \"show crypto pki certificates CA-ROOT-SELF\"",
        " action 0.4  regexp \"CA Certificate\" \"$_cli_result\" match",
        " action 0.5  if $_regexp_result eq \"1\"",
        " action 0.6   exit",
        " action 0.7  end",
        " action 0.8  cli command \"configure terminal\"",
        " action 0.9  cli command \"crypto pki authenticate CA-ROOT-SELF\" pattern \"yes/no\"",
        " action 0.91 wait 2",
        " action 0.92 cli command \"yes\" pattern \".*\"",
        " action 0.93 cli command \" \"",
        " action 0.94 cli command \"end\"",
        " action 0.95 cli command \"write memory\"",
        " action 0.96 cli command \"configure terminal\"",
        " action 0.97 cli command \"no event manager applet CA-ROOT-AUTHENTICATE\"",
        " action 0.98 cli command \"end\"",
        " action 0.99 cli command \"write memory\"",
        "!",
    ]


def _pki_ca_self_enroll_block_lines(hostname: str, domainname: str, ca_scep_url: str) -> list[str]:
    """Return CA self-enrollment block lines for CA-ROOT-SELF trustpoint.

    Order: clock set → key generation → trustpoint definition → ip http trustpoint.
    The trustpoint must exist before 'ip http secure-trustpoint' references it."""
    fqdn = f"{hostname}.{domainname}"
    return [
        "!",
        f"do clock set {_pki_clock_set_today(backdate_days=1)}",
        "!",
        "crypto key generate rsa modulus 2048 label CA-ROOT-SELF",
        "!",
        "crypto pki trustpoint CA-ROOT-SELF",
        f" enrollment url {ca_scep_url}",
        " enrollment retry count 15",
        " enrollment retry period 60",
        " auto-enroll 70 regenerate",
        f" subject-name cn={fqdn}",
        f" subject-alt-name {fqdn}",
        " revocation-check none",
        " rsakeypair CA-ROOT-SELF",
        "!",
        "ip http secure-server",
        "ip http secure-trustpoint CA-ROOT-SELF",
        "!",
    ]


def _inject_pki_client_trustpoint(
    rendered: str,
    hostname: str,
    domainname: str,
    ca_url: str,
    *,
    key_label: str = "CA-ROOT",
    inject_clock_eem: bool = True,
) -> str:
    """Insert PKI client trustpoint definition before 'crypto ikev2 proposal' and
    EEM applets at the end of the config (before the final 'end').

    Two separate injection points are required:
    - Trustpoint definition BEFORE 'crypto ikev2 proposal': IOS-XE processes startup
      config sequentially and silently rejects forward references to undefined trustpoints,
      so the trustpoint must be defined before the IKEv2 profile references it.
    - EEM applets LAST (before final 'end'): each EEM applet's closing 'end' exits
      IOS-XE global config mode. If placed before interface/routing/crypto sections,
      those sections are never loaded from startup config.

    Falls back to before 'end' for the trustpoint when no IKEv2 section is present.
    """
    fqdn = f"{hostname}.{domainname}"
    trustpoint_block = [
        "!",
        f"do clock set {_pki_clock_set_today()}",
        "!",
        f"crypto key generate rsa modulus 2048 label {key_label}",
        "!",
        "crypto pki trustpoint CA-ROOT-SELF",
        f" enrollment url {ca_url}",
        " enrollment retry count 15",
        " enrollment retry period 60",
        " revocation-check none",
        f" rsakeypair {key_label}",
        f" subject-name cn={fqdn}",
        f" subject-alt-name {fqdn}",
        " auto-enroll 70 regenerate",
        "!",
        "ip http secure-server",
        "ip http secure-trustpoint CA-ROOT-SELF",
        "!",
        "alias configure authc crypto pki authenticate CA-ROOT-SELF",
        "alias exec checkcert show crypto pki certificates CA-ROOT-SELF",
        "!",
    ]
    lines = rendered.splitlines()
    # Inject trustpoint before "crypto ikev2 proposal" (forward reference fix).
    # Fall back to before first EEM applet so non-EEM config precedes all EEM.
    try:
        inject_idx = next(
            i for i, line in enumerate(lines)
            if line.strip().startswith("crypto ikev2 proposal")
        )
    except StopIteration:
        try:
            inject_idx = next(
                i for i, line in enumerate(lines)
                if line.strip().startswith("event manager")
            )
        except StopIteration:
            try:
                inject_idx = next(
                    i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "end"
                )
            except StopIteration:
                inject_idx = len(lines)
    lines[inject_idx:inject_idx] = trustpoint_block
    # Inject EEM applets LAST (before final 'end') so all EEM stays at the end.
    if inject_clock_eem:
        eem_block = _pki_client_wait_for_ca_eem_lines()
        try:
            end_idx = next(
                i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "end"
            )
            lines[end_idx:end_idx] = eem_block
        except StopIteration:
            lines.extend(eem_block)
            lines.append("end")
    return "\n".join(lines)


def _inject_getvpn_gm_config(
    rendered: str,
    hostname: str,
    domainname: str,
    getvpn_protocol: str,
    getvpn_group_id: int,
    getvpn_ks_ip: str,
    wan_interface: str,
) -> str:
    """Insert GET VPN Group Member configuration before the final 'end'.

    Adds IKE control plane (ISAKMP or IKEv2), GDOI/GKM group registration,
    crypto map definition, and applies crypto map to the WAN interface.
    """
    gm_lines: list[str] = ["!"]

    if getvpn_protocol == "gikev2":
        gm_lines.extend([
            "crypto ikev2 proposal GETVPN-IKE2-PROP",
            " encryption aes-cbc-256",
            " integrity sha256",
            " group 19",
            "!",
            "crypto ikev2 policy GETVPN-IKE2-POL",
            " match fvrf any",
            " proposal GETVPN-IKE2-PROP",
            "!",
            "crypto ikev2 profile GETVPN-IKE2-PROFILE",
            f" match identity remote fqdn domain {domainname}",
            f" identity local fqdn {hostname}.{domainname}",
            " authentication local rsa-sig",
            " authentication remote rsa-sig",
            " pki trustpoint CA-ROOT-SELF",
            "!",
            f"crypto gkm group GETVPN",
            f" identity number {getvpn_group_id}",
            f" server address ipv4 {getvpn_ks_ip}",
            " client protocol gikev2 GETVPN-IKE2-PROFILE",
            f" client registration interface {wan_interface}",
            "!",
        ])
    else:
        gm_lines.extend([
            "crypto isakmp policy 10",
            " encryption aes 256",
            " hash sha256",
            " authentication rsa-sig",
            " group 14",
            "!",
            "crypto gdoi group GETVPN",
            f" identity number {getvpn_group_id}",
            f" server address ipv4 {getvpn_ks_ip}",
            "!",
        ])

    gm_lines.extend([
        "crypto map GETVPN-MAP local-address Loopback0",
        "crypto map GETVPN-MAP 10 gdoi",
        " set group GETVPN",
        "!",
        f"interface {wan_interface}",
        " crypto map GETVPN-MAP",
        "!",
        "alias exec gm show crypto gdoi",
        "alias exec gmsa show crypto gdoi gm",
        "alias exec ikesa show crypto isakmp sa",
        "alias exec mycert show crypto pki certificates CA-ROOT-SELF",
        "!",
    ])

    lines = rendered.splitlines()
    try:
        inject_idx = next(
            i for i, line in enumerate(lines)
            if line.strip().startswith("event manager")
        )
    except StopIteration:
        try:
            inject_idx = next(
                i for i in range(len(lines) - 1, -1, -1) if lines[i].strip() == "end"
            )
        except StopIteration:
            inject_idx = len(lines)
    lines[inject_idx:inject_idx] = gm_lines
    return "\n".join(lines)


class Renderer:
    """A class to render (random) network topologies with templated configuration
    generation."""

    J2SUFFIX = ".jinja2"

    def __init__(self, args: Namespace, cfg: Config):
        self.args = args
        self.config = cfg

        self.template: Template
        self.client: ClientLibrary
        self.lab: Lab

        if args.nodes is None:
            raise TopogenError("need to provide number of nodes!")

        self.template = self.load_template()
        self.client = self.initialize_client()

        self.lab = self.client.create_lab(args.labname)
        _LOGGER.info("lab: %s", self.lab.id)

        # these will be /32 addresses
        self.loopbacks = IPv4Network(cfg.loopbacks).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.loopbacks.prefixlen
        )
        # we do not want to use .0
        next(self.loopbacks)

        # these will be /30 addresses (4 addresses, 1 network, 1 broadcast, 2
        # hosts) e.g. 2 bits (hence the -2)
        self.p2pnets = IPv4Network(cfg.p2pnets).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.p2pnets.prefixlen - 2
        )

        self.coords = iter(CoordsGenerator(distance=args.distance))

    def load_template(self) -> Template:
        """load the template"""
        name = self.args.template
        env = Environment(
            loader=PackageLoader("topogen"), autoescape=select_autoescape()
        )
        try:
            return env.get_template(f"{name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(f"template does not exist: {name}") from exc

    def _load_companion_eigrp_template_for_dmvpn_flat_pair(self) -> Template:
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        base = str(getattr(self.args, "template", ""))
        if not base.endswith("-dmvpn"):
            raise TopogenError(
                "DMVPN underlay 'flat-pair' requires a '-dmvpn' template (e.g., iosv-dmvpn or csr-dmvpn)"
            )
        eigrp_name = base[: -len("-dmvpn")] + "-eigrp"
        try:
            return env.get_template(f"{eigrp_name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(
                f"DMVPN underlay 'flat-pair' requires companion template '{eigrp_name}'"
            ) from exc

    def initialize_client(self) -> ClientLibrary:
        """initialize the PCL"""
        cainfo: Union[bool, str] = self.args.cafile
        try:
            os.stat(self.args.cafile)
        except (FileNotFoundError, TypeError):
            # TypeError is raised when cafile is None. We set
            # cafile to None when args.insecure is set.
            cainfo = not self.args.insecure

        url = os.environ.get("VIRL2_URL")
        username = os.environ.get("VIRL2_USER")
        password = os.environ.get("VIRL2_PASS")
        if not url or not username or not password:
            raise TopogenError(
                "Online mode requires VIRL2_URL, VIRL2_USER, VIRL2_PASS set in this shell. "
                "Example (PowerShell): $env:VIRL2_URL='https://192.168.1.164'; $env:VIRL2_USER='admin'; $env:VIRL2_PASS='yourpass'; topogen ..."
            )
        try:
            client = ClientLibrary(
                url=url,
                username=username,
                password=password,
                ssl_verify=cainfo,
            )
            if not client.is_system_ready():
                raise TopogenError("system is not ready")
            return client
        except ConnectTimeout as exc:
            raise TopogenError("no connection: " + str(exc)) from None
        except InitializationError as exc:
            raise TopogenError(
                "CML client init failed. Check VIRL2_URL, VIRL2_USER, VIRL2_PASS are set in this shell. Details: " + str(exc)
            ) from exc

    @staticmethod
    def import_yaml_to_cml(yaml_path: str, args: Namespace, size_already_logged: bool = False) -> int:
        """Import an offline YAML file into CML via virl2_client.

        When size_already_logged is False (e.g. --import-yaml only), prints file size.
        When True (generate then import), offline step already printed size; skip duplicate.
        Prints lab URL and optionally starts the lab in the background (non-blocking).
        """
        disable_pcl_loggers()
        path = Path(yaml_path)
        if not path.exists():
            raise TopogenError(f"YAML file not found: {yaml_path}")
        size_bytes = path.stat().st_size
        size_kb = size_bytes / 1024
        if not size_already_logged:
            _LOGGER.warning("Lab file: %s (%.1f KB)", path, size_kb)
        _LOGGER.warning("Importing to CML...")
        client = _init_client_from_args(args)
        labname = getattr(args, "labname", None)
        if labname:
            lab = client.import_lab_from_path(path, title=labname)
        else:
            lab = client.import_lab_from_path(path)
        if getattr(args, "staging", False) and _staging_version_ok(getattr(args, "cml_version", "0.0.0")):
            abort = not getattr(args, "staging_no_abort", False)
            try:
                lab._set_properties({
                    "node_staging": {
                        "enabled": True,
                        "start_remaining": True,
                        "abort_on_failure": abort,
                    }
                })
                _LOGGER.warning("Node staging enabled (CML 2.10)")
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("Could not enable node staging via API: %s", exc)
        base_url = os.environ.get(
            "VIRL2_URL",
            client.url if hasattr(client, "url") else "http://localhost",
        ).rstrip("/")
        _LOGGER.warning("Lab URL: %s/lab/%s", base_url, lab.id)
        _start_lab_in_background(lab, args)
        return 0

    @staticmethod
    def validate_flat_topology(total_nodes: int, group_size: int) -> int:
        """Validate flat star L2 topology constraints and return access switch count.

        - Access switch: group_size routers + 1 uplink must be <= 32 ports
        - Core switch: number of access switches must be <= 32 ports
        """
        if group_size < 1:
            raise TopogenError("--flat-group-size must be >= 1")

        access_ports_required = group_size + 1  # routers + uplink to core
        if access_ports_required > 32:
            raise TopogenError(
                f"group size {group_size} requires {access_ports_required} ports on an access switch, "
                "which exceeds the typical 32-port limit; reduce --flat-group-size"
            )

        num_access = math.ceil(total_nodes / group_size)
        if num_access > 32:
            raise TopogenError(
                f"{total_nodes} nodes with group size {group_size} requires {num_access} access switches, "
                "which exceeds a typical 32-port core unmanaged switch; increase --flat-group-size"
            )

        return num_access

    @staticmethod
    def new_interface(cmlnode: Node) -> Interface:
        """create a new CML interface for the given node"""
        iface = cmlnode.next_available_interface()
        if iface is None:
            iface = cmlnode.create_interface()
        return iface

    def create_nx_network(self):
        """create a new random network using NetworkX"""

        # cluster size
        size = int(self.args.nodes / 8)
        size = max(size, 20)

        # how many clusters? ensure at least one
        clusters = int(self.args.nodes / size)
        remain = self.args.nodes - clusters * size
        dimensions = int(math.sqrt(self.args.nodes) * self.args.distance)

        constructor = [
            (size, size * 2, 0.999) if a < clusters else (remain, remain * 2, 0.999)
            for a in range(clusters + (1 if remain > 0 else 0))
        ]

        graph = nx.random_shell_graph(constructor)

        # for testing/troubleshooting, this is quite useful
        # graph = nx.barbell_graph(5, 0)

        if not nx.is_connected(graph):
            complement = list(nx.k_edge_augmentation(graph, k=1))
            graph.add_edges_from(complement)
        pos = nx.kamada_kawai_layout(graph, scale=dimensions)
        for key, value in pos.items():
            graph.nodes[key]["pos"] = Point(int(value[0]), int(value[1]))
        return graph

    def _apply_online_lab_intent(self) -> None:
        """Set description, hidden notes, scaled annotation; optional INTENT-SPOT node."""
        try:
            context = f"online, {self.args.mode}"
            desc = _build_intent_description(self.args, context=context)
            coords = _node_coords_from_cml_lab(self.lab)
            x1, y1 = _scaled_intent_annotation_xy(coords)

            self.lab.description = desc
            self.lab.notes = _intent_notes_html(desc)
            self.lab.create_annotation(
                "text",
                border_color="#FFFFFF",
                border_style="",
                color="#FFFFFF",
                rotation=0,
                text_bold=False,
                text_content=desc,
                text_font="monospace",
                text_italic=False,
                text_size=1,
                text_unit="pt",
                thickness=1,
                x1=x1,
                y1=y1,
                z_index=0,
            )

            if getattr(self.args, "intent_spot", False):
                self.create_node("INTENT-SPOT", INTENT_SPOT_NODE_DEF, Point(x1, y1))
        except Exception as exc:  # pragma: no cover - best effort only
            _LOGGER.warning("Online intent metadata failed (best-effort): %s", exc)

    def create_node(self, label: str, node_def: str, coords=Point(0, 0)):
        """create a CML2 node with the given attributes"""

        try:
            node = self.lab.create_node(
                label=label,
                node_definition=node_def,
                x=coords.x,
                y=coords.y,
                populate_interfaces=True,
            )
            # this is needed, otherwise the default interfaces which are created
            # might be missing locally
            self.lab.sync(topology_only=True)
            return node
        except HTTPError as exc:
            raise TopogenError("API error") from exc

    def create_ext_conn(self, coords=Point(0, 0)):
        """create an external connector node"""
        return self.create_node(EXT_CON_NAME, "external_connector", coords)

    def create_dns_host(self, coords=Point(0, 0)):
        """create the DNS host node"""
        node = self.create_node(DNS_HOST_NAME, "alpine", coords)
        node.create_interface()  # this is eth1
        return node

    def create_router(self, label: str, coords=Point(0, 0)):
        """create a router node (this uses the template given, e.g. iosv)"""
        node_def = getattr(self.args, "dev_template", self.args.template)
        return self.create_node(label, node_def, coords)

    def next_network(self) -> Set[IPv4Interface]:
        """return the next point-to-point network"""
        p2pnet = next(self.p2pnets)
        return set(IPv4Interface(f"{i}/{p2pnet.netmask}") for i in p2pnet.hosts())

    def render_node_network(self) -> int:
        """render the NX random network"""

        disable_pcl_loggers()

        manager = None
        ticks = None
        _LOGGER.warning("Creating network")
        graph = self.create_nx_network()

        if self.args.progress:
            manager = enlighten.get_manager()
            eprog = manager.counter(
                total=graph.number_of_edges() + graph.number_of_nodes(),
                desc="topology",
                unit="elements",
                leave=False,
                color="cyan",
            )

        # OOB management network setup (declare early so it's available in edge loop)
        enable_mgmt = getattr(self.args, "enable_mgmt", False)
        mgmt_slot = getattr(self.args, "mgmt_slot", 5)
        oob_switches: list = []
        oob_agg = None
        mgmt_ext_conn = None
        oob_group = max(1, int(getattr(self.args, "flat_group_size", 20)))

        # Two-tier OOB: SWoob0 (aggregation) + SWoob1..N (access, one per group)
        if enable_mgmt:
            total = self.args.nodes
            num_oob_sw = math.ceil(total / oob_group)
            distance = int(getattr(self.args, "distance", 200))

            mgmt_bridge = getattr(self.args, "mgmt_bridge", False)
            if mgmt_bridge:
                mgmt_ext_conn = self.create_node("ext-conn-mgmt", "external_connector", Point(-440, 0))
                mgmt_ext_conn.configuration = "System Bridge"
                _LOGGER.warning("Management external connector: %s", mgmt_ext_conn.label)

            oob_agg = self.create_node("SWoob0", "unmanaged_switch", Point(-200, 0))
            if hasattr(oob_agg, "hide_links"):
                oob_agg.hide_links = True
            _LOGGER.warning("OOB aggregation switch: %s", oob_agg.label)

            if mgmt_bridge:
                self.lab.create_link(
                    mgmt_ext_conn.get_interface_by_slot(0),
                    self.new_interface(oob_agg),
                )
                _LOGGER.warning("Creating mgmt ext-conn link")

            for i in range(num_oob_sw):
                ox = -200 - (i + 1) * distance
                oy = (i + 1) * distance
                acc = self.create_node(f"SWoob{i + 1}", "unmanaged_switch", Point(ox, oy))
                if hasattr(acc, "hide_links"):
                    acc.hide_links = True
                self.lab.create_link(self.new_interface(acc), self.new_interface(oob_agg))
                oob_switches.append(acc)
                _LOGGER.warning("OOB access switch: %s", acc.label)

        _LOGGER.warning("Creating edges and nodes")
        for edge in graph.edges:
            src, dst = edge
            prefix = next(self.p2pnets)
            graph.edges[edge]["prefix"] = prefix
            graph.edges[edge]["hosts"] = iter(prefix.hosts())
            for node_index in [src, dst]:
                node = graph.nodes[node_index]
                if node.get("cml2node") is None:
                    cml2node = self.create_router(f"R{node_index + 1}", node["pos"])
                    _LOGGER.info("router: %s", cml2node.label)
                    node["cml2node"] = cml2node

                    if enable_mgmt and oob_switches:
                        dev_def = getattr(self.args, "dev_template", self.args.template)
                        router_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                        mgmt_if = cml2node.create_interface(slot=router_mgmt_slot)
                        sw_idx = node_index // oob_group
                        oob_if = self.new_interface(oob_switches[sw_idx])
                        self.lab.create_link(mgmt_if, oob_if)
                        _LOGGER.warning("mgmt-link: %s slot %d -> %s", cml2node.label, router_mgmt_slot, oob_switches[sw_idx].label)

                    if self.args.progress:
                        eprog.update()  # type:ignore
            src_iface = self.new_interface(graph.nodes[src]["cml2node"])
            dst_iface = self.new_interface(graph.nodes[dst]["cml2node"])
            self.lab.create_link(src_iface, dst_iface)

            desc = (
                f"{src_iface.node.label} {src_iface.label} -> "
                + f"{dst_iface.node.label} {dst_iface.label}"
            )
            _LOGGER.info("link: %s", desc)
            graph.edges[edge]["order"] = {
                src: src_iface,
                dst: dst_iface,
            }

            if self.args.progress:
                eprog.update()  # type: ignore

        if self.args.progress:
            nprog = manager.counter(  # type: ignore
                total=graph.number_of_nodes(),
                replace=eprog,  # type: ignore
                desc="configs ",
                unit=" configs",
                leave=False,
                color="cyan",
            )

        # create the external connector
        ext_con = self.create_ext_conn(coords=Point(0, 0))
        _LOGGER.warning("External connector: %s", ext_con.label)

        # create the DNS host
        dns_addr, dns_via = self.next_network()
        dns_host = self.create_dns_host(coords=Point(self.args.distance, 0))
        _LOGGER.warning("DNS host: %s", dns_host.label)
        dns_iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_addr.ip)
        dns_zone: list[DNShost] = []

        # link the two
        self.lab.create_link(
            ext_con.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.warning("Creating ext-conn link")

        core = sorted(
            nx.degree_centrality(graph).items(), key=lambda e: e[1], reverse=True
        )[0][0]
        _LOGGER.warning("Identified core node is R%s", core + 1)

        _LOGGER.warning("Creating node configurations")
        for node_index, nbrs in graph.adj.items():
            interfaces: list[TopogenInterface] = []

            for _, eattr in nbrs.items():
                prefix = eattr["prefix"]
                hosts = eattr["hosts"]
                order = eattr["order"]

                addr = IPv4Interface(f"{next(hosts)}/{prefix.netmask}")
                label = format_interface_description(order, node_index)
                interfaces.append(
                    TopogenInterface(address=addr, description=label, slot=order[node_index].slot)
                )
                dns_zone.append(DNShost(format_dns_entry(order, node_index), addr.ip))

            if node_index == core:
                core_iface = self.new_interface(graph.nodes[node_index]["cml2node"])
                self.lab.create_link(
                    dns_iface,
                    core_iface,
                )

                # Use a stupidly high node number for the DNS host, otherwise,
                # in case the DNS host is selected as the central node, the
                # pair would only have one element (prior to this, 0 was used
                # as the key).
                pair = {core: core_iface, 999999: dns_iface}
                label = format_interface_description(pair, node_index)
                assert core_iface.slot is not None
                interfaces.append(
                    TopogenInterface(address=dns_via, description=label, slot=core_iface.slot)
                )
                dns_zone.append(DNShost(format_dns_entry(pair, node_index), dns_via.ip))

                _LOGGER.warning("DNS host link")

            # need to sort interface list by slot
            interfaces.sort(key=lambda x: x.slot)

            # hack for IOL
            if self.args.template == "iol":
                leftover = 4 - len(interfaces) % 4
                if leftover in range(1, 4):  # 1, 2 or 3
                    for _ in range(leftover):
                        interfaces.append(
                            TopogenInterface(
                                IPv4Interface("0.0.0.0/0"),
                                description="unused",
                                slot=0,
                            )
                        )

            cmlnode: Node = graph.nodes[node_index]["cml2node"]
            loopback = IPv4Interface(next(self.loopbacks))
            node = TopogenNode(
                hostname=f"R{node_index + 1}",
                loopback=loopback,
                interfaces=interfaces,
            )

            # Build mgmt context for template
            mgmt_ctx = _build_mgmt_context(
                self.args,
                mgmt_slot=mgmt_slot,
                router_index=node_index + 1,
                loopback=loopback,
                hostname=node.hostname,
            )
            ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            # "origin" identifies the default gateway on the node connecting
            # to the DNS host
            config = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="" if node_index != core else dns_addr,
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(self.args, "archive", False),
            )
            if cmlnode is None:
                continue
            if getattr(self.args, "blank", False):
                cmlnode.configuration = ""  # type: ignore[method-assign]
            # this is a special one-off for the LXC / frr variannt
            elif self.args.template == "lxc":
                nameserver = (
                    self.config.nameserver if self.config.nameserver else dns_addr.ip
                )
                cfg = [
                    {
                        "name": "boot.sh",
                        "content": lxcfrr_bootconfig(
                            self.config,
                            node,
                            ["ospf", "bgp"],
                            str(nameserver),
                            False,
                        ),
                    },
                    {
                        "name": "node.cfg",
                        "content": config,
                    },
                ]
                cmlnode.configuration = cfg  # type: ignore[method-assign]
            else:
                cmlnode.configuration = config  # type: ignore[method-assign]

            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            _LOGGER.warning("Config created for %s", node.hostname)
            if self.args.progress:
                nprog.update()  # type: ignore

        # finalize the DNS host configuration
        node = TopogenNode(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                TopogenInterface(address=dns_addr),
                TopogenInterface(address=dns_via),
            ],
        )
        dns_zone.append(DNShost(f"{DNS_HOST_NAME}-eth1", dns_addr.ip))
        dns_host.config = dnshostconfig(self.config, node, dns_zone)
        _LOGGER.warning("Config created for DNS host")
        _LOGGER.warning("Done")

        if self.args.progress:
            nprog.close()  # type: ignore
            manager.stop()  # type: ignore

        self._apply_online_lab_intent()

        # Print lab URL
        import os
        base_url = os.environ.get('VIRL2_URL', self.client.url if hasattr(self.client, 'url') else 'http://localhost').rstrip('/')
        _LOGGER.warning(f"Lab URL: {base_url}/lab/{self.lab.id}")

        # Start lab if requested (non-blocking)
        _start_lab_in_background(self.lab, self.args)

        return 0

    def _render_dmvpn_flat_pair_network(self, nbma_net: IPv4Network, tunnel_net: IPv4Network) -> int:
        disable_pcl_loggers()

        total_routers = int(self.args.nodes)
        total_endpoints = (total_routers + 1) // 2

        manager = None
        ticks = None

        stub_evens = bool(getattr(self.args, "eigrp_stub", False)) and str(
            getattr(self.args, "dmvpn_routing", "eigrp")
        ).lower() == "eigrp"

        dmvpn_vrf = self.args.pair_vrf if getattr(self.args, "enable_vrf", False) else None
        dmvpn_fvrf = getattr(self.args, "dmvpn_fvrf", None)

        hubs_list = getattr(self.args, "dmvpn_hubs_list", None)
        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        max_odd_rnum = total_routers if (total_routers % 2) == 1 else (total_routers - 1)
        if max_odd_rnum > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for router number {max_odd_rnum}"
            )
        if max_odd_rnum > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for router number {max_odd_rnum}"
            )

        group = max(1, int(getattr(self.args, "flat_group_size", 20)))
        num_sw = Renderer.validate_flat_topology(total_endpoints, group)

        if self.args.progress:
            manager = enlighten.get_manager()
            ticks = manager.counter(
                total=1 + num_sw + total_routers,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        _LOGGER.warning(
            "[dmvpn/flat-pair] Creating %d routers (%d DMVPN endpoints)",
            total_routers,
            total_endpoints,
        )

        core = self.create_node("SWnbma0", "unmanaged_switch", Point(0, 0))
        if ticks:
            ticks.update()  # type: ignore
        switches: list[Node] = []
        for i in range(num_sw):
            x = (i + 1) * self.args.distance * 3
            sw = self.create_node(f"SWnbma{i+1}", "unmanaged_switch", Point(x, 0))
            switches.append(sw)
            self.lab.create_link(self.new_interface(core), self.new_interface(sw))
            if ticks:
                ticks.update()  # type: ignore

        l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"

        pair_ips: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = self.config.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())
        for odd in range(1, total_routers + 1, 2):
            even = odd + 1
            if even > total_routers:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            pair_ips[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        eigrp_template = self._load_companion_eigrp_template_for_dmvpn_flat_pair()

        routers: list[tuple[int, TopogenNode, Node]] = []
        for rnum in range(1, total_routers + 1):
            hostname = f"R{rnum}"
            sw_index = ((rnum - 1) // 2) // group
            x = (sw_index + 1) * self.args.distance * 3
            y = ((rnum - 1) % (group * 2) + 1) * self.args.distance

            cml_router = self.create_router(hostname, Point(x, y))

            hi = (rnum // 256) & 0xFF
            lo = rnum % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            if rnum % 2 == 1:
                nbma_ip = IPv4Interface(
                    f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}"
                )
                tunnel_ip = IPv4Interface(
                    f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}"
                )
                pair_ip = pair_ips.get(rnum, (None, None))[0]
                ifaces = [
                    TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                    TopogenInterface(address=pair_ip, description="pair link", slot=1),
                    TopogenInterface(address=tunnel_ip, description="dmvpn tunnel", slot=1000),
                ]
            else:
                pair_ip = pair_ips.get(rnum - 1, (None, None))[1]
                ifaces = [TopogenInterface(address=pair_ip, description="pair link", slot=0)]

            node = TopogenNode(hostname=hostname, loopback=loopback_ip, interfaces=ifaces)
            routers.append((rnum, node, cml_router))
            if ticks:
                ticks.update()  # type: ignore

        for rnum, _node, cml_router in routers:
            if (rnum % 2) == 0:
                continue
            endpoint_idx = (rnum + 1) // 2
            sw_index = (endpoint_idx - 1) // group
            sw = switches[sw_index]
            try:
                r_if = cml_router.get_interface_by_slot(0)
            except Exception:
                r_if = self.new_interface(cml_router)
            self.lab.create_link(r_if, self.new_interface(sw))

        for odd in range(1, total_routers + 1, 2):
            even = odd + 1
            if even > total_routers:
                continue
            odd_router = routers[odd - 1][2]
            even_router = routers[even - 1][2]
            try:
                odd_if = odd_router.get_interface_by_slot(1)
            except Exception:
                odd_if = self.new_interface(odd_router)
            try:
                even_if = even_router.get_interface_by_slot(0)
            except Exception:
                even_if = self.new_interface(even_router)
            self.lab.create_link(odd_if, even_if)

        hub_info: list[dict[str, IPv4Address]] = []
        for rnum, node, _cml_router in routers:
            if (rnum % 2) == 0:
                continue
            if rnum in hub_set:
                nbma_iface = next((i for i in node.interfaces if i.description == "dmvpn nbma"), None)
                tun_iface = next((i for i in node.interfaces if i.description == "dmvpn tunnel"), None)
                if nbma_iface and nbma_iface.address and tun_iface and tun_iface.address:
                    hub_info.append(
                        {
                            "hub_nbma_ip": nbma_iface.address.ip,
                            "hub_tunnel_ip": tun_iface.address.ip,
                        }
                    )

        for rnum, node, cml_router in routers:
            if (rnum % 2) == 1:
                rendered = self.template.render(
                    config=self.config,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    is_hub=(rnum in hub_set),
                    hub_info=hub_info,
                    dmvpn_tunnel_key=getattr(self.args, "dmvpn_tunnel_key", 10),
                    dmvpn_phase=getattr(self.args, "dmvpn_phase", 2),
                    dmvpn_vrf=dmvpn_vrf,
                    dmvpn_fvrf=dmvpn_fvrf,
                    dmvpn_security=getattr(self.args, "dmvpn_security", "none"),
                    dmvpn_psk=getattr(self.args, "dmvpn_psk", None),
                    dmvpn_trustpoint=getattr(self.args, "dmvpn_trustpoint", "CA-ROOT-SELF"),
                    ipsec_mode=getattr(self.args, "dmvpn_ipsec_mode", "transport"),
                    archive=getattr(self.args, "archive", False),
                )
                if getattr(self.args, "pki_enabled", False):
                    ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                    rendered = _inject_pki_client_trustpoint(
                        rendered, node.hostname, self.config.domainname, ca_url
                    )
            else:
                rendered = eigrp_template.render(
                    config=self.config,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    eigrp_stub=stub_evens,
                    archive=getattr(self.args, "archive", False),
                )
            try:
                cml_router.configuration = rendered  # type: ignore[method-assign]
            except Exception:
                pass

        hubs_str = ",".join(str(i["hub_tunnel_ip"]) for i in hub_info) if hub_info else ""
        _LOGGER.warning(
            "[dmvpn/flat-pair] NBMA: %s | Tunnel: %s | Hubs(tunnel): %s",
            nbma_net,
            tunnel_net,
            hubs_str,
        )

        self._apply_online_lab_intent()

        outfile = getattr(self.args, "yaml_output", None)
        if outfile:
            try:
                content = None
                if hasattr(self.client, "export_lab"):
                    content = self.client.export_lab(self.lab.id)  # type: ignore[attr-defined]
                elif hasattr(self.lab, "export"):
                    content = self.lab.export()  # type: ignore[attr-defined]
                elif hasattr(self.lab, "topology"):
                    content = str(self.lab.topology)  # type: ignore[attr-defined]
                if content is not None:
                    data = content if isinstance(content, bytes) else str(content).encode("utf-8")
                    with open(outfile, "wb") as fh:
                        fh.write(data)
                    _LOGGER.warning("Exported lab YAML to %s", outfile)
                else:
                    _LOGGER.error("YAML export not supported by client library")
            except Exception as exc:  # pragma: no cover
                _LOGGER.error("YAML export failed: %s", exc)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    def render_dmvpn_network(self) -> int:
        """Render a DMVPN topology (hub + spokes).

        DMVPN rendering is implemented in a later step.
        """

        disable_pcl_loggers()

        manager = None
        ticks = None

        try:
            nbma_net = IPv4Network(str(getattr(self.args, "dmvpn_nbma_cidr", "10.10.0.0/16")))
            tunnel_net = IPv4Network(
                str(getattr(self.args, "dmvpn_tunnel_cidr", "172.20.0.0/16"))
            )
        except Exception as exc:
            raise TopogenError(f"Invalid DMVPN CIDR: {exc}") from None

        underlay = getattr(self.args, "dmvpn_underlay", "flat")
        if underlay == "flat-pair":
            return self._render_dmvpn_flat_pair_network(nbma_net, tunnel_net)

        hubs_list = getattr(self.args, "dmvpn_hubs_list", None)
        if hubs_list:
            total_routers = int(self.args.nodes)
            spokes = total_routers - len(hubs_list)
        else:
            spokes = int(self.args.nodes)
            total_routers = spokes + 1

        if total_routers > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for {total_routers} routers"
            )
        if total_routers > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for {total_routers} routers"
            )

        if hubs_list:
            _LOGGER.warning(
                "[dmvpn] Creating %d hubs + %d spokes (total %d routers)",
                len(hubs_list),
                spokes,
                total_routers,
            )
        else:
            _LOGGER.warning(
                "[dmvpn] Creating 1 hub + %d spokes (total %d routers)",
                spokes,
                total_routers,
            )

        if self.args.progress:
            manager = enlighten.get_manager()
            ticks = manager.counter(
                total=1 + total_routers,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        nbma_sw = self.create_node("SWnbma0", "unmanaged_switch", Point(0, 0))
        if ticks:
            ticks.update()  # type: ignore

        # Deterministic Loopback0 addressing (match flat/offline behavior)
        l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"

        routers: list[tuple[TopogenNode, Node]] = []
        for idx in range(total_routers):
            hostname = f"R{idx + 1}"
            x = (idx + 1) * self.args.distance * 2
            y = self.args.distance * 2 if idx == 0 else -self.args.distance * 2

            cml_router = self.create_router(hostname, Point(x, y))

            try:
                wan_iface = cml_router.get_interface_by_slot(0)
            except Exception:  # pragma: no cover - defensive
                wan_iface = self.new_interface(cml_router)
            self.lab.create_link(wan_iface, self.new_interface(nbma_sw))

            nbma_ip = IPv4Interface(
                f"{nbma_net.network_address + (idx + 1)}/{nbma_net.prefixlen}"
            )
            tunnel_ip = IPv4Interface(
                f"{tunnel_net.network_address + (idx + 1)}/{tunnel_net.prefixlen}"
            )

            rnum = idx + 1
            hi = (rnum // 256) & 0xFF
            lo = rnum % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")
            node = TopogenNode(
                hostname=hostname,
                loopback=loopback_ip,
                interfaces=[
                    TopogenInterface(
                        address=nbma_ip,
                        description="dmvpn nbma",
                        slot=0,
                    ),
                    TopogenInterface(
                        address=tunnel_ip,
                        description="dmvpn tunnel",
                        slot=1000,
                    ),
                ],
            )

            routers.append((node, cml_router))
            if ticks:
                ticks.update()  # type: ignore

        # hub_info is a list of {hub_nbma_ip, hub_tunnel_ip} entries used by spoke templates
        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        hub_info: list[dict[str, IPv4Address]] = []
        for idx, (node, _cml_router) in enumerate(routers):
            rnum = idx + 1
            if rnum in hub_set:
                hub_info.append(
                    {
                        "hub_nbma_ip": node.interfaces[0].address.ip,  # type: ignore[union-attr]
                        "hub_tunnel_ip": node.interfaces[1].address.ip,  # type: ignore[union-attr]
                    }
                )

        for idx, (node, cml_router) in enumerate(routers):
            rnum = idx + 1
            rendered = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                is_hub=(rnum in hub_set),
                hub_info=hub_info,
                dmvpn_tunnel_key=getattr(self.args, "dmvpn_tunnel_key", 10),
                dmvpn_phase=getattr(self.args, "dmvpn_phase", 2),
                dmvpn_fvrf=getattr(self.args, "dmvpn_fvrf", None),
                dmvpn_security=getattr(self.args, "dmvpn_security", "none"),
                dmvpn_psk=getattr(self.args, "dmvpn_psk", None),
                dmvpn_trustpoint=getattr(self.args, "dmvpn_trustpoint", "CA-ROOT-SELF"),
                ipsec_mode=getattr(self.args, "dmvpn_ipsec_mode", "transport"),
                archive=getattr(self.args, "archive", False),
            )
            if getattr(self.args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, node.hostname, self.config.domainname, ca_url
                )
            try:
                cml_router.configuration = rendered  # type: ignore[method-assign]
            except Exception:
                pass

        if hub_info:
            hubs_str = ",".join(
                str(i["hub_tunnel_ip"]) for i in hub_info
            )
        else:
            hubs_str = ""
        _LOGGER.warning(
            "[dmvpn] NBMA: %s | Tunnel: %s | Hubs(tunnel): %s",
            nbma_net,
            tunnel_net,
            hubs_str,
        )

        self._apply_online_lab_intent()

        outfile = getattr(self.args, "yaml_output", None)
        if outfile:
            try:
                content = None
                if hasattr(self.client, "export_lab"):
                    content = self.client.export_lab(self.lab.id)  # type: ignore[attr-defined]
                elif hasattr(self.lab, "export"):
                    content = self.lab.export()  # type: ignore[attr-defined]
                elif hasattr(self.lab, "topology"):
                    content = str(self.lab.topology)  # type: ignore[attr-defined]
                if content is not None:
                    if isinstance(content, bytes):
                        data = content
                    else:
                        data = str(content).encode("utf-8")
                    with open(outfile, "wb") as fh:
                        fh.write(data)
                    _LOGGER.warning("Exported lab YAML to %s", outfile)
                else:
                    _LOGGER.error("YAML export not supported by client library")
            except Exception as exc:  # pragma: no cover - best-effort export
                _LOGGER.error("YAML export failed: %s", exc)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    def render_flat_pair_network(self) -> int:
        """Render a flat L2 management network with odd-even router pairing.

        Rules:
        - Create unmanaged switches like flat mode (same guardrails and positions).
        - Odd routers: Gi0/0 -> access switch; additionally link Gi0/1 <-> even router's Gi0/0.
        - Even routers: no link to access switch; only paired to preceding odd.
        - If last odd router has no even partner, its Gi0/1 remains unused.
        - Switch port counts (guardrails) remain based on configured group size.
        - Interface IP addressing and templates remain identical to flat mode for now
          (only Gi0/0 configured); pairing link has no IP unless templates are later updated.
        """

        disable_pcl_loggers()

        total = self.args.nodes
        group = max(1, int(self.args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)

        dev_def = getattr(self.args, "dev_template", self.args.template)
        if dev_def != "iosv":
            _LOGGER.warning(
                "Using custom device template '%s'; guardrails assume ~32-port unmanaged_switch and do not account for custom node definitions/images",
                dev_def,
            )

        _LOGGER.warning(
            "[flat-pair] Creating %d unmanaged switches for %d routers (group size %d)",
            num_sw,
            total,
            group,
        )

        # Core switch
        core = self.create_node("SW0", "unmanaged_switch", Point(0, 0))

        # Access switches positioned horizontally and connected to core
        switches: list[Node] = []
        for i in range(num_sw):
            x = (i + 1) * self.args.distance * 3
            sw = self.create_node(f"SW{i+1}", "unmanaged_switch", Point(x, 0))
            switches.append(sw)
            self.lab.create_link(self.new_interface(core), self.new_interface(sw))
            _LOGGER.info("switch-link: %s <-> %s", core.label, sw.label)

        # Pre-compute /30 p2p addressing for odd-even pairs from config.p2pnets
        pair_ips: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = self.config.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())  # safe fallback, yields no addresses
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            # Assign first host to odd Gi0/1, second to even Gi0/0
            pair_ips[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        # Create routers and attach ONLY odd router Gi0/0 to the access switch
        cml_routers: list[Node] = []
        for idx in range(total):
            router_label = f"R{idx + 1}"
            sw_index = idx // group
            rx = (sw_index + 1) * self.args.distance * 3
            ry = (idx % group + 1) * self.args.distance
            cml_router = self.create_router(router_label, Point(rx, ry))
            cml_routers.append(cml_router)

            # Configure addresses as in flat mode (Loopback and Gi0/0 only)
            ridx = idx + 1
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            g_addr = IPv4Interface(f"{g_base}.{hi}.{lo}/16")
            l_addr = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            # Build per-router interface configs:
            # - Odd routers: Gi0/0 with IP, plus Gi0/1. If a pair IP exists, assign it; else L2-only.
            # - Even routers: Gi0/0. If a pair IP exists, assign it; else L2-only.
            rnum = idx + 1
            if rnum % 2 == 1:
                # odd
                odd_ip = pair_ips.get(rnum, (None, None))[0]
                pair_vrf = (
                    getattr(self.args, "pair_vrf", None)
                    if getattr(self.args, "enable_vrf", False)
                    else None
                )
                ifaces = [
                    TopogenInterface(address=g_addr, description="mgmt flat-pair", slot=0),
                    TopogenInterface(
                        address=odd_ip,
                        vrf=pair_vrf,
                        description="pair link",
                        slot=1,
                    ),
                ]
            else:
                # even
                even_ip = pair_ips.get(rnum - 1, (None, None))[1]
                ifaces = [TopogenInterface(address=even_ip, description="pair link", slot=0)]

            node = TopogenNode(
                hostname=router_label,
                loopback=l_addr,
                interfaces=ifaces,
            )
            config = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                archive=getattr(self.args, "archive", False),
            )
            if getattr(self.args, "blank", False):
                cml_router.configuration = ""  # type: ignore[method-assign]
            else:
                cml_router.configuration = config  # type: ignore[method-assign]

            # Only odd routers connect Gi0/0 to access switch
            if (idx + 1) % 2 == 1:
                try:
                    r_if = cml_router.get_interface_by_slot(0)
                except Exception:
                    r_if = self.new_interface(cml_router)
                sw = switches[sw_index]
                s_if = self.new_interface(sw)
                self.lab.create_link(r_if, s_if)
                _LOGGER.info("link: %s Gi0/0 -> %s", cml_router.label, sw.label)

        # Create odd-even pairing links: R1 Gi0/1 <-> R2 Gi0/0, R3 Gi0/1 <-> R4 Gi0/0, ...
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                # No partner for last odd router; Gi0/1 remains unused
                _LOGGER.info("pair: R%d has no even partner; Gi0/1 unused", odd)
                continue

            odd_router = cml_routers[odd - 1]
            even_router = cml_routers[even - 1]

            # Ensure Gi0/1 exists on odd, Gi0/0 on even
            try:
                odd_if = odd_router.get_interface_by_slot(1)
            except Exception:
                odd_if = self.new_interface(odd_router)
            try:
                even_if = even_router.get_interface_by_slot(0)
            except Exception:
                even_if = self.new_interface(even_router)

            self.lab.create_link(odd_if, even_if)
            _LOGGER.info("pair-link: R%d Gi0/1 <-> R%d Gi0/0", odd, even)

        _LOGGER.warning("Flat-pair management network created")
        self._apply_online_lab_intent()
        return 0

    @staticmethod
    def offline_dmvpn_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML file locally for DMVPN mode.

        This does not contact a controller. It writes a minimal topology with:
        - SWnbma0 unmanaged switch (shared NBMA underlay)
        - Routers R1..R<n+1> (R1 hub, remaining routers are spokes)
        - Links: each router's WAN interface (slot 0) connected to SWnbma0
        - Per-router configuration rendered from the selected Jinja2 template
        """

        # set up Jinja to render configs from packaged templates
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        # DMVPN mode requires a template with Tunnel0/NHRP; use -dmvpn template if base was chosen
        tpl_name = (
            args.template
            if args.template.endswith("-dmvpn")
            else ("csr-dmvpn" if str(getattr(args, "dev_template", args.template)).lower() == "csr1000v" else "iosv-dmvpn")
        )
        try:
            tpl = env.get_template(f"{tpl_name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover - defensive
            raise TopogenError(f"template does not exist: {tpl_name}") from exc

        try:
            nbma_net = IPv4Network(str(getattr(args, "dmvpn_nbma_cidr", "10.10.0.0/16")))
            tunnel_net = IPv4Network(
                str(getattr(args, "dmvpn_tunnel_cidr", "172.20.0.0/16"))
            )
        except Exception as exc:
            raise TopogenError(f"Invalid DMVPN CIDR: {exc}") from None

        hubs_list = getattr(args, "dmvpn_hubs_list", None)
        if hubs_list:
            total_routers = int(args.nodes)
            spokes = total_routers - len(hubs_list)
        else:
            spokes = int(args.nodes)
            total_routers = spokes + 1

        manager = None
        ticks = None

        # CML input validation requires x/y coordinates to be within a bounded range.
        # The CML API currently enforces x <= 15000 (and similarly for y). Keep all
        # nodes within this range.
        max_coord = 15000

        if total_routers > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for {total_routers} routers"
            )
        if total_routers > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for {total_routers} routers"
            )

        nac_enabled = bool(getattr(args, "nac", False))
        cml2_enabled = bool(getattr(args, "terraform_cml2", False))
        outfile, nac_root, cml2_root = resolve_offline_artifact_paths(
            getattr(args, "offline_yaml"),
            nac_enabled=nac_enabled,
            cml2_enabled=cml2_enabled,
        )
        dev_def = getattr(args, "dev_template", args.template)

        def iface_label_for_slot(slot: int) -> str:
            # CML node definitions can have different interface naming.
            # csr1000v typically uses GigabitEthernet1, GigabitEthernet2, ...
            if str(dev_def).lower() == "csr1000v":
                return f"GigabitEthernet{slot + 1}"
            return f"GigabitEthernet0/{slot}"

        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")

        args_bits: list[str] = [f"nodes={args.nodes}", f"-m {args.mode}", f"-T {args.template}"]
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        args_bits.append(f"--dmvpn-phase {getattr(args, 'dmvpn_phase', 2)}")
        args_bits.append(f"--dmvpn-routing {getattr(args, 'dmvpn_routing', 'eigrp')}")
        args_bits.append(f"--dmvpn-security {getattr(args, 'dmvpn_security', 'none')}")
        args_bits.append(f"--dmvpn-ipsec-mode {getattr(args, 'dmvpn_ipsec_mode', 'transport')}")
        args_bits.append(f"--dmvpn-nbma-cidr {nbma_net}")
        args_bits.append(f"--dmvpn-tunnel-cidr {tunnel_net}")
        if hubs_list:
            args_bits.append(f"--dmvpn-hubs {getattr(args, 'dmvpn_hubs')}")
        if getattr(args, "pki_enabled", False):
            args_bits.append("--pki")
        if getattr(args, "getvpn_enabled", False):
            args_bits.append("--getvpn")
            args_bits.append(f"--getvpn-protocol {getattr(args, 'getvpn_protocol', 'gdoi')}")
            args_bits.append(f"--getvpn-group-id {getattr(args, 'getvpn_group_id', 1)}")
            args_bits.append(f"--getvpn-rekey-interval {getattr(args, 'getvpn_rekey_interval', 86400)}")
        version = getattr(args, "cml_version", "0.3.0")
        append_cml_schema_provenance_args(args_bits, args)
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
            if getattr(args, "mgmt_ipv4_dhcp", False):
                args_bits.append("--mgmt-ipv4-dhcp")
            ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
            if ipv6_mode == "dhcpv6":
                args_bits.append("--mgmt-ipv6-dhcp")
            elif ipv6_mode == "slaac":
                args_bits.append("--mgmt-ipv6-slaac")
            elif ipv6_mode == "static":
                args_bits.append("--mgmt-ipv6-static")
            elif ipv6_mode:
                args_bits.append(f"--mgmt-ipv6-mode {ipv6_mode}")
            if getattr(args, "mgmt_ipv6_static_link_local", False):
                args_bits.append("--mgmt-ipv6-static-link-local")
            if getattr(args, "mgmt_ipv6_cidr", None):
                args_bits.append(f"--mgmt-ipv6-cidr {args.mgmt_ipv6_cidr}")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        staging = getattr(args, "staging", False) and _staging_version_ok(version)
        if staging:
            args_bits.append("--staging")
        _append_common_offline_args_bits(args_bits, args)
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")

        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, dmvpn) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f"  description: \"{desc}\"")
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        if staging:
            lines.extend(_node_staging_lines(abort_on_failure=not getattr(args, "staging_no_abort", False)))
        lines.append("nodes:")

        getvpn_enabled = getattr(args, "getvpn_enabled", False)
        node_ids: dict[str, str] = {}
        nid = 0

        # NBMA underlay: flat-style star fabric (like flat mode)
        # One core unmanaged switch (SWnbma0) plus N access switches (SWnbma1..N).
        # Each router's WAN interface connects to exactly one access switch; each access
        # switch has one uplink to the core. This avoids the unmanaged_switch 32-port cap.
        MAX_SW_PORTS = 32
        group = max(1, int(getattr(args, "flat_group_size", 20)))
        if group + 1 > MAX_SW_PORTS:
            raise TopogenError(
                f"Invalid --flat-group-size {group}: requires {group + 1} ports per access switch (>32). Reduce --flat-group-size."
            )

        from math import ceil

        num_access = ceil(total_routers / group)
        if num_access > MAX_SW_PORTS:
            raise TopogenError(
                f"DMVPN NBMA requires {num_access} access switches with group_size={group}, but core unmanaged_switch supports only 32 uplinks. Increase --flat-group-size."
            )

        # OOB management switches (if --mgmt enabled) - mirrors NBMA switch pattern
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            num_oob_sw = num_access  # Match the number of NBMA switches
            # Precompute how many routers per OOB access switch (same grouping as NBMA)
            for i in range(num_oob_sw):
                start = i * oob_group
                end = min((i + 1) * oob_group, total_routers)
                oob_per_sw_counts.append(max(0, end - start))

        if getattr(args, "progress", False):
            manager = enlighten.get_manager()
            oob_ticks = (1 + (2 * num_oob_sw) + total_routers) if enable_mgmt else 0
            ticks = manager.counter(
                total=1 + (2 * num_access) + (2 * total_routers) + oob_ticks,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        # Match flat/flat-pair layout: core at (0,0), access switches along +X,
        # routers stacked under their access switch.
        base_distance = int(getattr(args, "distance", 200))
        base_sw_step_x = base_distance * 3
        # Scale X spacing so the right-most access switch stays within max_coord.
        sw_step_x = max(1, min(base_sw_step_x, max_coord // max(1, (num_access + 1))))
        # Scale router Y spacing so the bottom-most router stays within max_coord.
        router_step_y = max(1, min(base_distance, max_coord // max(1, (group + 2))))

        # Core NBMA switch (one port per access switch + one for CA-ROOT if --pki)
        swnbma0_port_count = num_access
        if getattr(args, "pki_enabled", False):
            swnbma0_port_count += 1
        if getvpn_enabled:
            swnbma0_port_count += 1
        node_ids["SWnbma0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SWnbma0']}")
        lines.append("    label: SWnbma0")
        lines.append("    node_definition: unmanaged_switch")
        if staging:
            lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
        lines.append("    x: 0")
        lines.append("    y: 0")
        lines.append("    interfaces:")
        for p in range(swnbma0_port_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append("        type: physical")

        if ticks:
            ticks.update()  # type: ignore

        # Access NBMA switches (each has 1 uplink + router-facing ports)
        # router_port_map[idx] -> (access_switch_label, access_port)
        router_port_map: list[tuple[str, int]] = []
        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            node_ids[sw_label] = f"n{nid}"; nid += 1
            sx = min(max_coord, (sidx + 1) * sw_step_x)
            lines.append(f"  - id: {node_ids[sw_label]}")
            lines.append(f"    label: {sw_label}")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
            lines.append(f"    x: {sx}")
            lines.append("    y: 0")
            lines.append("    interfaces:")

            start = sidx * group
            end = min((sidx + 1) * group, total_routers)
            router_count = max(0, end - start)
            if_count = 1 + router_count
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append("        type: physical")

            for p in range(1, if_count):
                router_port_map.append((sw_label, p))

            if ticks:
                ticks.update()  # type: ignore

        # OOB management switches (if --mgmt enabled)
        if enable_mgmt:
            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch (one port per OOB access switch + one for CA-ROOT if --pki)
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            if getvpn_enabled:
                swoob0_port_count += 1
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append("        type: physical")

            if ticks:
                ticks.update()  # type: ignore

            # OOB access switches
            base_distance = int(getattr(args, "distance", 200))
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * base_distance
                oy = (i + 1) * base_distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {oy}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append("        type: physical")

                if ticks:
                    ticks.update()  # type: ignore

        # Determine hub set and precompute hub_info for spoke templates
        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        hub_info: list[dict[str, IPv4Address]] = []
        for rnum in range(1, total_routers + 1):
            if rnum not in hub_set:
                continue
            hub_info.append(
                {
                    "hub_nbma_ip": IPv4Interface(
                        f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}"
                    ).ip,
                    "hub_tunnel_ip": IPv4Interface(
                        f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}"
                    ).ip,
                }
            )

        # Deterministic Loopback0 addressing (match flat mode)
        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"

        # Routers
        nac_router_nodes: list[TopogenNode] = []
        for idx in range(total_routers):
            n = idx + 1
            label = f"R{n}"
            node_ids[label] = f"n{nid}"; nid += 1

            nbma_ip = IPv4Interface(
                f"{nbma_net.network_address + n}/{nbma_net.prefixlen}"
            )
            tunnel_ip = IPv4Interface(
                f"{tunnel_net.network_address + n}/{tunnel_net.prefixlen}"
            )

            hi = (n // 256) & 0xFF
            lo = n % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")
            node = TopogenNode(
                hostname=label,
                loopback=loopback_ip,
                interfaces=[
                    TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                    TopogenInterface(address=tunnel_ip, description="dmvpn tunnel", slot=1000),
                ],
            )
            nac_node = TopogenNode(
                hostname=label,
                loopback=loopback_ip,
                interfaces=[
                    TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                    TopogenInterface(address=tunnel_ip, description="dmvpn tunnel", slot=1000),
                ],
            )
            _append_nac_mgmt_interface(nac_node, args, n)
            nac_router_nodes.append(nac_node)

            # Build mgmt context for template
            mgmt_ctx = _build_mgmt_context(
                args,
                mgmt_slot=mgmt_slot,
                router_index=n,
                loopback=loopback_ip,
                hostname=label,
            )
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            rendered = tpl.render(
                config=cfg,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                is_hub=(n in hub_set),
                hub_info=hub_info,
                dmvpn_tunnel_key=getattr(args, "dmvpn_tunnel_key", 10),
                dmvpn_phase=getattr(args, "dmvpn_phase", 2),
                dmvpn_fvrf=getattr(args, "dmvpn_fvrf", None),
                dmvpn_security=getattr(args, "dmvpn_security", "none"),
                dmvpn_psk=getattr(args, "dmvpn_psk", None),
                dmvpn_trustpoint=getattr(args, "dmvpn_trustpoint", "CA-ROOT-SELF"),
                ipsec_mode=getattr(args, "dmvpn_ipsec_mode", "transport"),
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )
            if getvpn_enabled:
                ks_ip = str(nbma_net.broadcast_address - 4)
                gm_wan = "GigabitEthernet1" if dev_def == "csr1000v" else "GigabitEthernet0/0"
                rendered = _inject_getvpn_gm_config(
                    rendered, label, cfg.domainname,
                    getattr(args, "getvpn_protocol", "gdoi"),
                    getattr(args, "getvpn_group_id", 1),
                    ks_ip, gm_wan,
                )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )
            rendered = _finalize_router_day0_config(rendered, cfg, nac_node, args)

            # Flat-like placement
            sw_index = idx // group
            x = min(max_coord, (sw_index + 1) * sw_step_x)
            y = min(max_coord, (idx % group + 1) * router_step_y)
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            if staging and n in hub_set:
                lines.append(f"    priority: {STAGING_PRIORITY_HUB_KS}")
            lines.append(f"    x: {x}")
            lines.append(f"    y: {y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append(f"        label: {iface_label_for_slot(0)}")
            lines.append("        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, rendered, getattr(args, "blank", False))

            if ticks:
                ticks.update()  # type: ignore

        # GET VPN Key Server node (if --getvpn enabled)
        if getvpn_enabled:
            ks_label = "KS"
            node_ids[ks_label] = f"n{nid}"; nid += 1

            ks_nbma_ip = IPv4Interface(f"{nbma_net.broadcast_address - 4}/{nbma_net.prefixlen}")
            ks_lo_ip = IPv4Interface(f"{l_base}.255.251/32")

            ks_dev_def = "csr1000v"
            ks_tpl = env.get_template(f"csr-getvpn-ks{Renderer.J2SUFFIX}")

            ks_node = TopogenNode(
                hostname=ks_label,
                loopback=ks_lo_ip,
                interfaces=[
                    TopogenInterface(
                        address=ks_nbma_ip, description="=== GETVPN Key Server ===", slot=0
                    )
                ],
            )
            ks_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ks_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ks_ntp_ctx = {"server": args.ntp_server, "vrf": getattr(args, "ntp_vrf", None)}
            ks_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ks_ntp_oob_ctx = {"server": args.ntp_oob_server, "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf"}
            ks_rendered = ks_tpl.render(
                config=cfg, node=ks_node, date=datetime.now(timezone.utc), origin="",
                mgmt=ks_mgmt_ctx, ntp=ks_ntp_ctx, ntp_oob=ks_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
                getvpn_protocol=getattr(args, "getvpn_protocol", "gdoi"),
                getvpn_group_id=getattr(args, "getvpn_group_id", 1),
                getvpn_rekey_interval=getattr(args, "getvpn_rekey_interval", 86400),
                getvpn_ks_ip=str(ks_nbma_ip.ip),
            )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                ks_rendered = _inject_pki_client_trustpoint(ks_rendered, ks_label, cfg.domainname, ca_url)

            ks_x = -400
            ks_y = 300
            lines.append(f"  - id: {node_ids[ks_label]}")
            lines.append(f"    label: {ks_label}")
            lines.append(f"    node_definition: {ks_dev_def}")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_HUB_KS}")
            lines.append(f"    x: {ks_x}")
            lines.append(f"    y: {ks_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                csr_slot = mgmt_slot - 1
                lines.append(f"      - id: i{csr_slot}")
                lines.append(f"        slot: {csr_slot}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ks_rendered, getattr(args, "blank", False))

        # CA-ROOT node (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1
            ca_nbma_ip = IPv4Interface(f"{nbma_net.broadcast_address - 1}/{nbma_net.prefixlen}")
            ca_loopback_ip = IPv4Interface(f"{l_base}.255.254/32")
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=ca_loopback_ip,
                interfaces=[
                    TopogenInterface(
                        address=ca_nbma_ip,
                        description="=== SCEP Enrollment URL ===",
                        slot=0,
                    )
                ],
            )
            try:
                ca_base_tpl = env.get_template(f"csr-eigrp{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                raise TopogenError("CA template not found: csr-eigrp")
            ca_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]
            ca_config_lines = ca_base_config.splitlines()
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"
            ca_scep_url = f"http://{ca_nbma_ip.ip}:80"
            non_eem_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + ["alias exec servcerts sh crypto pki server CA-ROOT cer", "!"]
            )
            eem_block = _pki_ca_authenticate_eem_lines()
            try:
                eem_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip().startswith("event manager"))
            except StopIteration:
                try:
                    eem_idx = next(i for i in range(len(ca_config_lines) - 1, -1, -1) if ca_config_lines[i].strip() == "end")
                except StopIteration:
                    eem_idx = len(ca_config_lines)
            ca_config_lines[eem_idx:eem_idx] = non_eem_block
            try:
                end_idx = next(i for i in range(len(ca_config_lines) - 1, -1, -1) if ca_config_lines[i].strip() == "end")
                ca_config_lines[end_idx:end_idx] = eem_block
            except StopIteration:
                ca_config_lines.extend(eem_block)
                ca_config_lines.append("end")
            ca_rendered = "\n".join(ca_config_lines)
            ca_x = -400
            ca_y = 200
            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append("    node_definition: csr1000v")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_CA_ROOT}")
            lines.append(f"    x: {ca_x}")
            lines.append(f"    y: {ca_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                ca_mgmt_slot_id = mgmt_slot - 1
                lines.append(f"      - id: i{ca_mgmt_slot_id}")
                lines.append(f"        slot: {ca_mgmt_slot_id}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ca_rendered, getattr(args, "blank", False))

        # Links
        lines.append("links:")
        lid = 0

        # Access-to-core links (NBMA fabric uplinks)
        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[sw_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{sidx}")

            if ticks:
                ticks.update()  # type: ignore

        # CA-ROOT -> SWnbma0 data link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            swnbma0_ca_port = num_access
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{swnbma0_ca_port}")

        # KS -> SWnbma0 data link (if --getvpn enabled)
        if getvpn_enabled:
            ks_label = "KS"
            swnbma0_ks_port = num_access
            if getattr(args, "pki_enabled", False):
                swnbma0_ks_port += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ks_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{swnbma0_ks_port}")

        # Router-to-NBMA links (each router uses its slot-0 interface)
        for idx in range(total_routers):
            rlabel = f"R{idx + 1}"
            sw_label, sw_port = router_port_map[idx]
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[sw_label]}")
            lines.append(f"    i2: i{sw_port}")

            if ticks:
                ticks.update()  # type: ignore

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

                if ticks:
                    ticks.update()  # type: ignore

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for idx in range(total_routers):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

                if ticks:
                    ticks.update()  # type: ignore

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                ca_mgmt_iface_id = mgmt_slot - 1  # CA is always CSR1000v
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

            # KS -> SWoob0 mgmt link (if --getvpn enabled)
            if getvpn_enabled:
                ks_label = "KS"
                ks_mgmt_iface_id = mgmt_slot - 1
                swoob0_ks_port = port_offset + num_oob_sw
                if getattr(args, "pki_enabled", False):
                    swoob0_ks_port += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ks_label]}")
                lines.append(f"    i1: i{ks_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ks_port}")

        _validate_nac_router_nodes_if_enabled(nac_root, nac_router_nodes, dev_def)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if nac_root is not None:
            nac_root.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _finalize_offline_yaml_with_intent(lines, desc, version, args)
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (dmvpn) written to %s (%.1f KB)", outfile, size_kb)
        _write_nac_tree_if_enabled(
            nac_root=nac_root,
            nodes=nac_router_nodes,
            device_template=dev_def,
            template=args.template,
            mode=args.mode,
            args=args,
        )
        write_cml2_lifecycle_if_enabled(args, outfile, cml2_root)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    @staticmethod
    def offline_dmvpn_flat_pair_yaml(args: Namespace, cfg: Config) -> int:
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            dmvpn_tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover
            raise TopogenError(f"template does not exist: {args.template}") from exc

        stub_evens = bool(getattr(args, "eigrp_stub", False)) and str(
            getattr(args, "dmvpn_routing", "eigrp")
        ).lower() == "eigrp"

        dmvpn_vrf = args.pair_vrf if getattr(args, "enable_vrf", False) else None
        dmvpn_fvrf = getattr(args, "dmvpn_fvrf", None)

        base = str(getattr(args, "template", ""))
        if not base.endswith("-dmvpn"):
            raise TopogenError(
                "DMVPN underlay 'flat-pair' requires a '-dmvpn' template (e.g., iosv-dmvpn or csr-dmvpn)"
            )
        eigrp_name = base[: -len("-dmvpn")] + "-eigrp"
        try:
            eigrp_tpl = env.get_template(f"{eigrp_name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(
                f"DMVPN underlay 'flat-pair' requires companion template '{eigrp_name}'"
            ) from exc

        try:
            nbma_net = IPv4Network(str(getattr(args, "dmvpn_nbma_cidr", "10.10.0.0/16")))
            tunnel_net = IPv4Network(str(getattr(args, "dmvpn_tunnel_cidr", "172.20.0.0/16")))
        except Exception as exc:
            raise TopogenError(f"Invalid DMVPN CIDR: {exc}") from None

        hubs_list = getattr(args, "dmvpn_hubs_list", None)
        total_routers = int(args.nodes)
        total_endpoints = (total_routers + 1) // 2

        manager = None
        ticks = None

        max_odd_rnum = total_routers if (total_routers % 2) == 1 else (total_routers - 1)
        if max_odd_rnum > (nbma_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN NBMA CIDR {nbma_net} is too small for router number {max_odd_rnum}"
            )
        if max_odd_rnum > (tunnel_net.num_addresses - 2):
            raise TopogenError(
                f"DMVPN tunnel CIDR {tunnel_net} is too small for router number {max_odd_rnum}"
            )

        max_coord = 15000
        group = max(1, int(getattr(args, "flat_group_size", 20)))
        num_access = Renderer.validate_flat_topology(total_endpoints, group)
        base_distance = int(getattr(args, "distance", 200))
        base_sw_step_x = base_distance * 3
        sw_step_x = max(1, min(base_sw_step_x, max_coord // max(1, (num_access + 1))))
        router_step_y = max(1, min(base_distance, max_coord // max(1, (group * 2 + 2))))

        # OOB management switches (if --mgmt enabled)
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            # OOB connects ALL routers (not just DMVPN endpoints), so size based on total_routers
            from math import ceil
            num_oob_sw = ceil(total_routers / oob_group)
            # Precompute how many routers per OOB access switch
            routers_per_oob = ceil(total_routers / num_oob_sw)
            for i in range(num_oob_sw):
                start = i * routers_per_oob
                end = min((i + 1) * routers_per_oob, total_routers)
                oob_per_sw_counts.append(max(0, end - start))

        if getattr(args, "progress", False):
            manager = enlighten.get_manager()
            oob_ticks = (1 + (2 * num_oob_sw) + total_routers) if enable_mgmt else 0
            ticks = manager.counter(
                total=1 + (2 * num_access) + total_routers + (2 * total_endpoints) + oob_ticks,
                desc="Progress",
                unit="steps",
                color="cyan",
                leave=False,
            )

        nac_enabled = bool(getattr(args, "nac", False))
        cml2_enabled = bool(getattr(args, "terraform_cml2", False))
        outfile, nac_root, cml2_root = resolve_offline_artifact_paths(
            getattr(args, "offline_yaml"),
            nac_enabled=nac_enabled,
            cml2_enabled=cml2_enabled,
        )
        dev_def = getattr(args, "dev_template", args.template)

        def iface_label_for_slot(slot: int) -> str:
            if str(dev_def).lower() == "csr1000v":
                return f"GigabitEthernet{slot + 1}"
            return f"GigabitEthernet0/{slot}"

        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")

        args_bits: list[str] = [f"nodes={args.nodes}", f"-m {args.mode}", f"-T {args.template}"]
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        args_bits.append(f"--dmvpn-underlay {getattr(args, 'dmvpn_underlay', 'flat')}")
        args_bits.append(f"--dmvpn-phase {getattr(args, 'dmvpn_phase', 2)}")
        args_bits.append(f"--dmvpn-routing {getattr(args, 'dmvpn_routing', 'eigrp')}")
        if stub_evens:
            args_bits.append("--eigrp-stub")
        args_bits.append(f"--dmvpn-security {getattr(args, 'dmvpn_security', 'none')}")
        args_bits.append(f"--dmvpn-ipsec-mode {getattr(args, 'dmvpn_ipsec_mode', 'transport')}")
        args_bits.append(f"--dmvpn-nbma-cidr {nbma_net}")
        args_bits.append(f"--dmvpn-tunnel-cidr {tunnel_net}")
        if hubs_list:
            args_bits.append(f"--dmvpn-hubs {getattr(args, 'dmvpn_hubs')}")
        if getattr(args, "pki_enabled", False):
            args_bits.append("--pki")
        if getattr(args, "getvpn_enabled", False):
            args_bits.append("--getvpn")
            args_bits.append(f"--getvpn-protocol {getattr(args, 'getvpn_protocol', 'gdoi')}")
            args_bits.append(f"--getvpn-group-id {getattr(args, 'getvpn_group_id', 1)}")
            args_bits.append(f"--getvpn-rekey-interval {getattr(args, 'getvpn_rekey_interval', 86400)}")
        version = getattr(args, "cml_version", "0.3.0")
        append_cml_schema_provenance_args(args_bits, args)
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        staging = getattr(args, "staging", False) and _staging_version_ok(version)
        if staging:
            args_bits.append("--staging")
        _append_common_offline_args_bits(args_bits, args)
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, dmvpn flat-pair) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f"  description: \"{desc}\"")
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        if staging:
            lines.extend(_node_staging_lines(abort_on_failure=not getattr(args, "staging_no_abort", False)))
        lines.append("nodes:")

        getvpn_enabled = getattr(args, "getvpn_enabled", False)
        node_ids: dict[str, str] = {}
        nid = 0

        node_ids["SWnbma0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SWnbma0']}")
        lines.append("    label: SWnbma0")
        lines.append("    node_definition: unmanaged_switch")
        if staging:
            lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
        lines.append("    x: 0")
        lines.append("    y: 0")
        # Core interfaces: one per access switch + 1 extra for CA-ROOT if --pki enabled
        swnbma0_port_count = num_access
        if getattr(args, "pki_enabled", False):
            swnbma0_port_count += 1
        if getvpn_enabled:
            swnbma0_port_count += 1
        lines.append("    interfaces:")
        for p in range(swnbma0_port_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append("        type: physical")

        endpoint_port_map: list[tuple[str, int]] = []
        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            node_ids[sw_label] = f"n{nid}"; nid += 1
            sx = min(max_coord, (sidx + 1) * sw_step_x)
            lines.append(f"  - id: {node_ids[sw_label]}")
            lines.append(f"    label: {sw_label}")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
            lines.append(f"    x: {sx}")
            lines.append("    y: 0")
            lines.append("    interfaces:")

            start = sidx * group
            end = min((sidx + 1) * group, total_endpoints)
            ep_count = max(0, end - start)
            if_count = 1 + ep_count
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append("        type: physical")
            for p in range(1, if_count):
                endpoint_port_map.append((sw_label, p))

            if ticks:
                ticks.update()  # type: ignore

        # OOB management switches (if --mgmt enabled)
        if enable_mgmt:
            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            # Ports for OOB access switches + 1 extra for CA-ROOT if --pki enabled
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append("        type: physical")

            if ticks:
                ticks.update()  # type: ignore

            # OOB access switches
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * base_distance
                oy = (i + 1) * base_distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {oy}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append("        type: physical")

                if ticks:
                    ticks.update()  # type: ignore

        if hubs_list:
            hub_set = set(int(h) for h in hubs_list)
        else:
            hub_set = {1}

        hub_info: list[dict[str, IPv4Address]] = []
        for ep in range(1, total_endpoints + 1):
            rnum = ep * 2 - 1
            if rnum not in hub_set:
                continue
            hub_info.append(
                {
                    "hub_nbma_ip": IPv4Interface(
                        f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}"
                    ).ip,
                    "hub_tunnel_ip": IPv4Interface(
                        f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}"
                    ).ip,
                }
            )

        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"

        pair_ips: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = cfg.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())
        for odd in range(1, total_routers + 1, 2):
            even = odd + 1
            if even > total_routers:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            pair_ips[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        nac_router_nodes: list[TopogenNode] = []
        for idx in range(total_routers):
            rnum = idx + 1
            label = f"R{rnum}"
            node_ids[label] = f"n{nid}"; nid += 1

            hi = (rnum // 256) & 0xFF
            lo = rnum % 256
            loopback_ip = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            # Build mgmt context for template
            mgmt_ctx = _build_mgmt_context(
                args,
                mgmt_slot=mgmt_slot,
                router_index=rnum,
                loopback=loopback_ip,
                hostname=label,
            )
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            if rnum % 2 == 1:
                nbma_ip = IPv4Interface(f"{nbma_net.network_address + rnum}/{nbma_net.prefixlen}")
                tun_ip = IPv4Interface(f"{tunnel_net.network_address + rnum}/{tunnel_net.prefixlen}")
                pair_ip = pair_ips.get(rnum, (None, None))[0]
                node = TopogenNode(
                    hostname=label,
                    loopback=loopback_ip,
                    interfaces=[
                        TopogenInterface(address=nbma_ip, description="dmvpn nbma", slot=0),
                        TopogenInterface(address=pair_ip, description="pair link", slot=1),
                        TopogenInterface(address=tun_ip, description="dmvpn tunnel", slot=1000),
                    ],
                )
                _append_nac_mgmt_interface(node, args, rnum)
                nac_router_nodes.append(node)
                rendered = dmvpn_tpl.render(
                    config=cfg,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    is_hub=(rnum in hub_set),
                    hub_info=hub_info,
                    dmvpn_tunnel_key=getattr(args, "dmvpn_tunnel_key", 10),
                    dmvpn_phase=getattr(args, "dmvpn_phase", 2),
                    dmvpn_vrf=dmvpn_vrf,
                    dmvpn_fvrf=dmvpn_fvrf,
                    dmvpn_security=getattr(args, "dmvpn_security", "none"),
                    dmvpn_psk=getattr(args, "dmvpn_psk", None),
                    dmvpn_trustpoint=getattr(args, "dmvpn_trustpoint", "CA-ROOT-SELF"),
                    ipsec_mode=getattr(args, "dmvpn_ipsec_mode", "transport"),
                    mgmt=mgmt_ctx,
                    ntp=ntp_ctx,
                    ntp_oob=ntp_oob_ctx,
                    archive=getattr(args, "archive", False),
                )
            else:
                pair_ip = pair_ips.get(rnum - 1, (None, None))[1]
                node = TopogenNode(
                    hostname=label,
                    loopback=loopback_ip,
                    interfaces=[TopogenInterface(address=pair_ip, description="pair link", slot=0)],
                )
                _append_nac_mgmt_interface(node, args, rnum)
                nac_router_nodes.append(node)
                rendered = eigrp_tpl.render(
                    config=cfg,
                    node=node,
                    date=datetime.now(timezone.utc),
                    origin="",
                    eigrp_stub=stub_evens,
                    mgmt=mgmt_ctx,
                    ntp=ntp_ctx,
                    ntp_oob=ntp_oob_ctx,
                    archive=getattr(args, "archive", False),
                )
            if getvpn_enabled:
                ks_ip = str(nbma_net.broadcast_address - 4)
                gm_wan = "GigabitEthernet1" if dev_def == "csr1000v" else "GigabitEthernet0/0"
                rendered = _inject_getvpn_gm_config(
                    rendered, label, cfg.domainname,
                    getattr(args, "getvpn_protocol", "gdoi"),
                    getattr(args, "getvpn_group_id", 1),
                    ks_ip, gm_wan,
                )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )
            rendered = _finalize_router_day0_config(rendered, cfg, node, args)

            sw_index = ((rnum - 1) // 2) // group
            x = min(max_coord, (sw_index + 1) * sw_step_x)
            y = min(max_coord, ((rnum - 1) % (group * 2) + 1) * router_step_y)

            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            if staging and rnum in hub_set:
                lines.append(f"    priority: {STAGING_PRIORITY_HUB_KS}")
            lines.append(f"    x: {x}")
            lines.append(f"    y: {y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append(f"        label: {iface_label_for_slot(0)}")
            lines.append("        type: physical")
            if rnum % 2 == 1:
                lines.append("      - id: i1")
                lines.append("        slot: 1")
                lines.append(f"        label: {iface_label_for_slot(1)}")
                lines.append("        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, rendered, getattr(args, "blank", False))

        # GET VPN Key Server node (if --getvpn enabled)
        if getvpn_enabled:
            ks_label = "KS"
            node_ids[ks_label] = f"n{nid}"; nid += 1
            ks_nbma_ip = IPv4Interface(f"{nbma_net.broadcast_address - 4}/{nbma_net.prefixlen}")
            ks_lo_ip = IPv4Interface("10.255.255.251/32")
            ks_dev_def = "csr1000v"
            ks_tpl = env.get_template(f"csr-getvpn-ks{Renderer.J2SUFFIX}")
            ks_node = TopogenNode(
                hostname=ks_label,
                loopback=ks_lo_ip,
                interfaces=[
                    TopogenInterface(
                        address=ks_nbma_ip, description="=== GETVPN Key Server ===", slot=0
                    )
                ],
            )
            ks_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ks_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ks_ntp_ctx = {"server": args.ntp_server, "vrf": getattr(args, "ntp_vrf", None)}
            ks_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ks_ntp_oob_ctx = {"server": args.ntp_oob_server, "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf"}
            ks_rendered = ks_tpl.render(
                config=cfg, node=ks_node, date=datetime.now(timezone.utc), origin="",
                mgmt=ks_mgmt_ctx, ntp=ks_ntp_ctx, ntp_oob=ks_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
                getvpn_protocol=getattr(args, "getvpn_protocol", "gdoi"),
                getvpn_group_id=getattr(args, "getvpn_group_id", 1),
                getvpn_rekey_interval=getattr(args, "getvpn_rekey_interval", 86400),
                getvpn_ks_ip=str(ks_nbma_ip.ip),
            )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{nbma_net.broadcast_address - 1}:80"
                ks_rendered = _inject_pki_client_trustpoint(ks_rendered, ks_label, cfg.domainname, ca_url)
            ks_x = -400
            ks_y = 300
            lines.append(f"  - id: {node_ids[ks_label]}")
            lines.append(f"    label: {ks_label}")
            lines.append(f"    node_definition: {ks_dev_def}")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_HUB_KS}")
            lines.append(f"    x: {ks_x}")
            lines.append(f"    y: {ks_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                csr_slot = mgmt_slot - 1
                lines.append(f"      - id: i{csr_slot}")
                lines.append(f"        slot: {csr_slot}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ks_rendered, getattr(args, "blank", False))

        # CA-ROOT node (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1

            # CA gets last usable IP in NBMA CIDR (avoid conflict with sequential router allocation)
            ca_nbma_ip = IPv4Interface(f"{nbma_net.broadcast_address - 1}/{nbma_net.prefixlen}")

            # CA loopback at upper end (same as flat mode: .255.254) for consistency with future CAs
            ca_loopback_ip = IPv4Interface(f"{l_base}.255.254/32")

            # Create CA node with NBMA interface (connects to SWnbma0)
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=ca_loopback_ip,
                interfaces=[
                    TopogenInterface(
                        address=ca_nbma_ip,
                        description="=== SCEP Enrollment URL ===",
                        slot=0,
                    )
                ],
            )

            # CA always uses EIGRP template (DMVPN default routing protocol)
            try:
                ca_base_tpl = env.get_template(f"csr-eigrp{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                raise TopogenError("CA template not found: csr-eigrp")

            # Render base config with EIGRP routing
            ca_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )

            # Append PKI-specific config
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]

            ca_config_lines = ca_base_config.splitlines()

            # Replace generic RSA key with named key (needed for PKI server)
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"

            ca_scep_url = f"http://{ca_nbma_ip.ip}:80"
            non_eem_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + ["alias exec servcerts sh crypto pki server CA-ROOT cer", "!"]
            )
            eem_block = _pki_ca_authenticate_eem_lines()
            try:
                eem_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip().startswith("event manager"))
            except StopIteration:
                try:
                    eem_idx = next(i for i in range(len(ca_config_lines) - 1, -1, -1) if ca_config_lines[i].strip() == "end")
                except StopIteration:
                    eem_idx = len(ca_config_lines)
            ca_config_lines[eem_idx:eem_idx] = non_eem_block
            try:
                end_idx = next(i for i in range(len(ca_config_lines) - 1, -1, -1) if ca_config_lines[i].strip() == "end")
                ca_config_lines[end_idx:end_idx] = eem_block
            except StopIteration:
                ca_config_lines.extend(eem_block)
                ca_config_lines.append("end")

            ca_rendered = "\n".join(ca_config_lines)

            # Place CA near SWnbma0 (core switch area)
            ca_x = -400
            ca_y = 200

            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append("    node_definition: csr1000v")  # CA is always CSR
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_CA_ROOT}")
            lines.append(f"    x: {ca_x}")
            lines.append(f"    y: {ca_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                ca_mgmt_slot_id = mgmt_slot - 1  # CA is always CSR, so slot-1
                lines.append(f"      - id: i{ca_mgmt_slot_id}")
                lines.append(f"        slot: {ca_mgmt_slot_id}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ca_rendered, getattr(args, "blank", False))

        lines.append("links:")
        lid = 0

        for sidx in range(num_access):
            sw_label = f"SWnbma{sidx + 1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[sw_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{sidx}")

        # CA-ROOT -> SWnbma0 data link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # SWnbma0's next available port after access switches
            swnbma0_ca_port = num_access
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{swnbma0_ca_port}")

        # KS -> SWnbma0 data link (if --getvpn enabled)
        if getvpn_enabled:
            ks_label = "KS"
            swnbma0_ks_port = num_access
            if getattr(args, "pki_enabled", False):
                swnbma0_ks_port += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ks_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SWnbma0']}")
            lines.append(f"    i2: i{swnbma0_ks_port}")

        for ep in range(1, total_endpoints + 1):
            rlabel = f"R{ep * 2 - 1}"
            sw_label, sw_port = endpoint_port_map[ep - 1]
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[sw_label]}")
            lines.append(f"    i2: i{sw_port}")

            if ticks:
                ticks.update()  # type: ignore

        for ep in range(1, total_endpoints + 1):
            odd = ep * 2 - 1
            even = odd + 1
            if even > total_routers:
                continue
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[f'R{odd}']}")
            lines.append("    i1: i1")
            lines.append(f"    n2: {node_ids[f'R{even}']}")
            lines.append("    i2: i0")

            if ticks:
                ticks.update()  # type: ignore

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

                if ticks:
                    ticks.update()  # type: ignore

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            # Map each router to an OOB access switch
            routers_per_oob = (total_routers + num_oob_sw - 1) // num_oob_sw
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for rnum in range(1, total_routers + 1):
                rlabel = f"R{rnum}"
                oob_sw_index = (rnum - 1) // routers_per_oob
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

                if ticks:
                    ticks.update()  # type: ignore

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                # CA is always CSR1000v, so use slot - 1
                ca_mgmt_iface_id = mgmt_slot - 1
                # SWoob0's next available port after ext-conn-mgmt (if present) and OOB access switches
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

            # KS -> SWoob0 mgmt link (if --getvpn enabled)
            if getvpn_enabled:
                ks_label = "KS"
                ks_mgmt_iface_id = mgmt_slot - 1
                swoob0_ks_port = port_offset + num_oob_sw
                if getattr(args, "pki_enabled", False):
                    swoob0_ks_port += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ks_label]}")
                lines.append(f"    i1: i{ks_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ks_port}")

        _validate_nac_router_nodes_if_enabled(nac_root, nac_router_nodes, dev_def)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if nac_root is not None:
            nac_root.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _finalize_offline_yaml_with_intent(lines, desc, version, args)
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (dmvpn, flat-pair) written to %s (%.1f KB)", outfile, size_kb)
        _write_nac_tree_if_enabled(
            nac_root=nac_root,
            nodes=nac_router_nodes,
            device_template=dev_def,
            template=args.template,
            mode=args.mode,
            args=args,
        )
        write_cml2_lifecycle_if_enabled(args, outfile, cml2_root)

        if ticks:
            ticks.close()  # type: ignore
        if manager:
            manager.stop()  # type: ignore

        return 0

    @staticmethod
    def offline_flat_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML file locally for flat mode.

        This does not contact a controller. It writes a minimal topology with:
        - SW0 core unmanaged switch
        - SW1..N access unmanaged switches (N = ceil(nodes/group))
        - Routers R1..R<n> using args.dev_template (e.g., iosv)
        - Links: each access switch linked to SW0; each router Gi0/0 to its access switch
        - Per-router configuration rendered from the selected Jinja2 template
        """

        # set up Jinja to render configs from packaged templates
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover - defensive
            raise TopogenError(f"template does not exist: {args.template}") from exc

        total = int(args.nodes)
        group = max(1, int(args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)
        nac_enabled = bool(getattr(args, "nac", False))
        cml2_enabled = bool(getattr(args, "terraform_cml2", False))
        outfile, nac_root, cml2_root = resolve_offline_artifact_paths(
            getattr(args, "offline_yaml"),
            nac_enabled=nac_enabled,
            cml2_enabled=cml2_enabled,
        )

        # CML input validation requires x/y coordinates to be within a bounded range.
        # Scale spacing so any node count and group size produces importable coordinates.
        max_coord = 15000
        base_distance = int(getattr(args, "distance", 200))
        base_sw_step_x = base_distance * 3
        sw_step_x = max(1, min(base_sw_step_x, max_coord // max(1, (num_sw + 1))))
        router_step_y = max(1, min(base_distance, max_coord // max(1, (group + 2))))

        # Warn about custom device templates/images which may affect interface behavior
        dev_def = getattr(args, "dev_template", args.template)
        if dev_def != "iosv":
            _LOGGER.warning(
                "Using custom device template '%s'; guardrails assume ~32-port unmanaged_switch and do not account for custom node definitions/images",
                dev_def,
            )

        # helper to compute addressing
        def addr_parts(n: int) -> tuple[int, int]:
            ridx = n
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            return hi, lo

        # Build YAML using CML 2.5+ schema (ids for nodes/links, and n1/i1/n2/i2)
        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")
        # Build an args summary to embed into the lab description (no secrets)
        args_bits: list[str] = [f"nodes={total}", f"-m {args.mode}", f"-T {args.template}"]
        dev_def = getattr(args, "dev_template", args.template)
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        if getattr(args, "enable_vrf", False):
            args_bits.append("--vrf")
            if getattr(args, "pair_vrf", None):
                args_bits.append(f"--pair-vrf {args.pair_vrf}")
        if args.mode.startswith("flat"):
            args_bits.append(f"--flat-group-size {args.flat_group_size}")
            if getattr(args, "loopback_255", False):
                args_bits.append("--loopback-255")
            if getattr(args, "gi0_zero", False):
                args_bits.append("--gi0-zero")
        version = getattr(args, "cml_version", "0.3.0")
        append_cml_schema_provenance_args(args_bits, args)
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
            _append_mgmt_ipv6_provenance_args(args_bits, args)
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        if getattr(args, "pki_enabled", False):
            args_bits.append("--pki")
        if getattr(args, "getvpn_enabled", False):
            args_bits.append("--getvpn")
            args_bits.append(f"--getvpn-protocol {getattr(args, 'getvpn_protocol', 'gdoi')}")
            args_bits.append(f"--getvpn-group-id {getattr(args, 'getvpn_group_id', 1)}")
            args_bits.append(f"--getvpn-rekey-interval {getattr(args, 'getvpn_rekey_interval', 86400)}")
        if getattr(args, "archive", False):
            args_bits.append("--archive")
        staging = getattr(args, "staging", False) and _staging_version_ok(version)
        if staging:
            args_bits.append("--staging")
        _append_common_offline_args_bits(args_bits, args)
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f'  description: "{desc}"')
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        if staging:
            lines.extend(_node_staging_lines(abort_on_failure=not getattr(args, "staging_no_abort", False)))
        lines.append("nodes:")

        getvpn_enabled = getattr(args, "getvpn_enabled", False)

        node_ids: dict[str, str] = {}
        nid = 0
        # Core switch
        node_ids["SW0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SW0']}")
        lines.append("    label: SW0")
        lines.append("    node_definition: unmanaged_switch")
        if staging:
            lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
        lines.append("    x: 0")
        lines.append("    y: 0")

        # Access switches with interface inventory
        # Precompute how many routers per access switch
        per_sw_counts: list[int] = []
        for i in range(num_sw):
            start = i * group + 1
            end = min((i + 1) * group, total)
            per_sw_counts.append(max(0, end - start + 1))

        # Core switch needs one port per access switch + 1 for CA if --pki + 1 for KS if --getvpn
        core_if_count = num_sw
        if getattr(args, "pki_enabled", False):
            core_if_count += 1
        if getvpn_enabled:
            core_if_count += 1
        lines.append("    interfaces:")
        for p in range(core_if_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append(f"        type: physical")

        # Access switches
        access_if_start_slots: list[int] = []
        for i in range(num_sw):
            label = f"SW{i+1}"
            node_ids[label] = f"n{nid}"; nid += 1
            x = min(max_coord, (i + 1) * sw_step_x)
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
            lines.append(f"    x: {x}")
            lines.append("    y: 0")
            # Each access switch: 1 uplink + ports for attached routers
            if_count = 1 + per_sw_counts[i]
            lines.append("    interfaces:")
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append(f"        type: physical")
            access_if_start_slots.append(0)

        # OOB management switches (if --mgmt enabled) - mirrors access switch pattern
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            from math import ceil
            num_oob_sw = ceil(total / oob_group)
            # Precompute how many routers per OOB access switch
            for i in range(num_oob_sw):
                start = i * oob_group + 1
                end = min((i + 1) * oob_group, total)
                oob_per_sw_counts.append(max(0, end - start + 1))

            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            # Ports for OOB access switches + 1 extra for CA-ROOT if --pki + 1 for KS if --getvpn
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            if getvpn_enabled:
                swoob0_port_count += 1
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append(f"        type: physical")

            # OOB access switches
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * args.distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {(i + 1) * args.distance}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append(f"        type: physical")

        # Routers (with Gi0/0 interface defined at slot 0)
        dev_def = getattr(args, "dev_template", args.template)
        g_base = "10.0" if getattr(args, "gi0_zero", False) else "10.10"
        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"
        nac_router_nodes: list[TopogenNode] = []
        for idx in range(total):
            n = idx + 1
            label = f"R{n}"
            node_ids[label] = f"n{nid}"; nid += 1
            hi, lo = addr_parts(n)
            g_ip = f"{g_base}.{hi}.{lo}"
            l_ip = f"{l_base}.{hi}.{lo}"

            # Render configuration using the same template logic as online path
            node = TopogenNode(
                hostname=label,
                loopback=IPv4Interface(f"{l_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{g_ip}/16"), description="mgmt flat", slot=0
                    )
                ],
            )
            _append_nac_mgmt_interface(node, args, n)
            nac_router_nodes.append(node)
            # Build mgmt context for template
            mgmt_ctx = _build_mgmt_context(
                args,
                mgmt_slot=mgmt_slot,
                router_index=n,
                loopback=node.loopback,
                hostname=label,
            )
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            rendered = tpl.render(
                config=cfg,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )
            if getvpn_enabled:
                ks_ip = f"{g_base}.255.251"
                gm_wan = "GigabitEthernet1" if dev_def == "csr1000v" else "GigabitEthernet0/0"
                rendered = _inject_getvpn_gm_config(
                    rendered, label, cfg.domainname,
                    getattr(args, "getvpn_protocol", "gdoi"),
                    getattr(args, "getvpn_group_id", 1),
                    ks_ip, gm_wan,
                )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )
            rendered = _finalize_router_day0_config(rendered, cfg, node, args)

            rx = min(max_coord, (idx // group + 1) * sw_step_x)
            ry = min(max_coord, (idx % group + 1) * router_step_y)
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {rx}")
            lines.append(f"    y: {ry}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            if dev_def == "csr1000v":
                lines.append("        label: GigabitEthernet1")
            else:
                lines.append("        label: GigabitEthernet0/0")
            lines.append("        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, rendered, getattr(args, "blank", False))

        # Create GET VPN Key Server if --getvpn enabled
        if getvpn_enabled:
            ks_label = "KS"
            node_ids[ks_label] = f"n{nid}"; nid += 1

            ks_g_ip = f"{g_base}.255.251"
            ks_l_ip = f"{l_base}.255.251"
            ks_dev_def = "csr1000v"

            ks_tpl = env.get_template(f"csr-getvpn-ks{Renderer.J2SUFFIX}")

            ks_node = TopogenNode(
                hostname=ks_label,
                loopback=IPv4Interface(f"{ks_l_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{ks_g_ip}/16"), description="=== GETVPN Key Server ===", slot=0
                    )
                ],
            )
            ks_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ks_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ks_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ks_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ks_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ks_rendered = ks_tpl.render(
                config=cfg,
                node=ks_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ks_mgmt_ctx,
                ntp=ks_ntp_ctx,
                ntp_oob=ks_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
                getvpn_protocol=getattr(args, "getvpn_protocol", "gdoi"),
                getvpn_group_id=getattr(args, "getvpn_group_id", 1),
                getvpn_rekey_interval=getattr(args, "getvpn_rekey_interval", 86400),
                getvpn_ks_ip=ks_g_ip,
            )
            # KS also needs PKI client trustpoint for CA enrollment
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                ks_rendered = _inject_pki_client_trustpoint(
                    ks_rendered, ks_label, cfg.domainname, ca_url
                )

            ks_x = -args.distance * 2
            lines.append(f"  - id: {node_ids[ks_label]}")
            lines.append(f"    label: {ks_label}")
            lines.append(f"    node_definition: {ks_dev_def}")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_HUB_KS}")
            lines.append(f"    x: {ks_x}")
            lines.append(f"    y: {args.distance}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                csr_slot = mgmt_slot - 1
                lines.append(f"      - id: i{csr_slot}")
                lines.append(f"        slot: {csr_slot}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ks_rendered, getattr(args, "blank", False))

        # Create PKI Root CA router if --pki enabled
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1

            # CA gets last usable IP in the flat CIDR (e.g., 10.10.255.254/16)
            ca_g_ip = f"{g_base}.255.254"
            ca_l_ip = f"{l_base}.255.254"

            # CA-ROOT is always CSR1000v (required for PKI server features)
            ca_dev_def = "csr1000v"

            # Determine which CSR template to use based on regular router template
            # This ensures CA uses same routing protocol as regular routers
            template_name = getattr(args, "template", "iosv")
            if "ospf" in template_name or template_name == "iosv":  # iosv defaults to OSPF
                ca_template_name = "csr-ospf"
            elif "eigrp" in template_name:
                ca_template_name = "csr-eigrp"
            else:
                ca_template_name = "csr-eigrp"  # Default to EIGRP if unknown

            # Load appropriate CSR template
            try:
                ca_base_tpl = env.get_template(f"{ca_template_name}{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                ca_base_tpl = tpl  # Fallback to default template

            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=IPv4Interface(f"{ca_l_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{ca_g_ip}/16"), description="=== SCEP Enrollment URL ===", slot=0
                    )
                ],
            )
            ca_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            # Render base config with routing protocol
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )

            # CA clock EEM: one-shot 90s to set clock + ntp master if NTP not synced (so PKI server can start)
            ca_config_lines = ca_base_config.rstrip().split('\n')
            # Remove trailing "end" if present
            if ca_config_lines and ca_config_lines[-1].strip() == "end":
                ca_config_lines.pop()

            # Replace generic RSA key with named key for PKI
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"
                    break

            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]
            ca_scep_url = f"http://{ca_g_ip}:80"
            non_eem_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + ["alias exec servcerts sh crypto pki server CA-ROOT cer", "!"]
            )
            try:
                eem_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip().startswith("event manager"))
            except StopIteration:
                eem_idx = len(ca_config_lines)
            ca_config_lines[eem_idx:eem_idx] = non_eem_block
            ca_config_lines.extend(_pki_ca_authenticate_eem_lines())
            ca_config_lines.append("end")

            ca_rendered = '\n'.join(ca_config_lines)

            # Position CA to the left of SW0
            ca_x = -args.distance * 3
            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append(f"    node_definition: {ca_dev_def}")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_CA_ROOT}")
            lines.append(f"    x: {ca_x}")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            if ca_dev_def == "csr1000v":
                lines.append("        label: GigabitEthernet1")
            else:
                lines.append("        label: GigabitEthernet0/0")
            lines.append("        type: physical")
            if enable_mgmt:
                if ca_dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ca_rendered, getattr(args, "blank", False))

        # Links section
        lines.append("links:")
        lid = 0
        # Access -> core (use port equal to index for both ends)
        for i in range(num_sw):
            acc = f"SW{i+1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[acc]}")
            lines.append(f"    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{i}")
        # Routers -> access switch
        per_sw_next_port = [1 for _ in range(num_sw)]  # reserve 0 for uplink
        for idx in range(total):
            n = idx + 1
            rlabel = f"R{n}"
            sw_index = idx // group + 1
            acc = f"SW{sw_index}"
            acc_port = per_sw_next_port[sw_index - 1]
            per_sw_next_port[sw_index - 1] += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[acc]}")
            lines.append(f"    i2: i{acc_port}")

        # CA-ROOT -> SW0 link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # SW0's next available port is after all access switch uplinks (i0 through i{num_sw-1})
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{num_sw}")

        # KS -> SW0 link (if --getvpn enabled)
        if getvpn_enabled:
            ks_label = "KS"
            sw0_ks_port = num_sw
            if getattr(args, "pki_enabled", False):
                sw0_ks_port += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ks_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{sw0_ks_port}")

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for idx in range(total):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                # CA is always CSR1000v, so use slot - 1
                ca_mgmt_iface_id = mgmt_slot - 1
                # SWoob0's next available port after ext-conn-mgmt (if present) and OOB access switches
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

            # KS -> SWoob0 mgmt link (if --getvpn enabled)
            if getvpn_enabled:
                ks_label = "KS"
                ks_mgmt_iface_id = mgmt_slot - 1
                swoob0_ks_port = port_offset + num_oob_sw
                if getattr(args, "pki_enabled", False):
                    swoob0_ks_port += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ks_label]}")
                lines.append(f"    i1: i{ks_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ks_port}")

        _validate_nac_router_nodes_if_enabled(nac_root, nac_router_nodes, dev_def)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if nac_root is not None:
            nac_root.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _finalize_offline_yaml_with_intent(lines, desc, version, args)
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (flat) written to %s (%.1f KB)", outfile, size_kb)
        _write_nac_tree_if_enabled(
            nac_root=nac_root,
            nodes=nac_router_nodes,
            device_template=dev_def,
            template=args.template,
            mode=args.mode,
            args=args,
        )
        write_cml2_lifecycle_if_enabled(args, outfile, cml2_root)
        return 0
    @staticmethod
    def offline_flat_pair_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML locally for flat-pair mode.

        Differences from flat:
        - Only odd routers connect Gi0/0 to the access switch.
        - Each odd router also links Gi0/1 <-> even router's Gi0/0.
        - If last odd has no partner, its Gi0/1 remains unused.
        - Access/core switches and guardrails are identical to flat; port counts unchanged.
        - Interfaces receive same addressing as flat for Gi0/0 (deterministic), pair link has no IPs.
        """

        # set up Jinja to render configs from packaged templates
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:  # pragma: no cover - defensive
            raise TopogenError(f"template does not exist: {args.template}") from exc

        total = int(args.nodes)
        group = max(1, int(args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)
        nac_enabled = bool(getattr(args, "nac", False))
        cml2_enabled = bool(getattr(args, "terraform_cml2", False))
        outfile, nac_root, cml2_root = resolve_offline_artifact_paths(
            getattr(args, "offline_yaml"),
            nac_enabled=nac_enabled,
            cml2_enabled=cml2_enabled,
        )

        # CML input validation requires x/y coordinates to be within a bounded range.
        # Scale spacing so any node count and group size produces importable coordinates.
        max_coord = 15000
        base_distance = int(getattr(args, "distance", 200))
        base_sw_step_x = base_distance * 3
        sw_step_x = max(1, min(base_sw_step_x, max_coord // max(1, (num_sw + 1))))
        router_step_y = max(1, min(base_distance, max_coord // max(1, (group + 2))))

        # helper to compute addressing
        def addr_parts(n: int) -> tuple[int, int]:
            ridx = n
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            return hi, lo

        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")
        # Build an args summary to embed into the lab description (no secrets)
        args_bits: list[str] = [f"nodes={total}", f"-m {args.mode}", f"-T {args.template}"]
        dev_def = getattr(args, "dev_template", args.template)
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        if getattr(args, "enable_vrf", False):
            args_bits.append("--vrf")
            if getattr(args, "pair_vrf", None):
                args_bits.append(f"--pair-vrf {args.pair_vrf}")
        args_bits.append(f"--flat-group-size {args.flat_group_size}")
        if getattr(args, "loopback_255", False):
            args_bits.append("--loopback-255")
        if getattr(args, "gi0_zero", False):
            args_bits.append("--gi0-zero")
        if getattr(args, "enable_mgmt", False):
            args_bits.append("--mgmt")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        if getattr(args, "pki_enabled", False):
            args_bits.append("--pki")
        if getattr(args, "getvpn_enabled", False):
            args_bits.append("--getvpn")
            args_bits.append(f"--getvpn-protocol {getattr(args, 'getvpn_protocol', 'gdoi')}")
            args_bits.append(f"--getvpn-group-id {getattr(args, 'getvpn_group_id', 1)}")
            args_bits.append(f"--getvpn-rekey-interval {getattr(args, 'getvpn_rekey_interval', 86400)}")
        version = getattr(args, "cml_version", "0.3.0")
        append_cml_schema_provenance_args(args_bits, args)
        staging = getattr(args, "staging", False) and _staging_version_ok(version)
        if staging:
            args_bits.append("--staging")
        _append_common_offline_args_bits(args_bits, args)
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {getattr(args, 'offline_yaml', '').replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, flat-pair) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        # Full args in description (visible in Lab Description pop-up); same intent in notes (hidden span) + annotation for CI/CD grep
        lines.append(f'  description: "{desc}"')
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        if staging:
            lines.extend(_node_staging_lines(abort_on_failure=not getattr(args, "staging_no_abort", False)))
        lines.append("nodes:")

        getvpn_enabled = getattr(args, "getvpn_enabled", False)

        node_ids: dict[str, str] = {}
        nid = 0
        # Core switch
        node_ids["SW0"] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids['SW0']}")
        lines.append("    label: SW0")
        lines.append("    node_definition: unmanaged_switch")
        if staging:
            lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
        lines.append("    x: 0")
        lines.append("    y: 0")

        # Determine router counts per access switch (same as flat)
        per_sw_counts: list[int] = []
        for i in range(num_sw):
            start = i * group + 1
            end = min((i + 1) * group, total)
            per_sw_counts.append(max(0, end - start + 1))

        # Core interfaces: one per access switch + 1 extra for CA-ROOT if --pki enabled
        sw0_port_count = num_sw
        if getattr(args, "pki_enabled", False):
            sw0_port_count += 1
        if getvpn_enabled:
            sw0_port_count += 1
        lines.append("    interfaces:")
        for p in range(sw0_port_count):
            lines.append(f"      - id: i{p}")
            lines.append(f"        slot: {p}")
            lines.append(f"        label: port{p}")
            lines.append(f"        type: physical")

        # Access switches
        access_if_start_slots: list[int] = []
        for i in range(num_sw):
            label = f"SW{i+1}"
            node_ids[label] = f"n{nid}"; nid += 1
            x = min(max_coord, (i + 1) * sw_step_x)
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_DATA_SWITCH}")
            lines.append(f"    x: {x}")
            lines.append("    y: 0")
            # 1 uplink + ports for all routers in the group (unchanged)
            if_count = 1 + per_sw_counts[i]
            lines.append("    interfaces:")
            for p in range(if_count):
                lines.append(f"      - id: i{p}")
                lines.append(f"        slot: {p}")
                lines.append(f"        label: port{p}")
                lines.append(f"        type: physical")
            access_if_start_slots.append(0)

        # OOB management switches (if --mgmt enabled) - mirrors access switch pattern
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        oob_group = group  # reuse flat_group_size for OOB switches
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            from math import ceil
            num_oob_sw = ceil(total / oob_group)
            # Precompute how many routers per OOB access switch
            for i in range(num_oob_sw):
                start = i * oob_group + 1
                end = min((i + 1) * oob_group, total)
                oob_per_sw_counts.append(max(0, end - start + 1))

            # External connector (optional)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            # OOB core switch
            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            # If bridge enabled, add port 0 for external connector
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            # Ports for OOB access switches + 1 extra for CA-ROOT if --pki enabled
            swoob0_port_count = num_oob_sw
            if getattr(args, "pki_enabled", False):
                swoob0_port_count += 1
            if getvpn_enabled:
                swoob0_port_count += 1
            for p in range(swoob0_port_count):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append(f"        type: physical")

            # OOB access switches
            for i in range(num_oob_sw):
                oob_label = f"SWoob{i+1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * args.distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {(i + 1) * args.distance}")
                # Each OOB access switch: 1 uplink + ports for attached routers
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append(f"        type: physical")

        # Pre-compute /30 p2p addressing for odd-even pairs from cfg.p2pnets
        pair_ips_off: dict[int, tuple[IPv4Interface, IPv4Interface]] = {}
        try:
            pfx = cfg.p2pnets
            p2p_iter = IPv4Network(pfx).subnets(prefixlen_diff=IPV4LENGTH - pfx.prefixlen - 2)
        except Exception:
            p2p_iter = iter(())
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                break
            p2pnet = next(p2p_iter)
            hosts = list(p2pnet.hosts())
            pair_ips_off[odd] = (
                IPv4Interface(f"{hosts[0]}/{p2pnet.netmask}"),
                IPv4Interface(f"{hosts[1]}/{p2pnet.netmask}"),
            )

        # Routers: include Gi0/0 for all; include Gi0/1 for odd routers only
        dev_def = getattr(args, "dev_template", args.template)
        g_base = "10.0" if getattr(args, "gi0_zero", False) else "10.10"
        l_base = "10.255" if getattr(args, "loopback_255", False) else "10.20"
        nac_router_nodes: list[TopogenNode] = []
        for idx in range(total):
            n = idx + 1
            label = f"R{n}"
            node_ids[label] = f"n{nid}"; nid += 1
            hi, lo = addr_parts(n)
            g_ip = f"{g_base}.{hi}.{lo}"
            l_ip = f"{l_base}.{hi}.{lo}"

            # Render configuration using the same template logic as online path
            # Offline config mirrors online behavior with optional p2p IPs
            is_odd = n % 2 == 1
            if is_odd:
                odd_ip = pair_ips_off.get(n, (None, None))[0]
                pair_vrf = (
                    getattr(args, "pair_vrf", None)
                    if getattr(args, "enable_vrf", False)
                    else None
                )
                ifaces = [
                    TopogenInterface(
                        address=IPv4Interface(f"{g_ip}/16"), description="mgmt flat-pair", slot=0
                    ),
                    TopogenInterface(
                        address=odd_ip,
                        vrf=pair_vrf,
                        description="pair link",
                        slot=1,
                    ),
                ]
            else:
                even_ip = pair_ips_off.get(n - 1, (None, None))[1]
                ifaces = [TopogenInterface(address=even_ip, description="pair link", slot=0)]

            node = TopogenNode(
                hostname=label,
                loopback=IPv4Interface(f"{l_ip}/32"),
                interfaces=ifaces,
            )
            _append_nac_mgmt_interface(node, args, n)
            nac_router_nodes.append(node)
            # Build mgmt/ntp context for template
            mgmt_ctx = _build_mgmt_context(
                args,
                mgmt_slot=mgmt_slot,
                router_index=n,
                loopback=node.loopback,
                hostname=label,
            )
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            rendered = tpl.render(
                config=cfg,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )
            if getvpn_enabled and is_odd:
                ks_ip = f"{g_base}.255.251"
                gm_wan = "GigabitEthernet1" if dev_def == "csr1000v" else "GigabitEthernet0/0"
                rendered = _inject_getvpn_gm_config(
                    rendered, label, cfg.domainname,
                    getattr(args, "getvpn_protocol", "gdoi"),
                    getattr(args, "getvpn_group_id", 1),
                    ks_ip, gm_wan,
                )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_url
                )
            rendered = _finalize_router_day0_config(rendered, cfg, node, args)

            rx = min(max_coord, (idx // group + 1) * sw_step_x)
            ry = min(max_coord, (idx % group + 1) * router_step_y)
            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {rx}")
            lines.append(f"    y: {ry}")
            lines.append("    interfaces:")
            def iface_label_for_slot(slot: int) -> str:
                # CML node definitions can have different interface naming.
                # csr1000v typically uses GigabitEthernet1, GigabitEthernet2, ...
                if str(dev_def).lower() == "csr1000v":
                    return f"GigabitEthernet{slot + 1}"
                return f"GigabitEthernet0/{slot}"

            # Always slot 0
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append(f"        label: {iface_label_for_slot(0)}")
            lines.append("        type: physical")
            # Odd routers have slot 1 for the pair link
            if n % 2 == 1:
                lines.append("      - id: i1")
                lines.append("        slot: 1")
                lines.append(f"        label: {iface_label_for_slot(1)}")
                lines.append("        type: physical")
            # Mgmt interface (if --mgmt enabled)
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, rendered, getattr(args, "blank", False))

        # Create GET VPN Key Server if --getvpn enabled
        if getvpn_enabled:
            ks_label = "KS"
            node_ids[ks_label] = f"n{nid}"; nid += 1
            ks_g_ip = f"{g_base}.255.251"
            ks_l_ip = f"{l_base}.255.251"
            ks_dev_def = "csr1000v"
            ks_tpl = env.get_template(f"csr-getvpn-ks{Renderer.J2SUFFIX}")
            ks_node = TopogenNode(
                hostname=ks_label,
                loopback=IPv4Interface(f"{ks_l_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{ks_g_ip}/16"), description="=== GETVPN Key Server ===", slot=0
                    )
                ],
            )
            ks_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ks_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ks_ntp_ctx = {"server": args.ntp_server, "vrf": getattr(args, "ntp_vrf", None)}
            ks_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ks_ntp_oob_ctx = {"server": args.ntp_oob_server, "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf"}
            ks_rendered = ks_tpl.render(
                config=cfg, node=ks_node, date=datetime.now(timezone.utc), origin="",
                mgmt=ks_mgmt_ctx, ntp=ks_ntp_ctx, ntp_oob=ks_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
                getvpn_protocol=getattr(args, "getvpn_protocol", "gdoi"),
                getvpn_group_id=getattr(args, "getvpn_group_id", 1),
                getvpn_rekey_interval=getattr(args, "getvpn_rekey_interval", 86400),
                getvpn_ks_ip=ks_g_ip,
            )
            if getattr(args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                ks_rendered = _inject_pki_client_trustpoint(ks_rendered, ks_label, cfg.domainname, ca_url)
            ks_x = -args.distance * 2
            lines.append(f"  - id: {node_ids[ks_label]}")
            lines.append(f"    label: {ks_label}")
            lines.append(f"    node_definition: {ks_dev_def}")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_HUB_KS}")
            lines.append(f"    x: {ks_x}")
            lines.append(f"    y: {args.distance}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                csr_slot = mgmt_slot - 1
                lines.append(f"      - id: i{csr_slot}")
                lines.append(f"        slot: {csr_slot}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ks_rendered, getattr(args, "blank", False))

        # CA-ROOT node (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            node_ids[ca_label] = f"n{nid}"; nid += 1

            # CA gets last usable IP in the flat CIDR (e.g. 10.10.255.254/16), same as flat mode
            ca_loopback_ip = f"{l_base}.255.254"
            ca_data_ip = f"{g_base}.255.254"

            # Create CA node with data interface (connects to SW0)
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=IPv4Interface(f"{ca_loopback_ip}/32"),
                interfaces=[
                    TopogenInterface(
                        address=IPv4Interface(f"{ca_data_ip}/16"),
                        description="=== SCEP Enrollment URL ===",
                        slot=0,
                    )
                ],
            )

            # Build CA config using same template selection logic as offline_flat_yaml
            # Determine which CSR template to use based on regular router template
            template_name = getattr(args, "template", "iosv")
            if "ospf" in template_name or template_name == "iosv":
                ca_template_name = "csr-ospf"
            elif "eigrp" in template_name:
                ca_template_name = "csr-eigrp"
            else:
                ca_template_name = "csr-eigrp"

            try:
                ca_base_tpl = env.get_template(f"{ca_template_name}{Renderer.J2SUFFIX}")
            except TemplateNotFound:
                raise TopogenError(f"CA template not found: {ca_template_name}")

            # Render base config with routing protocol
            ca_mgmt_ctx = _build_mgmt_context(args, mgmt_slot=mgmt_slot)
            ca_ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }
            ca_base_config = ca_base_tpl.render(
                config=cfg,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )

            # Append PKI-specific config
            pki_config_lines = [
                "ntp master 6",
                "!",
                "ip http server",
                "!",
                "crypto pki server CA-ROOT",
                " database level complete",
                " no database archive",
                " grant auto",
                " lifetime certificate 7300",
                " lifetime ca-certificate 7300",
                " database url flash:",
                " no shutdown",
                "!",
            ]

            ca_config_lines = ca_base_config.splitlines()

            # Replace generic RSA key with named key (needed for PKI server)
            for i, line in enumerate(ca_config_lines):
                if line.strip() == "crypto key generate rsa modulus 2048":
                    ca_config_lines[i] = "crypto key generate rsa modulus 2048 label CA-ROOT.server"

            ca_scep_url = f"http://{ca_data_ip}:80"
            non_eem_block = (
                pki_config_lines
                + _pki_ca_self_enroll_block_lines("CA-ROOT", cfg.domainname, ca_scep_url)
                + ["alias exec servcerts sh crypto pki server CA-ROOT cer", "!"]
            )
            eem_block = _pki_ca_authenticate_eem_lines()
            try:
                eem_idx = next(i for i, line in enumerate(ca_config_lines) if line.strip().startswith("event manager"))
            except StopIteration:
                try:
                    eem_idx = next(i for i in range(len(ca_config_lines) - 1, -1, -1) if ca_config_lines[i].strip() == "end")
                except StopIteration:
                    eem_idx = len(ca_config_lines)
            ca_config_lines[eem_idx:eem_idx] = non_eem_block
            try:
                end_idx = next(i for i in range(len(ca_config_lines) - 1, -1, -1) if ca_config_lines[i].strip() == "end")
                ca_config_lines[end_idx:end_idx] = eem_block
            except StopIteration:
                ca_config_lines.extend(eem_block)
                ca_config_lines.append("end")

            ca_rendered = "\n".join(ca_config_lines)

            # Place CA near SW0 (core switch area)
            ca_x = -400
            ca_y = 200

            lines.append(f"  - id: {node_ids[ca_label]}")
            lines.append(f"    label: {ca_label}")
            lines.append("    node_definition: csr1000v")  # CA is always CSR
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_CA_ROOT}")
            lines.append(f"    x: {ca_x}")
            lines.append(f"    y: {ca_y}")
            lines.append("    interfaces:")
            lines.append("      - id: i0")
            lines.append("        slot: 0")
            lines.append("        label: GigabitEthernet1")
            lines.append("        type: physical")
            if enable_mgmt:
                ca_mgmt_slot_id = mgmt_slot - 1  # CA is always CSR, so slot-1
                lines.append(f"      - id: i{ca_mgmt_slot_id}")
                lines.append(f"        slot: {ca_mgmt_slot_id}")
                lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, ca_rendered, getattr(args, "blank", False))

        # Links
        lines.append("links:")
        lid = 0
        # Access -> core
        for i in range(num_sw):
            acc = f"SW{i+1}"
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[acc]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{i}")

        # CA-ROOT -> SW0 data link (if --pki enabled)
        if getattr(args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # SW0's next available port after access switches
            sw0_ca_port = num_sw
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ca_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{sw0_ca_port}")

        # KS -> SW0 link (if --getvpn enabled)
        if getvpn_enabled:
            ks_label = "KS"
            sw0_ks_port = num_sw
            if getattr(args, "pki_enabled", False):
                sw0_ks_port += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[ks_label]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids['SW0']}")
            lines.append(f"    i2: i{sw0_ks_port}")

        # Router -> access switch (only odd routers connect Gi0/0 to access switch)
        router_sw_port: dict[str, tuple[str, int]] = {}
        per_sw_next_port = [1 for _ in range(num_sw)]  # reserve 0 for uplink
        for idx in range(total):
            n = idx + 1
            if n % 2 == 0:
                continue  # even routers do not connect to access switch
            rlabel = f"R{n}"
            sw_index = idx // group + 1
            acc = f"SW{sw_index}"
            acc_port = per_sw_next_port[sw_index - 1]
            per_sw_next_port[sw_index - 1] += 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[rlabel]}")
            lines.append("    i1: i0")
            lines.append(f"    n2: {node_ids[acc]}")
            lines.append(f"    i2: i{acc_port}")

        # Odd-even pairing links: R1 i1 <-> R2 i0, R3 i1 <-> R4 i0, ...
        for odd in range(1, total + 1, 2):
            even = odd + 1
            if even > total:
                break
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[f'R{odd}']}")
            lines.append("    i1: i1")
            lines.append(f"    n2: {node_ids[f'R{even}']}")
            lines.append("    i2: i0")

        # OOB access -> OOB core links (if --mgmt enabled)
        if enable_mgmt:
            # External connector -> SWoob0 link (if --mgmt-bridge enabled)
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            # OOB access switches -> SWoob0 links
            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i+1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

            # Routers -> OOB access switch
            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]  # reserve 0 for uplink
            for idx in range(total):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

            # CA-ROOT -> SWoob0 mgmt link (if --pki enabled)
            if getattr(args, "pki_enabled", False):
                ca_label = "CA-ROOT"
                # CA is always CSR1000v, so use slot - 1
                ca_mgmt_iface_id = mgmt_slot - 1
                # SWoob0's next available port after ext-conn-mgmt (if present) and OOB access switches
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ca_label]}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

            # KS -> SWoob0 mgmt link (if --getvpn enabled)
            if getvpn_enabled:
                ks_label = "KS"
                ks_mgmt_iface_id = mgmt_slot - 1
                swoob0_ks_port = port_offset + num_oob_sw
                if getattr(args, "pki_enabled", False):
                    swoob0_ks_port += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[ks_label]}")
                lines.append(f"    i1: i{ks_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ks_port}")

        _validate_nac_router_nodes_if_enabled(nac_root, nac_router_nodes, dev_def)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if nac_root is not None:
            nac_root.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _finalize_offline_yaml_with_intent(lines, desc, version, args)
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning("Offline YAML (flat-pair) written to %s (%.1f KB)", outfile, size_kb)
        _write_nac_tree_if_enabled(
            nac_root=nac_root,
            nodes=nac_router_nodes,
            device_template=dev_def,
            template=args.template,
            mode=args.mode,
            args=args,
        )
        write_cml2_lifecycle_if_enabled(args, outfile, cml2_root)
        return 0

    @staticmethod
    def offline_nx_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML file locally for NX mode.

        Uses NetworkX random_shell_graph + kamada_kawai_layout to produce a
        partially-meshed random topology with direct router-to-router p2p links.
        Mirrors the online render_node_network topology exactly.

        Topology:
        - ext-conn-0 (external_connector) for outbound connectivity
        - dns-host (Alpine Linux) — DNS/NAT gateway connected to ext-conn-0
        - dns-host eth1 links to the core router (highest degree centrality)
        - Core router gets default route + OSPF default-information originate
        - Routers R1..R<n> with point-to-point /30 links derived from the graph edges
        - Loopback0 addresses from cfg.loopbacks (/32)
        - Optional OOB management switch fabric (--mgmt)
        """

        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(f"template does not exist: {args.template}") from exc

        total = int(args.nodes)
        distance = int(getattr(args, "distance", 200))
        nac_enabled = bool(getattr(args, "nac", False))
        cml2_enabled = bool(getattr(args, "terraform_cml2", False))
        outfile, nac_root, cml2_root = resolve_offline_artifact_paths(
            getattr(args, "offline_yaml"),
            nac_enabled=nac_enabled,
            cml2_enabled=cml2_enabled,
        )

        # --- Generate NX graph (mirrors create_nx_network) ---
        size = int(total / 8)
        size = max(size, 20)
        clusters = int(total / size)
        remain = total - clusters * size
        dimensions = int(math.sqrt(total) * distance)

        constructor = [
            (size, size * 2, 0.999) if a < clusters else (remain, remain * 2, 0.999)
            for a in range(clusters + (1 if remain > 0 else 0))
        ]

        graph = nx.random_shell_graph(constructor)

        if not nx.is_connected(graph):
            complement = list(nx.k_edge_augmentation(graph, k=1))
            graph.add_edges_from(complement)

        pos = nx.kamada_kawai_layout(graph, scale=dimensions)

        # Scale coordinates to stay within CML's 15000-coordinate limit
        max_coord = 15000
        raw_coords = {k: (int(v[0]), int(v[1])) for k, v in pos.items()}
        if raw_coords:
            extent = max(
                max(abs(c) for pair in raw_coords.values() for c in pair),
                1,
            )
            scale = min(1.0, (max_coord - 100) / extent)
        else:
            scale = 1.0
        node_coords = {k: (int(v[0] * scale), int(v[1] * scale)) for k, v in raw_coords.items()}

        # --- Allocate p2p /30 subnets for each edge ---
        p2pnets_iter = IPv4Network(cfg.p2pnets).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.p2pnets.prefixlen - 2
        )

        # Reserve first /30 for ext-conn ↔ dns-host ↔ core-router link
        # Online uses set() unpacking which assigns dns_addr=.2, dns_via=.1
        # for CPython small-int set iteration order; we match that.
        dns_prefix = next(p2pnets_iter)
        dns_hosts = list(dns_prefix.hosts())
        dns_addr = IPv4Interface(f"{dns_hosts[1]}/{dns_prefix.prefixlen}")
        dns_via = IPv4Interface(f"{dns_hosts[0]}/{dns_prefix.prefixlen}")

        # Identify core node (highest degree centrality, mirrors online)
        core = sorted(
            nx.degree_centrality(graph).items(), key=lambda e: e[1], reverse=True
        )[0][0]

        edge_info: dict[tuple[int, int], tuple[IPv4Network, IPv4Address, IPv4Address]] = {}
        for edge in graph.edges:
            prefix = next(p2pnets_iter)
            hosts = list(prefix.hosts())
            edge_info[edge] = (prefix, hosts[0], hosts[1])

        # --- Build per-node interface lists (sorted by neighbor for determinism) ---
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        dev_def_early = getattr(args, "dev_template", args.template)
        reserved_mgmt_slot: int | None = None
        if enable_mgmt:
            reserved_mgmt_slot = (
                mgmt_slot - 1 if dev_def_early == "csr1000v" else mgmt_slot
            )

        def _next_topo_slot(slot: int) -> int:
            if reserved_mgmt_slot is not None and slot == reserved_mgmt_slot:
                return slot + 1
            return slot

        node_ifaces: dict[int, list[dict[str, Any]]] = {}
        for node_index in graph.nodes:
            ifaces: list[dict[str, Any]] = []
            slot = 0
            for neighbor in sorted(graph.adj[node_index]):
                slot = _next_topo_slot(slot)
                canonical = (min(node_index, neighbor), max(node_index, neighbor))
                prefix, host0, host1 = edge_info[canonical]
                if node_index == canonical[0]:
                    ip = host0
                else:
                    ip = host1
                ifaces.append({
                    "slot": slot,
                    "neighbor": neighbor,
                    "address": IPv4Interface(f"{ip}/{prefix.prefixlen}"),
                })
                slot += 1
            # Core node gets an extra interface for the DNS host link
            if node_index == core:
                slot = _next_topo_slot(slot)
                ifaces.append({
                    "slot": slot,
                    "neighbor": -1,
                    "address": dns_via,
                    "dns_link": True,
                })
            node_ifaces[node_index] = ifaces

        # Update cfg.nameserver so templates reference the DNS host IP
        cfg.nameserver = str(dns_addr.ip)

        # --- Allocate loopbacks (/32) from cfg.loopbacks, skip .0 ---
        loopback_iter = IPv4Network(cfg.loopbacks).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.loopbacks.prefixlen
        )
        next(loopback_iter)  # skip .0
        node_loopbacks: dict[int, IPv4Interface] = {}
        for node_index in sorted(graph.nodes):
            node_loopbacks[node_index] = IPv4Interface(next(loopback_iter))

        # --- Common flag reads ---
        dev_def = getattr(args, "dev_template", args.template)
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        version = getattr(args, "cml_version", "0.3.0")
        staging = getattr(args, "staging", False) and _staging_version_ok(version)
        pki_enabled = getattr(args, "pki_enabled", False)
        ca_scep_url = _offline_ca_mgmt_scep_url(args, total) if pki_enabled else None
        nac_router_nodes: list[TopogenNode] = []

        # --- Build YAML header ---
        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")

        args_bits: list[str] = [f"nodes={total}", f"-m {args.mode}", f"-T {args.template}"]
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        append_cml_schema_provenance_args(args_bits, args)
        if enable_mgmt:
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        if getattr(args, "archive", False):
            args_bits.append("--archive")
        if staging:
            args_bits.append("--staging")
        _append_common_offline_args_bits(args_bits, args)
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {str(outfile).replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, nx) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        lines.append(f'  description: "{desc}"')
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        if staging:
            lines.extend(_node_staging_lines(abort_on_failure=not getattr(args, "staging_no_abort", False)))
        lines.append("nodes:")

        node_ids: dict[str, str] = {}
        nid = 0

        # --- External connector (ext-conn-0) ---
        node_ids[EXT_CON_NAME] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids[EXT_CON_NAME]}")
        lines.append(f"    label: {EXT_CON_NAME}")
        lines.append("    node_definition: external_connector")
        lines.append("    x: 0")
        lines.append("    y: 0")
        lines.append("    interfaces:")
        lines.append("      - id: i0")
        lines.append("        slot: 0")
        lines.append("        label: port")
        lines.append("        type: physical")

        # Reserve DNS host node ID (emitted after routers once dns_zone is built)
        node_ids[DNS_HOST_NAME] = f"n{nid}"; nid += 1

        # --- OOB management infrastructure (if --mgmt) ---
        oob_group = max(1, int(getattr(args, "flat_group_size", 20)))
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            num_oob_sw = math.ceil(total / oob_group)
            for i in range(num_oob_sw):
                start = i * oob_group + 1
                end = min((i + 1) * oob_group, total)
                oob_per_sw_counts.append(max(0, end - start + 1))

            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            swoob0_extra = 1 if pki_enabled else 0
            for p in range(num_oob_sw + swoob0_extra):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append(f"        type: physical")

            for i in range(num_oob_sw):
                oob_label = f"SWoob{i + 1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {(i + 1) * distance}")
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append(f"        type: physical")

        # --- Router nodes ---
        dns_zone: list[DNShost] = []
        for node_index in sorted(graph.nodes):
            label = f"R{node_index + 1}"
            node_ids[label] = f"n{nid}"; nid += 1
            x, y = node_coords[node_index]
            ifaces = node_ifaces[node_index]
            loopback = node_loopbacks[node_index]

            topo_ifaces = []
            for iface in ifaces:
                if iface.get("dns_link"):
                    iface_desc = f"to {DNS_HOST_NAME}"
                elif iface["neighbor"] < 0:
                    iface_desc = "stub"
                else:
                    iface_desc = f"to R{iface['neighbor'] + 1}"
                topo_ifaces.append(TopogenInterface(
                    address=iface["address"],
                    description=iface_desc,
                    slot=iface["slot"],
                ))
            topo_ifaces.sort(key=lambda xi: xi.slot)

            node_obj = TopogenNode(
                hostname=label,
                loopback=loopback,
                interfaces=topo_ifaces,
            )
            _append_nac_mgmt_interface(node_obj, args, node_index + 1)
            nac_router_nodes.append(node_obj)

            mgmt_ctx = _build_mgmt_context(
                args,
                mgmt_slot=mgmt_slot,
                router_index=node_index + 1,
                loopback=loopback,
                hostname=label,
            )
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            is_core = node_index == core
            rendered = tpl.render(
                config=cfg,
                node=node_obj,
                date=datetime.now(timezone.utc),
                origin=dns_addr if is_core else "",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )
            if pki_enabled and ca_scep_url:
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_scep_url
                )
            rendered = _finalize_router_day0_config(rendered, cfg, node_obj, args)

            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {x}")
            lines.append(f"    y: {y}")
            lines.append("    interfaces:")
            for iface in ifaces:
                s = iface["slot"]
                if dev_def == "csr1000v":
                    iface_label = f"GigabitEthernet{s + 1}"
                else:
                    iface_label = f"GigabitEthernet0/{s}"
                lines.append(f"      - id: i{s}")
                lines.append(f"        slot: {s}")
                lines.append(f"        label: {iface_label}")
                lines.append(f"        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    lines.append(f"      - id: i{csr_slot}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    lines.append(f"      - id: i{mgmt_slot}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, rendered, getattr(args, "blank", False))
            dns_zone.append(DNShost(label.lower(), loopback.ip))

        if pki_enabled and enable_mgmt:
            nid = _emit_offline_ca_root_mgmt_node(
                env,
                cfg,
                args,
                lines,
                node_ids,
                nid,
                tpl,
                enable_mgmt,
                mgmt_slot,
                staging,
                total,
                distance,
            )

        # --- DNS / NAT host node (alpine, emitted after routers so dns_zone is complete) ---
        dns_zone.append(DNShost(f"{DNS_HOST_NAME}-eth1", dns_addr.ip))
        dns_node = TopogenNode(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                TopogenInterface(address=dns_addr),
                TopogenInterface(address=dns_via),
            ],
        )
        dns_config = dnshostconfig(cfg, dns_node, dns_zone)
        lines.append(f"  - id: {node_ids[DNS_HOST_NAME]}")
        lines.append(f"    label: {DNS_HOST_NAME}")
        lines.append("    node_definition: alpine")
        lines.append(f"    x: {distance}")
        lines.append("    y: 0")
        lines.append("    interfaces:")
        lines.append("      - id: i0")
        lines.append("        slot: 0")
        lines.append("        label: eth0")
        lines.append("        type: physical")
        lines.append("      - id: i1")
        lines.append("        slot: 1")
        lines.append("        label: eth1")
        lines.append("        type: physical")
        _emit_config(lines, dns_config, getattr(args, "blank", False))

        # --- Links section ---
        lines.append("links:")
        lid = 0

        # ext-conn-0 ↔ dns-host (eth0)
        lines.append(f"  - id: l{lid}"); lid += 1
        lines.append(f"    n1: {node_ids[EXT_CON_NAME]}")
        lines.append("    i1: i0")
        lines.append(f"    n2: {node_ids[DNS_HOST_NAME]}")
        lines.append("    i2: i0")

        # dns-host (eth1) ↔ core router (dns_link slot)
        core_label = f"R{core + 1}"
        dns_slot = next(i["slot"] for i in node_ifaces[core] if i.get("dns_link"))
        lines.append(f"  - id: l{lid}"); lid += 1
        lines.append(f"    n1: {node_ids[DNS_HOST_NAME]}")
        lines.append("    i1: i1")
        lines.append(f"    n2: {node_ids[core_label]}")
        lines.append(f"    i2: i{dns_slot}")

        # Build (node, neighbor) -> slot lookup
        slot_lookup: dict[tuple[int, int], int] = {}
        for ni, ifaces_list in node_ifaces.items():
            for iface in ifaces_list:
                slot_lookup[(ni, iface["neighbor"])] = iface["slot"]

        for edge in graph.edges:
            src, dst = edge
            src_label = f"R{src + 1}"
            dst_label = f"R{dst + 1}"
            src_slot = slot_lookup[(src, dst)]
            dst_slot = slot_lookup[(dst, src)]
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[src_label]}")
            lines.append(f"    i1: i{src_slot}")
            lines.append(f"    n2: {node_ids[dst_label]}")
            lines.append(f"    i2: i{dst_slot}")

        # OOB management links (if --mgmt)
        if enable_mgmt:
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i + 1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

            router_mgmt_iface_id = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]
            for idx in range(total):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

            if pki_enabled:
                ca_mgmt_iface_id = mgmt_slot - 1
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['CA-ROOT']}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

        # --- Write file ---
        _validate_nac_router_nodes_if_enabled(nac_root, nac_router_nodes, dev_def)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if nac_root is not None:
            nac_root.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _finalize_offline_yaml_with_intent(lines, desc, version, args)
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning(
            "Offline YAML (nx, %d nodes, %d edges) written to %s (%.1f KB)",
            graph.number_of_nodes(), graph.number_of_edges(), outfile, size_kb,
        )
        _write_nac_tree_if_enabled(
            nac_root=nac_root,
            nodes=nac_router_nodes,
            device_template=dev_def,
            template=args.template,
            mode=args.mode,
            args=args,
        )
        write_cml2_lifecycle_if_enabled(args, outfile, cml2_root)
        return 0

    @staticmethod
    def offline_simple_yaml(args: Namespace, cfg: Config) -> int:
        """Generate a CML-compatible YAML file locally for simple (chain) mode.

        Produces a linear chain topology R1-R2-R3-...-Rn with square spiral
        coordinates (matching the online render_node_sequence layout).
        Mirrors the online render_node_sequence topology exactly.

        Topology:
        - ext-conn-0 (external_connector) for outbound connectivity
        - dns-host (Alpine Linux) — DNS/NAT gateway connected to ext-conn-0
        - dns-host eth1 links to R1's backward interface (slot 1)
        - R1 gets default route + OSPF default-information originate
        - Routers R1..R<n> in a sequential chain
        - Point-to-point /30 links between consecutive routers
        - Loopback0 addresses from cfg.loopbacks (/32)
        - Optional OOB management switch fabric (--mgmt)
        """

        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        try:
            tpl = env.get_template(f"{args.template}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(f"template does not exist: {args.template}") from exc

        total = int(args.nodes)
        distance = int(getattr(args, "distance", 200))
        nac_enabled = bool(getattr(args, "nac", False))
        cml2_enabled = bool(getattr(args, "terraform_cml2", False))
        outfile, nac_root, cml2_root = resolve_offline_artifact_paths(
            getattr(args, "offline_yaml"),
            nac_enabled=nac_enabled,
            cml2_enabled=cml2_enabled,
        )

        # --- Generate square spiral coordinates (mirrors CoordsGenerator) ---
        # Online render_node_sequence consumes first coord for dns-host,
        # then subsequent coords for routers R1..Rn
        coords_gen = CoordsGenerator(distance=distance)
        coords_iter = iter(coords_gen)
        dns_host_coord = next(coords_iter)
        dns_host_xy = (dns_host_coord.x, dns_host_coord.y)
        node_coords: dict[int, tuple[int, int]] = {}
        for idx in range(total):
            pt = next(coords_iter)
            node_coords[idx] = (pt.x, pt.y)

        # --- Allocate p2p /30 subnets ---
        p2pnets_iter = IPv4Network(cfg.p2pnets).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.p2pnets.prefixlen - 2
        )

        # First /30 is for ext-conn ↔ dns-host ↔ R1 (mirrors online render_node_sequence)
        # Online uses set() unpacking which assigns dns_iface=.2, prev_iface=.1
        # for CPython small-int set iteration order; we match that.
        dns_prefix = next(p2pnets_iter)
        dns_hosts_list = list(dns_prefix.hosts())
        dns_addr = IPv4Interface(f"{dns_hosts_list[1]}/{dns_prefix.prefixlen}")
        dns_via = IPv4Interface(f"{dns_hosts_list[0]}/{dns_prefix.prefixlen}")
        cfg.nameserver = str(dns_addr.ip)

        # Allocate one /30 per router (mirrors online: src_iface, dst_iface = self.next_network())
        # Online uses set() unpacking: src_iface=.2, dst_iface=.1
        # Each router gets: slot 0 = fwd (src_iface), slot 1 = bwd (prev_iface)
        node_ifaces: dict[int, list[dict[str, Any]]] = {}
        prev_iface = dns_via
        for idx in range(total):
            prefix = next(p2pnets_iter)
            hosts = list(prefix.hosts())
            src_iface = IPv4Interface(f"{hosts[1]}/{prefix.prefixlen}")
            dst_iface = IPv4Interface(f"{hosts[0]}/{prefix.prefixlen}")
            is_r1 = idx == 0
            node_ifaces[idx] = [
                {"slot": 0, "neighbor": idx + 1 if idx < total - 1 else -1,
                 "address": src_iface, "direction": "fwd"},
                {"slot": 1, "neighbor": idx - 1 if not is_r1 else -1,
                 "address": prev_iface, "direction": "bwd",
                 "dns_link": is_r1},
            ]
            prev_iface = dst_iface

        # --- Allocate loopbacks (/32) from cfg.loopbacks, skip .0 ---
        loopback_iter = IPv4Network(cfg.loopbacks).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.loopbacks.prefixlen
        )
        next(loopback_iter)
        node_loopbacks: dict[int, IPv4Interface] = {}
        for idx in range(total):
            node_loopbacks[idx] = IPv4Interface(next(loopback_iter))

        # --- Common flag reads ---
        dev_def = getattr(args, "dev_template", args.template)
        enable_mgmt = getattr(args, "enable_mgmt", False)
        mgmt_slot = getattr(args, "mgmt_slot", 5)
        version = getattr(args, "cml_version", "0.3.0")
        staging = getattr(args, "staging", False) and _staging_version_ok(version)
        pki_enabled = getattr(args, "pki_enabled", False)
        ca_scep_url = _offline_ca_mgmt_scep_url(args, total) if pki_enabled else None

        # --- Build YAML header ---
        lines: list[str] = []
        lines.append("lab:")
        lines.append(f"  title: {args.labname}")

        args_bits: list[str] = [f"nodes={total}", f"-m {args.mode}", f"-T {args.template}"]
        if dev_def != args.template:
            args_bits.append(f"--device-template {dev_def}")
        append_cml_schema_provenance_args(args_bits, args)
        if enable_mgmt:
            args_bits.append("--mgmt")
            args_bits.append(f"--mgmt-cidr {args.mgmt_cidr}")
            if getattr(args, "mgmt_gw", None):
                args_bits.append(f"--mgmt-gw {args.mgmt_gw}")
            args_bits.append(f"--mgmt-slot {args.mgmt_slot}")
            if getattr(args, "mgmt_vrf", None):
                args_bits.append(f"--mgmt-vrf {args.mgmt_vrf}")
            if getattr(args, "mgmt_bridge", False):
                args_bits.append("--mgmt-bridge")
        if getattr(args, "ntp_server", None):
            args_bits.append(f"--ntp {args.ntp_server}")
            if getattr(args, "ntp_inband", False):
                args_bits.append("--ntp-inband")
            if getattr(args, "ntp_vrf", None):
                args_bits.append(f"--ntp-vrf {args.ntp_vrf}")
        if getattr(args, "ntp_oob_server", None):
            args_bits.append(f"--ntp-oob {args.ntp_oob_server}")
        if getattr(args, "archive", False):
            args_bits.append("--archive")
        if staging:
            args_bits.append("--staging")
        _append_common_offline_args_bits(args_bits, args)
        args_bits.append(f"-L {args.labname}")
        args_bits.append(f"--offline-yaml {str(outfile).replace(chr(92), '/')}")
        desc = (
            f"Generated by topogen v{TOPGEN_VERSION} (offline YAML, simple) | args: "
            + " ".join(args_bits)
        )
        if getattr(args, "remark", None):
            desc += f" | remark: {args.remark}"
        lines.append(f'  description: "{desc}"')
        lines.extend(_intent_notes_lines(desc))
        lines.append(f"  version: '{version}'")
        if staging:
            lines.extend(_node_staging_lines(abort_on_failure=not getattr(args, "staging_no_abort", False)))
        lines.append("nodes:")

        node_ids: dict[str, str] = {}
        nid = 0

        # --- External connector (ext-conn-0) ---
        node_ids[EXT_CON_NAME] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids[EXT_CON_NAME]}")
        lines.append(f"    label: {EXT_CON_NAME}")
        lines.append("    node_definition: external_connector")
        lines.append("    x: 0")
        lines.append("    y: 0")
        lines.append("    interfaces:")
        lines.append("      - id: i0")
        lines.append("        slot: 0")
        lines.append("        label: port")
        lines.append("        type: physical")

        # --- DNS / NAT host (alpine, right after ext-conn to match online node order) ---
        dns_zone_simple: list[DNShost] = []
        for zidx in range(total):
            dns_zone_simple.append(DNShost(f"r{zidx + 1}", node_loopbacks[zidx].ip))
        dns_node = TopogenNode(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                TopogenInterface(address=dns_addr),
                TopogenInterface(address=dns_via),
            ],
        )
        dns_config = dnshostconfig(cfg, dns_node, dns_zone_simple)
        node_ids[DNS_HOST_NAME] = f"n{nid}"; nid += 1
        lines.append(f"  - id: {node_ids[DNS_HOST_NAME]}")
        lines.append(f"    label: {DNS_HOST_NAME}")
        lines.append("    node_definition: alpine")
        lines.append(f"    x: {dns_host_xy[0]}")
        lines.append(f"    y: {dns_host_xy[1]}")
        lines.append("    interfaces:")
        lines.append("      - id: i0")
        lines.append("        slot: 0")
        lines.append("        label: eth0")
        lines.append("        type: physical")
        lines.append("      - id: i1")
        lines.append("        slot: 1")
        lines.append("        label: eth1")
        lines.append("        type: physical")
        _emit_config(lines, dns_config, getattr(args, "blank", False))

        # --- OOB management infrastructure (if --mgmt) ---
        oob_group = max(1, int(getattr(args, "flat_group_size", 20)))
        num_oob_sw = 0
        oob_per_sw_counts: list[int] = []
        if enable_mgmt:
            num_oob_sw = math.ceil(total / oob_group)
            for i in range(num_oob_sw):
                start = i * oob_group + 1
                end = min((i + 1) * oob_group, total)
                oob_per_sw_counts.append(max(0, end - start + 1))

            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                node_ids["ext-conn-mgmt"] = f"n{nid}"; nid += 1
                lines.append(f"  - id: {node_ids['ext-conn-mgmt']}")
                lines.append("    label: ext-conn-mgmt")
                lines.append("    node_definition: external_connector")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    x: -440")
                lines.append("    y: 0")
                lines.append("    configuration:")
                lines.append("      - name: default")
                lines.append("        content: System Bridge")
                lines.append("    interfaces:")
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port")
                lines.append("        type: physical")

            node_ids["SWoob0"] = f"n{nid}"; nid += 1
            lines.append(f"  - id: {node_ids['SWoob0']}")
            lines.append("    label: SWoob0")
            lines.append("    node_definition: unmanaged_switch")
            if staging:
                lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
            lines.append("    hide_links: true")
            lines.append("    x: -200")
            lines.append("    y: 0")
            lines.append("    interfaces:")
            port_offset = 1 if mgmt_bridge else 0
            if mgmt_bridge:
                lines.append("      - id: i0")
                lines.append("        slot: 0")
                lines.append("        label: port0")
                lines.append("        type: physical")
            swoob0_extra = 1 if pki_enabled else 0
            for p in range(num_oob_sw + swoob0_extra):
                port_num = p + port_offset
                lines.append(f"      - id: i{port_num}")
                lines.append(f"        slot: {port_num}")
                lines.append(f"        label: port{port_num}")
                lines.append(f"        type: physical")

            for i in range(num_oob_sw):
                oob_label = f"SWoob{i + 1}"
                node_ids[oob_label] = f"n{nid}"; nid += 1
                ox = -200 - (i + 1) * distance
                lines.append(f"  - id: {node_ids[oob_label]}")
                lines.append(f"    label: {oob_label}")
                lines.append("    node_definition: unmanaged_switch")
                if staging:
                    lines.append(f"    priority: {STAGING_PRIORITY_EXT_CONN_OOB}")
                lines.append("    hide_links: true")
                lines.append(f"    x: {ox}")
                lines.append(f"    y: {(i + 1) * distance}")
                oob_if_count = 1 + oob_per_sw_counts[i]
                lines.append("    interfaces:")
                for p in range(oob_if_count):
                    lines.append(f"      - id: i{p}")
                    lines.append(f"        slot: {p}")
                    lines.append(f"        label: port{p}")
                    lines.append(f"        type: physical")

        # --- Router nodes ---
        nac_router_nodes: list[TopogenNode] = []
        for idx in range(total):
            label = f"R{idx + 1}"
            node_ids[label] = f"n{nid}"; nid += 1
            x, y = node_coords[idx]
            ifaces = node_ifaces[idx]
            loopback = node_loopbacks[idx]

            topo_ifaces = []
            for iface in ifaces:
                if iface.get("dns_link"):
                    iface_desc = f"to {DNS_HOST_NAME}"
                elif iface["neighbor"] < 0:
                    iface_desc = "stub"
                else:
                    iface_desc = f"to R{iface['neighbor'] + 1}"
                topo_ifaces.append(TopogenInterface(
                    address=iface["address"],
                    description=iface_desc,
                    slot=iface["slot"],
                ))
            topo_ifaces.sort(key=lambda xi: xi.slot)

            node_obj = TopogenNode(
                hostname=label,
                loopback=loopback,
                interfaces=topo_ifaces,
            )
            _append_nac_mgmt_interface(node_obj, args, idx + 1)
            nac_router_nodes.append(node_obj)

            mgmt_ctx = _build_mgmt_context(
                args,
                mgmt_slot=mgmt_slot,
                router_index=idx + 1,
                loopback=loopback,
                hostname=label,
            )
            ntp_ctx = None
            if getattr(args, "ntp_server", None):
                ntp_ctx = {
                    "server": args.ntp_server,
                    "vrf": getattr(args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": args.ntp_oob_server,
                    "vrf": getattr(args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            rendered = tpl.render(
                config=cfg,
                node=node_obj,
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(args, "archive", False),
            )
            if pki_enabled and ca_scep_url:
                rendered = _inject_pki_client_trustpoint(
                    rendered, label, cfg.domainname, ca_scep_url
                )
            rendered = _finalize_router_day0_config(rendered, cfg, node_obj, args)

            lines.append(f"  - id: {node_ids[label]}")
            lines.append(f"    label: {label}")
            lines.append(f"    node_definition: {dev_def}")
            lines.append(f"    x: {x}")
            lines.append(f"    y: {y}")
            lines.append("    interfaces:")
            # i0 = Loopback0 (matches CML online export)
            lines.append("      - id: i0")
            lines.append("        label: Loopback0")
            lines.append("        type: loopback")
            for iface in ifaces:
                s = iface["slot"]
                iid = s + 1
                if dev_def == "csr1000v":
                    iface_label = f"GigabitEthernet{s + 1}"
                else:
                    iface_label = f"GigabitEthernet0/{s}"
                lines.append(f"      - id: i{iid}")
                lines.append(f"        slot: {s}")
                lines.append(f"        label: {iface_label}")
                lines.append(f"        type: physical")
            if enable_mgmt:
                if dev_def == "csr1000v":
                    csr_slot = mgmt_slot - 1
                    mgmt_iid = csr_slot + 1
                    lines.append(f"      - id: i{mgmt_iid}")
                    lines.append(f"        slot: {csr_slot}")
                    lines.append(f"        label: GigabitEthernet{mgmt_slot}")
                else:
                    mgmt_iid = mgmt_slot + 1
                    lines.append(f"      - id: i{mgmt_iid}")
                    lines.append(f"        slot: {mgmt_slot}")
                    lines.append(f"        label: GigabitEthernet0/{mgmt_slot}")
                lines.append("        type: physical")
            _emit_config(lines, rendered, getattr(args, "blank", False))

        if pki_enabled and enable_mgmt:
            nid = _emit_offline_ca_root_mgmt_node(
                env,
                cfg,
                args,
                lines,
                node_ids,
                nid,
                tpl,
                enable_mgmt,
                mgmt_slot,
                staging,
                total,
                distance,
            )

        # --- Links section ---
        lines.append("links:")
        lid = 0

        # ext-conn-0 ↔ dns-host (eth0)
        lines.append(f"  - id: l{lid}"); lid += 1
        lines.append(f"    n1: {node_ids[EXT_CON_NAME]}")
        lines.append("    i1: i0")
        lines.append(f"    n2: {node_ids[DNS_HOST_NAME]}")
        lines.append("    i2: i0")

        # dns-host (eth1) ↔ R1 (i2 = Gig0/1 = slot1, due to Loopback0 as i0)
        lines.append(f"  - id: l{lid}"); lid += 1
        lines.append(f"    n1: {node_ids[DNS_HOST_NAME]}")
        lines.append("    i1: i1")
        lines.append(f"    n2: {node_ids['R1']}")
        lines.append("    i2: i2")

        # Chain links: R1→R2, R2→R3, ..., R(n-1)→Rn
        # i1=Gig0/0(slot0)=fwd, i2=Gig0/1(slot1)=bwd (shifted by 1 for Loopback0)
        for src in range(total - 1):
            dst = src + 1
            lines.append(f"  - id: l{lid}")
            lid += 1
            lines.append(f"    n1: {node_ids[f'R{src + 1}']}")
            lines.append("    i1: i1")
            lines.append(f"    n2: {node_ids[f'R{dst + 1}']}")
            lines.append("    i2: i2")

        # OOB management links (if --mgmt)
        if enable_mgmt:
            mgmt_bridge = getattr(args, "mgmt_bridge", False)
            if mgmt_bridge:
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['ext-conn-mgmt']}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append("    i2: i0")

            port_offset = 1 if mgmt_bridge else 0
            for i in range(num_oob_sw):
                oob_acc = f"SWoob{i + 1}"
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[oob_acc]}")
                lines.append("    i1: i0")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{i + port_offset}")

            # +1 shift for Loopback0 at i0
            router_mgmt_iface_id = (mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot) + 1
            oob_per_sw_next_port = [1 for _ in range(num_oob_sw)]
            for idx in range(total):
                n = idx + 1
                rlabel = f"R{n}"
                oob_sw_index = idx // oob_group
                oob_acc = f"SWoob{oob_sw_index + 1}"
                oob_acc_port = oob_per_sw_next_port[oob_sw_index]
                oob_per_sw_next_port[oob_sw_index] += 1
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids[rlabel]}")
                lines.append(f"    i1: i{router_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids[oob_acc]}")
                lines.append(f"    i2: i{oob_acc_port}")

            if pki_enabled:
                ca_mgmt_iface_id = mgmt_slot - 1
                swoob0_ca_port = port_offset + num_oob_sw
                lines.append(f"  - id: l{lid}")
                lid += 1
                lines.append(f"    n1: {node_ids['CA-ROOT']}")
                lines.append(f"    i1: i{ca_mgmt_iface_id}")
                lines.append(f"    n2: {node_ids['SWoob0']}")
                lines.append(f"    i2: i{swoob0_ca_port}")

        # --- Write file ---
        num_edges = total - 1
        _validate_nac_router_nodes_if_enabled(nac_root, nac_router_nodes, dev_def)
        outfile.parent.mkdir(parents=True, exist_ok=True)
        if nac_root is not None:
            nac_root.mkdir(parents=True, exist_ok=True)
        if outfile.exists() and not getattr(args, "overwrite", False):
            raise TopogenError(
                f"Refusing to overwrite existing file: {outfile}. Use --overwrite to replace it."
            )
        if outfile.exists() and getattr(args, "overwrite", False):
            _LOGGER.warning("Overwriting existing offline YAML file %s", outfile)
        lines = _finalize_offline_yaml_with_intent(lines, desc, version, args)
        outfile.write_text("\n".join(lines), encoding="utf-8")
        size_kb = outfile.stat().st_size / 1024
        _LOGGER.warning(
            "Offline YAML (simple, %d nodes, %d edges) written to %s (%.1f KB)",
            total, num_edges, outfile, size_kb,
        )
        _write_nac_tree_if_enabled(
            nac_root=nac_root,
            nodes=nac_router_nodes,
            device_template=dev_def,
            template=args.template,
            mode=args.mode,
            args=args,
        )
        write_cml2_lifecycle_if_enabled(args, outfile, cml2_root)
        return 0

    def render_flat_network(self) -> int:
        """Render a flat L2 management network.

        - Create unmanaged switches, each serving up to args.flat_group_size routers.
        - Connect all unmanaged switches to a core to keep one broadcast domain (star).
        - Connect each router's Gig0/0 (slot 0) to its group's switch.
        - Do not assign IPs to interfaces; users will enable EIGRP on Gig0 later.
        """

        disable_pcl_loggers()

        total = self.args.nodes
        group = max(1, int(self.args.flat_group_size))
        num_sw = Renderer.validate_flat_topology(total, group)

        # Warn about custom device templates/images which may affect interface behavior
        dev_def = getattr(self.args, "dev_template", self.args.template)
        if dev_def != "iosv":
            _LOGGER.warning(
                "Using custom device template '%s'; guardrails assume ~32-port unmanaged_switch and do not account for custom node definitions/images",
                dev_def,
            )

        _LOGGER.warning("Creating %d unmanaged switches for %d routers (group size %d)", num_sw, total, group)

        # Core switch in the middle
        core = self.create_node("SW0", "unmanaged_switch", Point(0, 0))

        # Two-tier OOB: SWoob0 (aggregation) + SWoob1..N (access, one per group)
        enable_mgmt = getattr(self.args, "enable_mgmt", False)
        mgmt_slot = getattr(self.args, "mgmt_slot", 5)
        oob_switches: list = []
        oob_group = max(1, int(getattr(self.args, "flat_group_size", 20)))
        if enable_mgmt:
            num_oob_sw = math.ceil(total / oob_group)
            distance = int(getattr(self.args, "distance", 200))

            mgmt_bridge = getattr(self.args, "mgmt_bridge", False)
            if mgmt_bridge:
                mgmt_ext_conn = self.create_node("ext-conn-mgmt", "external_connector", Point(-440, 0))
                mgmt_ext_conn.configuration = "System Bridge"
                _LOGGER.warning("Management external connector: %s", mgmt_ext_conn.label)

            oob_agg = self.create_node("SWoob0", "unmanaged_switch", Point(-200, 0))
            if hasattr(oob_agg, "hide_links"):
                oob_agg.hide_links = True

            if mgmt_bridge:
                self.lab.create_link(
                    mgmt_ext_conn.get_interface_by_slot(0),
                    self.new_interface(oob_agg),
                )
                _LOGGER.warning("Creating mgmt ext-conn link")

            for i in range(num_oob_sw):
                ox = -200 - (i + 1) * distance
                oy = (i + 1) * distance
                acc = self.create_node(f"SWoob{i + 1}", "unmanaged_switch", Point(ox, oy))
                if hasattr(acc, "hide_links"):
                    acc.hide_links = True
                self.lab.create_link(self.new_interface(acc), self.new_interface(oob_agg))
                oob_switches.append(acc)
                _LOGGER.warning("OOB access switch: %s", acc.label)

        # Create access switches positioned horizontally
        switches: list[Node] = []
        for i in range(num_sw):
            x = (i + 1) * self.args.distance * 3
            sw = self.create_node(f"SW{i+1}", "unmanaged_switch", Point(x, 0))
            switches.append(sw)
            # Connect each access switch back to core (star)
            self.lab.create_link(self.new_interface(core), self.new_interface(sw))
            _LOGGER.info("switch-link: %s <-> %s", core.label, sw.label)

        # Create routers and attach Gig0/0 to the appropriate switch
        for idx in range(total):
            router_label = f"R{idx + 1}"
            # Stagger routers below their switch
            sw_index = idx // group
            rx = (sw_index + 1) * self.args.distance * 3
            ry = (idx % group + 1) * self.args.distance
            cml_router = self.create_router(router_label, Point(rx, ry))

            # Ensure we have an interface on router and switch, then link them
            try:
                r_if = cml_router.get_interface_by_slot(0)
            except Exception:  # pragma: no cover - defensive
                r_if = self.new_interface(cml_router)

            sw = switches[sw_index]
            s_if = self.new_interface(sw)
            self.lab.create_link(r_if, s_if)
            _LOGGER.info("link: %s Gi0/0 -> %s", cml_router.label, sw.label)

            if enable_mgmt and oob_switches:
                dev_def = getattr(self.args, "dev_template", self.args.template)
                router_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                try:
                    mgmt_if = cml_router.get_interface_by_slot(router_mgmt_slot)
                except Exception:
                    mgmt_if = cml_router.create_interface(slot=router_mgmt_slot)
                sw_idx = idx // oob_group
                oob_if = self.new_interface(oob_switches[sw_idx])
                self.lab.create_link(mgmt_if, oob_if)
                _LOGGER.info("mgmt-link: %s slot %d -> %s", cml_router.label, router_mgmt_slot, oob_switches[sw_idx].label)

            # Deterministic addressing (1-based index encoded in last 16 bits)
            ridx = idx + 1
            hi = (ridx // 256) & 0xFF
            lo = ridx % 256
            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            g_addr = IPv4Interface(f"{g_base}.{hi}.{lo}/16")
            l_addr = IPv4Interface(f"{l_base}.{hi}.{lo}/32")

            # Build mgmt context for template
            mgmt_ctx = _build_mgmt_context(
                self.args,
                mgmt_slot=mgmt_slot,
                router_index=ridx,
                loopback=l_addr,
                hostname=router_label,
            )
            ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            # Build config: Loopback0 and Gi0/0 with assigned addresses
            node = TopogenNode(
                hostname=router_label,
                loopback=l_addr,
                interfaces=[TopogenInterface(address=g_addr, description="mgmt flat", slot=0)],
            )
            config = self.template.render(
                config=self.config,
                node=node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(self.args, "archive", False),
            )
            if getattr(self.args, "getvpn_enabled", False):
                ks_ip = f"{g_base}.255.251"
                gm_wan = "GigabitEthernet1" if dev_def == "csr1000v" else "GigabitEthernet0/0"
                config = _inject_getvpn_gm_config(
                    config, router_label, self.config.domainname,
                    getattr(self.args, "getvpn_protocol", "gdoi"),
                    getattr(self.args, "getvpn_group_id", 1),
                    ks_ip, gm_wan,
                )
            if getattr(self.args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                config = _inject_pki_client_trustpoint(
                    config, router_label, self.config.domainname, ca_url
                )
            if getattr(self.args, "blank", False):
                cml_router.configuration = ""  # type: ignore[method-assign]
            else:
                cml_router.configuration = config  # type: ignore[method-assign]

        # Create PKI Root CA router if --pki enabled
        if getattr(self.args, "pki_enabled", False):
            ca_label = "CA-ROOT"
            # Position CA to the left of SW0
            ca_pos = Point(-self.args.distance * 3, 0)
            ca_router = self.create_router(ca_label, ca_pos)

            # Connect CA to core switch (SW0) on slot 0
            ca_if = ca_router.get_interface_by_slot(0)
            core_if = self.new_interface(core)
            self.lab.create_link(ca_if, core_if)
            _LOGGER.info("CA link: %s Gi0/0 -> %s", ca_label, core.label)

            if enable_mgmt and oob_switches:
                dev_def = getattr(self.args, "dev_template", self.args.template)
                ca_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                try:
                    ca_mgmt_if = ca_router.get_interface_by_slot(ca_mgmt_slot)
                except Exception:
                    ca_mgmt_if = ca_router.create_interface(slot=ca_mgmt_slot)
                oob_ca_if = self.new_interface(oob_switches[0])
                self.lab.create_link(ca_mgmt_if, oob_ca_if)
                _LOGGER.info("CA mgmt-link: %s slot %d -> %s", ca_label, ca_mgmt_slot, oob_switches[0].label)

            # Assign last usable IP in the flat CIDR (e.g., 10.10.255.254/16)
            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            ca_g_addr = IPv4Interface(f"{g_base}.255.254/16")
            ca_l_addr = IPv4Interface(f"{l_base}.255.254/32")

            # Build mgmt/ntp context for CA
            ca_mgmt_ctx = _build_mgmt_context(self.args, mgmt_slot=mgmt_slot)
            ca_ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ca_ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ca_ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ca_ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            # Build config using csr-pki-ca template
            ca_node = TopogenNode(
                hostname=ca_label,
                loopback=ca_l_addr,
                interfaces=[TopogenInterface(address=ca_g_addr, description="=== SCEP Enrollment URL ===", slot=0)],
            )
            # Load csr-pki-ca template (no trim_blocks/lstrip_blocks to preserve newlines)
            import jinja2
            from pathlib import Path
            template_dir = Path(__file__).parent / "templates"
            ca_template = jinja2.Environment(
                loader=jinja2.FileSystemLoader(template_dir),
            ).get_template("csr-pki-ca.jinja2")

            ca_config = ca_template.render(
                config=self.config,
                node=ca_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ca_mgmt_ctx,
                ntp=ca_ntp_ctx,
                ntp_oob=ca_ntp_oob_ctx,
                pki_ca_key="",
                pki_enrollment_url=str(ca_g_addr.ip),
                pki_clock_set=_pki_clock_set_today(backdate_days=1),
                archive=getattr(self.args, "archive", False),
            )
            ca_router.configuration = ca_config  # type: ignore[method-assign]
            _LOGGER.warning("PKI Root CA created: %s at %s", ca_label, ca_g_addr.ip)

        # Create GET VPN Key Server if --getvpn enabled
        if getattr(self.args, "getvpn_enabled", False):
            ks_label = "KS"
            ks_dev_def = "csr1000v"
            ks_pos = Point(-self.args.distance * 2, self.args.distance)
            ks_router = self.create_node(ks_label, ks_dev_def, ks_pos)

            ks_if = ks_router.get_interface_by_slot(0)
            core_ks_if = self.new_interface(core)
            self.lab.create_link(ks_if, core_ks_if)
            _LOGGER.info("KS link: %s Gi1 -> %s", ks_label, core.label)

            if enable_mgmt and oob_switches:
                ks_mgmt_slot = mgmt_slot - 1
                try:
                    ks_mgmt_if = ks_router.get_interface_by_slot(ks_mgmt_slot)
                except Exception:
                    ks_mgmt_if = ks_router.create_interface(slot=ks_mgmt_slot)
                oob_ks_if = self.new_interface(oob_switches[0])
                self.lab.create_link(ks_mgmt_if, oob_ks_if)
                _LOGGER.info("KS mgmt-link: %s slot %d -> %s", ks_label, ks_mgmt_slot, oob_switches[0].label)

            g_base = "10.0" if getattr(self.args, "gi0_zero", False) else "10.10"
            l_base = "10.255" if getattr(self.args, "loopback_255", False) else "10.20"
            ks_g_ip = f"{g_base}.255.251"
            ks_l_ip = f"{l_base}.255.251"
            ks_node = TopogenNode(
                hostname=ks_label,
                loopback=IPv4Interface(f"{ks_l_ip}/32"),
                interfaces=[TopogenInterface(
                    address=IPv4Interface(f"{ks_g_ip}/16"),
                    description="=== GETVPN Key Server ===",
                    slot=0,
                )],
            )

            import jinja2 as _jinja2
            from pathlib import Path as _Path
            _ks_tpl_dir = _Path(__file__).parent / "templates"
            ks_tpl = _jinja2.Environment(
                loader=_jinja2.FileSystemLoader(_ks_tpl_dir),
            ).get_template(f"csr-getvpn-ks{Renderer.J2SUFFIX}")

            ks_mgmt_ctx = _build_mgmt_context(self.args, mgmt_slot=mgmt_slot)
            ks_ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ks_ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ks_ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ks_ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            ks_config = ks_tpl.render(
                config=self.config,
                node=ks_node,
                date=datetime.now(timezone.utc),
                origin="",
                mgmt=ks_mgmt_ctx,
                ntp=ks_ntp_ctx,
                ntp_oob=ks_ntp_oob_ctx,
                getvpn_protocol=getattr(self.args, "getvpn_protocol", "gdoi"),
                getvpn_group_id=getattr(self.args, "getvpn_group_id", 1),
                getvpn_rekey_interval=getattr(self.args, "getvpn_rekey_interval", 86400),
                getvpn_ks_ip=ks_g_ip,
            )
            if getattr(self.args, "pki_enabled", False):
                ca_url = f"http://{g_base}.255.254:80"
                ks_config = _inject_pki_client_trustpoint(
                    ks_config, ks_label, self.config.domainname, ca_url
                )
            ks_router.configuration = ks_config  # type: ignore[method-assign]
            _LOGGER.warning("GET VPN Key Server created: %s at %s", ks_label, ks_g_ip)

        _LOGGER.warning("Flat management network created")
        self._apply_online_lab_intent()

        # Get lab definition size (and optionally export to file) so we can log size for online create
        outfile = getattr(self.args, "yaml_output", None)
        content = None
        try:
            if hasattr(self.client, "export_lab"):
                content = self.client.export_lab(self.lab.id)  # type: ignore[attr-defined]
            elif hasattr(self.lab, "export"):
                content = self.lab.export()  # type: ignore[attr-defined]
            elif hasattr(self.lab, "topology"):
                content = str(self.lab.topology)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - best-effort
            pass
        if content is not None:
            data = content if isinstance(content, bytes) else str(content).encode("utf-8")
            size_kb = len(data) / 1024
            _LOGGER.warning("Lab created (%.1f KB) - uploaded to controller", size_kb)
            if outfile:
                try:
                    with open(outfile, "wb") as fh:
                        fh.write(data)
                    _LOGGER.warning("Exported lab YAML to %s", outfile)
                except Exception as exc:  # pragma: no cover
                    _LOGGER.error("YAML export failed: %s", exc)
        else:
            _LOGGER.warning("Lab created - uploaded to controller")

        # Print lab URL
        import os
        base_url = os.environ.get('VIRL2_URL', self.client.url if hasattr(self.client, 'url') else 'http://localhost').rstrip('/')
        _LOGGER.warning(f"Lab URL: {base_url}/lab/{self.lab.id}")

        # Start lab if requested (non-blocking)
        _start_lab_in_background(self.lab, self.args)

        return 0

    def render_node_sequence(self):
        """render the square spiral / node sequence network. Note: due to TTL
        limitations, it does not make a lot of sense to have this larger than
        32 or so hosts if end-to-end connectivity is required... One can still
        hop hop-by-hop, but DNS won't work all the way back to the DNS host!
        """

        disable_pcl_loggers()
        prev_iface = None
        prev_cml2iface = None

        if self.args.progress:
            manager = enlighten.get_manager(coords=next(self.coords))
            ticks = manager.counter(
                total=self.args.nodes,
                desc="Progress",
                unit="nodes",
                color="cyan",
                leave=False,
            )

        # create the external connector
        cml2_node = self.create_ext_conn()
        _LOGGER.info("external connector: %s", cml2_node.label)

        # create the DNS host
        dns_iface, prev_iface = self.next_network()
        dns_via = prev_iface
        dns_host = self.create_dns_host(coords=next(self.coords))
        _LOGGER.info("DNS host: %s", dns_host.label)
        prev_cml2iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_iface.ip)
        dns_zone: list[DNShost] = []

        # link the two
        self.lab.create_link(
            cml2_node.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.info("ext-conn link")

        # Two-tier OOB: SWoob0 (aggregation) + SWoob1..N (access, one per group)
        enable_mgmt = getattr(self.args, "enable_mgmt", False)
        mgmt_slot = getattr(self.args, "mgmt_slot", 5)
        oob_switches: list = []
        oob_group = max(1, int(getattr(self.args, "flat_group_size", 20)))
        if enable_mgmt:
            num_oob_sw = math.ceil(self.args.nodes / oob_group)
            distance = int(getattr(self.args, "distance", 200))

            mgmt_bridge = getattr(self.args, "mgmt_bridge", False)
            if mgmt_bridge:
                mgmt_ext_conn = self.create_node("ext-conn-mgmt", "external_connector", Point(-440, 0))
                mgmt_ext_conn.configuration = "System Bridge"
                _LOGGER.warning("Management external connector: %s", mgmt_ext_conn.label)

            oob_agg = self.create_node("SWoob0", "unmanaged_switch", Point(-200, 0))
            if hasattr(oob_agg, "hide_links"):
                oob_agg.hide_links = True
            _LOGGER.warning("OOB aggregation switch: %s", oob_agg.label)

            if mgmt_bridge:
                self.lab.create_link(
                    mgmt_ext_conn.get_interface_by_slot(0),
                    self.new_interface(oob_agg),
                )
                _LOGGER.warning("Creating mgmt ext-conn link")

            for i in range(num_oob_sw):
                ox = -200 - (i + 1) * distance
                oy = (i + 1) * distance
                acc = self.create_node(f"SWoob{i + 1}", "unmanaged_switch", Point(ox, oy))
                if hasattr(acc, "hide_links"):
                    acc.hide_links = True
                self.lab.create_link(self.new_interface(acc), self.new_interface(oob_agg))
                oob_switches.append(acc)
                _LOGGER.warning("OOB access switch: %s", acc.label)

        for idx in range(self.args.nodes):
            loopback = IPv4Interface(next(self.loopbacks))
            src_iface, dst_iface = self.next_network()
            interfaces = [
                TopogenInterface(address=src_iface),
                TopogenInterface(address=prev_iface),
            ]
            node = TopogenNode(
                hostname=f"R{idx + 1}",
                loopback=loopback,
                interfaces=interfaces,
            )

            # Build mgmt context for template
            mgmt_ctx = _build_mgmt_context(
                self.args,
                mgmt_slot=mgmt_slot,
                router_index=idx + 1,
                loopback=loopback,
                hostname=node.hostname,
            )
            ntp_ctx = None
            if getattr(self.args, "ntp_server", None):
                ntp_ctx = {
                    "server": self.args.ntp_server,
                    "vrf": getattr(self.args, "ntp_vrf", None),
                }
            ntp_oob_ctx = None
            if getattr(self.args, "ntp_oob_server", None):
                ntp_oob_ctx = {
                    "server": self.args.ntp_oob_server,
                    "vrf": getattr(self.args, "mgmt_vrf", None) or "Mgmt-vrf",
                }

            config = self.template.render(
                config=self.config,
                node=node,
                mgmt=mgmt_ctx,
                ntp=ntp_ctx,
                ntp_oob=ntp_oob_ctx,
                archive=getattr(self.args, "archive", False),
            )
            node_def = getattr(self.args, "dev_template", self.args.template)
            cml2_node = self.create_node(
                node.hostname, node_def, next(self.coords)
            )
            cml2_node.config = config
            _LOGGER.info("node: %s", cml2_node.label)
            self.lab.create_link(prev_cml2iface, cml2_node.get_interface_by_slot(1))
            _LOGGER.info("link %s", prev_cml2iface.label)
            prev_cml2iface = cml2_node.get_interface_by_slot(0)

            if enable_mgmt and oob_switches:
                dev_def = getattr(self.args, "dev_template", self.args.template)
                router_mgmt_slot = mgmt_slot - 1 if dev_def == "csr1000v" else mgmt_slot
                mgmt_if = cml2_node.create_interface(slot=router_mgmt_slot)
                sw_idx = idx // oob_group
                oob_if = self.new_interface(oob_switches[sw_idx])
                self.lab.create_link(mgmt_if, oob_if)
                _LOGGER.warning("mgmt-link: %s slot %d -> %s", cml2_node.label, router_mgmt_slot, oob_switches[sw_idx].label)
            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            prev_iface = dst_iface
            if self.args.progress:
                ticks.update()  # type: ignore

        # finalize the DNS host configuration
        node = TopogenNode(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                TopogenInterface(address=dns_iface),
                TopogenInterface(address=dns_via),
            ],
        )
        dns_host.config = dnshostconfig(self.config, node, dns_zone)

        if self.args.progress:
            ticks.close()  # type: ignore
            manager.stop()  # type: ignore

        self._apply_online_lab_intent()

        # Print lab URL
        import os
        base_url = os.environ.get('VIRL2_URL', self.client.url if hasattr(self.client, 'url') else 'http://localhost').rstrip('/')
        _LOGGER.warning(f"Lab URL: {base_url}/lab/{self.lab.id}")

        # Start lab if requested (non-blocking)
        _start_lab_in_background(self.lab, self.args)

        return 0
