<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.1.0
Date Modified: 2026-06-03

- Called by: TG-S1 (Jira TG-132); gating deliverable for TG-S2 (TG-133) and TG-S7 (TG-139)
- Reads from: netascode/terraform-iosxe-nac-iosxe @ tag v0.1.0 (module SOURCE)
- Writes to: None (documentation / sign-off only)
- Calls into: z:\Marco\jira-nac-setup-v3.plan.md (Appendix A)

Purpose: TG-S1 schema-verification GATE. Confirm the exact nac.yaml key names/shape
TopoGen will emit against the pinned netascode/nac-iosxe 0.1.0 module by citing the
module SOURCE (offline, source-based verification — NO terraform run).
Blast Radius: Authoritative key contract for the nac.yaml writer (TG-S7) and the
TopoGen->NaC mapping matrix (TG-S2).
-->

# TG-S1 — Schema Verification (`--nac`, IOS-XE) — SOURCE-BASED GATE

**Ticket:** Jira TG-132 (TG-S1), first/gating ticket of Epic TG-131
(`--nac v3 Deployable Terraform MVP`).

**Verification method (locked):** This gate is verified **entirely by reading the
module SOURCE** at tag `v0.1.0`. There is no Terraform installed and no Terraform
host available, so the `terraform init/validate/plan` steps in the original scaffold
are **replaced** by direct source citations (file + line) proving each key name and
its nesting. Every key is cross-checked against what the module actually *reads* from
the YAML model.

**Source under verification:**
`https://github.com/netascode/terraform-iosxe-nac-iosxe` @ tag **`v0.1.0`**
(tree SHA `196a1c8ba8faed2df26f64847892e59e5ea9d65f`). Files were fetched from
`raw.githubusercontent.com/.../v0.1.0/...` and inspected offline.

---

## Target (Decision A — confirmed)

