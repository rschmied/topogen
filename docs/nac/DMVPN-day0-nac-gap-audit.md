# DMVPN day-0 ≡ NaC gap audit (TopoGen)

**Date:** 2026-06-08  
**Branch audited:** `main` (post TG-162 merge)  
**Pinned module:** `netascode/nac-iosxe/iosxe` **0.1.0**  
**Day-0 source:** `src/topogen/templates/csr-dmvpn.jinja2`, `iosv-dmvpn.jinja2`  
**NaC projection:** `src/topogen/nac.py` → `out/<lab>/nac/nac.yaml` (`iosxe.devices[].configuration.*`)  
**Automation:** `scripts/audit-dmvpn-day0-nac-gap.py --scan-existing`

Artifacts generated under `out/TG-GAP-AUDIT-*` (offline only; no CML apply).

---

## Executive summary

| Metric | Value |
|--------|-------|
| DMVPN-specific feature categories audited | **22** (interfaces, tunnel attrs, NHRP, routing, crypto, PKI, mgmt) |
| **Already aligned** on nac-iosxe 0.1.0 | **9** (~41%) |
| **Module blocked** (no 0.1.0 schema) | **8** (~36%) |
| **Keep day-0** (intentionally non-TF) | **3** (~14%) |
| **Emit** (TopoGen should fix/extend projection) | **2** (~9%) |

**Approximate TF-ownable day-0 today:** **~45–50%** of DMVPN-meaningful configuration.  
Boilerplate (SSH, users, EEM `TOPOGEN-NOSHUT`, `restconf`, base services) is excluded from this percentage.

### Can Terraform handle **3 hubs + PKI + IKEv2**?

**Answer: partial — not production-complete.**

| Layer | Terraform would own | Terraform would **not** own |
|-------|---------------------|-----------------------------|
| Interfaces | NBMA `GigabitEthernet1`, `Tunnel0` IPv4, `Loopback0` on all 6 routers | Pair links (N/A in flat 3-hub), OOB `GigabitEthernet5` |
| Tunnel attrs | `tunnel_source`, `ipv4.redirects: false`, `tunnel_protection_ipsec_profile: TOPGEN-IPSEC` | `tunnel mode gre multipoint`, `tunnel key`, NHRP hub/spoke maps, split-horizon |
| Crypto | **Nothing today** for IKEv2-PKI (see Emit gap) | IKEv2 rsa-sig profile body, IPsec transform/profile resources, `pki trustpoint` binding |
| PKI | — | CA-ROOT bootstrap, enrollment URL, auto-enroll, authenticate aliases (day-0 + `--pki`) |
| Routing | — | `router eigrp` (global or VRF AF) on all routers |

`terraform plan` on `out/TG-GAP-AUDIT-3hub-pki/nac/` succeeds but plans **only** system + L3 interfaces + tunnel protection **reference** — **no** `iosxe_crypto_*` resources. Apply would reference `TOPGEN-IPSEC` that Terraform never creates.

**PSK path (3-hub + IKEv2-PSK):** interfaces + full IKEv2-PSK/IPsec stack + tunnel protection are TF-ownable; NHRP/EIGRP/mGRE/tunnel-key remain day-0.

---

## TG-162 acceptance criteria cross-check

| Criterion (TG-162) | Status | Notes |
|--------------------|--------|-------|
| Tunnel source/dest/mode/key | **Partial** | `tunnel_source` + tunnel IPv4 modeled; **mode/key blocked** (no schema) |
| NHRP | **Blocked** | No NHRP resources in 0.1.0; hub/spoke day-0 differs, NaC identical |
| Tunnel protection | **Partial** | Flag emitted for PSK/PKI/RSA; **PKI crypto body missing** (Emit) |
| Routing over tunnel | **Blocked** | EIGRP only in day-0; module has OSPF processes, not EIGRP |
| PKI / trustpoint | **Partial** | Day-0 owns enrollment; NaC emits protection profile name only |

---

