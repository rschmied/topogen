#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-13
#
# - Called by: scripts/run-csr-ipv6-matrix.ps1
# - Reads from: live CML lab via virl2_client / console SSH
# - Writes to: evidence JSON under out/TG-190-csr-matrix/
# - Calls into: virl2_client, optional SSH
"""Live CSR OOB validation on BOOTED labs (console CLI)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.cml_console_cli import exec_commands_via_cml_console  # noqa: E402
from topogen.nac_mgmt_sync import _cml_client  # noqa: E402

GLOBAL_V6 = re.compile(r"Global unicast address\(es\):\s*\n\s*([0-9a-f:]+)", re.I)
IPV4_DHCP_ON_GI5 = re.compile(r"GigabitEthernet5\s+(\d+\.\d+\.\d+\.\d+)\s+YES\s+DHCP", re.I)


def _expectations(scenario: str) -> dict[str, bool]:
    base = {
        "vrf_forwarding": True,
        "ipv6_dhcp_stanza": False,
        "ipv6_autoconfig_stanza": False,
        "ipv4_dhcp_stanza": False,
        "no_ip_address_stanza": False,
        "ipv6_enable_stanza": False,
        "require_global_v6": False,
        "require_ipv4_dhcp_lease": False,
        "forbid_global_v6": False,
    }
    if scenario in ("CSR-01", "CSR-06"):
        base.update(
            no_ip_address_stanza=True,
            ipv6_enable_stanza=True,
            ipv6_dhcp_stanza=True,
            require_global_v6=True,
            forbid_global_v6=False,
        )
    elif scenario in ("CSR-02", "CSR-07"):
        base.update(
            no_ip_address_stanza=True,
            ipv6_enable_stanza=True,
            ipv6_autoconfig_stanza=True,
            require_global_v6=True,
        )
    elif scenario == "CSR-03":
        base.update(
            ipv4_dhcp_stanza=True,
            ipv6_enable_stanza=True,
            ipv6_dhcp_stanza=True,
            require_global_v6=True,
            require_ipv4_dhcp_lease=True,
        )
    elif scenario == "CSR-04":
        base.update(
            ipv4_dhcp_stanza=True,
            ipv6_enable_stanza=False,
            require_ipv4_dhcp_lease=True,
            forbid_global_v6=True,
        )
    else:
        raise ValueError(f"unknown scenario {scenario}")
    return base


def validate_lab(lab_id: str, scenario: str, node_label: str = "R1") -> dict:
    lab = _cml_client().join_existing_lab(lab_id)
    node = next((n for n in lab.nodes() if n.label == node_label), None)
    if node is None:
        raise RuntimeError(f"{node_label} not found in lab {lab_id}")
    if str(node.state) != "BOOTED":
        raise RuntimeError(f"{node_label} state {node.state}, expected BOOTED")

    cli_out = exec_commands_via_cml_console(
        lab,
        node_label,
        "show run int GigabitEthernet5",
        "show ip interface brief | include GigabitEthernet5",
        "show ipv6 interface GigabitEthernet5",
    )

    exp = _expectations(scenario)
    run_section = cli_out.split("show ip interface brief")[0]
    checks: dict[str, bool] = {
        "vrf_forwarding": "vrf forwarding Mgmt-vrf" in run_section,
        "ipv4_dhcp_stanza": "ip address dhcp" in run_section,
        "ipv6_dhcp_stanza": "ipv6 address dhcp" in run_section,
        "ipv6_autoconfig_stanza": "ipv6 address autoconfig" in run_section,
        "no_ip_address_stanza": "no ip address" in run_section,
        "ipv6_enable_stanza": "ipv6 enable" in run_section,
    }

    m_v6 = GLOBAL_V6.search(cli_out)
    checks["global_v6_present"] = bool(m_v6)
    m_v4 = IPV4_DHCP_ON_GI5.search(cli_out)
    checks["ipv4_dhcp_lease"] = bool(m_v4)

    failures: list[str] = []
    for key, required in exp.items():
        if key.startswith("require_"):
            if not required:
                continue
            field = key.replace("require_", "")
            if field == "global_v6" and not checks["global_v6_present"]:
                failures.append("missing global IPv6 on Gi5")
            elif field == "ipv4_dhcp_lease" and not checks["ipv4_dhcp_lease"]:
                failures.append("missing IPv4 DHCP lease on Gi5")
        elif key.startswith("forbid_"):
            if key == "forbid_global_v6" and required and checks["global_v6_present"]:
                failures.append("unexpected global IPv6 on Gi5")
        elif required and not checks.get(key, False):
            failures.append(f"missing {key}")

    return {
        "scenario": scenario,
        "lab_id": lab_id,
        "node": node_label,
        "pass": not failures,
        "failures": failures,
        "checks": checks,
        "mgmt_ipv4": m_v4.group(1) if m_v4 else None,
        "mgmt_ipv6": m_v6.group(1) if m_v6 else None,
        "run_int_excerpt": run_section[:500],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate CSR OOB live state")
    p.add_argument("--lab-id", required=True)
    p.add_argument("--scenario", required=True)
    p.add_argument("--node", default="R1")
    p.add_argument("--out", type=Path)
    p.add_argument(
        "--max-attempts",
        type=int,
        default=1,
        help="Retry when config or addresses are not ready yet (default: 1)",
    )
    p.add_argument(
        "--wait-seconds",
        type=int,
        default=30,
        help="Seconds between validation attempts (default: 30)",
    )
    args = p.parse_args(argv)

    report: dict = {}
    for attempt in range(1, max(1, args.max_attempts) + 1):
        report = validate_lab(args.lab_id, args.scenario, args.node)
        report["attempt"] = attempt
        if report["pass"]:
            break
        if attempt < args.max_attempts:
            print(
                f"attempt {attempt}/{args.max_attempts} failed; "
                f"retry in {args.wait_seconds}s: {report.get('failures')}",
                file=sys.stderr,
            )
            time.sleep(args.wait_seconds)

    text = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
