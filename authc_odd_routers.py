#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-02-21
#
# - Called by: Users (CLI utility)
# - Reads from: R1 jump host SSH, odd-router SSH (inband IPs)
# - Writes to: Odd-router startup configs (PKI fingerprint, authc)
# - Calls into: paramiko
"""
Execute PKI fingerprint config + authc on odd routers via R1 jump host.
R1 (gateway) at 192.168.1.230, odd routers at 10.10.0.3, 10.10.0.5, etc.
SSH: cisco/cisco
"""

import paramiko
import time

def execute_authc_via_r1(inband_ip, router_name):
    """SSH to R1, then from R1 SSH to odd router and execute config"""
    r1_ip = "192.168.1.230"
    username = "cisco"
    password = "cisco"
    
    try:
        print(f"\n{router_name} ({inband_ip}): Connecting via R1 ({r1_ip})...")
        
        # Step 1: SSH to R1
        r1_client = paramiko.SSHClient()
        r1_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        r1_client.connect(r1_ip, username=username, password=password, timeout=10)
        
        # Step 2: Open shell on R1
        r1_channel = r1_client.invoke_shell()
        r1_channel.settimeout(5)
        time.sleep(0.5)
        
        # Step 3: SSH from R1 to target router
        print(f"  → SSH from R1 to {router_name}...")
        r1_channel.send(f"ssh {username}@{inband_ip}\n")
        time.sleep(2)  # Wait for connection
        
        # Step 4: Respond to password prompt if needed
        try:
            output = r1_channel.recv(4096).decode()
            if "Password:" in output or "password:" in output:
                r1_channel.send(password + "\n")
                time.sleep(1)
        except:
            pass
        
        # Step 5: Execute command sequence on target router
        commands = [
            ("en", 1),  # enable
            (password, 1),  # enable password (if prompted)
            ("conf t", 1),  # configure terminal
            ("crypto pki trustpoint CA-ROOT-SELF", 1),  # enter trustpoint config
            ("fing 735394C6 9B66CCA6 450F48C0 C4552C75 49EB0E2D", 1),  # fingerprint
            ("exit", 1),  # exit trustpoint
            ("authc", 3),  # execute authc (might take longer)
            ("end", 1),  # exit config
        ]
        
        print(f"  → Executing config on {router_name}...")
        
        for cmd, wait_time in commands:
            r1_channel.send(cmd + "\n")
            time.sleep(wait_time)
            
            # Read any available output
            try:
                output = r1_channel.recv(4096).decode()
                if "Error" in output or "error" in output or "%" in output:
                    print(f"    ⚠️  {cmd} → {output[:80]}")
            except:
                pass
        
        # Step 6: Exit SSH session on target router
        print(f"  → Exiting {router_name}...")
        r1_channel.send("exit\n")
        time.sleep(1)
        
        # Step 7: Close R1 connection
        r1_channel.close()
        r1_client.close()
        
        print(f"{router_name}: ✓ SUCCESS")
        return True
        
    except Exception as e:
        print(f"{router_name} ({inband_ip}): ✗ FAILED - {e}")
        return False


def main():
    # Build ODD router list with inband IPs (10.10.0.3, 10.10.0.5... 10.10.0.199)
    # Assuming inband subnet 10.10.0.0/24 where router N is at 10.10.0.N
    odd_routers = {f"R{i}": f"10.10.0.{i}" for i in range(3, 200, 2)}  # R3-R199
    
    print(f"Targeting {len(odd_routers)} odd routers via R1 (192.168.1.230)")
    print(f"Inband IPs: 10.10.0.3, 10.10.0.5 ... 10.10.0.199\n")
    
    # SEQUENTIAL execution (each router config takes time, hop through R1)
    success_routers = []
    failed_routers = []
    
    for name, inband_ip in odd_routers.items():
        result = execute_authc_via_r1(inband_ip, name)
        if result:
            success_routers.append(name)
        else:
            failed_routers.append((name, inband_ip))
        time.sleep(1)  # Small delay between routers
    
    # RETRY failed routers (2 more attempts)
    if failed_routers:
        print(f"\n{'='*50}")
        print(f"RETRY PASS (attempt 2/3)...")
        print(f"{'='*50}\n")
        
        retry_failed = []
        for name, inband_ip in failed_routers:
            result = execute_authc_via_r1(inband_ip, name)
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
                result = execute_authc_via_r1(inband_ip, name)
                if result:
                    success_routers.append(name)
                else:
                    final_failed.append((name, inband_ip))
                time.sleep(1)
            
            failed_routers = final_failed
    
    # Summary
    success_count = len(success_routers)
    failed_count = len(failed_routers)
    
    print(f"\n{'='*50}")
    print(f"✓ Success: {success_count}/{len(odd_routers)}")
    print(f"✗ Failed: {failed_count}/{len(odd_routers)}")
    print(f"{'='*50}")
    
    # Save failed routers to file for manual retry
    if failed_routers:
        with open("failed_routers.txt", "w") as f:
            f.write("Failed routers (unable to reach after 3 attempts):\n")
            for name, ip in failed_routers:
                f.write(f"{name} ({ip})\n")
        print(f"\n⚠️  Failed routers saved to: failed_routers.txt")
        print("Run again after they boot to retry.")
    
    if success_count == len(odd_routers):
        print(f"\n🎉 All routers configured successfully!")


if __name__ == "__main__":
    main()
