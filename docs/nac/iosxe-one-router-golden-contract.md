<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.2.0
Date Modified: 2026-06-03

- Called by: Developers implementing TG-116, TG-117, TG-121
- Reads from: Canonical NaC model expectations for one-router IOS-XE output
- Writes to: None (documentation only)
- Calls into: tests/fixtures/nac/iosv-test/nac.yaml, docs/nac/topogen-to-nac-field-mapping.md, docs/nac/single-node-source-field-audit.md

Purpose: Define the source-of-truth contract for one-router IOS-XE NaC output.
Blast Radius: Contract changes affect adapter projection behavior and fixture tests.
-->

# IOS-XE one-router golden contract

This document defines the canonical NaC contract for a single IOS-XE router and is
the implementation target for TG-116, TG-117, and TG-121.

> **Superseded (TG-131 v3).** This describes the original device-level model
> (`hostname`/`platform`/`role`/`mgmt`). The shipped `--nac` MVP targets the official
> `netascode/nac-iosxe` schema (`iosxe.devices[].configuration.*`) and no longer emits
> `terraform.tfvars.json`. For the current contract see `README.md` (NaC MVP scope),
> `docs/nac/mapping-matrix.md`, and the golden fixtures under
> `tests/fixtures/nac/golden-flat-*`. The sections below are retained for historical context.

Field-source audit companion:

- `docs/nac/single-node-source-field-audit.md`

## Canonical root

The canonical root is:

`iosxe.devices[0]`

For MVP, exactly one device is expected in `iosxe.devices`, represented by
`iosv-01` in the golden fixture.

## Canonical data model

Canonical object shape for `iosxe.devices[0]`:

- `name` (required, string): stable device identifier, example `iosv-01`
- `hostname` (required, string): network hostname, example `iosv-01`
- `platform` (required, string): must be `iosxe` for this contract
- `role` (required, string): example `router`
- `template` (required, string): TopoGen template used to render startup config
- `device_template` (required, string): CML node definition, example `iosv`
- `mgmt` (required, object):
  - `ipv4` (required, string CIDR or host string)
  - `vrf` (optional, string)
- `loopbacks` (required, list):
  - item fields: `name` (required), `ipv4` (required)
- `interfaces` (required, list):
  - item fields: `name` (required), `ipv4` (optional), `description` (optional), `slot` (optional)
- `metadata` (optional, object):
  - `topogen` (optional, object): implementation metadata that does not alter adapter identity

### Audited derivation rules (TG-117)

The following field derivations are mandatory until dedicated source fields are
implemented in runtime code:

- `name`: deterministic canonical host key (`iosv-01`) for single-router fixture output
- `platform`: derive `iosxe` from resolved IOS-XE device templates (`iosv`, `csr1000v`)
- `role`: emit fixed value `router` for the simple router path
- `mgmt.ipv4`: fallback to loopback host IP when management IP is not available in source model

## Required vs optional fields

Required fields for MVP compliance:

- `iosxe`
- `iosxe.devices`
- `iosxe.devices[0].name`
- `iosxe.devices[0].hostname`
- `iosxe.devices[0].platform`
- `iosxe.devices[0].role`
- `iosxe.devices[0].template`
- `iosxe.devices[0].device_template`
- `iosxe.devices[0].mgmt`
- `iosxe.devices[0].mgmt.ipv4`
- `iosxe.devices[0].loopbacks`
- `iosxe.devices[0].interfaces`

Optional fields for MVP:

- `iosxe.devices[0].mgmt.vrf`
- `iosxe.devices[0].metadata`
- `iosxe.devices[0].interfaces[*].ipv4`
- `iosxe.devices[0].interfaces[*].description`
- `iosxe.devices[0].interfaces[*].slot`

## Deterministic ordering rules

Determinism is mandatory for snapshot comparison and adapter consistency.

- Top-level keys order: `iosxe`
- Under `iosxe`: `devices`
- Device key order:
  1. `name`
  2. `hostname`
  3. `platform`
  4. `role`
  5. `template`
  6. `device_template`
  7. `mgmt`
  8. `loopbacks`
  9. `interfaces`
  10. `metadata` (if present)
- `devices` list ordering: lexicographic by `name`
- `loopbacks` list ordering: natural interface index by loopback number (`Loopback0`, `Loopback1`, ...)
- `interfaces` list ordering: ascending physical interface index (`GigabitEthernet0/0`, `GigabitEthernet0/1`, ...)
- No runtime timestamps, random IDs, or non-deterministic key ordering in canonical fixture output

## Adapter projection requirements

The canonical contract is the source model. Adapter outputs must be pure
projections from `iosxe.devices[0]` with deterministic field order.

### `devices.yaml`

- Must include one device entry derived from `iosxe.devices[0]`
- Required projected fields:
  - `name <- iosxe.devices[0].name`
  - `hostname <- iosxe.devices[0].hostname`
  - `platform <- iosxe.devices[0].platform`
  - `role <- iosxe.devices[0].role`
  - `mgmt_ip <- iosxe.devices[0].mgmt.ipv4`

### `terraform.tfvars.json` (removed in TG-131 v3)

- **No longer emitted.** Terraform auto-loads `terraform.tfvars.json`, so it cannot
  honestly be labeled "not a Terraform input." The v3 path instead emits a Terraform
  workspace (`main.tf`/`versions.tf`/`terraform.tfvars.example`/`.gitignore`) that
  consumes `nac.yaml` via the `netascode/nac-iosxe` module, plus an informational
  `devices.yaml` device projection. Credentials are supplied via environment variables.

### `inventory.yaml`

- Must represent one host under inventory host scope
- Required projected fields:
  - host key: `iosxe.devices[0].name`
  - `ansible_host <- iosxe.devices[0].mgmt.ipv4` (host IP portion if CIDR)
  - `platform <- iosxe.devices[0].platform`

### `group_vars/all.yaml`

- Must include shared, non-host-specific variables only
- Required projected fields:
  - `nac_platform <- iosxe.devices[0].platform`
  - `nac_device_count <- len(iosxe.devices)`
- Must not duplicate host-specific mgmt addressing here

### `host_vars/iosv-01.yaml`

- Must include host-specific variables projected from `iosxe.devices[0]`
- Required projected fields:
  - `hostname`
  - `role`
  - `template`
  - `device_template`
  - `loopbacks`
  - `interfaces`

### `nac_metadata.yaml`

- Must include metadata describing contract provenance
- Required projected fields:
  - `schema <- "iosxe-one-router-golden-contract"`
  - `schema_version <- "1.0.0"`
  - `canonical_root <- "iosxe.devices[0]"`
  - `source_fixture <- "tests/fixtures/nac/iosv-test/nac.yaml"`

## MVP non-goals

The following are explicitly out of scope for TG-116 MVP:

- Multi-device canonical contract (`iosxe.devices[1+]`)
- Multi-platform canonical roots (NX-OS, IOS-XR, ASA, Linux)
- Runtime generation pipeline, CLI flags, or adapter execution logic
- Terraform or Ansible runtime execution/integration tests
- Automatic topology discovery from live controllers
