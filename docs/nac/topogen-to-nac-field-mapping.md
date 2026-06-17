<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.1.1
Date Modified: 2026-06-03

- Called by: Developers implementing TG-117 NaC adapters and tests
- Reads from: src/topogen/main.py, src/topogen/render.py, src/topogen/models.py
- Writes to: None (documentation only)
- Calls into: docs/nac/iosxe-one-router-golden-contract.md, docs/nac/single-node-source-field-audit.md

Purpose: Define the verified TopoGen-to-NaC field projection matrix for TG-117.
Blast Radius: Mapping changes affect canonical fixture generation, adapters, and Story 5 writer expectations.
-->

# TopoGen to NaC field mapping

Verified command context audited:

- Requested: `topogen 1 --mode simple --offline-yaml out/iosv-test.yaml --nac`
- Observed parser constraints:
  - `nodes` must be `2..1000` (`valid_node_count` in `src/topogen/main.py`)
  - `--nac` is currently unrecognized (no CLI flag in `create_argparser`)
- Effective audited generation path (minimum valid variant):
  - `python -m topogen 2 --mode simple --offline-yaml out/iosv-test.yaml`
  - `main.main()` -> `Renderer.offline_simple_yaml(args, cfg)`

Status values:

- `Required`: required by canonical Story 5 writer target
- `Optional`: present/derivable but not required for MVP compliance
- `Deferred`: not available in current codepath or intentionally postponed

| source_location | source_field | example_value | nac_target_field | status | notes |
|---|---|---|---|---|---|
| `src/topogen/main.py::main()` | `args.mode` | `simple` | `iosxe.devices[0].metadata.topogen.mode` | Optional | Parsed in CLI and forwarded into offline renderer path |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `node_obj.hostname` | `R1` | `iosxe.devices[0].hostname` | Required | Built from `TopogenNode(hostname=label, ...)` |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `node_obj.loopback` | `10.0.0.1/32` | `iosxe.devices[0].loopbacks[0].ipv4` | Required | Direct source from `node_loopbacks[idx]` |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `node_obj.interfaces[*].address` | `172.16.0.6/30`, `172.16.0.1/30` | `iosxe.devices[0].interfaces[*].ipv4` | Optional | P2P link addresses are deterministic per allocation order |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `node_obj.interfaces[*].description` | `to R2`, `to dns-host` | `iosxe.devices[0].interfaces[*].description` | Optional | Derived in `topo_ifaces` construction |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `node_obj.interfaces[*].slot` | `0`, `1` | `iosxe.devices[0].interfaces[*].slot` | Optional | Stable numeric ordering after `topo_ifaces.sort(key=lambda xi: xi.slot)` |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `args.template` | `iosv` | `iosxe.devices[0].template` | Required | Used to load Jinja template and should be projected into canonical output |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `dev_def` (`getattr(args, "dev_template", args.template)`) | `iosv` | `iosxe.devices[0].device_template` | Required | Canonical writer must read this resolved value |
| `src/topogen/models.py::TopogenInterface` | `vrf` | `None` | `iosxe.devices[0].interfaces[*].vrf` | Deferred | Field exists in model class but is not populated in offline simple router build |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `mgmt_ctx` | `None` (default command), or `{"enabled": True, "slot": 5, "vrf": "Mgmt-vrf", "gw": null}` | `iosxe.devices[0].mgmt.vrf` | Optional | Source only when `--mgmt`; there is no direct management IPv4 value in this path |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `args.dev_template` resolver (`iosv`/`csr1000v`) | `iosv` | `iosxe.devices[0].platform` | Required | Canonical platform should be mapped deterministically (`iosv`/`csr1000v` -> `iosxe`) |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | `node_definition` role context (`router` node block) | `router semantics from R1 node block` | `iosxe.devices[0].role` | Required | No explicit role field exists; canonical writer must emit fixed value `router` for this path |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` + `src/topogen/main.py::valid_node_count()` | absence of one-node support | `minimum routers = 2` | `iosxe.devices[0].name` | Required | For one-router canonical fixture, name must be deterministic synthetic value (`iosv-01`) |
| `src/topogen/render.py::Renderer.offline_simple_yaml()` | absence of static mgmt IP in `TopogenNode` and `mgmt_ctx` | `not present` | `iosxe.devices[0].mgmt.ipv4` | Required | MVP fallback: set from loopback host (`node_obj.loopback.ip`, e.g., `10.0.0.1`) until dedicated mgmt IP source is added |

## Confirmed field-source rules for Story 5 writer

- Use `node_obj` as the primary router source object (`hostname`, `loopback`, `interfaces`).
- Use `args.template` and resolved `dev_def` for template/device metadata.
- Derive `platform` as `iosxe` from known IOSv/CSR device templates in this path.
- Emit `role` as `router` for this topology path.
- Use deterministic naming transform for canonical fixture host key (`iosv-01`).
- Apply documented fallback for `mgmt.ipv4` using loopback host IP when management IP is not present in source objects.

## MVP fallback/default rules

When source-field gaps are encountered on the audited path
(`main.main()` -> `Renderer.offline_simple_yaml()`), use these deterministic rules:

- Missing one-router runtime input (CLI requires `nodes >= 2`):
  - Select first router object (`idx=0`, `R1`) from the minimum valid simple run.
- Missing canonical host key:
  - Normalize to `iosv-01` for single-router canonical fixture output.
- Missing explicit platform field in `TopogenNode`:
  - Map resolved `dev_def` values `iosv` and `csr1000v` to canonical `platform: iosxe`.
- Missing explicit role field in `TopogenNode`:
  - Emit fixed `role: router` for this path.
- Missing management IPv4 source:
  - Use `node_obj.loopback.ip` as canonical `mgmt.ipv4` until a dedicated management IP source is implemented.
