#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-03-22
#
# - Called by: Developers (manual regression), CI (future)
# - Reads from: Two CML YAML files (online export and offline-generated)
# - Writes to: stdout (comparison report), exit code (0=pass, 1=fail)
# - Calls into: yaml, re (stdlib)
#
# Purpose: Validate that offline-generated CML YAML structurally matches
#          an online CML export for the same topology mode and node count.
#
# Blast Radius: None (read-only comparison tool)
"""Compare an online CML export YAML against an offline-generated YAML.

Usage:
    python tests/compare_online_offline.py <online.yaml> <offline.yaml>

Checks node definitions, labels, coordinates, link topology, interface IDs,
IP addressing, nameserver, default routes, OSPF originate, and DNS host config.
Exit code 0 = all OK (cosmetic diffs noted), 1 = structural mismatch found.
"""

import re
import sys

import yaml


def extract_config_text(node):
    cfg = node.get("configuration", "")
    if isinstance(cfg, list):
        return cfg[0].get("content", "") if cfg else ""
    return cfg


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <online.yaml> <offline.yaml>")
        sys.exit(2)

    online_path, offline_path = sys.argv[1], sys.argv[2]
    with open(online_path) as f:
        online = yaml.safe_load(f)
    with open(offline_path) as f:
        offline = yaml.safe_load(f)

    failures = 0

    on_nodes = online["nodes"]
    off_nodes = offline["nodes"]

    print("=== NODE COMPARISON ===")
    print(f"  Online nodes: {len(on_nodes)}, Offline nodes: {len(off_nodes)}")
    if len(on_nodes) != len(off_nodes):
        print("  FAIL: node count mismatch")
        failures += 1

    for on, off in zip(on_nodes, off_nodes):
        on_label = on["label"]
        off_label = off["label"]
        on_def = on["node_definition"]
        off_def = off["node_definition"]
        on_xy = (on.get("x", "?"), on.get("y", "?"))
        off_xy = (off.get("x", "?"), off.get("y", "?"))

        coord_match = "OK" if on_xy == off_xy else f"DIFF on={on_xy} off={off_xy}"
        def_match = "OK" if on_def == off_def else "DIFF"
        label_match = "OK" if on_label == off_label else f"DIFF on={on_label} off={off_label}"

        if coord_match != "OK":
            failures += 1
        if def_match != "OK":
            failures += 1
        if label_match != "OK":
            failures += 1

        print(f"  {on_label:15s} def={def_match:3s} label={label_match:3s} coords={coord_match}")

    print()
    print("=== LINK COMPARISON ===")
    on_links = online["links"]
    off_links = offline["links"]
    print(f"  Online links: {len(on_links)}, Offline links: {len(off_links)}")
    if len(on_links) != len(off_links):
        print("  FAIL: link count mismatch")
        failures += 1

    for on, off in zip(on_links, off_links):
        on_str = f"{on['n1']}:{on['i1']} -- {on['n2']}:{on['i2']}"
        off_str = f"{off['n1']}:{off['i1']} -- {off['n2']}:{off['i2']}"
        match = "OK" if on_str == off_str else "DIFF"
        on_lbl = on.get("label", "")
        if match != "OK":
            failures += 1
        print(f"  {on_str:30s} | {off_str:30s} {match} ({on_lbl})")

    print()
    print("=== IP ADDRESSING COMPARISON ===")
    for on, off in zip(on_nodes, off_nodes):
        if on["node_definition"] != "iosv":
            continue
        on_cfg = extract_config_text(on)
        off_cfg = extract_config_text(off)
        on_ips = re.findall(r"ip address (\S+ \S+)", on_cfg)
        off_ips = re.findall(r"ip address (\S+ \S+)", off_cfg)
        on_ns = re.findall(r"ip name-server (\S+)", on_cfg)
        off_ns = re.findall(r"ip name-server (\S+)", off_cfg)
        on_dflt = re.findall(r"ip route 0.0.0.0 0.0.0.0 (\S+)", on_cfg)
        off_dflt = re.findall(r"ip route 0.0.0.0 0.0.0.0 (\S+)", off_cfg)
        on_doi = "default-information originate" in on_cfg
        off_doi = "default-information originate" in off_cfg

        label = on["label"]
        ip_match = "OK" if on_ips == off_ips else "DIFF"
        ns_match = "OK" if on_ns == off_ns else "DIFF"
        dflt_match = "OK" if on_dflt == off_dflt else "DIFF"
        doi_match = "OK" if on_doi == off_doi else "DIFF"

        print(f"  {label}: IPs={ip_match} nameserver={ns_match} default-route={dflt_match} doi={doi_match}")
        if ip_match != "OK":
            print(f"         on_ips={on_ips}")
            print(f"         off_ips={off_ips}")
        if ns_match != "OK":
            print(f"         on_ns={on_ns} off_ns={off_ns}")
            failures += 1
        if dflt_match != "OK":
            print(f"         on_dflt={on_dflt} off_dflt={off_dflt}")
            failures += 1

    print()
    print("=== DNS HOST CONFIG COMPARISON ===")
    for on, off in zip(on_nodes, off_nodes):
        if on["node_definition"] != "alpine":
            continue
        on_cfg = extract_config_text(on)
        off_cfg = extract_config_text(off)
        on_ip = re.findall(r"ip address add (\S+)", on_cfg)
        off_ip = re.findall(r"ip address add (\S+)", off_cfg)
        on_routes = re.findall(r"ip route add .* via (\S+)", on_cfg)
        off_routes = re.findall(r"ip route add .* via (\S+)", off_cfg)
        on_hosts = re.findall(r'echo.*"(\S+)\\t', on_cfg)
        off_hosts = re.findall(r'echo.*"(\S+)\\t', off_cfg)
        ip_match = "OK" if on_ip == off_ip else "DIFF"
        route_match = "OK" if on_routes == off_routes else "DIFF"
        hosts_match = "OK" if on_hosts == off_hosts else "DIFF"
        if ip_match != "OK":
            failures += 1
        if route_match != "OK":
            failures += 1
        if hosts_match != "OK":
            failures += 1
        print(f"  dns-host: eth1_ip={ip_match} routes_via={route_match} hosts={hosts_match}")
        if ip_match != "OK":
            print(f"         on={on_ip} off={off_ip}")
        if route_match != "OK":
            print(f"         on={on_routes} off={off_routes}")

    print()
    if failures:
        print(f"RESULT: {failures} structural difference(s) found.")
        sys.exit(1)
    else:
        print("RESULT: All structural checks passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