## Hub vs spoke (multi-hub)

Day-0 (`csr-dmvpn.jinja2`) branches on `is_hub`:

- **Hubs (R1,R3,R5 in P2):** `ip nhrp map multicast dynamic`, inter-hub `ip nhrp map <tunnel> <nbma>`, optional Phase 3 `ip nhrp redirect`, `no ip split-horizon eigrp`
- **Spokes (R2,R4,R6):** per-hub `ip nhrp map`, `ip nhrp nhs`, optional `ip nhrp shortcut`

**NaC today:** `nac.py` projects the **same** `interfaces.tunnels[]` shape for every router (only IPv4 addresses differ). No hub/spoke NHRP distinction is possible until nac-iosxe exposes NHRP resources and TopoGen maps role-aware data.

---

## Full feature matrix (all profiles)

Legend — **Gap class:** `Already aligned` | `Emit` | `Module blocked` | `Keep day-0`

| Feature (IOS CLI) | P1 | P2 | P3 | P4 | P5 | P6 | P7 | P8 | NaC / TF today | Gap class | Recommended action | Owner |
|-------------------|----|----|----|----|----|----|----|----|----------------|-----------|-------------------|-------|
| `hostname` | R* | R* | R* | R* | R* | R* | R* | R* | `system.hostname` | Already aligned | — | — |
| NBMA `interface GigabitEthernet*` IPv4 | R* | R* | R* | R* | R1,R3 | R* | R* | R* | `ethernets[]` | Already aligned | — | TopoGen |
| Pair link `GigabitEthernet2` | — | — | — | — | R1,R3 | — | — | — | `ethernets[]` + `vrf_forwarding` | Already aligned | — | TopoGen |
| `Loopback0` IPv4 | R* | R* | R* | R* | R* | R* | R* | R* | `loopbacks[]` | Already aligned | — | TopoGen |
| `Tunnel0` IPv4 | R* | R* | R* | R* | R1,R3 | R* | R* | R* | `tunnels[]` | Already aligned | — | TopoGen |
| `tunnel source` | R* | R* | R* | R* | R1,R3 | R* | R* | R* | `tunnel_source` (CSR: `GigabitEthernet1`, IOSv: `GigabitEthernet0/0`) | Already aligned | — | TopoGen |
| `no ip redirects` | R* | R* | R* | R* | R1,R3 | R* | R* | R* | `ipv4.redirects: false` | Already aligned | — | TopoGen |
| Overlay VRF (`--vrf --pair-vrf`) | — | — | — | — | R1–R4 | — | — | — | `vrf_forwarding` on tunnel/loopback/pair; `vrfs[]` | Already aligned | — | TopoGen |
| Front-side VRF (`--dmvpn-fvrf`) | — | — | — | — | — | R* | — | — | NBMA `vrf_forwarding`, `tunnel_vrf`, `ip_mtu: 1360`, `vrfs[]` | Already aligned | — | TopoGen |
| IKEv2-PSK + IPsec stack | — | — | R* | — | — | — | — | — | `configuration.crypto.*` (full stack) | Already aligned | — | TopoGen |
| `tunnel protection ipsec profile` | — | — | R* | R* | — | — | — | — | `tunnel_protection_ipsec_profile` | Partial | P4/PKI: emit crypto **or** omit protection until crypto exists | TopoGen |
| IKEv2-PKI rsa-sig + `pki trustpoint` | — | — | — | R* | — | — | — | — | **Not projected** (protection flag only) | Emit | Extend `_build_dmvpn_crypto_configuration` when 0.1.0+ supports PKI IKEv2 | TopoGen + upstream |
| `tunnel mode gre multipoint` | R* | R* | R* | R* | R1,R3 | R* | R* | R* | — | Module blocked | Document; upstream NHRP/tunnel-mode issue | nac-iosxe |
| `tunnel key` | R* | R* | R* | R* | R1,R3 | R* | R* | R* | — | Module blocked | Same | nac-iosxe |
| NHRP network-id / auth | R* | R* | R* | R* | R1,R3 | R* | R* | R* | — | Module blocked | Role-aware maps/NHS when schema exists | nac-iosxe + TopoGen |
| NHRP hub `map multicast dynamic` | R1 | R1,R3,R5 | R1 | R1 | R1,R3 | R1 | R1 | R1 | — | Module blocked | Hub-specific projection | nac-iosxe + TopoGen |
| NHRP spoke `nhs` + maps | R2,R3 | R2,R4,R6 | R2,R3 | R2,R3 | — | R2,R3 | R2,R3 | R2,R3 | — | Module blocked | Spoke-specific projection | nac-iosxe + TopoGen |
| Phase 3 redirect / shortcut | — | — | — | — | — | — | — | — | — | Module blocked | Default phase 2 in audit profiles | nac-iosxe |
| `router eigrp` (+ VRF AF) | R* | R* | R* | R* | R* | R* | R* | R* | — | Module blocked | Upstream EIGRP or OSPF migration decision | nac-iosxe / product |
| PKI enrollment / CA-ROOT | — | — | — | R* | — | — | — | — | — | Keep day-0 | CA bootstrap, enrollment timing, `--pki` staging | TopoGen day-0 |
| OOB `GigabitEthernet5` DHCP + `Mgmt-vrf` | — | — | — | — | — | — | R* | — | **Excluded** from `configuration.*` (TG-163) | Keep day-0 | Never emit in `ethernets[]`; sync `host` post-DHCP | TopoGen |
| IOSv live NaC apply | — | — | — | — | — | — | — | R* | Projection OK; **device unsupported** for NETCONF apply | Keep day-0 | IOSv for naming audit only; CSR1000v for live apply | Docs |

