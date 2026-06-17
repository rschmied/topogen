<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.0
Date Modified: 2026-02-19

- Called by: Users (developers, maintainers, CI/CD workflows)
- Reads from: Tool docstrings, examples, troubleshooting guides
- Writes to: None (documentation only, but guides tool usage)
- Calls into: start_routers_by_range.py, authc_config_via_jump.py

Purpose: Documentation and usage guide for TopoGen lab management tools.
         Explains each tool's purpose, arguments, workflow, and troubleshooting.

Blast Radius: None (documentation only, but critical for tool discoverability)
-->

# TopoGen Tools

Utility scripts for managing CML labs created with TopoGen.

## Tools

### `start_routers_by_range.py`

Start routers in a CML lab by name range via the CML API.

**Prerequisites:**
```powershell
pip install virl2-client
```

**Usage:**
```powershell
python start_routers_by_range.py --lab-id <LAB_ID> [--range START-END:STEP] [--url HTTPS://CML]
```

**Examples:**

Start odd routers (R3, R5, R7... R199):
```powershell
python start_routers_by_range.py `
  --lab-id 3078b3b3-42e8-4229-84db-f4742ec4a431 `
  --range 3-199:2
```

Start all routers (R1-R100):
```powershell
python start_routers_by_range.py `
  --lab-id 3078b3b3-42e8-4229-84db-f4742ec4a431 `
  --range 1-100:1
```

Start routers on custom CML server:
```powershell
python start_routers_by_range.py `
  --url https://your-cml-server `
  --lab-id <LAB_ID> `
  --range 3-199:2 `
  --username admin `
  --password admin
```

**Arguments:**
- `--lab-id` (required): Lab ID from CML (found in lab URL)
- `--range`: Router range in format `START-END` or `START-END:STEP` (default: `3-199:2`)
- `--url`: CML server URL (default: `https://192.168.1.164`)
- `--username`: CML username (default: `admin`)
- `--password`: CML password (default: `admin` or `CML_PASSWORD` env var)

**What it does:**
- Connects to CML controller
- Identifies routers in the specified range
- Starts each router via the CML API (no manual clicking)
- Shows success/failure summary
- Displays final router status

---

### `authc_config_via_jump.py`

Execute PKI trustpoint configuration + `authc` enrollment on routers via a jump host.

**Use case:** When you need to configure PKI on routers that are still booting, and you have a management router (e.g., R1) that's already up and can SSH into the inband network.

**Prerequisites:**
```powershell
pip install paramiko
```

**Usage:**
```powershell
python authc_config_via_jump.py --jump-host <IP> [--range START-END:STEP] [--subnet INBAND_SUBNET]
```

**Examples:**

Configure odd routers (R3-R199) via R1 jump host:
```powershell
python authc_config_via_jump.py `
  --jump-host 192.168.1.230 `
  --range 3-199:2 `
  --subnet 10.10.0
```

Configure all routers (R2-R100):
```powershell
python authc_config_via_jump.py `
  --jump-host 192.168.1.230 `
  --range 2-100:1
```

With custom fingerprint:
```powershell
python authc_config_via_jump.py `
  --jump-host 192.168.1.230 `
  --fingerprint "735394C6 9B66CCA6 450F48C0 C4552C75 49EB0E2D"
```

**Arguments:**
- `--jump-host` (required): Jump host management IP (e.g., R1 at 192.168.1.230)
- `--range`: Router range (default: `3-199:2` for odd routers)
- `--subnet`: Inband subnet for routers (default: `10.10.0`)
- `--username`: SSH username (default: `cisco`)
- `--password`: SSH password (default: `cisco` or `ROUTER_PASSWORD` env var)
- `--fingerprint`: PKI CA fingerprint (default: `735394C6 9B66CCA6 450F48C0 C4552C75 49EB0E2D`)

**What it does:**

Per router (sequential):
1. SSH to jump host (R1) with credentials
2. From jump host, SSH to target router inband IP
3. Execute CLI sequence:
   - `en` (enable)
   - `conf t` (configure terminal)
   - `crypto pki trustpoint CA-ROOT-SELF` (enter trustpoint config)
   - `fing <FINGERPRINT>` (add CA fingerprint)
   - `exit` (exit trustpoint)
   - `authc` (start enrollment)
   - `end` (exit config)
4. Exit the router SSH session
5. Move to next router

**Retry logic:**
- If a router fails to reach/configure, script retries it 2 more times (3 total attempts)
- All failed routers are saved to `failed_routers.txt`
- Run the script again later to retry unreachable routers

**Execution flow:**
```
Your machine
    ↓
SSH → Jump Host (R1 @ 192.168.1.230)
         ↓
      SSH → R3 (10.10.0.3)  → config + authc
      SSH → R5 (10.10.0.5)  → config + authc
      SSH → R7 (10.10.0.7)  → config + authc
      ... (repeats for all routers)
```

---

## Environment Variables

Both scripts support environment variables for credentials:

```powershell
# Set CML password
$env:CML_PASSWORD = "your-password"

# Set router SSH password
$env:ROUTER_PASSWORD = "your-password"

# Run script without repeating password
python start_routers_by_range.py --lab-id <ID>
python authc_config_via_jump.py --jump-host <IP>
```

---

## Typical Workflow

1. **Create lab with TopoGen:**
   ```powershell
   topogen -T iosv-dmvpn --pki --offline-yaml lab.yaml 100
   ```

2. **Import to CML:**
   ```powershell
   topogen --import-yaml lab.yaml --import --start
   ```

3. **Wait for routers to boot** (R1 first, then spokes)

4. **Start remaining odd routers (if needed):**
   ```powershell
   python tools/start_routers_by_range.py --lab-id <ID> --range 3-199:2
   ```

5. **Configure PKI on odd routers via R1:**
   ```powershell
   python tools/authc_config_via_jump.py --jump-host 192.168.1.230 --range 3-199:2
   ```

6. **Check enrollment status in CML UI** (Devices → Per-router status)

---

## Troubleshooting

**"Connection refused" or timeout:**
- Router hasn't finished booting yet
- Script will retry 3 times automatically
- Check CML UI for router status

**"Authentication failed":**
- Verify credentials (username/password)
- Ensure SSH is enabled on routers (usually default)
- Check jump host is reachable

**"No routers found in range":**
- Verify router naming matches expectation (R3, R5, etc.)
- Check `--range` argument syntax

**Fingerprint not recognized:**
- Verify CA is running and PKI server is accessible
- Check fingerprint format (should be 5 hex groups)
- Wait for CA to fully boot before running enrollment

---

## Notes

- Scripts run **sequentially per router** (not parallel) to avoid overwhelming the PKI infrastructure
- Each router config takes ~5-10 seconds
- With 99 routers, expect 10-15 minutes total
- Use `--username` / `--password` sparingly; prefer env vars or `--password` prompt
- Lab URLs are typically: `https://<cml>/lab/<lab-id>`

