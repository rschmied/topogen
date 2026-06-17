#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI utility)
# - Reads from: CML URL, lab ID, credentials (hardcoded in script)
# - Writes to: CML controller (node state: start)
# - Calls into: virl2_client
"""
Start all odd routers (R3-R199) in a CML lab via virl2_client API.
Lab URL: https://192.168.1.164/lab/3078b3b3-42e8-4229-84db-f4742ec4a431
"""

from virl2_client import ClientLibrary
import time

def start_odd_routers():
    # Configuration from lab URL
    cml_url = "https://192.168.1.164"
    lab_id = "3078b3b3-42e8-4229-84db-f4742ec4a431"
    username = "admin"
    password = "admin"
    
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
        
        # Identify odd routers (R3, R5, R7... R199)
        all_nodes = {node.label: node for node in lab.nodes()}
        odd_router_names = [f"R{i}" for i in range(3, 200, 2)]
        odd_routers = [all_nodes[name] for name in odd_router_names if name in all_nodes]
        
        print(f"Found {len(odd_routers)} odd routers to start\n")
        
        # Start each router
        started = 0
        failed = []
        
        for router in odd_routers:
            try:
                print(f"Starting {router.label}...", end=" ")
                router.start()
                print("✓")
                started += 1
            except Exception as e:
                print(f"✗ {e}")
                failed.append((router.label, str(e)))
        
        print(f"\n{'='*50}")
        print(f"✓ Started: {started}/{len(odd_routers)}")
        if failed:
            print(f"✗ Failed: {len(failed)}")
            for name, error in failed:
                print(f"  - {name}: {error}")
        print(f"{'='*50}")
        
        # Wait and show status
        print("\nWaiting 10 seconds for routers to boot...\n")
        time.sleep(10)
        
        print("Router status:")
        for router in odd_routers:
            status = router.state
            print(f"  {router.label}: {status}")

    except Exception as e:
        print(f"ERROR: {e}")
        return False
    
    return True


if __name__ == "__main__":
    success = start_odd_routers()
    exit(0 if success else 1)