`R*` = all DMVPN routers in profile. P2 = 6 routers (3 hubs, 3 spokes).

---

## Emit items (ranked by impact)

1. **IKEv2-PKI / IKEv2-RSA crypto body** — `_build_dmvpn_crypto_configuration()` only handles `ikev2-psk` (`nac.py:209–215`). PKI profiles emit `tunnel_protection_ipsec_profile` without creating `TOPGEN-IPSEC` in TF → broken apply. *Blocked on upstream PKI/trustpoint schema; until then omit protection flag or document apply order.*
2. **FVRF + IKEv2-PSK `match fvrf`** — Already implemented in PSK builder when `--dmvpn-fvrf` set; add regression test for P6+PSK combo (Emit test coverage, not new schema).

---

## Terraform plan sanity (recorded)

| Profile | Command | Plan result | Notable resources |
|---------|---------|-------------|-------------------|
| P3 PSK | `pytest -k dmvpn` (matrix `dmvpn-flat-psk-iosv`) | **Pass** | `iosxe_interface_tunnel`, `iosxe_crypto_ikev2_*`, `iosxe_crypto_ipsec_*`, `tunnel_protection_ipsec_profile` |
| P1 baseline CSR | `pytest -k dmvpn-flat-csr` | **Pass** | tunnel + `tunnel_source`; no crypto |
| P4 PKI | Manual `terraform plan` in `out/TG-GAP-AUDIT-P4-pki/nac/` | **Pass** (12 add) | system, ethernet, tunnel, loopback — **no crypto** despite `tunnel_protection_ipsec_profile` |

---

## Per-profile appendix (CLI snippets)

### P1 — Baseline 1-hub CSR (`out/TG-GAP-AUDIT-P1-baseline-1hub/`)

**Hub R1 (day-0 excerpt):**

```
interface Tunnel0
 ip address 172.20.0.1 255.255.0.0
 no ip redirects
 tunnel source GigabitEthernet1
 tunnel key 10
 tunnel mode gre multipoint
 ip nhrp network-id 10
 ip nhrp authentication DMVPNKEY
 ip nhrp map multicast dynamic
 no ip split-horizon eigrp 100
```

**Spoke R2 (day-0 excerpt):**

