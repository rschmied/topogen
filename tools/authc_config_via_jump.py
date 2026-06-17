#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-02-19
#
# - Called by: Users (CLI utility)
# - Reads from: Jump host SSH, router SSH (running configs)
# - Writes to: Router startup configs (PKI trustpoint, authc enrollment)
# - Calls into: paramiko, argparse
"""
Execute PKI config + authc on routers via jump host.

PURPOSE:
    Utility to configure PKI certificate-based authentication on routers that are
    still booting or not yet reachable directly. Uses a jump host (e.g., R1) to SSH
    into the inband network and configure each router sequentially.

    Handles DMVPN PKI enrollment workflow:
    - Configure trustpoint with CA fingerprint
    - Execute authc (SCEP enrollment) on each router
    - Retry failed routers (3 attempts total)

USAGE:
  python authc_config_via_jump.py --jump-host 192.168.1.230 [--range 3-199:2] [--subnet 10.10.0] [--username cisco] [--password cisco]

Examples:
  # Odd routers R3-R199 via R1
  python authc_config_via_jump.py --jump-host 192.168.1.230 --range 3-199:2 --subnet 10.10.0

  # All routers R2-R100
  python authc_config_via_jump.py --jump-host 192.168.1.230 --range 2-100:1 --subnet 10.10.0

  # With fingerprint
  python authc_config_via_jump.py --jump-host 192.168.1.230 --fingerprint "735394C6 9B66CCA6 450F48C0 C4552C75 49EB0E2D"
"""

import argparse
import paramiko
import time
import os


def execute_authc_via_jump(jump_ip, inband_ip, router_name, username, password, fingerprint):
    """SSH to jump host, then SSH to target router and execute config."""
    
    try:
        print(f"\n{router_name} ({inband_ip}): Connecting via jump host ({jump_ip})...")
        
        # Step 1: SSH to jump host
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump_client.connect(jump_ip, username=username, password=password, timeout=10)
        
        # Step 2: Open shell on jump host
        jump_channel = jump_client.invoke_shell()
        jump_channel.settimeout(5)
        time.sleep(0.5)
        
        # Step 3: SSH from jump host to target router
        print(f"  → SSH from jump host to {router_name}...")
        jump_channel.send(f"ssh {username}@{inband_ip}\n")
        time.sleep(2)
        
        # Step 4: Respond to password prompt
        try:
            output = jump_channel.recv(4096).decode()
            if "Password:" in output or "password:" in output:
                jump_channel.send(password + "\n")
                time.sleep(1)
        except:
            pass
        
        # Step 5: Execute command sequence on target router
        commands = [
            ("en", 1),
            (password, 1),
            ("conf t", 1),
            ("crypto pki trustpoint CA-ROOT-SELF", 1),
            (f"fing {fingerprint}", 1),
            ("exit", 1),
            ("authc", 3),
            ("end", 1),
        ]
        
        print(f"  → Executing config on {router_name}...")
        
        for cmd, wait_time in commands:
            jump_channel.send(cmd + "\n")
            time.sleep(wait_time)
            
            try:
                output = jump_channel.recv(4096).decode()
                if "Error" in output or "error" in output or "%" in output:
                    print(f"    ⚠️  {cmd} → {output[:80]}")
            except:
                pass
        
        # Step 6: Exit SSH session on target router
        print(f"  → Exiting {router_name}...")
        jump_channel.send("exit\n")
        time.sleep(1)
        
        # Step 7: Close jump host connection
        jump_channel.close()
        jump_client.close()
        
        print(f"{router_name}: ✓ SUCCESS")
        return True
        
    except Exception as e:
        print(f"{router_name} ({inband_ip}): ✗ FAILED - {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Execute PKI config + authc on routers via jump host",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Odd routers R3-R199
  %(prog)s --jump-host 192.168.1.230 --range 3-199:2

  # All routers R2-R100
  %(prog)s --jump-host 192.168.1.230 --range 2-100:1

  # Custom fingerprint and subnet
  %(prog)s --jump-host 192.168.1.230 --fingerprint "735394C6 9B66CCA6 450F48C0 C4552C75 49EB0E2D" --subnet 10.10.0
        """
    )
    
    parser.add_argument("--jump-host", required=True, help="Jump host IP (e.g., 192.168.1.230)")
    parser.add_argument("--range", default="3-199:2", help="Router range (start-end:step). Default: 3-199:2 (odd routers)")
    parser.add_argument("--subnet", default="10.10.0", help="Inband subnet for routers (default: 10.10.0)")
    parser.add_argument("--username", default="cisco", help="SSH username (default: cisco)")
    parser.add_argument("--password", default=os.getenv("ROUTER_PASSWORD", "cisco"), help="SSH password (default: cisco or ROUTER_PASSWORD env var)")
    parser.add_argument("--fingerprint", default="735394C6 9B66CCA6 450F48C0 C4552C75 49EB0E2D", help="PKI CA fingerprint")
    
    args = parser.parse_args()
    
    # Parse range
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
    
    # Build router list
    routers = {f"R{i}": f"{args.subnet}.{i}" for i in range(start, end + 1, step)}
    
    print(f"Targeting {len(routers)} routers via jump host ({args.jump_host})")
    print(f"Inband subnet: {args.subnet}")
    print(f"Range: R{start}-R{end} (step {step})\n")
    
    # Execute sequentially
    success_routers = []
    failed_routers = []
    
    for name, inband_ip in routers.items():
        result = execute_authc_via_jump(
            args.jump_host, inband_ip, name, args.username, args.password, args.fingerprint
        )
        if result:
            success_routers.append(name)
        else:
            failed_routers.append((name, inband_ip))
        time.sleep(1)
    
    # Retry failed routers (2 more attempts)
    if failed_routers:
        print(f"\n{'='*50}")
        print(f"RETRY PASS (attempt 2/3)...")
        print(f"{'='*50}\n")
        
        retry_failed = []
        for name, inband_ip in failed_routers:
            result = execute_authc_via_jump(
                args.jump_host, inband_ip, name, args.username, args.password, args.fingerprint
            )
            if result:
                success_routers.append(name)
            else:
                retry_failed.append((name, inband_ip))
            time.sleep(1)
        
        failed_routers = retry_failed
        
        # Final retry
        if failed_routers:
            print(f"\n{'='*50}")
            print(f"FINAL RETRY PASS (attempt 3/3)...")
            print(f"{'='*50}\n")
            
            final_failed = []
            for name, inband_ip in failed_routers:
                result = execute_authc_via_jump(
                    args.jump_host, inband_ip, name, args.username, args.password, args.fingerprint
                )
                if result:
                    success_routers.append(name)
                else:
                    final_failed.append((name, inband_ip))
                time.sleep(1)
            
            failed_routers = final_failed
    
    # Summary
    success_count = len(success_routers)
    failed_count = len(failed_routers)
    total = len(routers)
    
    print(f"\n{'='*50}")
    print(f"✓ Success: {success_count}/{total}")
    print(f"✗ Failed: {failed_count}/{total}")
    print(f"{'='*50}")
    
    # Save failed routers to file
    if failed_routers:
        with open("failed_routers.txt", "w") as f:
            f.write("Failed routers (unable to reach after 3 attempts):\n")
            for name, ip in failed_routers:
                f.write(f"{name} ({ip})\n")
        print(f"\n⚠️  Failed routers saved to: failed_routers.txt")
        print("Run again after they boot to retry.")
    
    if success_count == total:
        print(f"\n🎉 All routers configured successfully!")
    
    exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
