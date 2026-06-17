<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.0
Date Modified: 2026-06-03

- Called by: TG-S2 (Jira TG-133); authoritative input for TG-S4 (TG-135) and TG-S7 (TG-138)
- Reads from: docs/nac/schema-verification.md (TG-S1 confirmed key contract),
  z:\Marco\jira-nac-setup-v3.plan.md (Appendix A + Toolchain),
  src/topogen/models.py, src/topogen/render.py, src/topogen/main.py, src/topogen/nac.py
- Writes to: None (documentation / spec only)
- Calls into: docs/nac/iosxe-one-router-golden-contract.md (superseded device-level model — reconciled below)

Purpose: TG-S2 authoritative mapping matrix. Map every TopoGen internal model field to the
CONFIRMED netascode/nac-iosxe 0.1.0 schema key (iosxe.devices[].configuration.* form), including
per---device-template interface identity, and reconcile the older device-level golden-contract docs.
Blast Radius: Drives the nac.yaml writer (TG-S7) and host/VRF emission (TG-S4). This is a
SPEC/AUDIT deliverable only — no writer code is produced here.
-->

# TG-S2 — TopoGen → NaC Mapping Matrix (`--nac` v3, IOS-XE)

**Ticket:** Jira TG-133 (TG-S2), Epic TG-131 (`--nac v3 Deployable Terraform MVP`).
**Blocked by:** TG-132 (TG-S1) — **DONE**. This doc consumes its confirmed key contract verbatim.

## Source of truth (do not re-derive)

- Confirmed schema keys + source citations: `docs/nac/schema-verification.md` (TG-S1).
- Plan Appendix A + Toolchain: `z:\Marco\jira-nac-setup-v3.plan.md`.
- Target schema family: **`netascode/nac-iosxe 0.1.0`**, `iosxe.devices[].configuration.*` form.
- Toolchain pins (recorded for TG-S8, not emitted by this ticket): Terraform `>= 1.8.0`;
  provider `CiscoDevNet/iosxe = 0.15.0` (**not** 0.18.0); transitive `netascode/utils = 1.1.0-beta3`.

> **Scope note.** TG-S2 is a spec/audit ticket. It does **not** write `nac.py` writer code
> (that is TG-S7) and does **not** modify runtime behavior. Where TopoGen's current internal
> model cannot yet supply a confirmed key, this matrix records the gap as an explicit
> requirement for TG-S4 / TG-S7 rather than inventing data.

---

## 1. Internal model surface (audited from source)

The NaC writer is fed `list[TopogenNode]` via `write_nac_tree(..., nodes=nac_router_nodes, ...)`
plus the render context (`device_template`, `template`, `mode`) — see
`src/topogen/render.py` (e.g. `offline_simple_yaml` lines ~5855–6043) and
`src/topogen/nac.py::write_nac_tree`.

Internal dataclasses (`src/topogen/models.py`):

```text
TopogenNode:
  hostname:   str                      # e.g. "R1"
  loopback:   IPv4Interface | None     # e.g. 10.0.0.1/32  (single Loopback0 per node)
  interfaces: list[TopogenInterface]

TopogenInterface:
  address:     IPv4Interface | None    # e.g. 172.16.0.6/30
  vrf:         str | None              # e.g. "tenant" (flat-pair) — None = global table
  description: str                     # e.g. "to R2"
  slot:        int                     # physical slot index (0,1,...)
```

Render context / CLI flags that participate in the mapping (`src/topogen/main.py`):

- `--device-template` (`dest=dev_template`, default `iosv`; MVP allows `iosv`, `csr1000v`) — selects
  the per-platform interface identity rule (see §3). Maps to **no** schema key.
- `--template` (`-T`, default `iosv`) — TopoGen Jinja template; TopoGen-only, **no** schema key.
- `--mode` (`simple|nx|flat|flat-pair|dmvpn`) — TopoGen-only, **no** schema key.
- `--mgmt` (`dest=enable_mgmt`) — when set, `host` = mgmt IP and a mgmt interface + VRF are emitted.
- `--mgmt-slot` (default `5`) — mgmt interface slot → mgmt interface `id` (per-template, §3).
- `--mgmt-vrf` (default `Mgmt-vrf`; the literal `global` is normalized to `None` =
  global table in `main.py`) — mgmt interface `vrf_forwarding` + `vrfs[].name`.