```
interface Tunnel0
 ip address 172.20.0.2 255.255.0.0
 no ip redirects
 tunnel source GigabitEthernet1
 tunnel key 10
 tunnel mode gre multipoint
 ip nhrp network-id 10
 ip nhrp authentication DMVPNKEY
 ip nhrp map 172.20.0.1 10.10.0.1
 ip nhrp map multicast 10.10.0.1
 ip nhrp nhs 172.20.0.1
```

**NaC (both R1 and R2 — identical shape):**

```yaml
tunnels:
  - id: '0'
    ipv4: { address: <per-router>, address_mask: 255.255.0.0, redirects: false }
    tunnel_source: GigabitEthernet1
```

### P2 — 3-hub (`out/TG-GAP-AUDIT-P2-3hub/`)

**Hub R3 (day-0):** hub maps to peer hubs R1 and R5 (`ip nhrp map 172.20.0.1 …`, `ip nhrp map 172.20.0.5 …`) plus `map multicast dynamic`.

**Spoke R4 (day-0):** three `ip nhrp nhs` (R1, R3, R5) and matching static maps.

**NaC:** same tunnel block on all six devices — no hub/spoke NHRP semantics.

### P3 — IKEv2-PSK (`out/TG-GAP-AUDIT-P3-psk/`)

Day-0 and NaC both carry full `TOPGEN-*` IKEv2-PSK + IPsec stack; NaC adds `tunnel_protection_ipsec_profile: TOPGEN-IPSEC`. NHRP/EIGRP/mGRE remain day-0 only.

### P4 — PKI (`out/TG-GAP-AUDIT-P4-pki/`)

**Hub R1 (day-0 crypto excerpt):**

```
crypto ikev2 profile TOPGEN-IKEV2
 match identity remote fqdn domain virl.lab
 identity local fqdn R1.virl.lab
 authentication remote rsa-sig
 authentication local rsa-sig
 pki trustpoint CA-ROOT-SELF
crypto ipsec profile TOPGEN-IPSEC
 set transform-set TOPGEN-TS
 set ikev2-profile TOPGEN-IKEV2
```

**NaC:** `tunnel_protection_ipsec_profile: TOPGEN-IPSEC` only — no `configuration.crypto`.

### P7 — Mgmt bridge (`out/TG-GAP-AUDIT-P7-mgmt/`)

**Day-0 R1:**

```
vrf definition Mgmt-vrf
interface GigabitEthernet5
 description OOB Management
 vrf forwarding Mgmt-vrf
 ip address dhcp
```

**NaC:** no `GigabitEthernet5` in `configuration.interfaces.ethernets`; `host` empty until DHCP sync (`nac.py` TG-163). Correct by design.

### P8 — IOSv naming (`out/TG-GAP-AUDIT-P8-iosv/`)

Day-0: `tunnel source GigabitEthernet0/0`. NaC: `tunnel_source: GigabitEthernet0/0`, `ethernets[].id: '0/0'`. IOSv cannot live NaC apply (classic IOS / no NETCONF).

---

## Extension of DEVELOPER.md matrix (TG-162)

The table in `DEVELOPER.md` § “NaC DMVPN coverage matrix (TG-162)” remains authoritative for 0.1.0 scope. This audit **confirms** those rows and adds:

- **Emit:** IKEv2-PKI crypto projection gap (protection without profile resources)
- **Operational:** 3-hub NaC parity (same tunnel model on hubs and spokes)
- **TG-163 verified:** P7 OOB Gi5 excluded from TF interfaces
- **IOSv:** projection correct; live apply out of scope

---

## Jira breakdown (created)

**Epic:** TG-170 — DMVPN day-0 ≡ NaC — close projection gaps and track nac-iosxe upstream  
**Prior audit (Done):** TG-162 — relates to TG-170

