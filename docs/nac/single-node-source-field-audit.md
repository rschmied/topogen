<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.0
Date Modified: 2026-06-03

- Called by: Developers implementing TG-117 and Story 5 canonical writer
- Reads from: src/topogen/main.py, src/topogen/render.py, src/topogen/models.py, src/topogen/config.py
- Writes to: None (documentation only)
- Calls into: docs/nac/topogen-to-nac-field-mapping.md, docs/nac/iosxe-one-router-golden-contract.md

Purpose: Evidence-based audit of real single-router source fields for NaC generation.
Blast Radius: Incorrect audit data leads to incorrect NaC writer field mapping.
-->

# Single-node source field audit

This audit documents only fields confirmed from codepath inspection and command
execution evidence.

## Audited command context

Requested command context:

`topogen 1 --mode simple --offline-yaml out/iosv-test.yaml --nac`

Observed results:

1. `nodes=1` is rejected by `valid_node_count()` in `src/topogen/main.py`.
2. `--nac` is rejected because `create_argparser()` does not define this flag.

Verified command used to audit the active generation path:

`python -m topogen 2 --mode simple --offline-yaml out/iosv-test.yaml`

## Traced flow (CLI -> model build -> render)

### 1) CLI parse and dispatch

- `src/topogen/main.py::create_argparser()`
  - Defines `--mode`, `--offline-yaml`, `--device-template` (`dest="dev_template"`), and `nodes`.
  - Does not define `--nac`.
- `src/topogen/main.py::valid_node_count(value)`
  - Enforces range `2..1000`.
- `src/topogen/main.py::main()`
  - Loads config via `Config.load(args.configfile)`.
  - Offline route dispatch:
    - if `args.offline_yaml` and `args.mode == "simple"` ->
      `Renderer.offline_simple_yaml(args, cfg)`.

### 2) Model object construction in simple offline flow

- `src/topogen/render.py::Renderer.offline_simple_yaml(args, cfg)`
  - Builds deterministic loopbacks in `node_loopbacks`.
  - Builds per-router interface dicts in `node_ifaces`.
  - For each router index, constructs:
    - `TopogenInterface(address=..., description=..., slot=...)`
    - `TopogenNode(hostname=label, loopback=loopback, interfaces=topo_ifaces)`
  - Additional context objects:
    - `dev_def = getattr(args, "dev_template", args.template)`
    - `mgmt_ctx` (optional dict, only when `--mgmt`)
    - `ntp_ctx` and `ntp_oob_ctx` (optional dicts)
  - Template render call:
    - `tpl.render(config=cfg, node=node_obj, mgmt=mgmt_ctx, ntp=ntp_ctx, ntp_oob=ntp_oob_ctx, archive=...)`

### 3) Model class definitions (source schema)

- `src/topogen/models.py::TopogenNode`
  - `hostname: str`
  - `loopback: IPv4Interface | None`
  - `interfaces: list[TopogenInterface]`
- `src/topogen/models.py::TopogenInterface`
  - `address: IPv4Interface | None`
  - `vrf: str | None`
  - `description: str`
  - `slot: int`

## Observed source tree sample (sanitized, deterministic)

Sample is derived from the audited valid command:

`python -m topogen 2 --mode simple --offline-yaml out/iosv-test.yaml`

One-router source object at first router iteration (`idx=0`) in
`Renderer.offline_simple_yaml`:

```yaml
source_context:
  function: Renderer.offline_simple_yaml
  args:
    mode: simple
    template: iosv
    dev_template: iosv
    offline_yaml: out/iosv-test.yaml
    nodes: 2
  derived:
    label: R1
    dev_def: iosv
    mgmt_ctx: null
    ntp_ctx: null
    ntp_oob_ctx: null
  node_obj:
    hostname: R1
    loopback: 10.0.0.1/32
    interfaces:
      - slot: 0
        address: 172.16.0.6/30
        description: to R2
      - slot: 1
        address: 172.16.0.1/30
        description: to dns-host
```

## Confirmed gaps and MVP fallback/default behavior

### Gap 1: No `--nac` CLI flag

- Confirmed by parser error and absence from `create_argparser()`.
- MVP fallback behavior:
  - NaC writer entry should be callable from internal code path hooks without
    requiring `--nac` during TG-117 documentation stage.

### Gap 2: One-router invocation not currently allowed

- Confirmed by `valid_node_count()` minimum of 2.
- MVP fallback behavior:
  - Canonical one-router fixture generation should select first router from a
    minimum valid simple topology run (router `R1`) and normalize naming.

### Gap 3: No explicit `platform` field in `TopogenNode`

- Confirmed by `TopogenNode` schema.
- MVP fallback behavior:
  - Derive `platform: iosxe` from resolved `dev_def` value when `dev_def` is
    `iosv` or `csr1000v`.

### Gap 4: No explicit `role` field in `TopogenNode`

- Confirmed by `TopogenNode` schema.
- MVP fallback behavior:
  - Emit `role: router` as fixed value for the simple router path.

### Gap 5: No direct management IPv4 source in simple router model

- Confirmed in `node_obj` and `mgmt_ctx` construction (`mgmt_ctx` has slot/vrf/gw,
  but no management interface IP).
- MVP fallback behavior:
  - Populate canonical `mgmt.ipv4` from loopback host IP (`node_obj.loopback.ip`)
    until a dedicated management IP source is implemented.

## Implementation-ready constraints for Story 5 writer

- Use only confirmed source symbols documented above.
- Apply deterministic transforms only:
  - router index 0 -> canonical name `iosv-01`
  - `dev_def` -> `platform: iosxe`
  - missing mgmt IP -> loopback host fallback
- Do not read from rendered config text for canonical field extraction.