- **Module:** `netascode/nac-iosxe/iosxe = 0.1.0`.
- **Schema form:** `iosxe.devices[].configuration.*` (the module's own YAML/README form).
- **NOT the target:** the "IOS-XE New" overview model (`entity`/`device`/`interface` +
  `iosxe_*` keys). Different data-model family — explicitly out of scope.

### How the module reads the YAML (the spine that proves nesting)

The root module loads the model and derives a per-device `configuration` map:

```hcl
# main.tf (root)
locals {
  model    = module.model.model
  iosxe    = try(local.model.iosxe, {})          # line 16
  devices  = try(local.iosxe.devices, [])        # line 17  -> iosxe.devices[]
  device_config = { for device in try(local.iosxe.devices, []) :
    device.name => try(device.configuration, {}) # lines 19-21 -> name + configuration
  }
}
```

So throughout the module, `local.device_config[<name>]` **is** `iosxe.devices[].configuration`.
Every `device_config[name].<x>` reference below therefore proves the key
`iosxe.devices[].configuration.<x>`.

---

## Confirmed keys — with module v0.1.0 source citations

| nac.yaml key (our schema) | Module input read | Source citation (tag v0.1.0) |
|---|---|---|
| `iosxe.devices[]` | `local.iosxe.devices` | `main.tf:17` |
| `devices[].name` | `device.name` (map key + provider device) | `main.tf:20`; `modules/model/main.tf:9,194` |
| `devices[].host` | `try(device.host, null)` | `modules/model/main.tf:11,196`; README usage example (`host: 1.2.3.4`) |
| `devices[].configuration` | `try(device.configuration, {})` | `main.tf:20` |
| `configuration.system.hostname` | `device_config[name].system.hostname` | `iosxe_system.tf:5` |
| `configuration.interfaces.ethernets[]` | `device_config[name].interfaces.ethernets` | `iosxe_interfaces.tf:30` |
| `ethernets[].type` | `int.type` | `iosxe_interfaces.tf:35` (key build `:31`) |
| `ethernets[].id` | `int.id` | `iosxe_interfaces.tf:33` (key build `:31`) |
| `ethernets[].description` | `int.description` | `iosxe_interfaces.tf:39` |
| `ethernets[].vrf_forwarding` | `int.vrf_forwarding` | `iosxe_interfaces.tf:41` |
| `ethernets[].ipv4.address` | `int.ipv4.address` | `iosxe_interfaces.tf:42` |
| `ethernets[].ipv4.address_mask` | `int.ipv4.address_mask` | `iosxe_interfaces.tf:43` |
| `configuration.interfaces.loopbacks[]` | `device_config[name].interfaces.loopbacks` | `iosxe_interfaces.tf:846` |
| `loopbacks[].id` | `int.id` | `iosxe_interfaces.tf:849` (key build `:847`) |
| `loopbacks[].vrf_forwarding` | `int.vrf_forwarding` | `iosxe_interfaces.tf:852` |
| `loopbacks[].ipv4.address` | `int.ipv4.address` | `iosxe_interfaces.tf:853` |
| `loopbacks[].ipv4.address_mask` | `int.ipv4.address_mask` | `iosxe_interfaces.tf:854` |
| `configuration.vrfs[]` | `device_config[name].vrfs` | `iosxe_vrf.tf:4` |
| `vrfs[].name` | `vrf.name` | `iosxe_vrf.tf:7` (resource assign `:204`) |

### Verbatim source excerpts (key proofs)

System hostname — `iosxe_system.tf:5`:
```hcl
hostname = try(local.device_config[each.value.name].system.hostname, local.defaults.iosxe.configuration.system.hostname, null)
```

Ethernet interfaces — `iosxe_interfaces.tf:30,33,35,39,41,42,43`:
```hcl
for int in try(local.device_config[device.name].interfaces.ethernets, []) : {
  id             = trimprefix(int.id, "$string ")
  type           = try(int.type, ...)
  description    = try(int.description, ...)
  vrf_forwarding = try(int.vrf_forwarding, ...)
  ipv4_address      = try(int.ipv4.address, ...)
  ipv4_address_mask = try(int.ipv4.address_mask, ...)
```

Loopback interfaces — `iosxe_interfaces.tf:846,849,852,853,854`:
```hcl
for int in try(local.device_config[device.name].interfaces.loopbacks, []) : {
  id             = int.id
  vrf_forwarding = try(int.vrf_forwarding, ...)
  ipv4_address      = try(int.ipv4.address, ...)
  ipv4_address_mask = try(int.ipv4.address_mask, ...)
```

VRF definition — `iosxe_vrf.tf:4,7`:
```hcl
for vrf in try(local.device_config[device.name].vrfs, []) : {
  name = vrf.name
```

`host` (consumed by the model module that builds the provider device list) —
`modules/model/main.tf:11` and `:196`:
```hcl
host = try(device.host, null)
```

---

## Loopback `id` key — confirmed

The loopback identifier key is **`id`** (same as ethernets), read directly as
`int.id` at `iosxe_interfaces.tf:849`, and used to form the interface name at
`:847` (`format("%s/Loopback%s", device.name, int.id)`). There is **no** alternate
loopback identifier key (e.g. `number`/`unit`). Examples using `id: '0'` are correct.

## Required vs. required-but-defaulted fields

Read from source, these YAML keys are **mandatory** (referenced with no `try()`
fallback, so an absent key fails the module):

- `devices[].name` — used as a `for_each` map key (`main.tf:20`, every resource).
- `ethernets[].id` — `int.id` with no `try()` (`iosxe_interfaces.tf:33`).
- `loopbacks[].id` — `int.id` with no `try()` (`iosxe_interfaces.tf:849`).
- `vrfs[].name` — `vrf.name` with no `try()` (`iosxe_vrf.tf:7`).

**Required-but-defaulted** (module supplies a default, so we need not emit them):

- `ethernets[].type` — `try(int.type, defaults..., null)` (`iosxe_interfaces.tf:35`).
  Defaulted to `null` in source, but in practice TopoGen always emits `type`
  (e.g. `GigabitEthernet`) since the rendered interface name needs it.
- `managed` (device + ethernet) — defaulted `true` via `defaults/defaults.yaml`
  (`devices.managed: true`, `...ethernets.managed: true`) — do **not** emit.
- All other interface/system/VRF attributes use `try(..., null)` and are optional;
  the MVP surface intentionally emits none of them.
- Module-level: at least one of `yaml_directories`, `yaml_files`, or `model` must be
  non-empty (`variables.tf:17-20` validation) — satisfied by the scaffold's
  `yaml_files = ["nac.yaml"]`. (The scaffold deliberately uses `yaml_files`, not
  `yaml_directories = ["."]`, which would also ingest the Ansible/informational
  YAML and break `yaml_merge` — see TG-145.)

## `host` placement note (not a schema error, but worth recording)

`host` is **not** read by the root `*.tf` resource files; it is consumed only by the
`modules/model` submodule, which assembles the provider device list
(`modules/model/main.tf:11,196`). The provider is then configured with
`devices = local.provider_devices` (`main.tf:27`). This confirms `host` lives at
`iosxe.devices[].host` (device level, sibling of `name`/`configuration`) — exactly as
Appendix A places it.

---

## Appendix A example reconciliation (by inspection vs. source)

Every key present in both examples maps to a real module input cited above. No
unknown/unsupported keys appear in either example.

### Example 1 — `golden-simple-no-mgmt`
| Key in example | Maps to | Verdict |
|---|---|---|
| `devices[].name` | `main.tf:20` | OK |
| `devices[].host` | `modules/model/main.tf:11` | OK |
| `configuration.system.hostname` | `iosxe_system.tf:5` | OK |
| `...ethernets[].type` / `id` / `description` | `iosxe_interfaces.tf:35/33/39` | OK |
| `...ethernets[].ipv4.address` / `address_mask` | `iosxe_interfaces.tf:42/43` | OK |
| `...loopbacks[].id` | `iosxe_interfaces.tf:849` | OK |
| `...loopbacks[].ipv4.address` / `address_mask` | `iosxe_interfaces.tf:853/854` | OK |
| (no VRF keys emitted) | n/a | OK (global table) |

**Result: Example 1 reconciled — no mismatches.**

### Example 2 — `golden-simple-mgmt` (mgmt interface in `Mgmt-vrf`)
| Key in example | Maps to | Verdict |
|---|---|---|
| `devices[].name` | `main.tf:20` | OK |
| `devices[].host` (mgmt IP) | `modules/model/main.tf:11` | OK |
| `configuration.system.hostname` | `iosxe_system.tf:5` | OK |
| `configuration.vrfs[].name` | `iosxe_vrf.tf:7` | OK |
| `...ethernets[].type` / `id` | `iosxe_interfaces.tf:35/33` | OK |
| `...ethernets[].vrf_forwarding` | `iosxe_interfaces.tf:41` | OK |
| `...ethernets[].ipv4.address` / `address_mask` | `iosxe_interfaces.tf:42/43` | OK |

**Result: Example 2 reconciled — no mismatches.**

---

## Corrections discovered (fed back into the v3 plan, Appendix A / Toolchain)

1. **Provider pin is `= 0.15.0`, not `= 0.18.0`.** The module's own `versions.tf` at
   tag `v0.1.0` pins the provider exactly:
   ```hcl
   # versions.tf:5-12 (tag v0.1.0)
   iosxe = { source = "CiscoDevNet/iosxe", version = "= 0.15.0" }
   utils = { source = "netascode/utils",   version = "= 1.1.0-beta3" }
   ```
   The v3 plan repeatedly states `CiscoDevNet/iosxe = 0.18.0` "dictated by the module".
   That is **wrong for 0.1.0** — the root `versions.tf` (TG-S8) must pin `= 0.15.0` to
   avoid an `init` conflict. (The README Requirements table at v0.1.0 also lists
   `iosxe = 0.15.0`.) `utils = 1.1.0-beta3` and `terraform >= 1.8.0` are confirmed
   correct.

   > Per the plan's "TG-S1 re-derive rule", the provider pin is dictated by the module;
   > since the published module is `0.1.0`, the correct derived pin is `= 0.15.0`.

## Rejected / wrong shapes (recorded so nobody repeats them)

- `ipv4.mask` — wrong; the module reads **`address_mask`** (`iosxe_interfaces.tf:43,854`).
- interface `vrf:` / `vrf_forward:` — wrong; the module reads **`vrf_forwarding`**
  (`iosxe_interfaces.tf:41,852`).
- top-level `hostname` / `platform` / `role` / `template` / `mgmt` on the device —
  not read; hostname lives at `configuration.system.hostname`.
- `entity`/`device`/`interface` + `iosxe_*` overview model — different toolchain, not
  this module.
- Provider `= 0.18.0` — wrong for module `0.1.0` (see correction #1).

---

## Sign-off

- [x] Each key confirmed against module **v0.1.0 SOURCE** with file:line citations
      (table + verbatim excerpts above).
- [x] Loopback identifier key confirmed as **`id`** (`iosxe_interfaces.tf:849`).
- [x] Required vs. required-but-defaulted fields recorded.
- [x] Appendix A **Example 1** (no-mgmt) reconciled — no mismatches.
- [x] Appendix A **Example 2** (mgmt) reconciled — no mismatches.
- [x] Corrections captured and fed back to the v3 plan (provider pin `= 0.15.0`).
- [x] **GATE CLOSED** — TG-S2 (mapping matrix) and TG-S7 (`nac.yaml` writer) cleared to
      proceed on the confirmed key contract above.

> Note on method: the original scaffold's live `terraform validate` step is
> intentionally **not** performed (no Terraform toolchain/host available). It is
> superseded by the source citations above, which prove acceptance at the level the
> module actually enforces (the keys it reads from the YAML model).
