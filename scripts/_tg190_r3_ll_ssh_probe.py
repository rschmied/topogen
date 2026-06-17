import re
import subprocess
import sys

import paramiko

GLOBAL = "2001:db8:1700:21F8:7EC0:5054:FF:FE58:4AA4"
USER, PASS = "cisco", "cisco"
IFACE = "GigabitEthernet0/5"


def ssh_exec(host: str, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=USER,
        password=PASS,
        timeout=timeout,
        allow_agent=False,
        look_for_keys=False,
        disabled_algorithms={"keys": ["rsa-sha2-512", "rsa-sha2-256"]},
    )
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    client.close()
    return rc, out, err


def parse_link_local(show: str) -> str | None:
    m = re.search(r"link-local address is (FE80:[0-9A-Fa-f:]+)", show, re.I)
    if m:
        return m.group(1).upper()
    m = re.search(r"(FE80::[0-9A-Fa-f:]+)", show, re.I)
    return m.group(1).upper() if m else None


def windows_iface_index_for_global(global_addr: str) -> int | None:
    p2 = subprocess.run(
        ["netsh", "interface", "ipv6", "show", "route"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    for line in p2.stdout.splitlines():
        if global_addr.lower() in line.lower() or "2001:db8:1700" in line.lower():
            m = re.search(r"Interface\s+(\d+)", line, re.I)
            if m:
                return int(m.group(1))
    p = subprocess.run(
        ["netsh", "interface", "ipv6", "show", "address"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    idx = None
    for line in p.stdout.splitlines():
        m = re.search(r"Interface\s+(\d+)", line, re.I)
        if m:
            idx = int(m.group(1))
    return idx


def main() -> int:
    rc, out, err = ssh_exec(GLOBAL, f"show ipv6 interface {IFACE}")
    if rc != 0 and not out:
        print("GLOBAL_SSH_FAIL", err or out)
        return 1
    ll = parse_link_local(out)
    if not ll:
        print("NO_LL", out)
        return 1
    print("LL", ll)

    idx = windows_iface_index_for_global(GLOBAL)
    if idx is None:
        print("NO_IFACE_IDX")
        return 1
    print("IFACE_IDX", idx)

    ll_host = f"{ll}%{idx}"
    rc2, out2, err2 = ssh_exec(ll_host, "show hostname")
    hostname = out2.strip().splitlines()[0] if out2.strip() else ""
    ok = rc2 == 0 and bool(hostname)
    print("HOSTNAME", hostname)
    print(f"Router R3 Method SSH Target {ll} Result {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
