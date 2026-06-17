# TG-195 — AI implementation prompt
# Static IPv6 on OOB management interface (FF10 embedding)
# Copy everything below this line into Jira TG-195 or a fresh Cursor agent chat.

You are implementing **TG-195** in the topogen repo.

- **Jira:** [TG-195](https://roberthosford.atlassian.net/browse/TG-195)
- **Canonical remote:** `https://wwwin-github.cisco.com/rohosfor/topogen.git` (`cisco` remote)
- **Branch:** `TG-195-static-ipv6-oob` (from `cisco/main` — includes TG-194 `--cml-server`)
- **Parent epic:** [TG-189](https://roberthosford.atlassian.net/browse/TG-189) (IPv6 on OOB management plane)
- **Prerequisites (Done on `cisco/main`):**
  - **TG-190** — dynamic OOB IPv6 (`--mgmt-ipv6-dhcp`, `--mgmt-ipv6-slaac`, legacy `--mgmt-ipv6-mode`)
  - **TG-191** — NaC mgmt sync scaffold (`nac/sync-nac-mgmt.py`, `nac_mgmt_sync.py`)
  - **TG-194** — `--cml-server 2.10` maps to schema `0.3.1` (prefer `--cml-server 2.10` in examples)
- **Related (not this ticket):** TG-83 (broader deterministic mgmt), TG-87 (dnsmasq DHCPv6 server)

**Git policy:** Push, PR, and merge **only** to `cisco`. **NEVER** push/PR/merge to `origin` (public mirror) unless the operator explicitly asks.

---

## Problem

TG-190 delivered **dynamic** OOB IPv6 (SLAAC/DHCPv6). `--mgmt-ipv6-cidr` is **metadata only** today — it does not render `ipv6 address` on IOSv Gi0/5 or CSR Gi5.

Operators who know their prefix at generate time need **static** IPv6 on OOB, with NaC `ansible_host` populated **without** `sync-nac-mgmt`.

---

## Goal

Add **explicit opt-in** static IPv6 OOB for **IOS/CSR routers only** (`R1`…`R{n}`):

1. Render `ipv6 address <global>/<len>` on OOB in mgmt VRF (IOSv + CSR).
2. **FF10 embedding** from mgmt IPv4 carve + operator `--mgmt-ipv6-cidr /64`.
3. Optional **`--mgmt-ipv6-static-link-local`**: one `fe80::FF10:…` per router from **Loopback0**, same on every IPv6-enabled interface.
4. NaC inventory at generate time — no live sync.
5. Fail-fast mutual exclusion with dynamic IPv6 flags.

**No host auto-detect** (`--mgmt-ipv6-prefix-from-host` deferred). Operator supplies explicit `/64`.

**Never** commit real ISP prefixes in docs/tests — use `2001:db8:1:2::/64` or `fd80::/64` only.

---

## Design decisions

| Topic | TG-195 plan |
|-------|-------------|
| Global algorithm | IPv4 mgmt carve (`mgmt_net.network_address + router_index`) → `{anchor}:FF10:254:{c}:{d}/64` |
| Sentinel | **FF10** (avoids SLAAC EUI-64 **FFFE**) |
| Prefix | **`--mgmt-ipv6-cidr /64` required** with `--mgmt-ipv6-static` |
| Link-local | Optional; from **loopback** `10.20.hi.lo` → `fe80::FF10:20:{hi}:{lo}` (not mgmt carve) |
| Scope | Routers only; skip `loopback is None` |
| NaC `ansible_host` | Global only — never link-local |

### Address reference (default `--mgmt-cidr 10.254.0.0/16`)

| Router | Loopback0 | Mgmt IPv4 | Global (`2001:db8:1:2::/64`) | Link-local (flag) |
|--------|-----------|-----------|-------------------------------|-------------------|
| R1 | `10.20.0.1` | `10.254.0.1` | `2001:db8:1:2:FF10:254:0:1/64` | `fe80::FF10:20:0:1` |
| R3 | `10.20.0.3` | `10.254.0.3` | `2001:db8:1:2:FF10:254:0:3/64` | `fe80::FF10:20:0:3` |

ULA anchor `fd80::/64`: R1 global `fd80::FF10:254:0:1/64`.

### Operator logging (INFO per router)

```text
mgmt IPv6 static R1: global=2001:db8:1:2:FF10:254:0:1/64 loopback=10.20.0.1 link-local=fe80::FF10:20:0:1
```

---

## CLI flag matrix

### New flags

| Flag | Requires | Conflicts with | Effect |
|------|----------|----------------|--------|
| `--mgmt-ipv6-static` | `--mgmt`, named `--mgmt-vrf`, `--mgmt-ipv6-cidr /64` | `--mgmt-ipv6-dhcp`, `--mgmt-ipv6-slaac`, `--mgmt-ipv6-mode` | Static global OOB |
| `--mgmt-ipv6-static-link-local` | `--mgmt-ipv6-static` | — | Loopback-derived LL on all `ipv6 enable` ifaces |

### Must fail (exit 2)

| Combination |
|-------------|
| `--mgmt-ipv6-static` without `--mgmt` or without named `--mgmt-vrf` |
| `--mgmt-ipv6-static` without `--mgmt-ipv6-cidr` |
| `--mgmt-ipv6-static-link-local` without `--mgmt-ipv6-static` |
| `--mgmt-ipv6-static` + `--mgmt-ipv6-dhcp` / `--mgmt-ipv6-slaac` / `--mgmt-ipv6-mode` |
| Invalid `--mgmt-ipv6-cidr` |

### Valid examples

```bash
# Minimal static global
topogen -m flat 2 -T iosv --device-template iosv \
  --mgmt --mgmt-vrf Mgmt-vrf \
  --mgmt-ipv6-static --mgmt-ipv6-cidr fd80::/64 \
  --cml-server 2.10 --offline-yaml out/TG-195/iosv-flat2.yaml --overwrite

# Global + static link-local
topogen -m flat 2 -T iosv --device-template iosv \
  --mgmt --mgmt-vrf Mgmt-vrf \
  --mgmt-ipv6-static --mgmt-ipv6-static-link-local \
  --mgmt-ipv6-cidr 2001:db8:1:2::/64 \
  --cml-server 2.10 --offline-yaml out/TG-195/iosv-doc-ll.yaml --overwrite

# NaC without sync
topogen -m flat 2 -T iosv --device-template iosv \
  --mgmt --mgmt-vrf Mgmt-vrf \
  --mgmt-ipv6-static --mgmt-ipv6-cidr fd80::/64 --nac \
  --offline-yaml out/TG-195/nac-flat2.yaml --overwrite
```

---

## Code touchpoints

| Area | File |
|------|------|
| CLI + guardrails | `src/topogen/main.py` |
| Address helpers | `src/topogen/mgmt_addressing.py` (**new**) |
| Mgmt context | `src/topogen/render.py` |
| OOB templates | `src/topogen/templates/_iosv_mgmt_oob.jinja2`, `_csr_mgmt_oob.jinja2` |
| Shared LL partial | `src/topogen/templates/_static_link_local.jinja2` (**new**) |
| Data-plane hook | `iosv.jinja2`, `csr1000v.jinja2` (where `ipv6 enable` exists) |
| NaC | `src/topogen/nac.py`, `nac_mgmt_sync.py` |
| Tests | see Test matrix below |
| Docs | `README.md`, `DEVELOPER.md`, `CHANGES.md`, `TODO.md` |

### `mgmt_addressing.py`

- `mgmt_ipv4_static_host(mgmt_cidr, router_index) -> IPv4Address`
- `parse_static_ipv6_anchor(cidr) -> IPv6Network` (normalize `/64`)
- `mgmt_ipv6_static_address(ipv4_host, anchor, mgmt_cidr) -> IPv6Interface`
- `mgmt_ipv6_static_link_local(loopback_host) -> IPv6Address`

### Templates (static branch)

```jinja2
{%- elif ipv6_mode == 'static' %}
    ipv6 address {{ mgmt.ipv6_address }}
    {% include '_static_link_local.jinja2' %}
```

---

## Test matrix

### Test file layout

| File | What |
|------|------|
| `tests/test_mgmt_addressing.py` | **New** — unit tests U01–U09 |
| `tests/test_mgmt_ipv6_vrf.py` | Offline render R01–R12, R-N01–R-N02 |
| `tests/test_nac_cli_guardrails.py` | CLI N01–N10, P01–P04 |
| `tests/test_nac_writer.py` | NaC NAC01–NAC05 |

**Conventions:** negatives → `SystemExit`, stderr substring; fixtures use `fd80::/64` and `2001:db8:1:2::/64` only.

**Shared argv base:** `2 --mode flat -T iosv --device-template iosv --mgmt --mgmt-vrf Mgmt-vrf`

### A. Unit tests — `test_mgmt_addressing.py` (positive)

| ID | Test name | Input | Expected |
|----|-----------|-------|----------|
| U01 | `test_global_fd80_r1` | mgmt `10.254.0.1`, `fd80::/64` | `fd80::FF10:254:0:1/64` |
| U02 | `test_global_fd80_r2` | mgmt `10.254.0.2`, `fd80::/64` | `fd80::FF10:254:0:2/64` |
| U03 | `test_global_doc_prefix_r1` | mgmt `10.254.0.1`, `2001:db8:1:2::/64` | `2001:db8:1:2:FF10:254:0:1/64` |
| U04 | `test_global_third_octet` | mgmt `10.254.2.1`, doc prefix | `2001:db8:1:2:FF10:254:2:1/64` |
| U05 | `test_link_local_default_loopback_r1` | loopback `10.20.0.1` | `fe80::FF10:20:0:1` |
| U06 | `test_link_local_default_loopback_r3` | loopback `10.20.0.3` | `fe80::FF10:20:0:3` |
| U07 | `test_link_local_loopback_255_r1` | loopback `10.255.0.1` | `fe80::FF10:255:0:1` |
| U08 | `test_parse_anchor_normalizes_slash64` | `/48` or `/56` input | normalized `/64` |
| U09 | `test_no_real_prefix_in_fixtures` | module constants | no `2001:db8:` in test data |

### B. CLI guardrails — `test_nac_cli_guardrails.py`

#### B1. Negative (must fail)

| ID | Test name | Extra flags | stderr substring |
|----|-----------|-------------|------------------|
| N01 | `test_static_requires_mgmt` | static + cidr, no `--mgmt` | `IPv6 OOB` or `require --mgmt` |
| N02 | `test_static_requires_named_mgmt_vrf` | static + cidr, no `--mgmt-vrf` | `named --mgmt-vrf` |
| N03 | `test_static_rejects_global_vrf` | `--mgmt-vrf global` + static | `named --mgmt-vrf` |
| N04 | `test_static_requires_ipv6_cidr` | static only | `--mgmt-ipv6-cidr` |
| N05 | `test_static_rejects_invalid_cidr` | bad cidr | `Invalid --mgmt-ipv6-cidr` |
| N06 | `test_link_local_requires_static` | LL flag only | `--mgmt-ipv6-static` |
| N07 | `test_static_rejects_slaac_flag` | static + `--mgmt-ipv6-slaac` | `conflicts` / `mutually exclusive` |
| N08 | `test_static_rejects_dhcp_flag` | static + `--mgmt-ipv6-dhcp` | `conflicts` / `mutually exclusive` |
| N09 | `test_static_rejects_legacy_mode_slaac` | static + `--mgmt-ipv6-mode slaac` | `conflicts` |
| N10 | `test_static_rejects_legacy_mode_dhcpv6` | static + `--mgmt-ipv6-mode dhcpv6` | `conflicts` |

#### B2. Positive (must parse)

| ID | Test name | Flags |
|----|-----------|-------|
| P01 | `test_valid_static_minimal` | `--mgmt-ipv6-static --mgmt-ipv6-cidr fd80::/64` |
| P02 | `test_valid_static_with_link_local` | P01 + `--mgmt-ipv6-static-link-local` |
| P03 | `test_cidr_without_static_unchanged` | `--mgmt-ipv6-slaac` + cidr only (metadata) |
| P04 | `test_static_doc_prefix_cidr` | static + `2001:db8:1:2::/64` |

### C. Offline render — `test_mgmt_ipv6_vrf.py`

#### C1. Positive

| ID | Test name | Assert |
|----|-----------|--------|
| R01 | `test_iosv_static_global_fd80_r1` | R1 OOB `fd80::FF10:254:0:1/64` |
| R02 | `test_iosv_static_global_r2` | R2 `…:0:2/64` |
| R03 | `test_iosv_static_doc_prefix` | `2001:db8:1:2:FF10:254:0:1/64` |
| R04 | `test_csr_static_global` | CSR Gi5 + `address-family ipv6` |
| R05 | `test_iosv_static_with_link_local` | global + `fe80::FF10:20:0:1 link-local` |
| R06 | `test_iosv_static_link_local_loopback_255` | `fe80::FF10:255:0:1` |
| R07 | `test_iosv_static_no_slaac_stanzas` | no `autoconfig` / `ipv6 address dhcp` |
| R08 | `test_iosv_bootstrap_static_global` | bootstrap static global |
| R09 | `test_iosv_bootstrap_static_link_local` | bootstrap link-local |
| R10 | `test_static_metadata_cidr_only_no_render` | slaac + cidr → still `autoconfig` |
| R11 | `test_loopback_unchanged_with_static` | Loopback0 `10.20.0.1` present |
| R12 | `test_provenance_args_bits` | provenance lists static flags |

#### C2. Negative

| ID | Test name | Expect |
|----|-----------|--------|
| R-N01 | `test_static_without_cidr_exits` | exit != 0 |
| R-N02 | `test_static_plus_slaac_exits` | exit != 0 |

### D. NaC — `test_nac_writer.py`

| ID | Test name | Assert |
|----|-----------|--------|
| NAC01 | `test_nac_static_ansible_host_global` | `ansible_host` = global, not `fe80::` |
| NAC02 | `test_nac_static_mgmt_ipv6_field` | `mgmt.ipv6` matches global |
| NAC03 | `test_nac_static_link_local_metadata` | `mgmt.ipv6_link_local` = `fe80::FF10:20:0:1` |
| NAC04 | `test_nac_metadata_mode_static` | `mgmt_ipv6_mode: static` |
| NAC05 | `test_select_host_prefers_global_not_ll` | `_select_host()` returns global |

### E. Regression

```bash
pytest tests/test_mgmt_addressing.py tests/test_mgmt_ipv6_vrf.py tests/test_nac_cli_guardrails.py tests/test_nac_writer.py -q
pytest tests/test_sync_nac_mgmt_ipv6_slaac.py -q
```

---

## Acceptance criteria

- [ ] `--mgmt-ipv6-static` + `--mgmt-ipv6-cidr` renders static global on OOB (IOSv + CSR)
- [ ] Optional `--mgmt-ipv6-static-link-local` renders loopback-derived LL (routers only)
- [ ] Guardrails: `--mgmt` + named `--mgmt-vrf`; conflicts with dynamic IPv6
- [ ] NaC inventory without live sync
- [ ] All test matrix IDs implemented and green
- [ ] README + DEVELOPER + CHANGES + TODO updated (File Chain revs)
- [ ] PR to `cisco/main`

---

## Out of scope

- `--mgmt-ipv6-prefix-from-host` (host scan)
- TG-87 dnsmasq DHCPv6 server
- Dual-stack static IPv6 + IPv4 DHCP (unless trivial)
- Real ISP prefixes in repo docs/tests
- Committing `out/` artifacts

---

## Operator: choosing `--mgmt-ipv6-cidr`

Copy first **four hextets** of a stable global from `ipconfig` → `--mgmt-ipv6-cidr PREFIX::/64`. Ignore Temporary IPv6 and `fe80::`. Offline labs: use `fd80::/64`.

---

## Definition of done

1. Bump doc revs on touched files
2. `pytest` green (test matrix above)
3. Commit on `TG-195-static-ipv6-oob`, push to `cisco`, open PR
4. Jira closeout: PR URL, test summary, file rev table
