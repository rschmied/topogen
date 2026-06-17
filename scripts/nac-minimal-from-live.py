#!/usr/bin/env python3
"""Strip Terraform-managed data-plane ethernets; keep host, hostname, loopback only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nac_yaml", type=Path)
    args = parser.parse_args()
    data = yaml.safe_load(args.nac_yaml.read_text(encoding="utf-8")) or {}
    for device in data.get("iosxe", {}).get("devices", []):
        config = device.get("configuration", {})
        ifaces = config.get("interfaces", {})
        ifaces.pop("ethernets", None)
        config["interfaces"] = ifaces
    args.nac_yaml.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    print(f"stripped ethernets from {args.nac_yaml}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
