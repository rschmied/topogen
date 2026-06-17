# File Chain (see DEVELOPER.md):
# Doc Version: v1.12.1
# Date Modified: 2026-06-13
#
"""
TopoGen Main Entry Point - CLI Argument Parsing and Application Bootstrap

PURPOSE:
    Entry point for the topogen CLI tool. Handles argument parsing, validation,
    configuration loading, and orchestrates the rendering pipeline based on user inputs.

WHO READS ME:
    - Users: via CLI command `topogen` or `python -m topogen.main`
    - gui.py: when launching GUI mode with Gooey

WHO I READ:
    - config.py: Configuration loading and defaults
    - models.py: TopogenError exception handling
    - render.py: Renderer class and topology generation functions
    - colorlog.py: Custom log formatting

DEPENDENCIES:
    - argparse: CLI argument parsing
    - logging: Application logging
    - os, sys: System operations

KEY EXPORTS:
    - main(): Application entry point
    - create_argparser(): Creates and configures the argument parser
    - valid_node_count(): Validates node count argument (1-1000 parser-level)

FLOW:
    1. Parse CLI arguments (create_argparser)
    2. Load configuration from config.toml (or defaults)
    3. Validate arguments (node count policy, IP addresses, flag dependencies)
    4. Create Renderer instance based on mode (nx, simple, flat, flat-pair, dmvpn)
    5. Execute online (CML API) or offline (YAML generation) workflow
"""

import argparse
import logging
import os
import sys

import topogen
from topogen.cml_server import resolve_cml_server_version, valid_cml_server
from topogen.models import TopogenError
from topogen.render import (
    Renderer,
    SUPPORTED_NAC_DEVICE_TEMPLATES,
    describe_nac_unsupported_nodes,
    get_templates,
)
from topogen.colorlog import CustomFormatter

_LOGGER = logging.getLogger(__name__)


def valid_node_count(value):
    ivalue = int(value)
    if ivalue < 1 or ivalue > 1000:
        raise argparse.ArgumentTypeError(
            f"invalid value {value}. Valid values are from 1-1000."
        )
    return ivalue


def validate_nodes_for_mode(args, parser):
    """Validate node counts while preserving non-NaC behavior."""
    if args.nodes is None:
        return
    if args.nodes > 1000:
        parser.error(
            f"invalid value {args.nodes}. Valid values are from 1-1000."
        )
    # Preserve legacy minimum for non-NaC paths.
    if not getattr(args, "nac", False) and args.nodes < 2:
        parser.error(
            f"argument nodes: invalid value {args.nodes}. Valid values are from 2-1000."
        )


def validate_nac_mvp_guardrails(args, parser):
    """Fail-fast guardrails for NaC CLI combinations."""
    if not getattr(args, "nac", False):
        return
    if getattr(args, "blank", False):
        parser.error(
            "--nac cannot be combined with --blank "
            "(Bootstrap Lab uses empty device configs; use --offline-yaml with --nac --bootstrap)"
        )
    if not getattr(args, "offline_yaml", None):
        parser.error("--nac requires --offline-yaml FILE (offline generation path)")
    dev_template = getattr(args, "dev_template", "iosv")
    if dev_template not in SUPPORTED_NAC_DEVICE_TEMPLATES:
        node_names = [f"R{i}" for i in range(1, int(args.nodes or 0) + 1)]
        unsupported = describe_nac_unsupported_nodes(node_names, dev_template)
        parser.error(
            "--nac supports IOS-XE router nodes only; unsupported node(s): "
            + "; ".join(unsupported)
            + ". Supported IOS-XE device templates: iosv, csr1000v."
        )
    if (
        getattr(args, "do_import", False)
        or getattr(args, "import_yaml", None)
        or getattr(args, "up", None)
    ):
        parser.error(
            "--nac requires local offline generation; "
            "import workflow flags are not supported (--import/--import-yaml/--up)"
        )
    if getattr(args, "yaml_output", None):
        parser.error(
            "--nac requires local offline generation; "
            "use --offline-yaml instead of --yaml online export"
        )


def validate_bootstrap_guardrails(args, parser):
    """Fail-fast guardrails for thin day-0 bootstrap generation."""
    if not getattr(args, "bootstrap", False):
        return
    if not getattr(args, "nac", False):
        parser.error("--bootstrap requires --nac (thin day-0 for Terraform-managed device config)")
    if getattr(args, "blank", False):
        parser.error("--bootstrap cannot be combined with --blank")
    if not getattr(args, "enable_mgmt", False):
        parser.error("--bootstrap requires --mgmt (OOB reachability for NaC/Terraform)")
    if getattr(args, "pki_enabled", False):
        parser.error("--bootstrap cannot be combined with --pki")
    if getattr(args, "getvpn_enabled", False):
        parser.error("--bootstrap cannot be combined with --getvpn")


# IPv4 OOB (DHCP or static from --mgmt-cidr) exhausts shared mgmt bridge pools above this.
MGMT_IPV4_OOB_NODE_LIMIT = 16


def finalize_mgmt_addressing_args(args, parser) -> None:
    """Resolve explicit DHCP flags and legacy --mgmt-ipv6-mode into a single model."""
    if not getattr(args, "enable_mgmt", False):
        return

    v6_dhcp = bool(getattr(args, "mgmt_ipv6_dhcp", False))
    v6_slaac = bool(getattr(args, "mgmt_ipv6_slaac", False))
    v6_mode = getattr(args, "mgmt_ipv6_mode", None)

    if v6_dhcp and v6_slaac:
        parser.error("--mgmt-ipv6-dhcp and --mgmt-ipv6-slaac are mutually exclusive")
    if v6_dhcp:
        if v6_mode and v6_mode != "dhcpv6":
            parser.error(
                "--mgmt-ipv6-dhcp conflicts with --mgmt-ipv6-mode "
                f"{v6_mode!r} (use one IPv6 acquisition method)"
            )
        args.mgmt_ipv6_mode = "dhcpv6"
    elif v6_slaac:
        if v6_mode and v6_mode != "slaac":
            parser.error(
                "--mgmt-ipv6-slaac conflicts with --mgmt-ipv6-mode "
                f"{v6_mode!r} (use one IPv6 acquisition method)"
            )
        args.mgmt_ipv6_mode = "slaac"

    v6_static = bool(getattr(args, "mgmt_ipv6_static", False))
    if v6_static:
        if v6_dhcp or v6_slaac:
            parser.error(
                "--mgmt-ipv6-static is mutually exclusive with "
                "--mgmt-ipv6-dhcp and --mgmt-ipv6-slaac"
            )
        if v6_mode and v6_mode not in ("static",):
            parser.error(
                f"--mgmt-ipv6-static conflicts with --mgmt-ipv6-mode "
                f"{v6_mode!r} (use one IPv6 acquisition method)"
            )
        args.mgmt_ipv6_mode = "static"

    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    v4_dhcp = bool(getattr(args, "mgmt_ipv4_dhcp", False))
    if not v4_dhcp and not ipv6_mode and getattr(args, "mgmt_bridge", False):
        # Backward compat: bridged OOB without explicit addressing still uses IPv4 DHCP.
        args.mgmt_ipv4_dhcp = True


