#!/usr/bin/env python3
"""Parallel SSH fan-out to IOSv routers listed in router-hosts.csv."""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import paramiko

# Legacy IOSv SSH (match OpenSSH: -o KexAlgorithms=... -o HostKeyAlgorithms=ssh-rsa)
LEGACY_DISABLED_ALGORITHMS: dict[str, list[str]] = {
    "pubkeys": ["rsa-sha2-512", "rsa-sha2-256"],
    "keys": ["rsa-sha2-512", "rsa-sha2-256"],
}

DEFAULT_HOSTS = Path(__file__).resolve().parent / "router-hosts.csv"
UPTIME_CMD = "show version | include uptime"
UPTIME_RE = re.compile(r"uptime is (.+)", re.IGNORECASE)


@dataclass(frozen=True)
class RouterHost:
    label: str
    ipv6_mgmt: str
    user: str
    password: str
    canonical: str = ""
    hostname: str = ""


def load_hosts(path: Path, labels: Iterable[str] | None = None) -> list[RouterHost]:
    wanted = {x.strip() for x in labels} if labels else None
    hosts: list[RouterHost] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = (row.get("label") or "").strip()
            if not label:
                continue
            if wanted is not None and label not in wanted:
                continue
            ipv6 = (row.get("ipv6_mgmt") or row.get("ipv6") or "").strip()
            if not ipv6:
                continue
            hosts.append(
                RouterHost(
                    label=label,
                    ipv6_mgmt=ipv6,
                    user=(row.get("user") or "cisco").strip(),
                    password=(row.get("password") or "cisco").strip(),
                    canonical=(row.get("canonical") or "").strip(),
                    hostname=(row.get("hostname") or label).strip(),
                )
            )
    return hosts


def run_ssh_command(host: RouterHost, command: str, timeout: float) -> tuple[str, str, str]:
    """Returns (label, status, output) where status is ok|fail."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host.ipv6_mgmt,
            port=22,
            username=host.user,
            password=host.password,
            timeout=timeout,
            banner_timeout=timeout,
            auth_timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
            disabled_algorithms=LEGACY_DISABLED_ALGORITHMS,
        )
        _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        combined = (out + err).strip()
        if stdout.channel.recv_exit_status() != 0 and not combined:
            return host.label, "fail", err.strip() or "non-zero exit"
        return host.label, "ok", combined
    except Exception as exc:  # noqa: BLE001 — per-host errors collected in batch
        return host.label, "fail", str(exc)
    finally:
        client.close()


def parse_uptime(text: str) -> str:
    for line in text.splitlines():
        m = UPTIME_RE.search(line)
        if m:
            return m.group(1).strip()
    one_line = " ".join(text.split())
    m = UPTIME_RE.search(one_line)
    if m:
        return m.group(1).strip()
    return one_line[:500] if one_line else ""


def fanout(
    hosts: list[RouterHost],
    command: str,
    workers: int,
    timeout: float,
) -> list[dict[str, str]]:
    by_label = {h.label: h for h in hosts}
    results: dict[str, dict[str, str]] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(run_ssh_command, h, command, timeout): h.label for h in hosts
        }
        for fut in as_completed(futures):
            label = futures[fut]
            h = by_label[label]
            lbl, status, output = fut.result()
            results[lbl] = {
                "label": lbl,
                "ipv6_mgmt": h.ipv6_mgmt,
                "status": status,
                "output": output,
            }

    return [results[h.label] for h in hosts if h.label in results]


def write_uptime_artifacts(base: Path, rows: list[dict[str, str]]) -> None:
    csv_path = base / "router-uptime.csv"
    md_path = base / "ROUTER-UPTIME.md"
    ok = sum(1 for r in rows if r["status"] == "ok")
    fail = len(rows) - ok

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label", "ipv6_mgmt", "status", "uptime", "raw_or_error"])
        for r in rows:
            uptime = parse_uptime(r["output"]) if r["status"] == "ok" else ""
            raw = r["output"] if r["status"] != "ok" else r["output"]
            w.writerow([r["label"], r["ipv6_mgmt"], r["status"], uptime, raw])

    lines = [
        "# Router uptime (batch SSH)",
        "",
        f"- **Total:** {len(rows)}",
        f"- **OK:** {ok}",
        f"- **Failed:** {fail}",
        "",
        "| Router | Status | Uptime / error |",
        "|--------|--------|----------------|",
    ]
    for r in rows:
        if r["status"] == "ok":
            cell = parse_uptime(r["output"]) or r["output"].replace("|", "\\|")[:120]
        else:
            cell = r["output"].replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(f"| {r['label']} | {r['status']} | {cell} |")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(f"Summary: {ok} ok, {fail} failed, {len(rows)} total")


def openssh_sample_command(host: RouterHost) -> str:
    bracket = f"[{host.ipv6_mgmt}]"
    opts = (
        "-6 -o KexAlgorithms=diffie-hellman-group14-sha1,diffie-hellman-group-exchange-sha1 "
        "-o HostKeyAlgorithms=ssh-rsa -o PubkeyAcceptedAlgorithms=ssh-rsa "
        "-o StrictHostKeyChecking=no"
    )
    return f"ssh {opts} {host.user}@{bracket}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a CLI command on many IOSv routers via parallel SSH (Paramiko)."
    )
    parser.add_argument(
        "--hosts",
        type=Path,
        default=DEFAULT_HOSTS,
        help=f"CSV path (default: {DEFAULT_HOSTS.name})",
    )
    parser.add_argument(
        "--command",
 "-c",
        default="",
        help="IOS command to run (required unless --uptime)",
    )
    parser.add_argument(
        "--uptime",
        action="store_true",
        help=f"Collect uptime via: {UPTIME_CMD}",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=25,
        help="Parallel SSH sessions (default: 25)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="Connect/command timeout seconds (default: 45)",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        help="Limit to router labels (e.g. R1 R2)",
    )
    parser.add_argument(
        "--print-openssh",
        metavar="LABEL",
        help="Print OpenSSH command for one router (interactive use)",
    )
    args = parser.parse_args()

    if not args.hosts.is_file():
        print(f"Hosts file not found: {args.hosts}", file=sys.stderr)
        return 1

    hosts = load_hosts(args.hosts, args.only)
    if not hosts:
        print("No hosts loaded.", file=sys.stderr)
        return 1

    if args.print_openssh:
        match = [h for h in hosts if h.label == args.print_openssh]
        if not match:
            all_h = load_hosts(args.hosts)
            match = [h for h in all_h if h.label == args.print_openssh]
        if not match:
            print(f"Unknown label: {args.print_openssh}", file=sys.stderr)
            return 1
        print(openssh_sample_command(match[0]))
        return 0

    command = UPTIME_CMD if args.uptime else args.command.strip()
    if not command:
        parser.error("Provide --command or use --uptime")

    t0 = time.perf_counter()
    rows = fanout(hosts, command, args.workers, args.timeout)
    elapsed = time.perf_counter() - t0
    print(f"Finished {len(rows)} hosts in {elapsed:.1f}s")

    if args.uptime:
        write_uptime_artifacts(args.hosts.parent, rows)
    else:
        for r in rows:
            print(f"\n=== {r['label']} ({r['ipv6_mgmt']}) [{r['status']}] ===")
            print(r["output"])

    fails = [r for r in rows if r["status"] != "ok"]
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
