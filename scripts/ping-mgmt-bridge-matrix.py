#!/usr/bin/env python3
"""Ping a target from every BOOTED CSR router in a CML lab (mgmt VRF)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

from virl2_client import ClientLibrary

SUCCESS_RE = re.compile(r"Success rate is (\d+) percent")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-id", required=True)
    parser.add_argument("--target", default="192.168.1.10")
    parser.add_argument("--vrf", default="Mgmt-vrf")
    parser.add_argument("--wait-booted", action="store_true")
    parser.add_argument("--timeout-sec", type=int, default=1800)
    parser.add_argument("--poll-sec", type=int, default=30)
    args = parser.parse_args()

    url = os.environ.get("VIRL2_URL", "https://192.168.1.183")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    client = ClientLibrary(url, user, password, ssl_verify=False)
    lab = client.join_existing_lab(args.lab_id)

    deadline = time.time() + args.timeout_sec
    while True:
        routers = [
            n
            for n in lab.nodes()
            if n.node_definition == "csr1000v" and n.label.startswith("R")
        ]
        booted = [n for n in routers if str(n.state) == "BOOTED"]
        if len(booted) == len(routers) or not args.wait_booted:
            break
        if time.time() >= deadline:
            break
        print(
            f"waiting: {len(booted)}/{len(routers)} BOOTED",
            flush=True,
        )
        time.sleep(args.poll_sec)
        lab.sync()

    report: dict[str, object] = {
        "target": args.target,
        "vrf": args.vrf,
        "success": [],
        "fail": [],
        "not_booted": [],
        "errors": [],
    }

    for node in sorted(
        [n for n in lab.nodes() if n.node_definition == "csr1000v" and n.label.startswith("R")],
        key=lambda n: int(n.label[1:]),
    ):
        label = node.label
        if str(node.state) != "BOOTED":
            report["not_booted"].append(label)  # type: ignore[union-attr]
            continue
        cmd = f"ping vrf {args.vrf} {args.target} repeat 3 timeout 2"
        try:
            output = str(node.run_pyats_command(cmd, config=False))
            match = SUCCESS_RE.search(output)
            rate = int(match.group(1)) if match else 0
            if rate > 0:
                report["success"].append(label)  # type: ignore[union-attr]
            else:
                report["fail"].append({"router": label, "output": output[-1200:]})  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"router": label, "error": str(exc)})  # type: ignore[union-attr]

    print(json.dumps(report, indent=2))
    return 0 if not report["fail"] and not report["not_booted"] and not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
