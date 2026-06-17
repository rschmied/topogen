<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.0
Date Modified: 2026-06-13

- Called by: Operators / AI agents running TG-190 CP2 live validation
- Reads from: DEVELOPER.md, repo scripts, CML 2.10 controller
- Writes to: None (runbook prompt only)
- Calls into: None

Purpose: AI validation prompt for TG-190 Checkpoint 2 (external bridge DHCPv6/SLAAC).
-->

# TG-190 — AI validation prompt (Checkpoint 2: DHCPv6 live)
# Copy everything below this line into Jira TG-190 or a fresh Cursor agent chat.

You are continuing **TG-190** validation in the topogen repo — **Checkpoint 2 (CP2): live DHCPv6 address acquisition** on the OOB management interface.

- **Canonical remote:** `https://wwwin-github.cisco.com/rohosfor/topogen.git` (`cisco` remote)
- **Parent epic:** TG-189 (IPv6 on OOB management plane)
- **Branch:** `TG-190-dhcpv6-validation` (from `cisco/main`)
- **Related (Done on main):** TG-190 CP1 (offline render + SLAAC client config, PR #46), TG-191 (emitted `nac/sync-nac-mgmt.py`), TG-192 (CML CI/CD pipeline, PR #27, merge `53ee0b7`)
- **Explicitly separate:** TG-87 (dnsmasq DHCPv6 **server** on DNS host) — **do not implement**

**Git policy:** Push, PR, and merge **only** to `cisco`. **NEVER** push/PR/merge to `origin` (public mirror).

---

## First step — branch

```bash
git fetch cisco
git checkout main
git merge --ff-only cisco/main
git checkout -b TG-190-dhcpv6-validation
```

Work on this branch for any fixes discovered during CP2 validation (e.g. sync mode for `dhcpv6`). Do **not** commit `out/`, `*.tfstate*`, terraform logs, or credentials.

---

## What CP1 already proved (Done — do not redo)

- `--mgmt-ipv6-mode {slaac,dhcpv6}` with `--mgmt` + named `--mgmt-vrf`
- Router templates render `ipv6 address autoconfig` (SLAAC) or `ipv6 address dhcp` (DHCPv6 client) on OOB Gi
- CSR `vrf definition` includes `address-family ipv6`
- Unit tests: `tests/test_mgmt_ipv6_vrf.py`, `tests/test_nac_cli_guardrails.py`
- SLAAC live path validated (mgmt-bridge + external RA)

See `docs/TG-190-checkpoint-1.md` for CP1 scope boundaries.

---

## CP2 goal (this session)

Prove **stateful DHCPv6 client** on the OOB interface acquires a **global IPv6** in `Mgmt-vrf` when:

1. Routers use `ipv6 address dhcp` on OOB Gi (Gi0/5 iosv / Gi5 csr)
2. `--mgmt-bridge` connects `SWoob0` → `ext-conn-mgmt` (System Bridge) to the **CML host**
3. The **external DHCPv6 server already on the CML host** serves leases (operator-managed — **not** an in-lab node)

Deploy and validate **two** small flat labs (6 routers each):

| Lab title | Template | Device |
|-----------|----------|--------|
| `TG-190-dhcpv6-iosv6` | `iosv` | `iosv` |
| `TG-190-dhcpv6-csr6` | `csr-ospf` | `csr1000v` |

---

## Generate commands (correct — no extras)

**Do not** add `--mgmt-ipv6-cidr` unless the operator explicitly asks. It is optional metadata only; it does not change `ipv6 address dhcp` on the router.

**Do not** add an in-lab `mgmt-dhcp6` / dnsmasq node. External server only.

```powershell
# IOSv — 6-node flat
python -m topogen --cml-version 0.3.1 -L "TG-190-dhcpv6-iosv6" `
  6 --mode flat -T iosv --device-template iosv `
  --offline-yaml "out/TG-190-dhcpv6-iosv6/TG-190-dhcpv6-iosv6.yaml" `
  --nac --bootstrap --terraform-cml2 --overwrite `
  --mgmt --mgmt-vrf Mgmt-vrf --mgmt-ipv6-mode dhcpv6 --mgmt-bridge

# CSR1000v — 6-node flat
python -m topogen --cml-version 0.3.1 -L "TG-190-dhcpv6-csr6" `
  6 --mode flat -T csr-ospf --device-template csr1000v `
  --offline-yaml "out/TG-190-dhcpv6-csr6/TG-190-dhcpv6-csr6.yaml" `
  --nac --bootstrap --terraform-cml2 --overwrite `
  --mgmt --mgmt-vrf Mgmt-vrf --mgmt-ipv6-mode dhcpv6 --mgmt-bridge
```

---

## Live deploy

Prerequisites (shell):

```powershell
$env:TF_VAR_address = "https://192.168.1.183"   # CML controller
$env:TF_VAR_username = "..."
$env:TF_VAR_password = "..."
$env:TF_VAR_skip_verify = "true"
$env:VIRL2_URL = $env:TF_VAR_address
$env:VIRL2_USER = $env:TF_VAR_username
$env:VIRL2_PASS = $env:TF_VAR_password
$env:IOSXE_USERNAME = "cisco"
$env:IOSXE_PASSWORD = "cisco"
```

**Operator caveat — CML 2.10 + pyATS (not MCP):**

- Generate with `--cml-version 0.3.1` (CML **2.10** schema). Built-in **pyATS runs on the CML controller**, not on the operator PC.
- Mgmt sync uses `nac/sync-nac-mgmt.py` + `VIRL2_*` API — **not** CML MCP (MCP is Cursor/agent-only).
- Pass `--set-pyats-creds` on sync so nodes have pyATS CLI credentials (defaults match bootstrap `cisco`/`cisco`).
- `terraform -var=wait=true` waits for **BOOTED**, not DHCPv6/SLAAC addresses — retry sync until `mgmt_sync.json` shows all routers.
- Fallback: `--cml-snoop-only` if controller pyATS fails. See `DEVELOPER.md` → *CML 2.10, pyATS, and mgmt sync*.

Per lab:

```powershell
Set-Location "out/<lab>/cml2"
terraform init -input=false
terraform apply -auto-approve -var="wait=true"
$labId = terraform output -raw lab_id
```

If apply fails with `import lab: system not ready`, wait for CML to finish booting/restarting and retry. Confirm API reachability before blaming the lab YAML.

---

## CP2 pass criteria (per lab, sample R1 + spot-check R3/R6)

After BOOTED, set pyATS creds on routers if needed (`cisco` / `cisco` / enable `cisco`).

**Config smoke (CP1 — must still pass):**

- `show run int GigabitEthernet0/5` (iosv) or `GigabitEthernet5` (csr)
  - `vrf forwarding Mgmt-vrf`
  - `ipv6 enable`
  - `ipv6 address dhcp`
- CSR: `show run vrf definition Mgmt-vrf` includes `address-family ipv6`

**Address acquisition (CP2 — new):**

- `show ipv6 interface <mgmt-intf>` — up/up; global unicast from DHCPv6 (not link-local only)
- `show ipv6 dhcp interface` — bound / valid lease (iosv/csr syntax as applicable)
- Optional: ping6 from R1 to CML host or another router mgmt address in same VRF

Record evidence under `out/<lab>/live/` (CLI snippets, `mgmt_sync.json` if sync run).

---

## Mgmt sync + NaC (optional CP2 extension)

After addresses are acquired, sync into NaC inventory:

```powershell
python "out/<lab>/nac/sync-nac-mgmt.py" `
  --lab-id $labId --nac-root "out/<lab>/nac" --set-pyats-creds
```

Re-run if addresses are not ready on first pass. Use `--cml-snoop-only` only when controller pyATS is unavailable.

`default_sync_mode_from_args()` maps `dhcpv6` and `slaac` to the IPv6 sync path. If sync still fails, check CP2 address acquisition on the router first.

NaC apply (CSR only if iosv lacks NETCONF — iosv may stop at sync evidence):

```powershell
Set-Location "out/<lab>/nac"
terraform init -input=false
terraform apply -auto-approve -parallelism=1   # csr: use -parallelism=1 if parallel NETCONF races
```

---

## Teardown

Only when operator confirms:

```powershell
Set-Location "out/<lab>/cml2"
terraform destroy -auto-approve
```

---

## Constraints (read carefully)

| Do | Don't |
|----|--------|
| Use `--mgmt-bridge` + external CML DHCPv6 | Add in-lab DHCPv6 server nodes (TG-87) |
| Use flags the operator asked for only | Add `--mgmt-ipv6-cidr` unless explicitly requested |
| Create branch `TG-190-dhcpv6-validation` | Push to `origin` |
| Minimal fixes for dhcpv6 sync if CP2 blocked | Large refactors or TG-192 pipeline changes |
| Commit only source/test/doc fixes | Commit `out/`, tfstate, logs, secrets |

---

## Acceptance checklist

- [ ] Branch `TG-190-dhcpv6-validation` from `cisco/main`
- [ ] `TG-190-dhcpv6-iosv6` generated **without** `--mgmt-ipv6-cidr`; deployed; 6/6 BOOTED
- [ ] `TG-190-dhcpv6-csr6` generated **without** `--mgmt-ipv6-cidr`; deployed; 6/6 BOOTED
- [ ] CP1 config lines present on OOB Gi (both device types)
- [ ] CP2: global IPv6 via DHCPv6 on mgmt intf (sample + spot-check)
- [ ] Evidence captured under `out/*/live/` (not committed)
- [ ] If sync broken for `dhcpv6`: fix `default_sync_mode_from_args` + test; PR to **cisco**
- [ ] Update `docs/TG-190-checkpoint-1.md` or `CHANGES.md` with CP2 results when complete
- [ ] Jira TG-190 comment with lab IDs, pass/fail, and CP2 notes

---

## Jira summary (paste into TG-190 comment when CP2 passes)

TG-190 CP2: Live DHCPv6 client on OOB (`ipv6 address dhcp` + `--mgmt-bridge` + external CML DHCPv6). Validated 6× iosv flat (`TG-190-dhcpv6-iosv6`) and 6× csr flat (`TG-190-dhcpv6-csr6`). Config smoke + global address acquisition on Mgmt-vrf. Branch: `TG-190-dhcpv6-validation`. No in-lab DHCPv6 server (TG-87 remains separate).