def _mgmt_uses_ipv4_oob(args) -> bool:
    """True when router OOB will carry IPv4 (DHCP, static from --mgmt-cidr, or bridge DHCP)."""
    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    if ipv6_mode and not getattr(args, "mgmt_ipv4_dhcp", False):
        return False
    if getattr(args, "mgmt_ipv4_dhcp", False):
        return True
    if getattr(args, "mgmt_bridge", False):
        return True
    return bool(getattr(args, "enable_mgmt", False))


def validate_mgmt_ipv6_guardrails(args, parser):
    """Fail-fast guardrails for OOB management addressing (TG-190, TG-195)."""
    ipv6_mode = getattr(args, "mgmt_ipv6_mode", None)
    v6_static = bool(getattr(args, "mgmt_ipv6_static", False))
    v6_static_ll = bool(getattr(args, "mgmt_ipv6_static_link_local", False))

    if v6_static_ll:
        if not getattr(args, "enable_mgmt", False):
            parser.error("--mgmt-ipv6-static-link-local requires --mgmt")
        if ipv6_mode not in ("static", "slaac", "dhcpv6"):
            parser.error(
                "--mgmt-ipv6-static-link-local requires an IPv6 OOB mode "
                "(--mgmt-ipv6-static, --mgmt-ipv6-slaac, --mgmt-ipv6-dhcp, "
                "or --mgmt-ipv6-mode slaac|dhcpv6)"
            )

    if getattr(args, "mgmt_ipv6_gw", None) and not v6_static:
        parser.error("--mgmt-ipv6-gw requires --mgmt-ipv6-static")

    if getattr(args, "mgmt_ipv6_gw_vrf", None) and not getattr(
        args, "mgmt_ipv6_gw", None
    ):
        parser.error("--mgmt-ipv6-gw-vrf requires --mgmt-ipv6-gw")

    if v6_static:
        if not getattr(args, "enable_mgmt", False):
            parser.error(
                "IPv6 OOB flags (--mgmt-ipv6-static) require --mgmt"
            )
        mgmt_vrf = getattr(args, "mgmt_vrf", None)
        if mgmt_vrf and str(mgmt_vrf).lower() == "global":
            mgmt_vrf = None
        if not mgmt_vrf:
            parser.error(
                "IPv6 OOB requires a named --mgmt-vrf (not global routing table)"
            )
        if not getattr(args, "mgmt_ipv6_cidr", None):
            parser.error("--mgmt-ipv6-static requires --mgmt-ipv6-cidr <prefix>/64")
        from ipaddress import IPv6Address, IPv6Network

        try:
            IPv6Network(args.mgmt_ipv6_cidr, strict=False)
        except ValueError as exc:
            parser.error(f"Invalid --mgmt-ipv6-cidr: {exc}")
        if getattr(args, "mgmt_ipv6_gw", None):
            try:
                IPv6Address(args.mgmt_ipv6_gw)
            except ValueError as exc:
                parser.error(f"Invalid --mgmt-ipv6-gw: {exc}")
        return

    node_count = int(getattr(args, "nodes", 0) or 0)
    if (
        _mgmt_uses_ipv4_oob(args)
        and node_count >= MGMT_IPV4_OOB_NODE_LIMIT
    ):
        parser.error(
            f"With --mgmt and {node_count} nodes, IPv4 OOB (ip address dhcp or static "
            f"addresses from --mgmt-cidr) exhausts the shared management bridge and can "
            f"destabilize the lab. Use --mgmt-ipv6-dhcp or --mgmt-ipv6-slaac with a named "
            f"--mgmt-vrf (and --mgmt-bridge for external RA/DHCPv6) for IPv6-only OOB "
            f"at scale."
        )
    if not ipv6_mode:
        if getattr(args, "mgmt_ipv6_cidr", None):
            from ipaddress import IPv6Network

            try:
                IPv6Network(args.mgmt_ipv6_cidr, strict=False)
            except ValueError as exc:
                parser.error(f"Invalid --mgmt-ipv6-cidr: {exc}")
        return
    if not getattr(args, "enable_mgmt", False):
        parser.error(
            "IPv6 OOB flags (--mgmt-ipv6-dhcp, --mgmt-ipv6-slaac, "
            "--mgmt-ipv6-mode, --mgmt-ipv6-static) require --mgmt"
        )
    mgmt_vrf = getattr(args, "mgmt_vrf", None)
    if mgmt_vrf and str(mgmt_vrf).lower() == "global":
        mgmt_vrf = None
    if not mgmt_vrf:
        parser.error(
            "IPv6 OOB requires a named --mgmt-vrf (not global routing table)"
        )
    if getattr(args, "mgmt_ipv6_cidr", None):
        from ipaddress import IPv6Network

        try:
            IPv6Network(args.mgmt_ipv6_cidr, strict=False)
        except ValueError as exc:
            parser.error(f"Invalid --mgmt-ipv6-cidr: {exc}")


def validate_cml2_lifecycle_guardrails(args, parser):
    """Fail-fast guardrails for CML2 Terraform lifecycle scaffold generation."""
    if not getattr(args, "terraform_cml2", False):
        return
    if not getattr(args, "offline_yaml", None):
        parser.error("--terraform-cml2 requires --offline-yaml FILE (offline generation path)")
    if (
        getattr(args, "do_import", False)
        or getattr(args, "import_yaml", None)
        or getattr(args, "up", None)
    ):
        parser.error(
            "--terraform-cml2 requires local offline generation; "
            "import workflow flags are not supported (--import/--import-yaml/--up)"
        )
    if getattr(args, "yaml_output", None):
        parser.error(
            "--terraform-cml2 requires local offline generation; "
            "use --offline-yaml instead of --yaml online export"
        )


