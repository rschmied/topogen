# TG-190 Checkpoint 1 — OOB IPv6 mgmt in VRF (offline render + CML config smoke)

Epic: **TG-189** · Story: **TG-190** · Branch: `TG-190-oob-slaac-dhcpv6`

## In scope (Checkpoint 1 ONLY)

- **CLI:** `--mgmt-ipv6-mode {slaac,dhcpv6}` (requires `--mgmt` + `--mgmt-vrf`, not `global`; compatible with `--mgmt-bridge` for CP2 reachability)
- **CLI:** optional `--mgmt-ipv6-cidr` (SLAAC prefix / DHCPv6 pool hint; carried in render context)
- **`render.py`:** centralized `_build_mgmt_context()` with IPv6 fields
- **Router templates** (`csr1000v.jinja2`, `iosv.jinja2`): OOB management interface gets IPv6 in mgmt VRF — SLAAC (`ipv6 address autoconfig`) or DHCPv6 client (`ipv6 address dhcp`); CSR adds `address-family ipv6` under vrf definition when IPv6 mgmt is enabled
- **Unit tests:** offline render asserts expected lines on OOB Gi; CLI guardrail tests in `tests/test_nac_cli_guardrails.py` and `tests/test_mgmt_ipv6_vrf.py`
- **CML config smoke (CP1):** lab boots; OOB interface shows expected IPv6 mgmt lines in running-config and `show ipv6 interface` (no global SLAAC address required yet)

## Scale: IPv6-only OOB for large labs

Labs with **16 or more routers** and `--mgmt` **must** set `--mgmt-ipv6-mode` (`slaac` or `dhcpv6`) with a named `--mgmt-vrf`. The default IPv4 OOB path (`ip address dhcp` on Gi0/5 / Gi5, or static addresses carved from `--mgmt-cidr`) assigns one IPv4 lease or host per router on the shared management bridge; at 300-node scale this exhausts the bridge DHCP pool and can crash or destabilize the entire lab network. Use `--mgmt-ipv6-mode slaac --mgmt-bridge` (and optional `--mgmt-ipv6-cidr`) for IPv6-only OOB with no IPv4 on the management interface.

## External management bridge (CML — CP2 / address acquisition)

`--mgmt-bridge` bridges `SWoob0` to the CML host via `ext-conn-mgmt` so external RA/DHCPv6 can reach OOB interfaces. **CP1 config smoke** does not require a global SLAAC address; bridge + RA source are needed for live address acquisition (CP2).

## Explicitly OUT of Checkpoint 1

- dnsmasq DHCPv6 server on DNS host (TG-87 / CP2)
- NaC inventory `ansible_host` IPv6 (TG-83 / CP3)
- Dual-stack IPv4+IPv6 on the same OOB interface
- **SLAAC global address acquisition** on OOB (needs RA/dnsmasq or external prefix — CP2)
- Full topology-mode regression matrix (see follow-up below)

## Checkpoint 1 DONE when

```bash
pytest tests/test_mgmt_ipv6_vrf.py tests/test_nac_cli_guardrails.py -q
```

passes, and offline render with:

```bash
topogen 2 --mode simple --offline-yaml out.yaml --mgmt --mgmt-vrf Mgmt-vrf --mgmt-ipv6-mode slaac -T csr1000v
```

shows IPv6 on `GigabitEthernet5` (CSR) or `GigabitEthernet0/5` (IOSv), vrf IPv6 address-family (CSR), and **no regression** on the default IPv4 `--mgmt` path (`ip address dhcp`).

## CML config smoke (initial validation — flat mode first)

Initial live CML validation uses **flat** mode (not simple). A full mode matrix is follow-up work after flat passes.

Set controller credentials in the shell (`VIRL2_*`; `-i` if the controller uses a self-signed cert):

```bash
# PowerShell
$env:VIRL2_URL = "https://192.168.1.183"
$env:VIRL2_USER = "admin"
$env:VIRL2_PASS = "<secret>"

topogen --cml-version 0.3.1 -L "TG-190-SLAAC-CP1-flat" `
  -m flat -T iosv --device-template iosv `
  --mgmt --mgmt-vrf Mgmt-vrf --mgmt-ipv6-mode slaac `
  --mgmt-ipv6-cidr fd00:10:254::/64 `
  -i 4
```

Use a **new lab title** with a `-flat` suffix if an earlier `TG-190-SLAAC-CP1` simple-mode lab already exists.

After boot, set pyATS creds on IOSv routers (`cisco` / `cisco` / enable `cisco`), then on **R1** (CML MCP `send_cli_command`):

- `show run int Gi0/5` — expect `vrf forwarding Mgmt-vrf`, `ipv6 enable`, `ipv6 address autoconfig`
- `show ipv6 interface GigabitEthernet0/5` — up/up; `VPN Routing/Forwarding "Mgmt-vrf"`; link-local present; `Stateless address autoconfig enabled`
- `show ipv6 interface brief` — Gi0/5 up with link-local (IOSv does not accept `show ipv6 interface vrf <name>`)

**CP1 pass criteria:** config smoke only (correct lines on OOB Gi in VRF). **CP1 does not require** a global SLAAC address on the OOB interface.

## Follow-up: full topology mode test matrix (not CP1)

Run after flat CP1 smoke passes. Same IPv6 mgmt flags; vary `-m` / node count as appropriate:

| Mode | Notes |
|------|--------|
| `simple` | Minimal 2-router smoke (offline + CML) |
| `flat` | **First** live CML target (4 routers) |
| `flat-pair` | Odd/even pair links + OOB |
| `nx` | NX-style layout |
| `dmvpn` + `--mgmt` | Overlay + OOB (flat underlay default) |
| `dmvpn` + `--dmvpn-underlay flat-pair` + `--mgmt` | DMVPN on flat-pair underlay |

CSR1000v variants mirror IOSv where templates differ (`GigabitEthernet5` vs `GigabitEthernet0/5`).
