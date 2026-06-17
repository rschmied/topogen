#!/usr/bin/env python3
"""One-shot: parallel SSH to lab routers, add imdone alias. Not part of topogen package."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from netmiko import ConnectHandler

ROUTERS = {
    "R1": "2001:db8:1700:21f8:7ec0:5054:ff:fe58:65c9",
    "R2": "2001:db8:1700:21f8:7ec0:5054:ff:fe27:33d5",
    "R3": "2001:db8:1700:21f8:7ec0:5054:ff:fe4d:8c8",
    "R4": "2001:db8:1700:21f8:7ec0:5054:ff:fee0:2b88",
    "R5": "2001:db8:1700:21f8:7ec0:5054:ff:fe2a:526",
    "R6": "2001:db8:1700:21f8:7ec0:5054:ff:fedb:c394",
}
USER = "cisco"
PASS = "cisco"
ALIAS = "alias exec imdone show version | include uptime"


def push(label: str, host: str) -> str:
    device = {
        "device_type": "cisco_xe",
        "host": host,
        "username": USER,
        "password": PASS,
        "secret": PASS,
        "global_delay_factor": 2,
        "timeout": 30,
    }
    try:
        conn = ConnectHandler(**device)
        conn.enable()
        conn.send_config_set([ALIAS])
        conn.save_config()
        verify = conn.send_command("show run | include alias exec imdone")
        conn.disconnect()
        if "alias exec imdone" in verify:
            return f"* I am done ({label})"
        return f"FAILED {label}: alias not verified"
    except Exception as exc:
        return f"FAILED {label}: {exc}"


def main() -> int:
    results: list[str] = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(push, lbl, ip): lbl for lbl, ip in ROUTERS.items()}
        for fut in as_completed(futures):
            results.append(fut.result())
    for line in sorted(results, key=lambda s: s):
        print(line)
    return 0 if all(r.startswith("* I am done") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