def normalize_template_inputs(args):
    """Normalize template aliases and align device-template defaults."""
    template = str(getattr(args, "template", "") or "").strip()
    template_lower = template.lower()

    aliases = {
        "crsv": "csr1000v",
    }
    resolved_template = aliases.get(template_lower, template_lower)
    if resolved_template:
        args.template = resolved_template

    dev_template = str(getattr(args, "dev_template", "iosv") or "iosv").strip().lower()

    # If user selected a CSR template and did not explicitly override the
    # default node definition, align to csr1000v automatically.
    if resolved_template == "csr1000v" and dev_template == "iosv":
        args.dev_template = "csr1000v"
    elif resolved_template.startswith("csr-") and dev_template == "iosv":
        args.dev_template = "csr1000v"
    else:
        args.dev_template = dev_template


def create_argparser(parser_class=argparse.ArgumentParser):
    """create the argparser for topogen"""
    parser = parser_class(
        prog=topogen.__name__, description=topogen.__description__
    )
    is_gooey = getattr(parser_class, "__name__", "") == "GooeyParser"
    config_settings = parser.add_argument_group("configuration")

    config_settings.add_argument(
        "-c",
        "--config",
        dest="configfile",
        help="Use the configuration from this file, defaults to %(default)s",
        default="config.toml",
    )
    config_settings.add_argument(
        "-w",
        "--write",
        dest="writeconfig",
        action="store_true",
        help="Write the default configuration to a file and exit",
        default=False,
    )
    config_settings.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {topogen.__version__}"
    )
    config_settings.add_argument(
        "-l",
        "--loglevel",
        type=str,
        default=os.environ.get("LOG_LEVEL", "WARN"),
        help="DEBUG, INFO, WARN, ERROR, CRITICAL, defaults to %(default)s",
    )
    config_settings.add_argument(
        "-p",
        "--progress",
        action="store_true",
        help="show a progress bar",
    )
    config_settings.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress non-essential output (INFO/WARN); only errors and final result",
    )

    parser.add_argument(
        "--ca",
        dest="cafile",
        help="Use the CA certificate from this file (PEM format), defaults to %(default)s",
        default="ca.pem",
    )
    parser.add_argument(
        "-i",
        "--insecure",
        action="store_true",
        help="If no CA provided, do not verify TLS (insecure!)",
        default=False,
    )
    parser.add_argument(
        "-d",
        "--distance",
        type=int,
        default=200,
        help="Node distance, default %(default)d",
    )
    parser.add_argument(
        "-L",
        "--labname",
        type=str,
        default=None,
        help='Lab name to create, default "topogen lab"',
    )
    parser.add_argument(
        "-R",
        "--remark",
        type=str,
        default=None,
        help="Add a custom remark/note to the lab description (optional)",
    )
    if is_gooey:
        parser.add_argument(
            "-T",
            "--template",
            type=str,
            choices=get_templates(),
            help='Template name to use, defaults to "%(default)s"',
            default="iosv",
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "-T",
            "--template",
            type=str,
            help='Template name to use, defaults to "%(default)s"',
            default="iosv",
        )
    if is_gooey:
        parser.add_argument(
            "--device-template",
            dest="dev_template",
            type=str,
            choices=("iosv", "csr1000v", "iol", "lxc"),
            default="iosv",
            help='CML node definition to use for routers (e.g., iosv, iol, lxc). Defaults to "%(default)s"',
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "--device-template",
            dest="dev_template",
            type=str,
            default="iosv",
            help='CML node definition to use for routers (e.g., iosv, iol, lxc). Defaults to "%(default)s"',
        )
    parser.add_argument(
        "--list-templates",
        dest="listtemplates",
        action="store_true",
        help="List all available templates",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=("nx", "simple", "flat", "flat-pair", "dmvpn"),
        default="simple",
        help='mode of operation, default is "%(default)s"',
    )

    parser.add_argument(
        "--dmvpn-phase",
        dest="dmvpn_phase",
        type=int,
        choices=(2, 3),
        default=2,
        help='DMVPN phase (2 or 3), default %(default)d',
    )
    parser.add_argument(
        "--dmvpn-routing",
        dest="dmvpn_routing",
        type=str,
        choices=("eigrp", "ospf"),
        default="eigrp",
        help='Routing protocol over DMVPN tunnel, default "%(default)s"',
    )
    parser.add_argument(
        "--eigrp-stub",
        dest="eigrp_stub",
        action="store_true",
        default=False,
        help="Enable EIGRP stub (connected summary) on selected routers (DMVPN flat-pair: even routers)",
    )
    parser.add_argument(
        "--dmvpn-security",
        dest="dmvpn_security",
        type=str,
        choices=("none", "ikev2-psk", "ikev2-pki", "ikev2-rsa"),
        default="none",
        help='DMVPN security: none, ikev2-psk (requires --dmvpn-psk), ikev2-pki (requires --pki), ikev2-rsa (PKI/cert, requires --dmvpn-trustpoint), default "%(default)s"',
    )
    parser.add_argument(
        "--dmvpn-trustpoint",
        dest="dmvpn_trustpoint",
        type=str,
        default="CA-ROOT-SELF",
        help="DMVPN IKEv2 PKI trustpoint name (used when --dmvpn-security ikev2-rsa), default CA-ROOT-SELF",
    )
    parser.add_argument(
        "--dmvpn-psk",
        dest="dmvpn_psk",
        type=str,
        default=None,
        help="DMVPN IKEv2 pre-shared key (used when --dmvpn-security ikev2-psk)",
    )
    if is_gooey:
        parser.add_argument(
            "--dmvpn-underlay",
            dest="dmvpn_underlay",
            type=str,
            choices=("flat", "flat-pair"),
            default="flat",
            help='DMVPN underlay topology, default "%(default)s"',
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "--dmvpn-underlay",
            dest="dmvpn_underlay",
            type=str,
            choices=("flat", "flat-pair"),
            default="flat",
            help='DMVPN underlay topology, default "%(default)s"',
        )
    parser.add_argument(
        "--dmvpn-nbma-cidr",
        dest="dmvpn_nbma_cidr",
        type=str,
        default="10.10.0.0/16",
        help='NBMA underlay CIDR for DMVPN WAN segment, default "%(default)s"',
    )
    parser.add_argument(
        "--dmvpn-tunnel-cidr",
        dest="dmvpn_tunnel_cidr",
        type=str,
        default="172.20.0.0/16",
        help='Tunnel overlay CIDR for DMVPN Tunnel0 addressing, default "%(default)s"',
    )
    if is_gooey:
        parser.add_argument(
            "--dmvpn-tunnel-key",
            dest="dmvpn_tunnel_key",
            type=int,
            default=10,
            help='DMVPN Tunnel0 key (GRE tunnel key), default %(default)d',
            gooey_options={"widget": "IntegerField"},
        )
        parser.add_argument(
            "--dmvpn-hubs",
            dest="dmvpn_hubs",
            type=str,
            default=None,
            help="Comma-separated router numbers to act as DMVPN hubs (e.g., 1,21,41). When set, the nodes argument is interpreted as total routers.",
            gooey_options={"widget": "TextField"},
        )
    else:
        parser.add_argument(
            "--dmvpn-tunnel-key",
            dest="dmvpn_tunnel_key",
            type=int,
            default=10,
            help='DMVPN Tunnel0 key (GRE tunnel key), default %(default)d',
        )
        parser.add_argument(
            "--dmvpn-hubs",
            dest="dmvpn_hubs",
            type=str,
            default=None,
            help="Comma-separated router numbers to act as DMVPN hubs (e.g., 1,21,41). When set, the nodes argument is interpreted as total routers.",
        )
    parser.add_argument(
        "--flat-group-size",
        dest="flat_group_size",
        type=int,
        default=20,
        help="Routers per unmanaged switch when using flat mode, default %(default)d",
    )
    parser.add_argument(
        "--loopback-255",
        dest="loopback_255",
        action="store_true",
        help="Use 10.255.C.D/32 for Loopback0 addressing in flat mode (default is 10.20.C.D/32)",
    )
    parser.add_argument(
        "--gi0-zero",
        dest="gi0_zero",
        action="store_true",
        help="Use 10.0.C.D/16 for Gi0/0 addressing in flat mode (default is 10.10.C.D/16)",
    )
    parser.add_argument(
        "--vrf",
        dest="enable_vrf",
        action="store_true",
        help="Enable VRF configuration (applies to flat-pair odd-router Gi0/1 when combined with --pair-vrf)",
        default=False,
    )
    parser.add_argument(
        "--pair-vrf",
        dest="pair_vrf",
        type=str,
        default="tenant",
        help='VRF name to apply to the flat-pair odd-router Gi0/1 (pair link), default "%(default)s"',
    )
    parser.add_argument(
        "--dmvpn-fvrf",
        dest="dmvpn_fvrf",
        type=str,
        default=None,
        help='Enable Front Door VRF: place the NBMA interface into the named transport VRF (e.g. INTERNET). Adds tunnel vrf, match fvrf to IKEv2, and ip tcp adjust-mss 1360 on Tunnel0.',
    )
    parser.add_argument(
        "--dmvpn-ipsec-mode",
        dest="dmvpn_ipsec_mode",
        type=str,
        choices=("transport", "tunnel"),
        default="transport",
        help='DMVPN IPsec transform-set mode: transport (default, recommended for GRE) or tunnel, default "%(default)s"',
    )
    parser.add_argument(
        "--mgmt",
        dest="enable_mgmt",
        action="store_true",
        default=False,
        help=(
            "Enable OOB management fabric (SWoob, router mgmt interfaces, optional VRF). "
            "Addressing is separate: --mgmt-ipv4-dhcp and/or --mgmt-ipv6-dhcp / --mgmt-ipv6-slaac."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv4-dhcp",
        dest="mgmt_ipv4_dhcp",
        action="store_true",
        default=False,
        help=(
            "IPv4 DHCP on the OOB interface (ip address dhcp). With --mgmt-bridge and no "
            "other addressing flags, IPv4 DHCP is implied for backward compatibility."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv6-dhcp",
        dest="mgmt_ipv6_dhcp",
        action="store_true",
        default=False,
        help=(
            "IPv6 DHCPv6 on the OOB interface (ipv6 address dhcp). IPv6-only unless "
            "combined with --mgmt-ipv4-dhcp. Requires --mgmt and named --mgmt-vrf."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv6-slaac",
        dest="mgmt_ipv6_slaac",
        action="store_true",
        default=False,
        help=(
            "IPv6 SLAAC on the OOB interface (ipv6 address autoconfig). IPv6-only unless "
            "combined with --mgmt-ipv4-dhcp. Requires --mgmt and named --mgmt-vrf."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv6-static",
        dest="mgmt_ipv6_static",
        action="store_true",
        default=False,
        help=(
            "Static global IPv6 on OOB (ipv6 address <prefix>). Requires --mgmt, named "
            "--mgmt-vrf, and --mgmt-ipv6-cidr /64. Routers are IPv6 hosts only (no "
            "ipv6 unicast-routing)."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv6-static-link-local",
        dest="mgmt_ipv6_static_link_local",
        action="store_true",
        default=False,
        help=(
            "With --mgmt-ipv6-static, --mgmt-ipv6-slaac, or --mgmt-ipv6-dhcp, also render "
            "loopback-derived fe80::FF10:… link-local on OOB (and other IPv6-enabled "
            "interfaces). IOS uses the static link-local as the IID source for SLAAC globals."
        ),
    )
    parser.add_argument(
        "--mgmt-cidr",
        dest="mgmt_cidr",
        type=str,
        default="10.254.0.0/16",
        help='Management network CIDR, default "%(default)s"',
    )
    parser.add_argument(
        "--mgmt-gw",
        dest="mgmt_gw",
        type=str,
        default=None,
        help="Management network gateway IP (optional); adds a default route in the mgmt VRF if set",
    )
    parser.add_argument(
        "--mgmt-ipv6-gw",
        dest="mgmt_ipv6_gw",
        type=str,
        default=None,
        help=(
            "Optional IPv6 default-route next hop in the mgmt VRF with "
            "--mgmt-ipv6-static (ipv6 route vrf … ::/0 …)."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv6-gw-vrf",
        dest="mgmt_ipv6_gw_vrf",
        type=str,
        default=None,
        help=(
            "Optional VRF for --mgmt-ipv6-gw (default: same as --mgmt-vrf). "
            "Use 'global' for ipv6 route ::/0 without a VRF clause."
        ),
    )
    parser.add_argument(
        "--mgmt-slot",
        dest="mgmt_slot",
        type=int,
        default=5,
        help="Interface slot for management (IOSv Gi0/N, CSR GiN), default %(default)d",
    )
    parser.add_argument(
        "--mgmt-vrf",
        dest="mgmt_vrf",
        type=str,
        default="Mgmt-vrf",
        help='VRF name for management interface (default: "%(default)s"); use "global" for global routing table',
    )
    parser.add_argument(
        "--mgmt-bridge",
        dest="mgmt_bridge",
        action="store_true",
        default=False,
        help="Add external-connector to bridge OOB management network to external network (requires --mgmt)",
    )
    parser.add_argument(
        "--mgmt-ipv6-mode",
        dest="mgmt_ipv6_mode",
        type=str,
        choices=("slaac", "dhcpv6"),
        default=None,
        help=(
            "Legacy alias for --mgmt-ipv6-slaac (slaac) or --mgmt-ipv6-dhcp (dhcpv6). "
            "Prefer the explicit flags for new labs."
        ),
    )
    parser.add_argument(
        "--mgmt-ipv6-cidr",
        dest="mgmt_ipv6_cidr",
        type=str,
        default=None,
        help=(
            "Required with --mgmt-ipv6-static (/64 anchor for FF10 embedding). "
            "Optional metadata hint for --mgmt-ipv6-dhcp / --mgmt-ipv6-slaac "
            "(e.g. fd80::/64 or 2001:db8:1:2::/64)."
        ),
    )
    parser.add_argument(
        "--ntp",
        dest="ntp_server",
        type=str,
        default=None,
        help="NTP server IP address (optional)",
    )
    parser.add_argument(
        "--ntp-vrf",
        dest="ntp_vrf",
        type=str,
        default=None,
        help="VRF for NTP (e.g. Mgmt-vrf). Omit for global. With --mgmt, default is mgmt VRF unless --ntp-inband.",
    )
    parser.add_argument(
        "--ntp-inband",
        dest="ntp_inband",
        action="store_true",
        default=False,
        help="Put --ntp server in global (inband); no VRF. Use when CA is NTP server on data network.",
    )
    parser.add_argument(
        "--ntp-oob",
        dest="ntp_oob_server",
        type=str,
        default=None,
        help="Optional second NTP server in mgmt VRF (e.g. external NTP). Use with --mgmt.",
    )
    parser.add_argument(
        "--pki",
        dest="pki_enabled",
        action="store_true",
        default=False,
        help="Enable PKI Root CA (adds CA-ROOT router for certificate services)",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        default=False,
        help="Enable config archive and rundiff alias on routers (archive log config, path flash:, write-memory)",
    )
    parser.add_argument(
        "--getvpn",
        dest="getvpn_enabled",
        action="store_true",
        default=False,
        help="Enable GET VPN (Group Encrypted Transport VPN) with a Key Server and all routers as Group Members (requires --pki)",
    )
    parser.add_argument(
        "--getvpn-group-id",
        dest="getvpn_group_id",
        type=int,
        default=1,
        help="GET VPN GDOI/GKM group identity number, default %(default)d",
    )
    parser.add_argument(
        "--getvpn-rekey-interval",
        dest="getvpn_rekey_interval",
        type=int,
        default=86400,
        help="GET VPN rekey lifetime in seconds, default %(default)d (24h)",
    )
    if is_gooey:
        parser.add_argument(
            "--getvpn-protocol",
            dest="getvpn_protocol",
            type=str,
            choices=("gdoi", "gikev2"),
            default="gdoi",
            help='GET VPN control plane protocol: gdoi (ISAKMP/IKEv1) or gikev2 (IKEv2), default "%(default)s"',
            gooey_options={"widget": "Dropdown"},
        )
    else:
        parser.add_argument(
            "--getvpn-protocol",
            dest="getvpn_protocol",
            type=str,
            choices=("gdoi", "gikev2"),
            default="gdoi",
            help='GET VPN control plane protocol: gdoi (ISAKMP/IKEv1) or gikev2 (IKEv2), default "%(default)s"',
        )
    parser.add_argument(
        "--staging",
        dest="staging",
        action="store_true",
        default=False,
        help="Enable CML 2.10 node staging for boot ordering (requires --cml-version >= 0.3.1). "
        "Also enabled automatically when --pki is used unless --no-staging is set.",
    )
    parser.add_argument(
        "--no-staging",
        dest="no_staging",
        action="store_true",
        default=False,
        help="Disable node staging even when --pki would auto-enable it; also disables --staging",
    )
    parser.add_argument(
        "--no-abort-on-failure",
        dest="staging_no_abort",
        action="store_true",
        default=False,
        help="With --staging, disable abort-on-failure so all nodes attempt to boot even if a higher-priority node fails",
    )
    parser.add_argument(
        "--pki-enroll",
        dest="pki_enroll_mode",
        type=str,
        choices=["scep", "cli"],
        default="scep",
        help="PKI enrollment mode: scep (auto via SCEP) or cli (manual CLI enrollment for external CA)",
    )
    parser.add_argument(
        "--start",
        dest="start_lab",
        action="store_true",
        default=False,
        help="Automatically start the lab after creation",
    )
    if is_gooey:
        parser.add_argument(
            "--yaml",
            dest="yaml_output",
            metavar="ONLINE_EXPORT_YAML_FILE",
            type=str,
            help="Export the created lab to a YAML file at ONLINE_EXPORT_YAML_FILE",
            gooey_options={"widget": "FileSaver"},
        )
        parser.add_argument(
            "--offline-yaml",
            dest="offline_yaml",
            metavar="OFFLINE_YAML_FILE",
            type=str,
            help="Generate a CML-compatible YAML locally (no controller required)",
            gooey_options={"widget": "FileSaver"},
        )
    else:
        parser.add_argument(
            "--yaml",
            dest="yaml_output",
            metavar="FILE",
            type=str,
            help="Export the created lab to a YAML file at FILE",
        )
        parser.add_argument(
            "--offline-yaml",
            dest="offline_yaml",
            metavar="FILE",
            type=str,
            help="Generate a CML-compatible YAML locally (no controller required)",
        )
    parser.add_argument(
        "--nac",
        dest="nac",
        action="store_true",
        default=False,
        help="Enable NaC artifacts for offline YAML generation (requires IOS-XE router templates)",
    )
    parser.add_argument(
        "--bootstrap",
        dest="bootstrap",
        action="store_true",
        default=False,
        help="Thin day-0 router config for --nac (mgmt reachability and RESTCONF only; requires --mgmt)",
    )
    parser.add_argument(
        "--terraform-cml2",
        "--cml2",
        dest="terraform_cml2",
        action="store_true",
        default=False,
        help="Enable Terraform lifecycle scaffold generation for offline CML2 labs",
    )
    parser.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        default=False,
        help="Allow overwriting an existing output file when using --offline-yaml",
    )
    parser.add_argument(
        "--intent-spot",
        dest="intent_spot",
        action="store_true",
        default=False,
        help="Add INTENT-SPOT debug unmanaged_switch at intent annotation coordinates for "
        "visual QA in CML Workbench (no router license; online and offline; not for production)",
    )
    parser.add_argument(
        "--import-yaml",
        dest="import_yaml",
        metavar="FILE",
        type=str,
        help="Path to existing offline YAML to import (skip generation); use with --import",
    )
    parser.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        default=False,
        help="Import the generated or specified YAML into CML (requires --offline-yaml or --import-yaml)",
    )
    parser.add_argument(
        "--up",
        dest="up",
        metavar="FILE",
        type=str,
        help="Shorthand for --import-yaml FILE --import --start (import YAML to CML and start lab)",
    )
    parser.add_argument(
        "--print-up-cmd",
        dest="print_up_cmd",
        action="store_true",
        default=False,
        help="With --offline-yaml, print the topogen --up <file> command to run later",
    )
    parser.add_argument(
        "--cml-server",
        dest="cml_server",
        type=valid_cml_server,
        default=None,
        metavar="MAJOR.MINOR",
        help="Target CML controller version (e.g. 2.10). Sets lab YAML schema when "
        "--cml-version is omitted; explicit --cml-version always wins.",
    )
    parser.add_argument(
        "--cml-version",
        dest="cml_version",
        type=str,
        default="0.3.0",
        choices=[
            "0.0.1",
            "0.0.2",
            "0.0.3",
            "0.0.4",
            "0.0.5",
            "0.1.0",
            "0.2.0",
            "0.2.1",
            "0.2.2",
            "0.3.0",
            "0.3.1",
        ],
        help="CML lab schema version for offline YAML (authoritative; CML 2.5: 0.2.0, "
        "2.6: 0.2.1, 2.7: 0.2.2, 2.8/2.9: 0.3.0, 2.10: 0.3.1). Use --cml-server as a "
        "convenience when schema is not set explicitly.",
    )
    parser.add_argument(
        "nodes",
        nargs="?",
        type=valid_node_count,
        help="Number of nodes to generate (2-1000; --nac offline generation also allows 1 where supported by the selected mode)",
    )
    parser.add_argument(
        "--allow-oversubscribe",
        dest="allow_oversubscribe",
        action="store_true",
        help="Bypass the recommended 520-node lab limit (use with caution)",
    )
    parser.add_argument(
        "--blank",
        dest="blank",
        action="store_true",
        default=False,
        help="Topology only: emit nodes and links but omit router configurations (enables CML Bootstrap Lab)",
    )
    return parser


def get_log_level(level_name: str) -> tuple[int, bool]:
    log_levels = {
        "CRITICAL": logging.CRITICAL,
        "ERROR": logging.ERROR,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "INFO": logging.INFO,
        "DEBUG": logging.DEBUG,
        "NOTSET": logging.NOTSET,
    }
    level_name = level_name.upper()
    if level_name in log_levels:
        return log_levels[level_name], False
    else:
        return logging.WARNING, True


def setup_logging(loglevel: str):
    """sets up the logging, takes the given loglevel and uses the custom,
    colorful log formatter
    """
    logging.basicConfig(level=logging.WARN)
    level, unknown_loglevel = get_log_level(loglevel)
    logging.root.setLevel(level)
    custom_formatter = CustomFormatter()
    for handler in logging.root.handlers:
        handler.setFormatter(custom_formatter)
    if unknown_loglevel:
        _LOGGER.warning("Unknown log level: %s", loglevel.upper())


def _cml_version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def resolve_staging_flags(args) -> None:
    """Apply PKI auto-staging defaults and CML version guardrails to args.staging (TG-165)."""
    if getattr(args, "no_staging", False):
        args.staging = False
    elif getattr(args, "pki_enabled", False) and not getattr(args, "staging", False):
        args.staging = True
        _LOGGER.warning(
            "Enabling node staging for --pki so CA-ROOT boots before enrolling routers. "
            "Pass --no-staging to disable."
        )

    if getattr(args, "staging", False):
        if _cml_version_tuple(getattr(args, "cml_version", "0.3.0")) < (0, 3, 1):
            _LOGGER.warning(
                "--staging ignored: requires CML 2.10 "
                "(--cml-server 2.10 or --cml-version 0.3.1)"
            )
            args.staging = False
            if getattr(args, "pki_enabled", False) and not getattr(args, "no_staging", False):
                _LOGGER.warning(
                    "PKI lab will boot all nodes simultaneously; CA may not be ready for enrollment."
                )


def main():
    """main function, returns 0 on success, 1 otherwise"""
    if len(sys.argv) > 1 and sys.argv[1] == "sync-nac-mgmt":
        from topogen.nac_mgmt_sync import main as sync_nac_mgmt_main

        return sync_nac_mgmt_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "provision-cml-user":
        from topogen.cml_user import main as provision_cml_user_main

        return provision_cml_user_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "capture-lab-evidence":
        from topogen.cml_lab_evidence import main as capture_lab_evidence_main

        return capture_lab_evidence_main(sys.argv[2:])

    if len(sys.argv) > 1 and sys.argv[1] == "finalize-ci-lab":
        from topogen.cml_ci_finalize import main as finalize_ci_lab_main

        return finalize_ci_lab_main(sys.argv[2:])

    parser = create_argparser()
    args = parser.parse_args()
    normalize_template_inputs(args)
    # Default lab name: when -L is not provided (None), derive from context.
    # --offline-yaml: use filename stem. --import-yaml / --up: leave None (let YAML title: take effect). Online: "topogen lab".
    if args.labname is None:
        if getattr(args, "offline_yaml", None):
            args.labname = os.path.splitext(os.path.basename(args.offline_yaml))[0]
        elif not getattr(args, "import_yaml", None) and not getattr(args, "up", None):
            args.labname = "topogen lab"
    if getattr(args, "quiet", False):
        args.loglevel = "ERROR"
    setup_logging(args.loglevel)

    def parse_dmvpn_hubs(value: str | None) -> list[int] | None:
        if value is None:
            return None
        raw = [p.strip() for p in str(value).split(",") if p.strip()]
        if not raw:
            parser.error("Invalid --dmvpn-hubs: must provide at least one hub router number")
        hubs: list[int] = []
        for p in raw:
            try:
                hubs.append(int(p))
            except ValueError:
                parser.error(f"Invalid --dmvpn-hubs entry '{p}': must be an integer")
        if len(set(hubs)) != len(hubs):
            parser.error("Invalid --dmvpn-hubs: duplicate hub numbers are not allowed")
        return hubs

    cfg = topogen.Config.load(args.configfile)
    if args.writeconfig:
        cfg.save(args.configfile)
        return 0

    if args.insecure:
        args.cafile = None

    if args.listtemplates:
        print("Available templates: ", ", ".join(get_templates()))
        return 0

    try:
        validate_nodes_for_mode(args, parser)
        args.dmvpn_hubs_list = parse_dmvpn_hubs(getattr(args, "dmvpn_hubs", None))
        validate_nac_mvp_guardrails(args, parser)
        validate_bootstrap_guardrails(args, parser)
        validate_cml2_lifecycle_guardrails(args, parser)

        if args.mode == "dmvpn" and getattr(args, "dmvpn_security", "none") == "ikev2-psk":
            psk = getattr(args, "dmvpn_psk", None)
            if not psk or not str(psk).strip():
                parser.error("--dmvpn-security ikev2-psk requires --dmvpn-psk <key>")
        if args.mode == "dmvpn" and getattr(args, "dmvpn_security", "none") == "ikev2-pki":
            if not getattr(args, "pki_enabled", False):
                parser.error("--dmvpn-security ikev2-pki requires --pki")
        if args.mode == "dmvpn" and getattr(args, "dmvpn_security", "none") == "ikev2-rsa":
            if not getattr(args, "dmvpn_trustpoint", "").strip():
                parser.error("--dmvpn-security ikev2-rsa requires --dmvpn-trustpoint (e.g. CA-ROOT-SELF)")

        # DMVPN flat-pair uses odd routers as DMVPN endpoints. If hubs are not
        # provided, default to the first 3 endpoint routers (R1,R3,R5), or fewer
        # if the lab is smaller.
        if args.mode == "dmvpn" and getattr(args, "dmvpn_underlay", "flat") == "flat-pair":
            if getattr(args, "dmvpn_hubs_list", None) is None:
                if not args.nodes:
                    parser.error("DMVPN requires nodes argument")
                max_odd_rnum = int(args.nodes) if (int(args.nodes) % 2) == 1 else (int(args.nodes) - 1)
                default_hubs = [h for h in (1, 3, 5) if h <= max_odd_rnum]
                args.dmvpn_hubs_list = default_hubs
                args.dmvpn_hubs = ",".join(str(h) for h in default_hubs)

        # Licensing / capacity guidance: soft cap at 520 unless bypassed
        if args.nodes and not getattr(args, "allow_oversubscribe", False) and args.nodes > 520:
            parser.error(
                f"nodes={args.nodes} exceeds the recommended maximum of 520 for typical enterprise licenses. "
                "Use --allow-oversubscribe to bypass this check if your environment supports more."
            )

        if args.mode == "dmvpn" and getattr(args, "dmvpn_hubs_list", None):
            if not args.nodes:
                parser.error("DMVPN requires nodes argument")
            hubs = args.dmvpn_hubs_list
            underlay = getattr(args, "dmvpn_underlay", "flat")
            if underlay == "flat-pair":
                total_routers = int(args.nodes)
                max_odd_rnum = total_routers if (total_routers % 2) == 1 else (total_routers - 1)
                out_of_range = [h for h in hubs if h < 1 or h > max_odd_rnum]
                if out_of_range:
                    bad = ",".join(str(h) for h in out_of_range)
                    parser.error(
                        "Invalid --dmvpn-hubs: hub router(s) "
                        f"{bad} do not exist as DMVPN endpoints in flat-pair (endpoints are odd routers R1..R{max_odd_rnum}; total routers R1..R{total_routers})"
                    )
            else:
                max_router = int(args.nodes)
                out_of_range = [h for h in hubs if h < 1 or h > max_router]
                if out_of_range:
                    bad = ",".join(str(h) for h in out_of_range)
                    parser.error(
                        f"Invalid --dmvpn-hubs: hub router(s) {bad} do not exist (lab has R1..R{max_router})"
                    )
        if args.mode == "dmvpn" and getattr(args, "dmvpn_underlay", "flat") == "flat-pair":
            hubs = getattr(args, "dmvpn_hubs_list", None)
            if hubs:
                even_hubs = [h for h in hubs if (h % 2) == 0]
                if even_hubs:
                    bad = ",".join(str(h) for h in even_hubs)
                    parser.error(
                        f"Invalid --dmvpn-hubs: hub router(s) {bad} are even-numbered, but DMVPN underlay 'flat-pair' uses odd routers as DMVPN endpoints"
                    )
        # Early validation for flat mode port assumptions
        if args.mode == "flat":
            if args.flat_group_size + 1 > 32:
                parser.error(
                    f"Invalid --flat-group-size {args.flat_group_size}: requires {args.flat_group_size + 1} ports per access switch (>32). Reduce --flat-group-size."
                )
            if args.nodes:
                from math import ceil

                if ceil(args.nodes / args.flat_group_size) > 32:
                    parser.error(
                        f"Invalid combination: nodes={args.nodes}, group_size={args.flat_group_size} requires more than 32 access switches (core ports). Increase --flat-group-size."
                    )
        # Validate GET VPN flags
        if getattr(args, "getvpn_enabled", False):
            if not getattr(args, "pki_enabled", False):
                parser.error("--getvpn requires --pki (PKI certificate authentication)")
            if args.mode not in ("flat", "flat-pair", "dmvpn"):
                parser.error("--getvpn requires mode flat, flat-pair, or dmvpn")

        resolve_cml_server_version(args, sys.argv)
        resolve_staging_flags(args)

        # Validate mgmt flags
        if getattr(args, "enable_mgmt", False):
            from ipaddress import IPv4Network
            try:
                IPv4Network(args.mgmt_cidr, strict=False)
            except ValueError as exc:
                parser.error(f"Invalid --mgmt-cidr: {exc}")
            if args.mgmt_gw:
                from ipaddress import IPv4Address
                try:
                    IPv4Address(args.mgmt_gw)
                except ValueError as exc:
                    parser.error(f"Invalid --mgmt-gw: {exc}")
            # Normalize mgmt_vrf: treat "global" or empty as None (global table)
            if args.mgmt_vrf and args.mgmt_vrf.lower() == "global":
                args.mgmt_vrf = None
        # Validate mgmt-bridge requires mgmt
        if getattr(args, "mgmt_bridge", False) and not getattr(args, "enable_mgmt", False):
            parser.error("--mgmt-bridge requires --mgmt to be enabled")
        finalize_mgmt_addressing_args(args, parser)
        validate_mgmt_ipv6_guardrails(args, parser)
        # Validate NTP flags
        if getattr(args, "ntp_server", None):
            from ipaddress import IPv4Address
            try:
                IPv4Address(args.ntp_server)
            except ValueError as exc:
                parser.error(f"Invalid --ntp: {exc}")
            # If ntp_vrf not set and OOB (--mgmt) is enabled, inherit mgmt_vrf (unless --ntp-inband).
            # Without --mgmt, NTP is inband so do not set ntp_vrf (no "ntp server vrf Mgmt-vrf").
            if not getattr(args, "ntp_inband", False):
                if (
                    not getattr(args, "ntp_vrf", None)
                    and getattr(args, "enable_mgmt", False)
                    and getattr(args, "mgmt_vrf", None)
                ):
                    args.ntp_vrf = args.mgmt_vrf
            else:
                args.ntp_vrf = None  # inband: no VRF for --ntp
            if getattr(args, "ntp_oob_server", None):
                from ipaddress import IPv4Address
                try:
                    IPv4Address(args.ntp_oob_server)
                except ValueError as exc:
                    parser.error(f"Invalid --ntp-oob: {exc}")
        # --up is shorthand for --import-yaml FILE --import --start (ignore empty string from GUI)
        up_val = getattr(args, "up", None)
        if up_val and str(up_val).strip():
            args.import_yaml = up_val.strip()
            args.do_import = True
            args.start_lab = True

        # --import requires a YAML source
        if getattr(args, "do_import", False):
            if not (getattr(args, "offline_yaml", None) or getattr(args, "import_yaml", None)):
                parser.error("--import requires --offline-yaml or --import-yaml")

        # Warn if --start used with --offline-yaml but not importing (start would do nothing)
        if (
            getattr(args, "start_lab", False)
            and getattr(args, "offline_yaml", None)
            and not getattr(args, "do_import", False)
        ):
            _LOGGER.warning("--start ignored: offline mode (--offline-yaml) does not create a lab on a controller; use --import to import then start")

        # Validate --blank: reject flags that create special nodes or only affect config content
        if getattr(args, "blank", False):
            if getattr(args, "bootstrap", False):
                parser.error("--blank cannot be combined with --bootstrap")
            if args.mode == "dmvpn":
                parser.error("--blank is not supported with DMVPN mode (use flat, flat-pair, simple, or nx)")
            if getattr(args, "pki_enabled", False):
                parser.error("--blank cannot be combined with --pki (Bootstrap Lab cannot generate PKI configs)")
            if getattr(args, "getvpn_enabled", False):
                parser.error("--blank cannot be combined with --getvpn (Bootstrap Lab cannot generate GET VPN configs)")
            _blank_rejected: list[str] = []
            if getattr(args, "ntp_server", None):
                _blank_rejected.append("--ntp")
            if getattr(args, "ntp_vrf", None):
                _blank_rejected.append("--ntp-vrf")
            if getattr(args, "ntp_inband", False):
                _blank_rejected.append("--ntp-inband")
            if getattr(args, "ntp_oob_server", None):
                _blank_rejected.append("--ntp-oob")
            if getattr(args, "archive", False):
                _blank_rejected.append("--archive")
            if getattr(args, "eigrp_stub", False):
                _blank_rejected.append("--eigrp-stub")
            if getattr(args, "enable_vrf", False):
                _blank_rejected.append("--vrf")
            if getattr(args, "pair_vrf", None) and args.pair_vrf != "tenant":
                _blank_rejected.append("--pair-vrf")
            if _blank_rejected:
                parser.error(
                    f"--blank cannot be combined with {', '.join(_blank_rejected)} "
                    "(no configs are rendered)"
                )

        # Import-only path: existing YAML, no generation
        if getattr(args, "import_yaml", None) and getattr(args, "do_import", False):
            return Renderer.import_yaml_to_cml(args.import_yaml, args)

        # Offline YAML path: generate, then optionally import
        if getattr(args, "offline_yaml", None):
            if args.mode == "dmvpn":
                if getattr(args, "dmvpn_underlay", "flat") == "flat-pair":
                    retval = Renderer.offline_dmvpn_flat_pair_yaml(args, cfg)
                else:
                    retval = Renderer.offline_dmvpn_yaml(args, cfg)
            elif args.mode == "nx":
                retval = Renderer.offline_nx_yaml(args, cfg)
            elif args.mode == "simple":
                retval = Renderer.offline_simple_yaml(args, cfg)
            elif args.mode == "flat-pair":
                retval = Renderer.offline_flat_pair_yaml(args, cfg)
            else:
                retval = Renderer.offline_flat_yaml(args, cfg)
            if retval != 0:
                return retval
            if getattr(args, "do_import", False):
                return Renderer.import_yaml_to_cml(
                    args.offline_yaml, args, size_already_logged=True
                )
            if getattr(args, "print_up_cmd", False) and not getattr(args, "up", None):
                _LOGGER.warning(
                    "When you're ready: topogen --up %s",
                    args.offline_yaml.replace("\\", "/"),
                )
            return retval

        renderer = Renderer(args, cfg)
        # argparse ensures correct mode
        if args.mode == "simple":
            retval = renderer.render_node_sequence()
        elif args.mode == "nx":
            retval = renderer.render_node_network()
        elif args.mode == "flat":
            retval = renderer.render_flat_network()
        elif args.mode == "dmvpn":
            retval = renderer.render_dmvpn_network()
        else:  # args.mode == "flat-pair"
            retval = renderer.render_flat_pair_network()
    except TopogenError as exc:
        _LOGGER.error(exc)
        retval = 1
    return retval


if __name__ == "__main__":
    sys.exit(main())
