#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-02-19
#
# - Called by: Users (CLI utility)
# - Reads from: CML controller API (lab metadata, node status)
# - Writes to: CML controller (router start commands)
# - Calls into: virl2_client, argparse
"""
Start routers in a CML lab by name range via CML API.

PURPOSE:
    Utility to start multiple routers in a CML lab without manual clicking.
    Useful when booting large topologies where you need to selectively start
    routers by range (e.g., odd routers, even routers, specific router tiers).

USAGE:
  python start_routers_by_range.py --lab-id <id> [--range 3-199:2] [--url https://cml] [--username admin] [--password admin]

Examples:
  # Start odd routers R3-R199
  python start_routers_by_range.py --lab-id 3078b3b3-42e8-4229-84db-f4742ec4a431 --range 3-199:2

  # Start all routers R1-R100
  python start_routers_by_range.py --lab-id 3078b3b3-42e8-4229-84db-f4742ec4a431 --range 1-100:1

  # With custom CML server
  python start_routers_by_range.py --url https://192.168.1.164 --lab-id <id> --range 3-199:2
"""

import argparse
import os
import time
from virl2_client import ClientLibrary


def start_routers(cml_url, lab_id, username, password, start, end, step):
    """Start routers R<start> to R<end> by <step> via CML API."""
    
    try:
        print(f"Connecting to CML ({cml_url})...")
        client = ClientLibrary(
            url=cml_url,
            username=username,
            password=password,
            ssl_verify=False
        )
        
        print(f"Getting lab ({lab_id})...")
        lab = client.get_lab(lab_id)
        print(f"Lab: {lab.title}\n")
        
        # Identify routers by range
        all_nodes = {node.label: node for node in lab.nodes()}
        router_names = [f"R{i}" for i in range(start, end + 1, step)]
        routers = [all_nodes[name] for name in router_names if name in all_nodes]
        
        if not routers:
            print(f"ERROR: No routers found in range R{start}-R{end} (step {step})")
            return False
        
        print(f"Found {len(routers)} routers to start (R{start}-R{end} step {step})\n")
        
        # Start each router
        started = 0
        failed = []
        
        for router in routers:
            try:
                print(f"Starting {router.label}...", end=" ")
                router.start()
                print("✓")
                started += 1
            except Exception as e:
                print(f"✗ {e}")
                failed.append((router.label, str(e)))
        
        print(f"\n{'='*50}")
        print(f"✓ Started: {started}/{len(routers)}")
        if failed:
            print(f"✗ Failed: {len(failed)}")
            for name, error in failed:
                print(f"  - {name}: {error}")
        print(f"{'='*50}")
        
        # Wait and show status
        print("\nWaiting 10 seconds for routers to boot...\n")
        time.sleep(10)
        
        print("Router status:")
        for router in routers:
            status = router.state
            print(f"  {router.label}: {status}")
        
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Start routers in a CML lab by name range",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start odd routers R3-R199
  %(prog)s --lab-id 3078b3b3-42e8-4229-84db-f4742ec4a431 --range 3-199:2

  # Start all routers R1-R100
  %(prog)s --lab-id 3078b3b3-42e8-4229-84db-f4742ec4a431 --range 1-100:1
        """
    )
    
    parser.add_argument("--url", default="https://192.168.1.164", help="CML server URL (default: https://192.168.1.164)")
    parser.add_argument("--lab-id", required=True, help="Lab ID (from URL or CML)")
    parser.add_argument("--username", default="admin", help="CML username (default: admin)")
    parser.add_argument("--password", default=os.getenv("CML_PASSWORD", "admin"), help="CML password (default: admin or CML_PASSWORD env var)")
    parser.add_argument("--range", default="3-199:2", help="Router range (start-end:step). Default: 3-199:2 (odd routers)")
    
    args = parser.parse_args()
    
    # Parse range (e.g., "3-199:2" -> start=3, end=199, step=2)
    try:
        if ":" in args.range:
            range_part, step = args.range.split(":")
            step = int(step)
        else:
            range_part = args.range
            step = 1
        
        start, end = map(int, range_part.split("-"))
    except (ValueError, IndexError):
        print(f"ERROR: Invalid range format '{args.range}'. Use 'start-end' or 'start-end:step'")
        return False
    
    success = start_routers(
        cml_url=args.url,
        lab_id=args.lab_id,
        username=args.username,
        password=args.password,
        start=start,
        end=end,
        step=step
    )
    
    exit(0 if success else 1)


if __name__ == "__main__":
    main()