- `--vrf` (`dest=enable_vrf`) + `--pair-vrf` (default `tenant`) — flat-pair odd-router Gi0/1 VRF.
  In `render.py` this is already baked into the model as `TopogenInterface.vrf = pair_vrf`
  (offline flat-pair: lines ~4620–4628), so it flows through the `vrf` field below.

---

## 2. Mapping matrix (TopoGen field → confirmed NaC key)

Confirmed NaC keys are all under `iosxe.devices[]` (the module's `local.device_config[name]`
spine; see `schema-verification.md`). "Nesting" is shown relative to a single device entry.

| # | TopoGen source (field / flag) | Confirmed NaC key | Nesting (under `iosxe.devices[]`) | Per-template notes | When omitted |
|---|---|---|---|---|---|
| 1 | `TopogenNode.hostname` (`"R1"`) | `system.hostname` | `configuration.system.hostname` | same all templates | never (always emit) |
| 2 | `TopogenNode.hostname` → device key | `name` | `devices[].name` (map key) | same | never (**required** map key) |
| 3 | slot-0 `TopogenInterface.address` host (no `--mgmt`) **/** mgmt iface IP (`--mgmt`) | `host` | `devices[].host` (sibling of `name`/`configuration`) | same | never (connection field) |
| 4 | `TopogenInterface` (per element of `interfaces`) | `ethernets[]` | `configuration.interfaces.ethernets[]` | id/type per §3 | element skipped if `address is None` (unused / L2-only link) |
| 5 | `TopogenInterface.slot` (+ `dev_template`) | `ethernets[].id` | `…ethernets[].id` | **IOSv** `0/<slot>`; **CSR1000v** `<slot+1>` (§3) | never for emitted ethernets (**required**) |
| 6 | platform of `dev_template` (label prefix) | `ethernets[].type` | `…ethernets[].type` | `GigabitEthernet` for both `iosv` and `csr1000v` | emitted in practice (needed to form iface name) |
| 7 | `TopogenInterface.description` (`"to R2"`) | `ethernets[].description` | `…ethernets[].description` | same | omit when `description == ""` |
| 8 | `TopogenInterface.address` (IP host part) | `ethernets[].ipv4.address` | `…ethernets[].ipv4.address` | dotted decimal host, **not** CIDR | omit when `address is None` |
| 9 | `TopogenInterface.address` (netmask) | `ethernets[].ipv4.address_mask` | `…ethernets[].ipv4.address_mask` | dotted decimal mask (e.g. `255.255.255.252`), **not** `/30`, key is `address_mask` not `mask` | omit when `address is None` |
| 10 | `TopogenInterface.vrf` (`"tenant"`) **/** mgmt: `--mgmt-vrf` | `ethernets[].vrf_forwarding` | `…ethernets[].vrf_forwarding` | key is `vrf_forwarding` (not `vrf`/`vrf_forward`) | omit when `vrf is None` / `--mgmt-vrf global` |
| 11 | `TopogenNode.loopback` | `loopbacks[]` | `configuration.interfaces.loopbacks[]` | single Loopback0 | omit list if `loopback is None` (e.g. dns-host; not a NaC router anyway) |
| 12 | Loopback number (`Loopback0`) | `loopbacks[].id` | `…loopbacks[].id` | `'0'` (loopback unit number, same all templates) | never for emitted loopback (**required**) |
| 13 | `TopogenNode.loopback` (IP host part) | `loopbacks[].ipv4.address` | `…loopbacks[].ipv4.address` | dotted decimal host | omit if no loopback |
| 14 | `TopogenNode.loopback` (netmask) | `loopbacks[].ipv4.address_mask` | `…loopbacks[].ipv4.address_mask` | `255.255.255.255` for `/32` | omit if no loopback |
| 15 | `--mgmt-vrf` (default `Mgmt-vrf`) **/** `--vrf`+`--pair-vrf` (default `tenant`) | `vrfs[].name` | `configuration.vrfs[].name` | same | omit whole `vrfs[]` when no VRF created (`--mgmt-vrf global` and no `--vrf`) |
| 16 | mgmt interface (`--mgmt`, slot `--mgmt-slot`) | extra `ethernets[]` entry | `configuration.interfaces.ethernets[]` | id per §3 (mgmt-slot); `vrf_forwarding` = mgmt VRF; `ipv4` = mgmt IP | omit entirely when `--mgmt` absent |

### Keys deliberately NOT emitted (TopoGen-only / out of MVP surface)

| TopoGen source | Reason no NaC key |
|---|---|
| `--template` / `args.template` | TopoGen Jinja template selector; not a device attribute. |
| `--mode` / `args.mode` | Topology mode; not a device attribute (no `metadata` in v3 surface). |
| `--device-template` / `dev_template` | Only selects the interface `id` rule (§3); platform is implicit in the `nac-iosxe` module — there is no `platform` key. |
| `TopogenInterface.slot` (raw int) | Consumed to build `ethernets[].id`; the integer itself is not a schema key. |
| role (always "router") | No `role` key in confirmed schema. |

> **MVP surface only** (per plan §"Official Schema Contract"): system/hostname + interfaces
> (IPv4) + loopbacks + VRF definitions. **No routing** (OSPF/BGP/static). No placeholder/empty
> blocks — emit a key only when backed by real model data.

### Required vs optional (from `schema-verification.md`)

- **Required (no module `try()` fallback):** `devices[].name`, `ethernets[].id`,
  `loopbacks[].id`, `vrfs[].name`. Missing any of these fails the module.
- **Emitted-by-convention:** `ethernets[].type` (module defaults to `null`, but TopoGen always
  emits `GigabitEthernet` so the rendered interface name is well-formed).
- **Optional (`try(..., null)`):** `description`, `vrf_forwarding`, `ipv4.*` — emit only when present.
- Do **not** emit module-defaulted keys such as `managed` (defaults `true`).

---

## 3. Per-`--device-template` interface identity (slot → id)

**Rule (robust, never hardcode `Gig1`):** reuse TopoGen's existing per-platform interface
label, then split it into `type` + `id` by stripping the interface-type prefix. The label is
produced by `src/topogen/nac.py::_interface_label` and the identical inline logic in
`render.py` (e.g. simple: lines ~5926–5929; mgmt: lines ~5934–5945).

| `--device-template` | TopoGen rendered label | NaC `type` | NaC `id` | slot 0 example | mgmt slot 5 example (`--mgmt`) |
|---|---|---|---|---|---|
| `iosv` (default) | `GigabitEthernet0/<slot>` | `GigabitEthernet` | `0/<slot>` | `id: '0/0'` | `id: '0/5'` |
| `csr1000v` | `GigabitEthernet<slot+1>` | `GigabitEthernet` | `<slot+1>` | `id: '1'` | `id: '5'` |

Notes:

- **IOSv:** data slot `s` → label `GigabitEthernet0/s` → `id: '0/s'`. mgmt uses
  `slot = --mgmt-slot` (default 5) → `GigabitEthernet0/5` → `id: '0/5'`.
- **CSR1000v:** data slot `s` → label `GigabitEthernet{s+1}` → `id: '{s+1}'` (so slot 0 → `'1'`).
  mgmt is special-cased in `render.py`: internal CML slot = `--mgmt-slot - 1`, but the **label**
  is `GigabitEthernet{--mgmt-slot}`, so the NaC `id` = `'5'` for default `--mgmt-slot 5`.
- **Loopback:** TopoGen models exactly one `Loopback0` per node (`TopogenNode.loopback`), so
  `loopbacks[].id` is always `'0'` on every template.
- `id` is emitted as a **string** (quoted), matching Appendix A examples (`id: '0/0'`, `id: '1'`,
  `id: '0'`).
- The rule generalizes if more IOS-XE templates are added later: derive the label from the
  platform renderer, then `type, id = split_on_type_prefix(label)`. Do not special-case `Gig1`.

---

## 4. Worked examples (model → confirmed schema)

### 4a. No `--mgmt` (global table) — `iosv`, slot-0 data IP as `host`

Model: `TopogenNode(hostname="R1", loopback=10.0.0.1/32, interfaces=[slot0=172.16.0.6/30 "to R2", slot1=172.16.0.1/30 "to dns-host"])`

```yaml
iosxe:
  devices:
    - name: iosv-01                 # device map key (see §5 naming note)
      host: 172.16.0.6              # slot-0 data IP (no mgmt)
      configuration:
        system:
          hostname: R1
        interfaces:
          ethernets:
            - type: GigabitEthernet
              id: '0/0'
              description: to R2
              ipv4: { address: 172.16.0.6, address_mask: 255.255.255.252 }
            - type: GigabitEthernet
              id: '0/1'
              description: to dns-host
              ipv4: { address: 172.16.0.1, address_mask: 255.255.255.252 }
          loopbacks:
            - id: '0'
              ipv4: { address: 10.0.0.1, address_mask: 255.255.255.255 }
        # no vrfs[] — global table
```

### 4b. `--mgmt` (default `Mgmt-vrf`, `--mgmt-slot 5`) — `iosv`

```yaml
iosxe:
  devices:
    - name: iosv-01
      host: 10.254.0.1             # mgmt interface IP (in Mgmt-vrf)
      configuration:
        system:
          hostname: R1
        vrfs:
          - name: Mgmt-vrf         # emitted because TopoGen created the VRF
        interfaces:
          ethernets:
            - type: GigabitEthernet
              id: '0/5'            # --mgmt-slot 5 on IOSv
              vrf_forwarding: Mgmt-vrf
              ipv4: { address: 10.254.0.1, address_mask: 255.255.0.0 }
          loopbacks:
            - id: '0'
              ipv4: { address: 10.0.0.1, address_mask: 255.255.255.255 }
```

### 4c. flat-pair `--vrf --pair-vrf tenant` — `csr1000v` odd router Gi0/1

`TopogenInterface(address=odd_ip, vrf="tenant", description="pair link", slot=1)` →

```yaml
            - type: GigabitEthernet
              id: '2'              # slot 1 on CSR1000v → slot+1 = 2
              description: pair link
              vrf_forwarding: tenant
              ipv4: { address: ..., address_mask: ... }
```
plus `configuration.vrfs: [ { name: tenant } ]`.

---

## 5. Reconciliation with the older golden-contract docs (v3 form wins)

The pre-existing docs — `docs/nac/iosxe-one-router-golden-contract.md`,
`docs/nac/topogen-to-nac-field-mapping.md`, `docs/nac/single-node-source-field-audit.md` —
and the **current** `src/topogen/nac.py::build_canonical_nac_model` describe an **older
device-level model** (`iosxe.devices[].{hostname,platform,role,template,device_template,mgmt,…}`
with `loopbacks[].name`, `interfaces[].name`). That shape was an internal canonical fixture and
is **NOT** the `nac-iosxe 0.1.0` module input. **The v3 `configuration.*` form (this matrix)
is authoritative and supersedes it.**

| Older device-level key (superseded) | v3 confirmed key (wins) |
|---|---|
| `devices[].hostname` (top-level) | `devices[].configuration.system.hostname` |
| `devices[].platform` (`iosxe`) | *(none — implicit in the `nac-iosxe` module)* |
| `devices[].role` (`router`) | *(none)* |
| `devices[].template` | *(none — TopoGen Jinja selector only)* |
| `devices[].device_template` | *(none — only selects the interface id rule, §3)* |
| `devices[].mgmt.ipv4` | `devices[].host` (+ mgmt `ethernets[].ipv4`) |
| `devices[].mgmt.vrf` | `ethernets[].vrf_forwarding` + `configuration.vrfs[].name` |
| `loopbacks[].name` (`Loopback0`) | `loopbacks[].id` (`'0'`) |
| `loopbacks[].ipv4` (CIDR string) | `loopbacks[].ipv4.address` + `…address_mask` (dotted) |
| `interfaces[].name` (`GigabitEthernet0/0`) | `ethernets[].type` + `ethernets[].id` |
| `interfaces[].ipv4` (CIDR string) | `ethernets[].ipv4.address` + `…address_mask` (dotted) |
| `interfaces[].slot` | *(not emitted — drives `id`, §3)* |
| `interfaces[].description` | `ethernets[].description` (unchanged) |
| `metadata.topogen.{mode,node_id}` | *(none — not in v3 MVP surface)* |

Rejected shapes (from `schema-verification.md`, restated so nobody reintroduces them):
`ipv4.mask` (→ use `address_mask`); interface `vrf:`/`vrf_forward:` (→ use `vrf_forwarding`);
top-level `hostname/platform/role/template/mgmt` on the device; the `entity`/`device`/`interface`
+ `iosxe_*` overview model; provider `= 0.18.0` (→ `= 0.15.0`).

---

## 6. Data-availability gaps flagged for TG-S4 / TG-S7

These are **not** schema questions (the keys are confirmed) but model-plumbing gaps the writer
work must close. Recorded here so TG-S7 does not silently fall back to wrong sources:

1. **`host` source.** v3 requires `host` = slot-0 data IP (no `--mgmt`) or mgmt IP (`--mgmt`).
   The current `build_canonical_nac_model` instead uses the **loopback** IP as a `mgmt.ipv4`
   fallback (`nac.py` lines ~101–123). TG-S4 must switch `host` to slot-0 data IP / mgmt IP.
2. **Mgmt interface + mgmt VRF not propagated.** The mgmt interface (`--mgmt`, `--mgmt-slot`,
   `--mgmt-vrf`) is rendered **only into the CML YAML**, not into the `TopogenNode.interfaces`
   list passed to `write_nac_tree` (see simple path lines ~5876–5945: `node_obj` excludes mgmt;
   `mgmt_ctx` is template-only). TG-S4/TG-S7 must propagate mgmt slot/VRF/IP (and the resulting
   `vrfs[].name`) into the NaC model.
3. **`vrf_forwarding` currently dropped.** `TopogenInterface.vrf` is populated for flat-pair
   (`render.py` ~4625) and exists on the dataclass, but the current writer never reads it and
   never emits `vrf_forwarding` or `vrfs[]`. TG-S7 must map field #10 / #15.
4. **Device `name` vs `hostname`.** Current code synthesizes `name = iosv-{NN}` regardless of
   platform and stores `hostname` (`R1`) only in `metadata`. v3: `name` is the required device
   map key and `hostname` → `configuration.system.hostname`. TG-S7 must decide the `name`
   source (keep synthetic `iosv-NN`/`csr-NN`, or use the node label) and emit `system.hostname`
   from `TopogenNode.hostname`.
5. **Serialization.** v3 mandates ordered construction + `yaml.dump(sort_keys=False, width=…)`.
   The current writer already uses `sort_keys=False` — preserve that; do not switch to
   alphabetical sort.

---

## 7. Sign-off

- [x] Every internal model field mapped to a confirmed `nac-iosxe 0.1.0` key (or recorded as
      intentionally not-emitted) — §2.
- [x] Per-`--device-template` slot→id rule documented for `iosv` and `csr1000v`, robust and
      reusing TopoGen's existing label renderer — §3.
- [x] Worked examples for no-mgmt, mgmt, and flat-pair VRF — §4.
- [x] Older device-level golden-contract docs reconciled; **v3 `configuration.*` form wins** — §5.
- [x] Model-plumbing gaps handed to TG-S4 / TG-S7 — §6.
- [x] Consumes the TG-S1 confirmed contract verbatim; no schema re-derivation; no writer code.