| Key | Type | Summary |
|-----|------|---------|
| TG-171 | Story | Emit IKEv2-PKI crypto in NaC when nac-iosxe schema supports it |
| TG-172 | Story | Guard DMVPN tunnel protection when crypto body is absent in NaC |
| TG-173 | Task | Design multi-hub DMVPN NaC hub vs spoke role model |
| TG-174 | Task | Upstream spike: nac-iosxe NHRP, mGRE mode, and tunnel-key |
| TG-175 | Task | Upstream spike: EIGRP routing strategy for DMVPN NaC |
| TG-176 | Story | FVRF + IKEv2-PSK DMVPN NaC regression coverage |
| TG-177 | Task | Wire DMVPN day-0 NaC gap audit script into CI or release checklist |
| TG-178 | Story | 3-hub + PKI DMVPN live validation playbook |

### Original proposed breakdown (for reference)

1. **Emit IKEv2-PKI crypto when schema allows** → TG-171  
   - *AC:* Given `--dmvpn-security ikev2-pki`, `nac.yaml` includes IKEv2 rsa-sig profile + IPsec profile resources OR omits `tunnel_protection_ipsec_profile` until crypto exists; `terraform plan` shows crypto resources for PKI case; unit test in `test_nac_writer.py`.

2. **Guard tunnel protection without crypto body**  
   - *AC:* PKI/RSA profiles do not reference `TOPGEN-IPSEC` in NaC unless matching `configuration.crypto` is emitted; documented in `DEVELOPER.md`.

3. **Multi-hub DMVPN NaC role model (design)**  
   - *AC:* Design doc for hub vs spoke NHRP projection keyed off `is_hub` / `hub_info`; blocked implementation linked to upstream NHRP schema spike.

4. **nac-iosxe upstream spike: NHRP + mGRE + tunnel-key**  
   - *AC:* GitHub issue draft with required IOS-XE resources, sample `nac.yaml`, link to P2 day-0 snippets; no TopoGen code until schema version pinned.

5. **nac-iosxe upstream spike: EIGRP (or routing strategy)**  
   - *AC:* Decision record: wait for EIGRP in module vs migrate labs to OSPF for TF-owned routing; map `router eigrp` day-0 fields.

6. **FVRF + IKEv2-PSK regression**  
   - *AC:* `--dmvpn-fvrf WAN-VRF --dmvpn-security ikev2-psk` projects `match_fvrf`, `tunnel_vrf`, `ip_mtu`; terraform plan passes.

7. **CI: DMVPN gap audit script**  
   - *AC:* `scripts/audit-dmvpn-day0-nac-gap.py --scan-existing` runs in CI or release checklist; fails if P4 regresses to protection-without-crypto undetected.

8. **3-hub + PKI live validation**  
   - *AC:* CSR 6-node PKI profile: apply order (CA → DHCP sync → NaC), CLI checks for tunnel protection + enrolled cert (document in DEVELOPER.md when complete).

---

## Regenerating audit artifacts

```powershell
cd <repo-root>
python scripts/audit-dmvpn-day0-nac-gap.py --generate --overwrite
python scripts/audit-dmvpn-day0-nac-gap.py --scan-existing
```

Individual profile example:

```powershell
python -m topogen 6 --mode dmvpn --dmvpn-hubs 1,3,5 `
  -T csr-dmvpn --device-template csr1000v `
  --dmvpn-security ikev2-pki --pki --staging `
  --offline-yaml out/TG-GAP-AUDIT-3hub-pki.yaml `
  --nac --overwrite
```

---

## References

- `DEVELOPER.md` — NaC DMVPN coverage matrix (TG-162)
- `docs/nac/mapping-matrix.md` — TopoGen → NaC field mapping
- `scripts/validate-tg162-dmvpn-live.ps1` — offline / live DMVPN validation
- `src/topogen/nac.py` — `_build_dmvpn_crypto_configuration`, `_apply_dmvpn_tunnel_configuration`, TG-163 OOB exclusion
- `src/topogen/templates/csr-dmvpn.jinja2` — day-0 hub/spoke branching
