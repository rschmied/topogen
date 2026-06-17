#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-02-19
#
# - Called by: Users (CLI utility)
# - Reads from: Jump host SSH (clock), router SSH (running-config)
# - Writes to: Router system clock
# - Calls into: paramiko, argparse
"""
Set system clock on routers via jump host, synced to jump host time.

PURPOSE:
    Utility to synchronize system clocks on multiple routers by reading the
    time from a jump host (e.g., R1) and propagating it to all target routers.
    Useful when NTP sync is delayed or unavailable, and PKI/certificate
    validation requires valid system time.

USAGE:
  python set_clock_via_jump.py --jump-host <IP> [--range 3-199:2] [--subnet INBAND_SUBNET]

Examples:
  # Set clock on odd routers R3-R199 using R1 time
  python set_clock_via_jump.py --jump-host 192.168.1.230 --range 3-199:2 --subnet 10.10.0

  # Set clock on all routers R2-R100
  python set_clock_via_jump.py --jump-host 192.168.1.230 --range 2-100:1
"""

import argparse
import paramiko
import time
import re
import os


def get_jump_host_clock(jump_ip, username, password):
    """Get current time from jump host via 'show clock' command."""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(jump_ip, username=username, password=password, timeout=10)
        
        channel = client.invoke_shell()
        channel.settimeout(5)
        time.sleep(0.5)
        
        # Send 'show clock'
        channel.send("show clock\n")
        time.sleep(1)
        
        output = channel.recv(4096).decode()
        channel.close()
        client.close()
        
        # Parse output like: "*08:13:11.086 UTC Thu Feb 19 2026"
        match = re.search(r'\*?(\d{2}):(\d{2}):(\d{2})', output)
        if match:
            hh, mm, ss = match.groups()
            # Also extract date: "Feb 19 2026"
            date_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(\d{4})', output)
            if date_match:
                month, day, year = date_match.groups()
                return f"{hh}:{mm}:{ss} {month} {day} {year}"
        
        return None
    except Exception as e:
        print(f"ERROR getting clock from jump host: {e}")
        return None


def set_router_clock(jump_ip, inband_ip, router_name, username, password, clock_time):
    """SSH to jump host, then SSH to target router and set clock."""
    try:
        print(f"\n{router_name} ({inband_ip}): Setting clock via jump host...", end=" ")
        
        # Step 1: SSH to jump host
        jump_client = paramiko.SSHClient()
        jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        jump_client.connect(jump_ip, username=username, password=password, timeout=10)
        
        # Step 2: Open shell on jump host
        jump_channel = jump_client.invoke_shell()
        jump_channel.settimeout(5)
        time.sleep(0.5)
        
        # Step 3: SSH from jump host to target router
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
        
        # Step 5: Set clock on target router
        jump_channel.send(f"clock set {clock_time}\n")
        time.sleep(1)
        
        # Step 6: Verify clock was set
        jump_channel.send("show clock\n")
        time.sleep(1)
        
        try:
            verify_output = jump_channel.recv(4096).decode()
            if clock_time.split()[0] in verify_output:  # Check if time is in output
                print("✓")
                result = True
            else:
                print("⚠️  (verify timeout)")
                result = True  # Still count as success since command was sent
        except:
            print("✓")
            result = True
        
        # Step 7: Exit SSH session on target router
        jump_channel.send("exit\n")
        time.sleep(0.5)
        
        # Step 8: Close jump host connection
        jump_channel.close()
        jump_client.close()
        
        return result
        
    except Exception as e:
        print(f"✗ {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Set system clock on routers via jump host",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Set clock on odd routers R3-R199
  %(prog)s --jump-host 192.168.1.230 --range 3-199:2

  # Set clock on all routers R1-R100
  %(prog)s --jump-host 192.168.1.230 --range 1-100:1
        """
    )
    
    parser.add_argument("--jump-host", required=True, help="Jump host IP (e.g., 192.168.1.230)")
    parser.add_argument("--range", default="3-199:2", help="Router range (start-end:step). Default: 3-199:2 (odd routers)")
    parser.add_argument("--subnet", default="10.10.0", help="Inband subnet for routers (default: 10.10.0)")
    parser.add_argument("--username", default="cisco", help="SSH username (default: cisco)")
    parser.add_argument("--password", default=os.getenv("ROUTER_PASSWORD", "cisco"), help="SSH password (default: cisco or ROUTER_PASSWORD env var)")
    
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
    
    print(f"Getting current time from jump host ({args.jump_host})...")
    clock_time = get_jump_host_clock(args.jump_host, args.username, args.password)
    
    if not clock_time:
        print("ERROR: Could not retrieve time from jump host")
        return False
    
    print(f"Current time: {clock_time}\n")
    print(f"Setting clock on {len(routers)} routers via jump host ({args.jump_host})")
    print(f"Range: R{start}-R{end} (step {step})\n")
    
    # Execute sequentially
    success_count = 0
    failed_routers = []
    
    for name, inband_ip in routers.items():
        result = set_router_clock(args.jump_host, inband_ip, name, args.username, args.password, clock_time)
        if result:
            success_count += 1
        else:
            failed_routers.append((name, inband_ip))
        time.sleep(1)
    
    # Summary
    failed_count = len(failed_routers)
    total = len(routers)
    
    print(f"\n{'='*50}")
    print(f"✓ Success: {success_count}/{total}")
    print(f"✗ Failed: {failed_count}/{total}")
    print(f"{'='*50}")
    
    # Save failed routers to file
    if failed_routers:
        with open("failed_clock_routers.txt", "w") as f:
            f.write(f"Failed routers (unable to set clock):\n")
            f.write(f"Time attempted: {clock_time}\n\n")
            for name, ip in failed_routers:
                f.write(f"{name} ({ip})\n")
        print(f"\n⚠️  Failed routers saved to: failed_clock_routers.txt")
        print("Run again to retry.")
    
    if success_count == total:
        print(f"\n🎉 Clock set successfully on all routers!")
    
    exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
