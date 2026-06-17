<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.8.12
Date Modified: 2026-06-13

- Called by: Users (primary entry point), package managers (PyPI), GitHub viewers
- Reads from: None (documentation only)
- Writes to: None (documentation only)
- Calls into: References DEVELOPER.md, CONTRIBUTING.md, CHANGES.md, TESTED.md

Purpose: User-facing documentation for TopoGen features, installation, usage, and examples.
         Primary entry point for understanding what TopoGen does and how to use it.

Blast Radius: None (documentation only, does not affect code execution)
-->

# TopoGen for CML2

This package provides a `topogen` command which can create CML2 topologies.
It does this by using the PCL (VIRL Python Client Library) to talk to a live
controller, creating the lab, nodes and links on the fly.

**Why TopoGen:** TopoGen bridges the gap from design to a lab that [Ansible](https://www.ansible.com/), [Terraform](https://www.terraform.io/), and [pyATS](https://developer.cisco.com/docs/pyats/) can consume and take to the next step — config management, infra-as-code, or test automation.

![Demo](.images/demo.gif)

## Features

- create topologies of arbitrary size (up to 520 tested, this is N^2)
- can use templates to provide node configurations (currently a built-in
  DNS host template and an IOSv template exist)
- provide network numbering for all links (/30) and router loopbacks
- provide a DNS configuration so that all loopbacks and interface addresses can
  be resolved both from the DNS host as well as from all routers (provided the
  template configures DNS)
- provide a default route via DNS host, distributed via OSPF
- provide outbound NAT on the DNS host for the entire network
- flat L2 mode for large-scale labs (star of unmanaged switches with grouped routers)
- YAML export of generated labs via controller API
- offline YAML generation for CML (no controller needed) with `--offline-yaml`
- optional CML2 Terraform lifecycle scaffold with `--terraform-cml2`
- offline-to-CML import: `--import-yaml FILE` and `--import` to push YAML into CML (file size and lab URL printed; `--start` runs in background)

## Documentation map

| File | Audience | Purpose |
|------|----------|---------|
| README.md | Users | CLI usage, features, examples |
| DEVELOPER.md | Developers | Architecture, file chains, workflows |
| CONTRIBUTING.md | Contributors | Branching, commits, PR conventions |
| TESTED.md | CI/CD | Platform and dependency validation |
| CHANGES.md | All | Release history |
| TODO.md | Maintainers | Optional maintainer notes; internal backlog tracked in Jira (TG project) |
| PKI.md | Users, developers | PKI flags, CA-ROOT, EEM, auto-deploy certs, troubleshooting |
| docs/nac/iosxe-one-router-golden-contract.md | Developers | Canonical one-router IOS-XE NaC contract (TG-116) |
| docs/nac/topogen-to-nac-field-mapping.md | Developers | TopoGen-to-NaC field mapping matrix for adapter work |
| docs/nac/single-node-source-field-audit.md | Developers | Verified one-router source-field audit for NaC (TG-117) |
| tests/fixtures/nac/iosv-test/nac.yaml | Tests, developers | Deterministic golden fixture for NaC canonical output |

## NaC contract artifacts (TG-116)

The following artifacts are the source-of-truth for NaC implementation stories
TG-116, TG-117, and TG-121:

- `docs/nac/iosxe-one-router-golden-contract.md`
- `docs/nac/topogen-to-nac-field-mapping.md`
- `docs/nac/single-node-source-field-audit.md`
- `tests/fixtures/nac/iosv-test/nac.yaml`

They define canonical shape, required fields, deterministic ordering, and field
projection targets. Runtime CLI or adapter execution logic is intentionally out
of scope for this documentation-only contract baseline.

## Offline Network-as-Code (`--nac`)

`--nac` is an **offline-only** path that, alongside the offline CML YAML, emits a
deployable Network-as-Code workspace: a lean `nac.yaml` for the official
`netascode/nac-iosxe` Terraform module, a ready-to-run Terraform workspace, and
a read-only Ansible reachability stub.

It works with **any supported offline topology mode** (`simple`, `nx`, `flat`,
`flat-pair`, and `dmvpn` with `flat` or `flat-pair` underlay). You are not
limited to a fixed set of node counts or modes — use the same flags you would
for offline YAML generation and add `--nac`.

Guardrails:

- `--nac` requires `--offline-yaml` (local generation only; no `--import`,
  `--import-yaml`, `--up`, or online `--yaml` export)
- Router nodes must use an IOS-XE CML definition: `iosv` or `csr1000v` (align
  `-T` / `--template` with `--device-template`, e.g. `iosv-dmvpn` on `iosv`)
- With `--nac`, `nodes=1` is allowed when the selected mode supports a single
  router; without `--nac`, the minimum is `nodes=2`
- Labs that add non–IOS-XE nodes (e.g. `--pki` CA-ROOT on `csr1000v` while
  spokes use `iosv`) still fail fast before any `nac/` tree is written
- DMVPN semantics are unchanged: default `dmvpn` uses `nodes` as spoke count
  (R1 hub); with `--dmvpn-hubs`, `nodes` is total routers. DMVPN `flat-pair`
  uses odd routers as DMVPN endpoints and even routers as pair partners — only
  IOS-XE routers are projected into `nac.yaml`

Example shapes (not an exhaustive list):

```powershell
topogen 1 --mode simple --offline-yaml out/iosv-test.yaml --nac --overwrite
topogen 2 --mode nx --offline-yaml out/two-router-nx.yaml --nac --overwrite
topogen 2 --mode flat-pair --device-template csr1000v -T csr-eigrp `
  --mgmt --vrf --offline-yaml out/flat-pair-csr.yaml --nac --overwrite
```

DMVPN with NaC (offline YAML + `nac/` sibling tree):

```powershell
# Flat underlay: 3 total routers (R1 hub + R2,R3 spokes) when --dmvpn-hubs 1
topogen 3 --mode dmvpn --dmvpn-hubs 1 -T iosv-dmvpn --device-template iosv `
  --offline-yaml out/dmvpn-flat-nac.yaml --nac --overwrite

# Flat-pair underlay: nodes = total routers; odd = DMVPN endpoints
topogen 4 --mode dmvpn --dmvpn-underlay flat-pair -T iosv-dmvpn --device-template iosv `
  --offline-yaml out/dmvpn-flat-pair-nac.yaml --nac --overwrite
```

Deploy device config from the generated tree (after the lab is reachable):

```powershell
terraform -chdir=out\<lab>\nac init
# Set IOSXE_USERNAME, IOSXE_PASSWORD, IOSXE_URL (and lab mgmt reachability) in the shell
terraform -chdir=out\<lab>\nac plan
terraform -chdir=out\<lab>\nac apply
```

For `--offline-yaml out/<lab>.yaml --nac`, output layout is:

- `out/<lab>/<lab>.yaml` — offline CML YAML
- `out/<lab>/nac/nac.yaml` — lean NaC model (`iosxe.devices[].configuration.*`)
- `out/<lab>/nac/main.tf` — Terraform root calling `netascode/nac-iosxe/iosxe`
- `out/<lab>/nac/versions.tf` — Terraform/provider version pins
- `out/<lab>/nac/terraform.tfvars.example` — sample vars (copy to `terraform.tfvars`)
- `out/<lab>/nac/.gitignore` — ignores Terraform state/vars
- `out/<lab>/nac/inventory.yaml` — Ansible inventory
- `out/<lab>/nac/ansible.cfg` — Ansible config for the stub
- `out/<lab>/nac/group_vars/all.yaml` — shared Ansible vars (env-var credential lookups)
- `out/<lab>/nac/host_vars/*.yaml` — per-device Ansible vars
- `out/<lab>/nac/verify_reachability.yaml` — read-only `ios_facts` smoke playbook
- `out/<lab>/nac/devices.yaml` — informational device projection (not a Terraform input)
- `out/<lab>/nac/nac_metadata.yaml` — informational provenance (not a Terraform input)

Toolchain pins (in the generated Terraform):

- Module: `netascode/nac-iosxe/iosxe` `0.1.0` (transitively pulls `netascode/utils` `1.1.0-beta3`)
- Provider: `CiscoDevNet/iosxe` `0.15.0`
- Terraform: `>= 1.8.0`

Credentials and TLS:

- No secrets are written. Terraform reads device credentials from the environment
  (`IOSXE_USERNAME` / `IOSXE_PASSWORD` / `IOSXE_URL`); Ansible uses matching env-var
  lookups in `group_vars/all.yaml`.
- The generated provider sets `insecure = true` for lab convenience. This disables
  TLS verification and is **lab-only** — do not use it against production devices.

Offline vs. deployment (what TopoGen guarantees vs. what you supply):

- TopoGen guarantees the offline artifacts only: a schema-valid `nac.yaml`, a
  pinned Terraform workspace, and a parseable Ansible stub. RESTCONF/NETCONF is
  enabled in router day0 configs when `--nac` is set.
- You supply the deployment: running `terraform init/plan/apply`, running Ansible,
  device reachability, and credentials. `topogen` does not run any deployment or
  reachability tooling — those runners are intentionally out of scope.

### Thin day-0 bootstrap (`--bootstrap`)

Use `--nac --bootstrap` (not `--blank`) when you want CML to boot a **minimal
reachability skin** and let Terraform apply routing and interfaces from `nac.yaml`.
This is the recommended path for live NaC validation on CSR1000v.

- Requires `--nac`, `--mgmt`, and `--offline-yaml`
- Cannot be combined with `--blank`, `--pki`, or `--getvpn`
- CML router configs: hostname, creds, OOB Gi DHCP (`--mgmt-bridge`), SSH,
  RESTCONF/NETCONF only — no OSPF/EIGRP or tenant interfaces in CML YAML
- Full protocol/interface intent remains in `nac.yaml`

Example (2-node nx CSR, CML lifecycle + NaC):

```powershell
python -m topogen 2 --mode nx -T csr-ospf --device-template csr1000v `
  -L "my-bootstrap-lab" --mgmt --mgmt-bridge `
  --offline-yaml out/my-bootstrap-lab.yaml `
  --nac --bootstrap --terraform-cml2 --overwrite

terraform -chdir=out/my-bootstrap-lab/cml2 init
terraform -chdir=out/my-bootstrap-lab/cml2 apply -auto-approve `
  -var="address=$env:VIRL2_URL" -var="username=$env:VIRL2_USER" `
  -var="password=$env:VIRL2_PASS" -var="skip_verify=true" -var="wait=true"

$labId = terraform -chdir=out/my-bootstrap-lab/cml2 output -raw lab_id
python scripts/sync-nac-mgmt-dhcp.py --lab-id $labId `
  --nac-root out/my-bootstrap-lab/nac --device-template csr1000v

$env:IOSXE_USERNAME = "cisco"; $env:IOSXE_PASSWORD = "cisco"
terraform -chdir=out/my-bootstrap-lab/nac init
terraform -chdir=out/my-bootstrap-lab/nac apply -auto-approve
```

Generated YAML provenance (`description`, `notes`, annotation) includes
`--bootstrap` in the `args:` string when the flag is set.

## CML2 Terraform lifecycle scaffold (`--terraform-cml2`)

`--terraform-cml2` is an offline-only path that emits a Terraform lifecycle
workspace for the generated CML YAML. It uses the official `CiscoDevNet/cml2`
provider and the `cml2_lifecycle` resource so Terraform can import and start the
generated lab. `--cml2` is accepted as a short compatibility alias.

`--terraform-cml2` and `--nac` are independent: when both are set, `cml2/` and
`nac/` are sibling directories under `out/<lab>/` (lab topology in
`out/<lab>/<lab>.yaml`).

### Generate the scaffold

```powershell
topogen 2 --mode simple --offline-yaml out\cml2-simple.yaml --terraform-cml2 --overwrite
```

Optional: also emit NaC artifacts in the same run:

```powershell
topogen 2 --mode flat --offline-yaml out\cml2-nac.yaml --terraform-cml2 --nac --overwrite
```

### Apply with Terraform

From the repo (or any directory), point Terraform at the generated workspace.
Provide CML connection values via `TF_VAR_*` or a local `terraform.tfvars` (not
written by TopoGen — do not commit credentials).

```powershell
terraform -chdir=out\cml2-simple\cml2 init
$env:TF_VAR_address = "https://<your-cml-controller>/"
$env:TF_VAR_username = "<cml-user>"
$env:TF_VAR_password = "<cml-password>"
# Or use TF_VAR_token instead of username/password where your provider setup allows
terraform -chdir=out\cml2-simple\cml2 plan
terraform -chdir=out\cml2-simple\cml2 apply
```

After apply, use `terraform output` in that directory for lab ID, lifecycle
state, and node details. Device configuration (if you also used `--nac`) is a
separate step in `out/<lab>/nac/` after routers are reachable.

For `--offline-yaml out/<lab>.yaml --terraform-cml2`, output layout is:

- `out/<lab>/<lab>.yaml` — offline CML YAML
- `out/<lab>/cml2/main.tf` — `cml2_lifecycle` resource using `file(var.topology_file)`
- `out/<lab>/cml2/variables.tf` — CML connection inputs and lifecycle controls
- `out/<lab>/cml2/versions.tf` — Terraform/provider version constraints
- `out/<lab>/cml2/outputs.tf` — lab ID, lifecycle ID, state, boot status, and node details
- `out/<lab>/cml2/.gitignore` — ignores Terraform state/vars

No CML credentials are written. The generated `topology_file` default is a
relative path such as `../<lab>.yaml`; no machine-local paths are embedded.

## Code structure and dependencies

```
topogen CLI
    ↓
main.py (args + config)
    ↓
render.py (core engine)
    ↓
templates (*.jinja2)
    ↓
+--------------------+
| Offline: YAML file |
| Online: CML API    |
+--------------------+
```

For a developer-oriented starting point (repo layout, entrypoints, dependency chain, and Gooey notes), see [DEVELOPER.md](DEVELOPER.md).

## Installation

> **Important** Ensure that the PCL you install is compatible with your controller.
If it doesn't work, then try installing the wheel with Pip manually. The wheel can
be downloaded from your controller at the `/client` location.

Steps:

1. clone this directory
2. create virtual environment in it `python3 -mvenv .venv`
3. activate the venv `source .venv/bin/activate` (or with
   .fish or .bat, ...)
4. install using `python3 -m pip install -e .`

Alternatively, use Astral/uv:

1. clone this directory
2. create the venv: `uv venv`
3. activate the venv `source .venv/bin/activate` (optional, can also
   run with `uv run`)
4. install using `uv sync --frozen`

If `topogen -v` (or the generated lab description) shows an older version than this repo, reinstall the package in editable mode to refresh the installed package metadata:

```powershell
python -m pip install -e .
```

### Optional GUI (Gooey)

TopoGen includes an optional Gooey-based GUI entry point.

- Install: `pip install -e ".[gui]"`
- Run: `topogen-gui` (or `python -m topogen.gui`)

If you add or change CLI flags or GUI behavior in the repo (for example `--overwrite`), reinstall in editable mode to ensure the GUI reflects the latest code:

```powershell
python -m pip install -e ".[gui]"
```

Quick usage:

- Offline YAML (no controller):
  - Set `offline-yaml` to a filename under `out/`, e.g. `out\my-lab.yaml`
  - Leave the export `yaml` field empty
  - Choose `mode`, `template`, `device-template`, and `nodes`
  - Click Start and then import the YAML into CML (Tools → Import/Export → Import Lab)
- Online (create lab on a live controller):
  - Leave `offline-yaml` empty
  - Set environment variables before launching the GUI (PowerShell):
    - `$env:VIRL2_URL="https://controller/"`
    - `$env:VIRL2_USER="user"`
    - `$env:VIRL2_PASS="pass"`
  - Optionally set `yaml` to export the created lab after generation
  - Use `insecure` for a quick test, or provide a working `ca` file

Field mapping:

- `offline-yaml` (FILE): writes a CML-compatible YAML locally (`--offline-yaml`)
- `yaml` (FILE): exports the created online lab to a YAML file via the controller API (`--yaml`)

Note: `--device-template` maps to the CML node definition name (e.g., `iosv`, `csr1000v`). Available node definitions vary by CML server and version (and by installed images). The GUI shows a small convenience dropdown; if you use custom node definitions, prefer running the CLI where `--device-template` is free-form.

Note: In the GUI, `--template` is shown as a dropdown. The dropdown choices come from the packaged templates (`get_templates()`), and the default template is `iosv`. If you remove/rename `iosv.jinja2`, the GUI may error because the default is not in the available template choices.

If the Networkx mode (`--mode nx`) should be used, then the following
command is required instead to install SciPy and NumPy dependencies: `uv sync
--all-extras --dev --frozen`

At this point, the `topogen` command should be available. Alternatively,
if you did not activate the venv, use `uv run topogen`.

## Configuration

### CML2

CML2 access is provided via the environment.  Like shown with this shell snippet:

```shell
VIRL2_URL="https://cml-controller.cml.lab"
VIRL2_USER="someuser"
VIRL2_PASS="somepass"
export VIRL2_URL VIRL2_USER VIRL2_PASS
```

TopoGen reads these variables and passes them explicitly to the CML client, so setting them in the same shell session (e.g. PowerShell `$env:VIRL2_URL="https://controller"`) before running `topogen` is sufficient for online mode.

In addition, a CA file in PEM format can be provided which can be used to verify
the cert presented by the controller... The default CA file of the controller is
included in the repo.

For this to work, it's also required to have proper name resolution for the CML2
controller (e.g. add `192.168.254.123 cml-controller.cml.lab` with **the correct
IP** into your hosts file).

### Tool

Run the CLI with `topogen` (after install) or `python -m topogen`. The tool accepts a variety of command line switches. Run `topogen --help` (or `python -m topogen --help`) for the full, current list of flags.

```plain
$ topogen --help
usage: topogen [-h] [-c CONFIGFILE] [-w] [-v] [-l LOGLEVEL] [-p] [-q]
               [--ca CAFILE] [-i] [-d DISTANCE] [-L LABNAME] [-R REMARK]
               [-T TEMPLATE] [--device-template DEV_TEMPLATE]
               [--list-templates] [-m {nx,simple,flat,flat-pair,dmvpn}]
               [--dmvpn-phase {2,3}] [--dmvpn-routing {eigrp,ospf}]
               [--eigrp-stub]
               [--dmvpn-security {none,ikev2-psk,ikev2-pki,ikev2-rsa}]
               [--dmvpn-trustpoint DMVPN_TRUSTPOINT] [--dmvpn-psk DMVPN_PSK]
               [--dmvpn-underlay {flat,flat-pair}]
               [--dmvpn-nbma-cidr DMVPN_NBMA_CIDR]
               [--dmvpn-tunnel-cidr DMVPN_TUNNEL_CIDR]
               [--dmvpn-tunnel-key DMVPN_TUNNEL_KEY] [--dmvpn-hubs DMVPN_HUBS]
               [--flat-group-size FLAT_GROUP_SIZE] [--loopback-255]
               [--gi0-zero] [--vrf] [--pair-vrf PAIR_VRF]
               [--dmvpn-fvrf DMVPN_FVRF]
               [--dmvpn-ipsec-mode {transport,tunnel}] [--mgmt]
               [--mgmt-ipv4-dhcp] [--mgmt-ipv6-dhcp] [--mgmt-ipv6-slaac]
               [--mgmt-ipv6-static] [--mgmt-ipv6-static-link-local]
               [--mgmt-cidr MGMT_CIDR] [--mgmt-gw MGMT_GW]
               [--mgmt-slot MGMT_SLOT] [--mgmt-vrf MGMT_VRF] [--mgmt-bridge]
               [--mgmt-ipv6-mode {slaac,dhcpv6}] [--mgmt-ipv6-cidr MGMT_IPV6_CIDR]
               [--ntp NTP_SERVER] [--ntp-vrf NTP_VRF] [--ntp-inband]
               [--ntp-oob NTP_OOB_SERVER] [--pki] [--archive] [--getvpn]
               [--getvpn-group-id GETVPN_GROUP_ID]
               [--getvpn-rekey-interval GETVPN_REKEY_INTERVAL]
               [--getvpn-protocol {gdoi,gikev2}] [--staging] [--no-staging]
               [--no-abort-on-failure] [--pki-enroll {scep,cli}] [--start]
               [--yaml FILE] [--offline-yaml FILE] [--nac] [--bootstrap]
               [--terraform-cml2] [--overwrite] [--intent-spot]
               [--import-yaml FILE]
               [--import] [--up FILE] [--print-up-cmd]
               [--cml-version {0.0.1,0.0.2,0.0.3,0.0.4,0.0.5,0.1.0,0.2.0,0.2.1,0.2.2,0.3.0,0.3.1}]
               [--allow-oversubscribe] [--blank]
               [nodes]

Generate test topology files and configurations for CML2

positional arguments:
  nodes                 Number of nodes to generate (2-1000; --nac offline
                        generation also allows 1 where supported by the
                        selected mode)

options:
  -h, --help            show this help message and exit
  --ca CAFILE           Use the CA certificate from this file (PEM format),
                        defaults to ca.pem
  -i, --insecure        If no CA provided, do not verify TLS (insecure!)
  -d DISTANCE, --distance DISTANCE
                        Node distance, default 200
  -L LABNAME, --labname LABNAME
                        Lab name to create, default "topogen lab"
  -R REMARK, --remark REMARK
                        Add a custom remark/note to the lab description
                        (optional)
  -T TEMPLATE, --template TEMPLATE
                        Template name to use, defaults to "iosv"
  --device-template DEV_TEMPLATE
                        CML node definition to use for routers (e.g., iosv,
                        iol, lxc). Defaults to "iosv"
  --list-templates      List all available templates
  -m {nx,simple,flat,flat-pair,dmvpn}, --mode {nx,simple,flat,flat-pair,dmvpn}
                        mode of operation, default is "simple"
  --dmvpn-phase {2,3}   DMVPN phase (2 or 3), default 2
  --dmvpn-routing {eigrp,ospf}
                        Routing protocol over DMVPN tunnel, default "eigrp"
  --eigrp-stub          Enable EIGRP stub (connected summary) on selected
                        routers (DMVPN flat-pair: even routers)
  --dmvpn-security {none,ikev2-psk,ikev2-pki,ikev2-rsa}
                        DMVPN security: none, ikev2-psk (requires --dmvpn-
                        psk), ikev2-pki (requires --pki), ikev2-rsa (PKI/cert,
                        requires --dmvpn-trustpoint), default "none"
  --dmvpn-trustpoint DMVPN_TRUSTPOINT
                        DMVPN IKEv2 PKI trustpoint name (used when --dmvpn-
                        security ikev2-rsa), default CA-ROOT-SELF
  --dmvpn-psk DMVPN_PSK
                        DMVPN IKEv2 pre-shared key (used when --dmvpn-security
                        ikev2-psk)
  --dmvpn-underlay {flat,flat-pair}
                        DMVPN underlay topology, default "flat"
  --dmvpn-nbma-cidr DMVPN_NBMA_CIDR
                        NBMA underlay CIDR for DMVPN WAN segment, default
                        "10.10.0.0/16"
  --dmvpn-tunnel-cidr DMVPN_TUNNEL_CIDR
                        Tunnel overlay CIDR for DMVPN Tunnel0 addressing,
                        default "172.20.0.0/16"
  --dmvpn-tunnel-key DMVPN_TUNNEL_KEY
                        DMVPN Tunnel0 key (GRE tunnel key), default 10
  --dmvpn-hubs DMVPN_HUBS
                        Comma-separated router numbers to act as DMVPN hubs
                        (e.g., 1,21,41). When set, the nodes argument is
                        interpreted as total routers.
  --flat-group-size FLAT_GROUP_SIZE
                        Routers per unmanaged switch when using flat mode,
                        default 20
  --loopback-255        Use 10.255.C.D/32 for Loopback0 addressing in flat
                        mode (default is 10.20.C.D/32)
  --gi0-zero            Use 10.0.C.D/16 for Gi0/0 addressing in flat mode
                        (default is 10.10.C.D/16)
  --vrf                 Enable VRF configuration (applies to flat-pair odd-
                        router Gi0/1 when combined with --pair-vrf)
  --pair-vrf PAIR_VRF   VRF name to apply to the flat-pair odd-router Gi0/1
                        (pair link), default "tenant"
  --dmvpn-fvrf DMVPN_FVRF
                        Enable Front Door VRF: place the NBMA interface into
                        the named transport VRF (e.g. INTERNET). Adds tunnel
                        vrf, match fvrf to IKEv2, and ip tcp adjust-mss 1360
                        on Tunnel0.
  --dmvpn-ipsec-mode {transport,tunnel}
                        DMVPN IPsec transform-set mode: transport (default,
                        recommended for GRE) or tunnel, default "transport"
  --mgmt                Enable OOB management fabric (SWoob, router mgmt
                        interfaces, optional VRF). Addressing is separate:
                        --mgmt-ipv4-dhcp and/or --mgmt-ipv6-dhcp / --mgmt-ipv6-slaac.
  --mgmt-ipv4-dhcp      IPv4 DHCP on the OOB interface (ip address dhcp). With
                        --mgmt-bridge and no other addressing flags, IPv4 DHCP
                        is implied for backward compatibility.
  --mgmt-ipv6-dhcp      IPv6 DHCPv6 on the OOB interface (ipv6 address dhcp).
                        IPv6-only unless combined with --mgmt-ipv4-dhcp.
                        Requires --mgmt and named --mgmt-vrf.
  --mgmt-ipv6-slaac     IPv6 SLAAC on the OOB interface (ipv6 address
                        autoconfig). IPv6-only unless combined with --mgmt-ipv4-dhcp.
                        Requires --mgmt and named --mgmt-vrf.
  --mgmt-cidr MGMT_CIDR
                        Management network CIDR, default "10.254.0.0/16"
  --mgmt-gw MGMT_GW     Management network gateway IP (optional); adds a
                        default route in the mgmt VRF if set
  --mgmt-slot MGMT_SLOT
                        Interface slot for management (IOSv Gi0/N, CSR GiN),
                        default 5
  --mgmt-vrf MGMT_VRF   VRF name for management interface (default: "Mgmt-
                        vrf"); use "global" for global routing table
  --mgmt-bridge         Add external-connector to bridge OOB management
                        network to external network (requires --mgmt)
  --mgmt-ipv6-mode {slaac,dhcpv6}
                        Legacy alias for --mgmt-ipv6-slaac (slaac) or --mgmt-ipv6-dhcp
                        (dhcpv6). Prefer the explicit flags for new labs.
  --mgmt-ipv6-cidr MGMT_IPV6_CIDR
                        Optional IPv6 prefix hint for SLAAC/DHCPv6 pool (metadata;
                        static IPv6 OOB addressing not implemented).
  --ntp NTP_SERVER      NTP server IP address (optional)
  --ntp-vrf NTP_VRF     VRF for NTP (e.g. Mgmt-vrf). Omit for global. With
                        --mgmt, default is mgmt VRF unless --ntp-inband.
  --ntp-inband          Put --ntp server in global (inband); no VRF. Use when
                        CA is NTP server on data network.
  --ntp-oob NTP_OOB_SERVER
                        Optional second NTP server in mgmt VRF (e.g. external
                        NTP). Use with --mgmt.
  --pki                 Enable PKI Root CA (adds CA-ROOT router for
                        certificate services)
  --archive             Enable config archive and rundiff alias on routers
                        (archive log config, path flash:, write-memory)
  --getvpn              Enable GET VPN (Group Encrypted Transport VPN) with a
                        Key Server and all routers as Group Members (requires
                        --pki)
  --getvpn-group-id GETVPN_GROUP_ID
                        GET VPN GDOI/GKM group identity number, default 1
  --getvpn-rekey-interval GETVPN_REKEY_INTERVAL
                        GET VPN rekey lifetime in seconds, default 86400 (24h)
  --getvpn-protocol {gdoi,gikev2}
                        GET VPN control plane protocol: gdoi (ISAKMP/IKEv1) or
                        gikev2 (IKEv2), default "gdoi"
  --staging             Enable CML 2.10 node staging for boot ordering
                        (requires --cml-version >= 0.3.1). Also enabled
                        automatically when --pki is used unless --no-staging
                        is set.
  --no-staging          Disable node staging even when --pki would auto-enable
                        it; also disables --staging
  --no-abort-on-failure
                        With --staging, disable abort-on-failure so all nodes
                        attempt to boot even if a higher-priority node fails
  --pki-enroll {scep,cli}
                        PKI enrollment mode: scep (auto via SCEP) or cli
                        (manual CLI enrollment for external CA)
  --start               Automatically start the lab after creation
  --yaml FILE           Export the created lab to a YAML file at FILE
  --offline-yaml FILE   Generate a CML-compatible YAML locally (no controller
                        required)
  --nac                 Enable NaC artifacts for offline YAML generation
                        (requires IOS-XE router templates)
  --bootstrap           Thin day-0 router config for --nac (mgmt reachability
                        and RESTCONF only; requires --mgmt; incompatible with
                        --blank)
  --terraform-cml2, --cml2
                        Enable Terraform lifecycle scaffold generation for
                        offline CML2 labs
  --overwrite           Allow overwriting an existing output file when using
                        --offline-yaml
  --intent-spot         Add INTENT-SPOT debug unmanaged_switch at intent
                        annotation coordinates for visual QA in CML Workbench
                        (no router license; online and offline; not for
                        production)
  --import-yaml FILE    Path to existing offline YAML to import (skip
                        generation); use with --import
  --import              Import the generated or specified YAML into CML
                        (requires --offline-yaml or --import-yaml)
  --up FILE             Shorthand for --import-yaml FILE --import --start
                        (import YAML to CML and start lab)
  --print-up-cmd        With --offline-yaml, print the topogen --up <file>
                        command to run later
  --cml-version {0.0.1,0.0.2,0.0.3,0.0.4,0.0.5,0.1.0,0.2.0,0.2.1,0.2.2,0.3.0,0.3.1}
                        CML lab schema version for offline YAML (CML 2.5:
                        0.2.0, CML 2.7: 0.2.2, CML 2.8/2.9: 0.3.0, CML 2.10:
                        0.3.1)
  --allow-oversubscribe
                        Bypass the recommended 520-node lab limit (use with
                        caution)
  --blank               Topology only: emit nodes and links but omit router
                        configurations (enables CML Bootstrap Lab)

configuration:
  -c CONFIGFILE, --config CONFIGFILE
                        Use the configuration from this file, defaults to
                        config.toml
  -w, --write           Write the default configuration to a file and exit
  -v, --version         show program's version number and exit
  -l LOGLEVEL, --loglevel LOGLEVEL
                        DEBUG, INFO, WARN, ERROR, CRITICAL, defaults to WARN
  -p, --progress        show a progress bar
  -q, --quiet           suppress non-essential output (INFO/WARN); only errors
                        and final result
```

**CML version / schema compatibility:** The `--cml-version` flag sets the lab schema version in offline YAML **and** controls which optional fields are emitted. It is **authoritative** when passed explicitly. **`--cml-server`** is a convenience alias for operators who think in controller versions — it sets the schema only when `--cml-version` is omitted. Known mapping:

- CML 2.5 = schema `0.2.0`. CML 2.6 = `0.2.1`. CML 2.7 = `0.2.2`. No `smart_annotations` in YAML.
- CML 2.8–2.9 = schema `0.3.0`. `smart_annotations` included.
- CML 2.10 = schema `0.3.1`. Adds `lab.node_staging` and per-node `priority` for staged boot.
- Unknown future `--cml-server` (e.g. `2.13`) → highest known schema (`0.3.1` today) with an INFO log. Versions below the lowest mapped release (e.g. `2.4`) use the nearest lower anchor (`2.5` / `0.2.0`).

When targeting CML 2.7 or earlier, use `--cml-version 0.2.2` (or lower), or `--cml-server 2.7`. TopoGen automatically omits `smart_annotations` for schema versions `<= 0.2.2`.

At a minimum, the amount of nodes to be created must be provided.

#### Modes

There are three modes available right now:

- `nx`: this creates a partially meshed topology.  It also places nodes in clusters
  which is more pronounced with many nodes (>40).
- `simple` (which is the default): this creates a single string of nodes, laid out
  in a square / spiral pattern.
- `flat`: builds a flat L2 fabric for large-scale experiments. One core unmanaged
  switch (SW0) connects to N access unmanaged switches (SW1..N). Each router
  connects only to its access switch on `Gi0/0`. Group size per access switch is
  controlled by `--flat-group-size` (default 20). No router-to-router links are
  created in this mode.

```mermaid
graph TD
    SWcore["SW0 (core)"]
    SW1["SW1"]
    SW2["SW2"]
    SWcore --- SW1
    SWcore --- SW2
    SW1 ---|"Gi0/0"| R1
    SW1 ---|"Gi0/0"| R2
    SW1 ---|"Gi0/0"| R3
    SW2 ---|"Gi0/0"| R4
    SW2 ---|"Gi0/0"| R5
    SW2 ---|"Gi0/0"| R6
```

- `flat-pair`: similar to `flat`, but routers are odd/even paired.
  - Odd routers: `Gi0/0` connects to the access switch and `Gi0/1` connects to the even router's `Gi0/0`.
  - Even routers: no access-switch link; only paired to the preceding odd router.
  - If the last router is odd and has no partner, its `Gi0/1` is unused.

```mermaid
graph TD
    SWcore["SW0 (core)"]
    SW1["SW1"]
    SWcore --- SW1
    SW1 ---|"Gi0/0"| R1["R1 (odd)"]
    R1 ---|"Gi0/1 -- Gi0/0"| R2["R2 (even)"]
    SW1 ---|"Gi0/0"| R3["R3 (odd)"]
    R3 ---|"Gi0/1 -- Gi0/0"| R4["R4 (even)"]
    SW1 ---|"Gi0/0"| R5["R5 (odd, unpaired)"]
```
- `dmvpn`: hub-and-spoke DMVPN topology.
  - Default behavior: `nodes` is the number of **spokes** (R1 is hub; R2.. are spokes). So **total router count = nodes + 1** (e.g. `nodes=5` → R1 hub + R2–R6 spokes = 6 routers).
  - Multi-hub: use `--dmvpn-hubs` to specify hub router numbers (e.g., `1,21,41`).
    - When `--dmvpn-hubs` is set, `nodes` is interpreted as total routers (`R1..R<nodes>`).
    - **Important:** `--dmvpn-hubs` is a comma-separated *list of router numbers*, not a hub count. For example, `--dmvpn-hubs 3` means **R3 is the (only) hub**, not "3 hubs".
  - Underlay selection: use `--dmvpn-underlay` to choose the underlay model.
    - `flat` (default): DMVPN routers attach to a flat L2 fabric.
    - `flat-pair`: `nodes` is the total router count in the lab (`R1..R<nodes>`).
      - Odd routers (`R1,R3,R5,...`): DMVPN overlay routers (hubs + spokes) (Tunnel0 + NHRP + routing).
      - Even routers (`R2,R4,R6,...`): non-DMVPN pair partners (no Tunnel0/NHRP).
      - Spokes are the odd routers not selected as hubs; this is always derived from `nodes`.
  - Optional: set `--dmvpn-tunnel-key` to configure a GRE tunnel key (default: 10).
  - Optional: set `--dmvpn-security ikev2-psk` to protect DMVPN with IKEv2+PSK.
    - Requires `--dmvpn-psk <key>`.
    - Uses IPsec transport mode by default with `tunnel protection ipsec profile ...` on `Tunnel0`. Use `--dmvpn-ipsec-mode tunnel` to switch to tunnel mode.
    - **Important:** if you set `--dmvpn-security ikev2-psk` but omit `--dmvpn-psk`, TopoGen exits with an error.
  - Optional: set `--dmvpn-security ikev2-pki` to protect DMVPN with IKEv2 and certificate-based auth (PKI).
    - Requires `--pki` (adds CA-ROOT and injects trustpoint CA-ROOT-SELF on non-CA routers).
    - IKEv2 profile uses `authentication local rsa-sig` / `authentication remote rsa-sig` and `pki trustpoint CA-ROOT-SELF`.
    - **Important:** if you set `--dmvpn-security ikev2-pki` but omit `--pki`, TopoGen exits with an error.
    - **Note:** DMVPN with IKEv2 PKI is not yet validated; tunnels may not come up (IKEv2 SA / enrollment troubleshooting in progress).
  - Optional: `--archive` — enable config archive and `rundiff` alias on all IOS/IOS-XE routers in flat, flat-pair, and dmvpn modes (`archive` with `log config`, `path flash:`, `write-memory`). Omit to leave archive config out of generated configs.
  - Optional: `-q` / `--quiet` — suppress INFO and WARNING; only errors and final result (useful for scripts and CI/CD).
  - Defaults:
    - NBMA: `10.10.0.0/16` (router WAN on slot 0)
    - Tunnel: `172.20.0.0/16` (Tunnel0)
    - Phase 2, EIGRP, no security

Notes:

- For offline YAML, the NBMA underlay is built as a flat-style L2 fabric (core + access unmanaged switches) to avoid unmanaged switch port limits. `--flat-group-size` controls routers per access switch.
- Offline DMVPN YAML layout follows the same placement style as `flat` / `flat-pair` (switches in a row, routers stacked under each switch).

Lab naming (recommended):

- Use the lab name to track the feature, platform, and size.
- Convention example: `IOSXE-DMVPN-P2-EIGRP-N3`
  - `IOSXE`: CSR1000v (IOS-XE)
  - `DMVPN`: feature
  - `P2`: DMVPN Phase 2
  - `EIGRP`: routing protocol over the tunnel
  - `N3`: total router count (hub + spokes)

Examples:

- Offline YAML (recommended):

```powershell
topogen -m dmvpn -T iosv-dmvpn --device-template iosv --offline-yaml out\dmvpn-iosv.yaml 2
```

- Offline YAML (flat with PKI and archive): 4 routers + CA-ROOT; config archive and `rundiff` alias on all IOS/IOS-XE nodes.

```powershell
topogen -m flat 4 -T iosv --pki --archive --offline-yaml out\flat-pki-archive.yaml --overwrite
```

- Online (flat with PKI and archive): set `VIRL2_URL`, `VIRL2_USER`, `VIRL2_PASS` in the same shell, then create the lab. Use `-i` if the controller uses a self-signed cert.

```powershell
$env:VIRL2_URL = "https://192.168.1.164"; $env:VIRL2_USER = "admin"; $env:VIRL2_PASS = "yourpass"
python -m topogen -m flat 4 -T iosv --pki --archive -i
```

- Offline YAML (multi-hub): 60 spokes + 3 hubs (`R1,R21,R41`) = 63 routers total.

```powershell
topogen --cml-version 0.3.0 -m dmvpn -T iosv-dmvpn --device-template iosv `
  -L "IOS-DMVPN-3H-P2-EIGRP-N63" `
  --offline-yaml out\IOS-DMVPN-3H-P2-EIGRP-N63.yaml `
  --dmvpn-hubs 1,21,41 63
```

- Offline YAML (multi-hub, IOS-XE): 60 spokes + 3 hubs (`R1,R21,R41`) = 63 routers total.

```powershell
topogen --cml-version 0.3.0 -m dmvpn -T csr-dmvpn --device-template csr1000v `
  -L "IOSXE-DMVPN-3H-P2-EIGRP-N63" `
  --offline-yaml out\IOSXE-DMVPN-3H-P2-EIGRP-N63.yaml `
  --dmvpn-hubs 1,21,41 63
```

- Offline YAML (DMVPN flat-pair, IOSv): 314 routers total (`R1..R314`). Odd routers participate in the DMVPN overlay (hubs + spokes).

```powershell
topogen -m dmvpn --dmvpn-underlay flat-pair -T iosv-dmvpn --device-template iosv --eigrp-stub -L IOSV-DMVPN-FLAT-PAIR-EIGRP-N314 --offline-yaml out\IOSV-DMVPN-FLAT-PAIR-EIGRP-N314.yaml --overwrite 314
```

- Offline YAML (DMVPN flat-pair, IOSv, VRF + IKEv2-PSK): 50 routers total, 3 hubs (`R1,R21,R41`).

```powershell
topogen --cml-version 0.3.0 -m dmvpn --dmvpn-underlay flat-pair -T iosv-dmvpn --device-template iosv --dmvpn-hubs 1,21,41 --dmvpn-phase 3 --dmvpn-routing eigrp --dmvpn-security ikev2-psk --dmvpn-psk "topogen123" --vrf --progress --offline-yaml out\IOSV-DMVPN-FLAT-PAIR-3H-P3-EIGRP-VRF-IPSEC-PSK-N50.yaml --overwrite 50
```

- Offline YAML (DMVPN flat-pair, IOSv, mgmt + mgmt bridge): 20 routers total, 3 hubs (`R1,R3,R5`). Bridges the OOB management switch (SWoob0) to your external network using an `external_connector` ("System Bridge" mode).

```powershell
topogen --cml-version 0.3.0 -m dmvpn --dmvpn-underlay flat-pair -T iosv-dmvpn --device-template iosv --dmvpn-hubs 1,3,5 --dmvpn-phase 3 --dmvpn-routing eigrp --dmvpn-security ikev2-psk --dmvpn-psk "topogen123" --mgmt --mgmt-bridge --mgmt-cidr 10.254.0.0/16 --mgmt-slot 5 --mgmt-vrf Mgmt-vrf --offline-yaml out\IOSV-DMVPN-FLAT-PAIR-3H-P3-EIGRP-MGMT-BRIDGE-N20.yaml --overwrite 20
```

- Offline YAML (DMVPN with IKEv2 PKI): 4 routers (1 hub + 3 spokes), cert-based auth; requires `--pki` (CA-ROOT + client trustpoints).

```powershell
topogen --cml-version 0.3.0 -m dmvpn -T csr-dmvpn --device-template csr1000v --dmvpn-security ikev2-pki --pki --offline-yaml out\IOSXE-DMVPN-IKEV2-PKI-N4.yaml --overwrite 4
```

- Offline YAML (DMVPN Phase 3, IKEv2 PKI, 1 hub + 10 spokes): Flat underlay, lab name matches filename. Bring up CA-ROOT first, then R1 (hub), then R2..R11 (see **DMVPN with IKEv2 PKI: bring-up order** above).

```powershell
# IOSv (lab title = DMVPN-P3-IOSv-11)
topogen -m dmvpn -T iosv-dmvpn --device-template iosv --dmvpn-phase 3 --dmvpn-routing eigrp --dmvpn-security ikev2-pki --dmvpn-nbma-cidr 10.10.0.0/16 --dmvpn-tunnel-cidr 172.20.0.0/16 --dmvpn-hubs 1 --pki --cml-version 0.3.0 --mgmt --mgmt-cidr 10.254.0.0/16 --mgmt-slot 5 --mgmt-vrf Mgmt-vrf --ntp 10.10.255.254 --ntp-inband -L "DMVPN-P3-IOSv-11" --offline-yaml out/DMVPN-P3-IOSv-11.yaml --overwrite 11

# CSR (lab title = DMVPN-P3-CSR-11)
topogen -m dmvpn -T csr-dmvpn --device-template csr1000v --dmvpn-phase 3 --dmvpn-routing eigrp --dmvpn-security ikev2-pki --dmvpn-nbma-cidr 10.10.0.0/16 --dmvpn-tunnel-cidr 172.20.0.0/16 --dmvpn-hubs 1 --pki --cml-version 0.3.0 --mgmt --mgmt-cidr 10.254.0.0/16 --mgmt-slot 5 --mgmt-vrf Mgmt-vrf --ntp 10.10.255.254 --ntp-inband -L "DMVPN-P3-CSR-11" --offline-yaml out/DMVPN-P3-CSR-11.yaml --overwrite 11
```

- Offline YAML (DMVPN Phase 3, IKEv2 PKI, flat-pair underlay, 10 total routers): odd routers (R1,R3,R5,R7,R9) are DMVPN endpoints; even routers (R2,R4,R6,R8,R10) are pair partners with no DMVPN. R1 is hub. CA-ROOT added automatically by `--pki`.

```powershell
# IOSv flat-pair PKI
topogen --cml-version 0.3.0 -m dmvpn --dmvpn-underlay flat-pair -T iosv-dmvpn --device-template iosv --dmvpn-phase 3 --dmvpn-routing eigrp --dmvpn-security ikev2-pki --dmvpn-nbma-cidr 10.10.0.0/16 --dmvpn-tunnel-cidr 172.20.0.0/16 --dmvpn-hubs 1 --pki --cml-version 0.3.0 --mgmt --mgmt-cidr 10.254.0.0/16 --mgmt-slot 5 --mgmt-vrf Mgmt-vrf --mgmt-bridge --ntp 10.10.255.254 --ntp-inband -L "DMVPN-P3-PKI-FP-10-OOB-EXT-IOSv-v1" --offline-yaml "out/DMVPN-P3-PKI-FP-10-OOB-EXT-IOSv-v1.yaml" --overwrite 10

# CSR flat-pair PKI
topogen --cml-version 0.3.0 -m dmvpn --dmvpn-underlay flat-pair -T csr-dmvpn --device-template csr1000v --dmvpn-phase 3 --dmvpn-routing eigrp --dmvpn-security ikev2-pki --dmvpn-nbma-cidr 10.10.0.0/16 --dmvpn-tunnel-cidr 172.20.0.0/16 --dmvpn-hubs 1 --pki --cml-version 0.3.0 --mgmt --mgmt-cidr 10.254.0.0/16 --mgmt-slot 5 --mgmt-vrf Mgmt-vrf --mgmt-bridge --ntp 10.10.255.254 --ntp-inband -L "DMVPN-P3-PKI-FP-10-OOB-EXT-CSR-v1" --offline-yaml "out/DMVPN-P3-PKI-FP-10-OOB-EXT-CSR-v1.yaml" --overwrite 10
```

- Offline YAML (DMVPN flat-pair, IOS-XE): 314 routers total (`R1..R314`). Odd routers participate in the DMVPN overlay (hubs + spokes).

```powershell
topogen -m dmvpn --dmvpn-underlay flat-pair -T csr-dmvpn --device-template csr1000v --eigrp-stub -L IOSXE-DMVPN-FLAT-PAIR-EIGRP-N314 --offline-yaml out\IOSXE-DMVPN-FLAT-PAIR-EIGRP-N314.yaml --overwrite 314
```

- Offline YAML (GET VPN with GDOI): 4 routers as Group Members, Key Server (KS), CA-ROOT for PKI. Uses ISAKMP/IKEv1 control plane (legacy GDOI).

```powershell
# GDOI (default)
topogen -m flat -T iosv-eigrp --pki --getvpn --offline-yaml out\GETVPN-GDOI-N4.yaml --overwrite 4

# G-IKEv2 (modern IKEv2-based)
topogen -m flat -T iosv-eigrp --pki --getvpn --getvpn-protocol gikev2 --offline-yaml out\GETVPN-GIKEV2-N4.yaml --overwrite 4

# GETVPN with DMVPN underlay
topogen -m dmvpn -T csr-dmvpn --device-template csr1000v --pki --getvpn --offline-yaml out\GETVPN-DMVPN-N4.yaml --overwrite 4
```

Notes:

- `--eigrp-stub`: enables `eigrp stub connected summary` on DMVPN `flat-pair` even routers (pair partners).

- Online (controller):

```powershell
topogen -m dmvpn -T iosv-dmvpn --device-template iosv 2
```

> [!NOTE]
> Flat mode implements a star fabric (not chained). Unmanaged switch interfaces are
> labeled `portN` in generated offline YAML (CML UI may present differently).

#### Templates

To list the available templates, use the `--list-templates` switch.  Templates include:

- `iosv`: default IOSv OSPF-based template
- `iosv-eigrp`: IOSv template that configures EIGRP 100 and advertises both `Gi0/0`
  and `Loopback0` (with `Loopback0` set to passive)
- `iosv-eigrp-stub`: IOSv template that configures EIGRP 100 and advertises both `Gi0/0`
  and `Loopback0` (with `Loopback0` set to passive) and enables eigrp stub connected summary
- `iosv-eigrp-nonflat`: IOSv template for simple/NX modes. EIGRP 100 with passive-interface Loopback0; advertises 10.0.0.0/8 (Lo0) and 172.16.0.0/12 (p2p links).
- `csr-eigrp`: CSR1000v (IOS-XE) template for flat/flat-pair modes. Uses `vrf definition TENANT` and CSR interface labels (`GigabitEthernet1/2/...`).

To choose a specific template, provide the `--template=iosv` switch.

[!NOTE] In non-flat (simple/NX) EIGRP labs, the DNS/jumphost does not run EIGRP, so a default route (0/0) is not automatically originated into the EIGRP domain. Until this is improved, manually originate a default on the intended exit router, or configure a per-router static default toward the DNS path. This does not affect flat/offline mode.

Currently, all router nodes are using the same configuration template. The CML node
definition can be selected independently via `--device-template`.

### Flat mode addressing (deterministic)

In `flat` mode, interface addresses are deterministic and encode the router number
in the last 16 bits (1-based). For router `Rn` where `n` is 1..N:

- `Gi0/0` = `10.10.C.D/16`
- `Loopback0` = `10.20.C.D/32`

Where `C = floor(n / 256)` and `D = n % 256`.

Examples:

- `R1`   → `Gi0/0 10.10.0.1/16`, `Lo0 10.20.0.1/32`
- `R256` → `Gi0/0 10.10.1.0/16`, `Lo0 10.20.1.0/32`
- `R257` → `Gi0/0 10.10.1.1/16`, `Lo0 10.20.1.1/32`

### Scaling limits and assumptions (flat mode)

Flat mode builds a star fabric (not chained). Practical port limits apply:

- Access switch: `group_size + 1` ports (routers + 1 uplink to core) should be ≤ ~32
- Core switch: `ceil(nodes / group_size)` uplinks should be ≤ ~32

Defaults are safe for large labs (e.g., 300 nodes with `--flat-group-size 20` → 21 ports/access, 15 on core).

Assumptions and caveats:

- **Coordinate layout is automatic.** TopoGen scales node x/y positions to always stay within CML's 15,000-coordinate limit, regardless of node count or `--flat-group-size`. You do not need to manually adjust group size to avoid import errors.
- The guardrails assume the `unmanaged_switch` node definition has roughly 32 usable ports.
- Custom node definitions/images (including customized unmanaged switch or different router images) may change interface counts, labels, or slot allocation. The guardrails do not auto-detect such customizations.
- In generated offline YAML, unmanaged switch interfaces are labeled `portN`; the CML UI may present different labels.

Licensing guidance:

- Typical base licenses allow ~20 nodes. Enterprise tiers often allow up to 520 nodes total.
- A soft cap of 520 nodes is enforced by default; use `--allow-oversubscribe` to bypass if your environment supports more.

Version-specific capacity:

- CML 2.9+ (lab schema `0.3.0`): empirically supports flat labs up to ~500 nodes.
- CML 2.5–2.7 (lab schema `0.2.0`–`0.2.2`): practical enterprise limit ~300 nodes for this flat EIGRP scenario.
- Use `--cml-version` matching your target CML (see schema compatibility note above).

Recommended group sizes (stay within 32-port limits):

- 300 nodes: `--flat-group-size 20` → 15 access switches; core ports 15
- 500 nodes (CML 2.9+):
  - `--flat-group-size 20` → 25 access; core ports 25 (safe)
  - `--flat-group-size 25` → 20 access; core ports 20 (safe)
  - `--flat-group-size 30` → 17 access; core ports 17 (safe; access uses 31 ports incl. uplink)

### YAML export (controller)

When `--yaml FILE` is provided, the created lab is exported to the given file after
generation via the controller API. The connected controller must support lab export
via the PCL; otherwise the tool will log an error.

### Offline YAML export (no controller)

Use `--offline-yaml FILE` to emit a CML-compatible YAML locally without contacting
the controller. This is ideal for very large labs and for environments where API
export is not available.

By default, TopoGen will refuse to overwrite an existing offline YAML file.

- If `FILE` already exists, the run fails with a clear error.
- Use `--overwrite` to overwrite the existing file.

Tip: add `--progress` to show a progress bar (opt-in).

TopoGen does not pick an output filename automatically; you must provide one. We recommend `out/` for generated artifacts.

- Schema selection: `--cml-version` chooses the lab schema version (see schema compatibility note above).
- Topology: star fabric with one core `SW0`, N access `SW1..N`, and routers `R1..R${nodes}`.
- Configs: rendered from the chosen template (e.g. `iosv-eigrp`).
- Import: In CML, go to Tools → Import/Export → Import Lab and select the YAML.

### Offline-to-CML import (CLI)

You can import an offline YAML into CML from the CLI so you don't have to use the CML UI.

- **`--import-yaml FILE`**: path to an existing offline YAML (skip generation). Use with `--import`.
- **`--import`**: import the generated or specified YAML into CML via virl2_client. Requires `--offline-yaml` or `--import-yaml`. Prints file size (KB) before import and lab URL after import (clickable).
- **`-L` on import**: when importing with `--import-yaml`, the YAML's `title:` field is used as the lab title by default (no need to repeat `-L`). Pass `-L "name"` to override the YAML title (e.g. for importing the same YAML multiple times with different names).
- **`--start`**: after import (or online creation), start the lab in the background so the CLI returns immediately; check the CML UI for when the lab has started.
- **`--up FILE`**: shorthand for `--import-yaml FILE --import --start` (import YAML to CML and start lab in one flag).
- **`--print-up-cmd`**: with `--offline-yaml`, after generating prints the exact `topogen --up <file>` command to run later (when you're ready to deploy).

Workflows:

- Generate, then import: `topogen -T iosv-eigrp -m flat --offline-yaml out\lab.yaml 10` then `topogen --import-yaml out\lab.yaml --import`
- Generate, import, and start: `topogen -T iosv-eigrp -m flat --offline-yaml out\lab.yaml --import --start 10`
- Import existing (e.g. after editing) and start: `topogen --import-yaml out\lab.yaml --import --start` or **`topogen --up out\lab.yaml`**
- Generate, then deploy when ready: `topogen ... --offline-yaml out\lab.yaml --print-up-cmd` (prints "When you're ready: topogen --up out/lab.yaml"), then later run `topogen --up out\lab.yaml`

**Intent/metadata (TG-167):** TopoGen embeds the same provenance string in three places — `lab.description` (visible), `lab.notes` (hidden white 1pt span in the Guide), and a white 1pt canvas text annotation — for **both** offline YAML (`--offline-yaml`) and **online** lab create (live CML API). Placement is scaled **down-only** below the topology at `(max(node x), max(node y) + 1500)` so Workbench Fit/zoom stays on the lab (never use off-canvas coordinates like `-9999`).

Optional **`--intent-spot`** adds a debug `INTENT-SPOT` **`unmanaged_switch`** at the annotation coordinates for visual QA in Workbench. Default is **off** (no extra node). Does not consume a router license.

Example — offline generate and grep (PowerShell):

```powershell
topogen -T iosv-eigrp -m flat -L my-lab --offline-yaml out\my-lab.yaml 3
Select-String -Path out\my-lab.yaml -Pattern "Generated by topogen"
```

Example — online create with QA marker (requires `VIRL2_*` env vars):

```powershell
topogen -m simple --device-template iosv --intent-spot -i 4
```

The embedded string (identical in `description`, `notes`, and annotation `text_content`) looks like:

```
Generated by topogen v0.3.0 (offline YAML, simple) | args: nodes=3 -m simple -T iosv --device-template iosv --cml-version 0.3.1 -L my-lab --offline-yaml out/my-lab.yaml
```

Online labs use `(online, <mode>)` in the context field instead of `(offline YAML, …)`. Defaults (`--device-template`, `--cml-version`, etc.) are recorded even when not passed explicitly, making the string self-contained for regeneration.

**PKI:** PKI (CA-ROOT) is validated. DMVPN with `--dmvpn-security ikev2-pki` and `--pki` brings up tunnels with IKEv2 certificate-based authentication. Manual certificate enrollment is required on first boot (see **PKI client EEM** below).

**CA server boot order:** When using `--pki`, CA-ROOT must be online before enrolling routers. With `--cml-version 0.3.1` or later, TopoGen **auto-enables node staging** when `--pki` is set (CA-ROOT boots first via priority 900) — you do not need a separate `--staging` flag. Pass `--no-staging` to boot all nodes simultaneously. On older schemas (`--cml-version < 0.3.1`), staging is skipped with a warning; bring CA-ROOT online manually before R1..R*n*.

**Node staging (`--staging` / `--pki`):** CML 2.10 (schema `0.3.1`) supports automated boot ordering via node staging. Use `--staging` with `--cml-version 0.3.1`, or use `--pki` (staging is auto-enabled unless `--no-staging`). Priority tiers (higher boots first):

| Priority | Node type |
|----------|-----------|
| 1000 | External connectors, OOB switches |
| 950 | Data switches (SW0, SW1, SWnbma*) |
| 900 | CA-ROOT (when `--pki`) |
| 800 | Key Server (KS, when `--getvpn`), DMVPN hubs |
| *(none)* | All other routers — boot via "Start Remaining Nodes" |

Example (explicit staging, non-PKI lab):

```powershell
topogen -m flat-pair -T iosv-eigrp --cml-version 0.3.1 --staging --offline-yaml out/staging-lab.yaml 10
```

Example (PKI lab — staging auto-enabled; use `--cml-version 0.3.1`):

```powershell
topogen -m dmvpn -T csr-dmvpn --device-template csr1000v --pki --dmvpn-security ikev2-pki --cml-version 0.3.1 --offline-yaml out/pki-staged.yaml --overwrite 4
```

When staging is requested (via `--staging` or `--pki`) with `--cml-version < 0.3.1`, a warning is logged and staging is omitted.

> **CML 2.10 import note:** CML includes `node_staging` in exported YAML but does not apply the lab-level enable switch on import — per-node priorities are imported, but "Enable Node Staging" remains off. When using `--up` or `--import`, topogen enables node staging automatically via the CML API after import. For manual UI imports, enable "Node Staging" in the lab settings dialog after importing.

**DMVPN with IKEv2 PKI: bring-up order** — For DMVPN labs using `--dmvpn-security ikev2-pki` and `--pki`, start nodes in this order so crypto and NHRP come up cleanly:

1. **CA-ROOT** — Start the CA node and wait until the PKI server is enabled (e.g. "Certificate server now enabled" or CA self-enrollment complete). The CA must be reachable (e.g. at 10.10.255.254) for SCEP before any router enrolls.
2. **R1 (hub)** — Start the hub. EEM auto-enrollment fires at 300 s; if CA-ROOT is not ready in time, authenticate manually: `configure terminal` → `authc` → `yes` → `end` → `write memory`. (See **PKI client EEM** below.)
3. **Spokes (R2, R3, …)** — Start spokes in any order. Get the CA fingerprint from R1 (or CA-ROOT) after R1 has authenticated. On each spoke, from exec run `crypto pki authenticate CA-ROOT-SELF fingerprint <fingerprint>`, then `write memory` — no interactive yes required.

Use `--mgmt` for OOB SSH; use `--mgmt-vrf global` to keep management in the global routing table. For step-by-step troubleshooting (clock, certificates, IKEv2), see [docs/VPN-DEBUG-DMVPN-IKEv2-PKI.md](docs/VPN-DEBUG-DMVPN-IKEv2-PKI.md).

**PKI and clock:** PKI uses the `do` command to set the clock (e.g. `do clock set ...`) in the generated config so the device clock is authoritative before the CA starts and clients enroll. The CA-ROOT clock is backdated by 1 day so its certificate's `notBefore` is always earlier than any client's clock, preventing `%PKI-3-CERTIFICATE_INVALID_NOT_YET_VALID` errors on first boot. Clients use today's date. For labs where you prefer to rely on NTP or external automation for time, a future `--clock-set` option may allow disabling this behavior (see TODO.md).

**PKI and DMVPN flat-pair:** In DMVPN with `--dmvpn-underlay flat-pair`, even routers (R2, R4, …) have no link to the NBMA/10.10.0.0 network; they are only connected to their odd partner. The CA-ROOT is on the NBMA network. So **even routers cannot reach the CA and do not get certificates**; only odd routers (DMVPN endpoints) can enroll. This is by design. Use OOB management (e.g. `--mgmt`) if even routers need to reach NTP or other services.

**PKI client EEM:** Both EEM applets are structurally fixed and registered at boot. `CLIENT-PKI-SET-CLOCK` fires at 300 s; `CLIENT-PKI-AUTHENTICATE` fires at 305 s. If CA-ROOT is not reachable when the timer fires (e.g. still booting), automated enrollment is skipped for that boot and manual authentication is required. On any router, run `configure terminal` → `authc` → `yes` → `end` → `write memory`. To skip the interactive prompt, run from exec: `crypto pki authenticate CA-ROOT-SELF fingerprint <fingerprint>` then `write memory`.

### VRF support (flat-pair)

In `flat-pair` mode, an optional VRF can be applied to the odd router pair-link interface (`Gi0/1`).

- `--vrf`: enable VRF configuration
- `--pair-vrf NAME`: VRF name to use (default: `tenant`)

When enabled, the generated router configs include a `ip vrf NAME` stanza and apply `ip vrf forwarding NAME` under `Gi0/1` on odd routers.

### Management Network (OOB)

All modes (`simple`, `nx`, `flat`, `flat-pair`, `dmvpn`) support an optional out-of-band management network. This adds a dedicated `SWoob0` unmanaged switch and connects each router's management interface to it.

- `--mgmt`: enable OOB management fabric (switch + router mgmt interfaces)
- `--mgmt-ipv4-dhcp`: IPv4 DHCP on OOB Gi (`ip address dhcp`); implied when `--mgmt-bridge` with no other addressing flags
- `--mgmt-ipv6-dhcp`: IPv6 DHCPv6 on OOB Gi (`ipv6 address dhcp`); requires named `--mgmt-vrf`
- `--mgmt-ipv6-slaac`: IPv6 SLAAC on OOB Gi (`ipv6 address autoconfig`); requires named `--mgmt-vrf`
- `--mgmt-ipv6-static`: static global IPv6 on OOB Gi; requires `--mgmt`, named `--mgmt-vrf`, and `--mgmt-ipv6-cidr /64` (IPv6 host — no `ipv6 unicast-routing`)
- `--mgmt-ipv6-static-link-local`: with static global, also render loopback-derived `fe80::FF10:…` link-local on OOB
- `--mgmt-ipv6-mode {slaac,dhcpv6}`: legacy alias for the two dynamic IPv6 flags above
- `--mgmt-ipv6-cidr PREFIX`: **required** with `--mgmt-ipv6-static` (`/64` anchor); optional metadata hint for SLAAC/DHCPv6
- `--mgmt-cidr CIDR`: management network CIDR (default: `10.254.0.0/16`)
- `--mgmt-gw IP`: optional gateway IP; adds a default route in the mgmt VRF
- `--mgmt-slot N`: interface slot for management (default: 5; IOSv uses Gi0/5, CSR uses Gi5)
- `--mgmt-vrf NAME`: VRF name for management interface (default: `Mgmt-vrf`); use `global` for global routing table
- `--mgmt-bridge`: add external-connector to bridge OOB management network to external network (requires `--mgmt`)

When enabled, router configs get OOB management interfaces per the addressing flags (IPv4 DHCP, IPv6 DHCPv6, IPv6 SLAAC, or dual-stack). Labs with **16+ routers** and `--mgmt` require an explicit IPv6 mode (or split IPv6 flag) and a named `--mgmt-vrf`. On IOS/IOS-XE, run exec aliases by name at the `#` prompt (e.g. `topogen-test` prints the test banner; `show alias` only lists alias definitions).

Example (external bridge, IPv6 DHCPv6 only on CML 2.10):

```powershell
topogen -m flat 6 --mgmt --mgmt-bridge --mgmt-vrf Mgmt-vrf --mgmt-ipv6-dhcp `
  --cml-version 0.3.1 --nac --offline-yaml out/flat-v6-dhcp.yaml --overwrite
```

Example (static IPv6 OOB, no live sync, documentation prefix):

```powershell
topogen -m flat 2 -T iosv --device-template iosv --mgmt --mgmt-vrf Mgmt-vrf `
  --mgmt-ipv6-static --mgmt-ipv6-cidr 2001:db8:1:2::/64 `
  --cml-server 2.10 --nac --offline-yaml out/static-v6.yaml --overwrite
# R1 OOB: ipv6 address 2001:db8:1:2:FF10:254:0:1/64 (no ipv6 unicast-routing)
```

#### Verifying connectivity (IPv6 OOB)

OOB IPv6 lives in the management VRF (`Mgmt-vrf` by default). Always include `vrf` on ping — a plain `ping ipv6 …` uses the global table and typically returns **No valid route**. Link-local targets (`fe80::/10`) also require the outgoing OOB interface (CSR: `GigabitEthernet5`; IOSv: `GigabitEthernet0/5`).

With `--mgmt-ipv6-static-link-local`, routers get loopback-derived link-locals (`fe80::FF10:…`); the bridged gateway is commonly `fe80::10`. From R1/R2 after the lab is up:

```
R1#ping vrf Mgmt-vrf ipv6 fe80::10
Output Interface: GigabitEthernet5
Packet sent with a source address of FE80::FF10:20:0:1%GigabitEthernet5
!!!!! Success rate is 100 percent (5/5)

R2#ping vrf Mgmt-vrf ipv6 fe80::10%GigabitEthernet5
Packet sent with a source address of FE80::FF10:20:0:2%GigabitEthernet5
!!!!! Success rate is 100 percent (5/5)

R1#ping vrf Mgmt-vrf ipv6 2001:db8:1700:21f8:7ec0::23
!!!!! Success rate is 100 percent (5/5)
```

The first command relies on the interactive **Output Interface** prompt; the second appends `%GigabitEthernet5` on the destination. Use your lab’s global prefix/host (SLAAC, static, or a host on the bridged LAN) for the third line — replace `2001:db8:1700:21f8:7ec0::23` if your prefix differs (`2001:db8:…` in offline examples).

Verify the TopoGen test marker with `show alias | include JIRA` — aliases are non-destructive plain-text expansions.

On the Windows host attached to the CML system bridge, confirm the bridged NIC picked up addresses:

```powershell
ipconfig
```

The `--mgmt-bridge` flag creates an `ext-conn-mgmt` external_connector node using "System Bridge" mode, connecting SWoob0 to your physical/external network. This enables bidirectional connectivity, allowing routers to reach external resources (internet, NTP servers, external DHCP) and external systems to access the lab's management network.

```mermaid
graph TD
    subgraph data ["Data Plane (flat)"]
        SW0["SW0 (core)"]
        SW1dat["SW1"]
        SW0 --- SW1dat
        SW1dat ---|"Gi0/0"| R1
        SW1dat ---|"Gi0/0"| R2
        SW1dat ---|"Gi0/0"| R3
    end
    subgraph mgmt ["OOB Management"]
        extconn["ext-conn-mgmt"]
        SWoob0["SWoob0 (core)"]
        SWoob1["SWoob1"]
        extconn --- SWoob0
        SWoob0 --- SWoob1
    end
    R1 ---|"Gi0/5"| SWoob1
    R2 ---|"Gi0/5"| SWoob1
    R3 ---|"Gi0/5"| SWoob1
```

Example (flat mode with mgmt network):

```powershell
topogen --cml-version 0.3.0 -L "Flat-Mgmt-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --mgmt --offline-yaml out/flat-mgmt-10.yaml 10
```

Example (flat mode with mgmt network + VRF + gateway):

```powershell
topogen --cml-version 0.3.0 -L "Flat-Mgmt-VRF-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --mgmt --mgmt-vrf MGMT --mgmt-gw 10.254.0.1 --offline-yaml out/flat-mgmt-vrf-10.yaml 10
```

Example (DMVPN flat mode with mgmt network):

```powershell
topogen --cml-version 0.3.0 -L "DMVPN-Mgmt-5" -T iosv-dmvpn --device-template iosv -m dmvpn \
  --mgmt --offline-yaml out/dmvpn-mgmt-5.yaml 5
```

Example (DMVPN flat-pair mode with mgmt network):

```powershell
topogen --cml-version 0.3.0 -L "DMVPN-FlatPair-Mgmt-10" -T iosv-dmvpn --device-template iosv -m dmvpn \
  --dmvpn-underlay flat-pair --mgmt --offline-yaml out/dmvpn-flat-pair-mgmt-10.yaml 10
```

Example (flat mode with mgmt network + external bridge for internet access):

```powershell
topogen --cml-version 0.3.0 -L "Flat-Mgmt-Bridge-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --mgmt --mgmt-bridge --offline-yaml out/flat-mgmt-bridge-10.yaml 10
```

### NTP Configuration

An optional NTP server can be configured on all routers.

- `--ntp IP`: NTP server IP address
- `--ntp-vrf NAME`: VRF for NTP source (e.g. `Mgmt-vrf`). Omit for global table. When `--mgmt` is used, defaults to the mgmt VRF unless `--ntp-inband` is set.
- `--ntp-inband`: force NTP into the global (inband) routing table instead of the mgmt VRF. Use when the NTP server is on the data network (e.g. the CA router is also the NTP server).
- `--ntp-oob IP`: optional second NTP server in the mgmt VRF. Use with `--mgmt` for a dedicated OOB NTP source (e.g. an external NTP appliance).

Example (flat mode with mgmt + NTP in mgmt VRF):

```powershell
topogen --cml-version 0.3.0 -L "Flat-Mgmt-NTP-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --mgmt --mgmt-vrf MGMT --ntp 10.254.0.1 --offline-yaml out/flat-mgmt-ntp-10.yaml 10
```

Example (DMVPN with NTP inband -- CA router is the NTP server on the data network):

```powershell
topogen --cml-version 0.3.0 -m dmvpn -T iosv-dmvpn --device-template iosv --dmvpn-phase 3 \
  --dmvpn-routing eigrp --dmvpn-security ikev2-pki --dmvpn-hubs 1 --pki \
  --mgmt --mgmt-vrf Mgmt-vrf --ntp 10.10.255.254 --ntp-inband \
  -L "DMVPN-P3-NTP-Inband-11" --offline-yaml out/dmvpn-p3-ntp-inband-11.yaml 11
```

Example (flat mode with mgmt + dual NTP -- inband + OOB):

```powershell
topogen --cml-version 0.3.0 -L "Flat-Dual-NTP-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --mgmt --mgmt-vrf Mgmt-vrf --ntp 10.10.255.254 --ntp-inband \
  --ntp-oob 192.168.1.10 --offline-yaml out/flat-dual-ntp-10.yaml 10
```

### Blank Mode (Bootstrap Lab)

Use `--blank` to generate a topology (nodes, links, switches, coordinates) with empty configuration on all router nodes. This makes the lab eligible for CML's **Bootstrap Lab** feature, which auto-generates stub configs (hostname, `no shutdown` on interfaces, default credentials) for every node.

Works for both offline YAML generation and online lab creation via the CML API.

**When to use:** You want CML to provide its own default configs instead of TopoGen-rendered startup configs — for example, to get a working topology quickly without protocol-specific configuration, or to use Bootstrap Lab as a starting point for manual config.

**Process (offline):**

1. Generate a blank topology YAML:

```powershell
python -m topogen -T iosv -m flat --device-template iosv --blank --offline-yaml out\blank-flat.yaml --overwrite 4
```

2. Import the YAML into CML (or use `--import` to do it in one step):

```powershell
python -m topogen --import-yaml out\blank-flat.yaml --import -i
```

3. In CML Workbench, open the imported lab, then go to **Lab → Bootstrap Lab**. CML detects that nodes have empty configs and offers to generate stub configs for each node.

4. Start the lab. Each router boots with CML-generated defaults (hostname matching the node label, interfaces up, console/VTY access).

**Process (online):**

1. Create a blank lab directly on the CML controller:

```powershell
$env:VIRL2_URL="https://controller/"; $env:VIRL2_USER="user"; $env:VIRL2_PASS="pass"
python -m topogen -T iosv -m nx --device-template iosv --blank -i -L "blank-nx-10" 10
```

2. Open the lab in CML Workbench, then go to **Lab → Bootstrap Lab** to generate stub configs.

**Notes:**
- `--blank` works with simple, nx, flat, and flat-pair modes. It is not supported with DMVPN mode.
- `--blank` cannot be combined with `--nac` (use `--nac --bootstrap` for thin day-0 + Terraform-managed config).
- `--blank` cannot be combined with `--pki` or `--getvpn` (Bootstrap Lab cannot generate PKI or GET VPN configs).
- Config-only flags are also rejected: `--ntp`, `--ntp-vrf`, `--ntp-inband`, `--ntp-oob`, `--archive`, `--eigrp-stub`, `--vrf`, `--pair-vrf` (no configs are rendered, so these have no effect).
- Topology flags (`--mgmt`, `--mgmt-bridge`, `--flat-group-size`, `--staging`, `--no-staging`, `--distance`, etc.) remain allowed.
- Unmanaged switches and external connectors are not affected — they never carry configuration.

## Examples

Create a 300-node flat star lab directly on a controller (insecure TLS):

```powershell
$env:VIRL2_URL="https://controller/"; $env:VIRL2_USER="user"; $env:VIRL2_PASS="pass"
topogen -L "FlatLab-300-star" -T iosv -m flat --flat-group-size 20 --insecure --progress 300
```
Create a 20-node simple lab with EIGRP (non-flat):

```powershell
topogen -L "Simple-20-eigrp" -T iosv-eigrp-nonflat --device-template iosv `
  -m simple --distance 250 --insecure --progress 20
```

Create a 20-node NX lab with EIGRP (non-flat):

```powershell
topogen -L "NX-20-eigrp" -T iosv-eigrp-nonflat --device-template iosv `
  -m nx --distance 250 --insecure --progress 20
```

Create a 10-node simple lab with OOB management, external bridge, NTP, and auto-start:

```powershell
$env:VIRL2_URL="https://controller/"; $env:VIRL2_USER="user"; $env:VIRL2_PASS="pass"
topogen -L "Simple-10-Mgmt-Bridge" -T iosv-eigrp --device-template iosv -m simple \
  --mgmt --mgmt-bridge --mgmt-vrf Mgmt-vrf --ntp 192.168.1.10 --ntp-vrf Mgmt-vrf \
  --start --insecure --progress 10
```

Create and export a 500-node NX lab with EIGRP (YAML filename is Git-ignored):

```powershell
topogen -L "NX-500-eigrp" -T iosv-eigrp-nonflat --device-template iosv `
  -m nx --distance 300 --yaml NX-500-eigrp.yaml --insecure --progress 500
```

Create the same lab with EIGRP config and export YAML:

```powershell
$env:VIRL2_URL="https://controller/"; $env:VIRL2_USER="user"; $env:VIRL2_PASS="pass"
topogen -L "FlatLab-300-star-eigrp" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --yaml "flatlab-300-star-eigrp.yaml" --insecure 300
```

Create a 10-node offline YAML (no controller):

```powershell
topogen --cml-version 0.3.0 -L "TestOffline-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --offline-yaml out/test-offline-10.yaml 10
```

Re-generate the same file (requires `--overwrite`):

```powershell
topogen --cml-version 0.3.0 -L "TestOffline-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --offline-yaml out/test-offline-10.yaml --overwrite 10
```

Or write to a new filename (no overwrite required):

```powershell
topogen --cml-version 0.3.0 -L "TestOffline-10" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 5 --offline-yaml out/test-offline-10-v2.yaml 10
```

Create a 12-node `flat-pair` offline YAML with VRF enabled on odd routers (`Gi0/1`):

```powershell
topogen --cml-version 0.3.0 -L "vasailli" -T iosv --device-template iosv -m flat-pair \
  --flat-group-size 20 --vrf --pair-vrf TENANT --offline-yaml out/vasailli-12-flat-pair.yaml 12
```

Create a 40-node `flat-pair` offline YAML using CSR1000v (IOS-XE) and VRF EIGRP:

```powershell
topogen --cml-version 0.3.0 -L "IOSXE-VRF-EIGRP-40" -T csr-eigrp --device-template csr1000v -m flat-pair \
  --flat-group-size 20 --vrf --pair-vrf TENANT --offline-yaml out/iosxe-vrf-eigrp-40.yaml 40
```

Create a 300-node offline YAML:

```powershell
topogen --cml-version 0.3.0 -L "FlatLab-300-star-eigrp-l32" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --offline-yaml out/flatlab-300-star-eigrp-l32.yaml 300
```

Create a 500-node offline YAML:

```powershell
topogen --cml-version 0.3.0 -L "FlatLab-500-star-eigrp-l32" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --offline-yaml out/flatlab-500-star-eigrp-l32.yaml 500
```

Addressing variant examples (flat mode):

- Use Lo0 in 10.255.C.D/32 and Gi0/0 in 10.0.C.D/16 (offline YAML):

```powershell
topogen --cml-version 0.3.0 -L "FlatLab-300-addr-variant" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --loopback-255 --gi0-zero --offline-yaml out/flatlab-300-addr-variant.yaml 300
```

- Same addressing variant on controller (online):

```powershell
topogen -L "FlatLab-300-addr-variant" -T iosv-eigrp --device-template iosv -m flat \
  --flat-group-size 20 --loopback-255 --gi0-zero --insecure 300
```

> Note: Generated offline YAML artifacts are recommended to be written under `out/` and are ignored by Git.

#### Other Configuration

IP address ranges are configured via a configuration file, if present.  The
defaults are like shown here:

```toml
loopbacks = "10.0.0.0/8"
p2pnets = "172.16.0.0/12"
nameserver = "8.8.8.8"
domainname = "virl.lab"
username = "cisco"
password = "cisco"
```

The username and password are used for the device configurations (e.g. the
Alpine DNS node and the generated routers).  The nameserver value is not used
at the moment (it is actually replaced with the IP address of the DNS host's
second interface / NIC facing the router network).

## Operation

> [!NOTE]
> For large online builds (e.g., simple/NX with hundreds of nodes), the CML UI may not
> visibly update the topology immediately. It is normal for no changes to appear until
> roughly 25% of the creation process has completed. Let TopoGen continue; nodes and
> links will show up progressively as creation advances.

The topology has an external connector and a DNS-host (based on Alpine).  On
that host, a dnsmasq DNS server is running which can resolve all IP addresses
of all topology router loopbacks.  All topology routers are also using this
DNS server (assuming they have connectivity to it).

> [!NOTE]
>
> Since the Alpine node does not include dnsmasq by default, it
> will pull in and install this package from the Internet. Therefore it
> is required to have Internet connectivity for this to work! Once the
> network has been created and full connectivity is established, it
> should be possible to SSH/Telnet to all nodes using their node names.
> The below shows logging into the Jumphost (at 192.168.255.100) via
> the controller (at 192.168.122.245) and then onward to router `r1`
> using its name.

```plain
rschmied@delle:~/Projects/topogen$ ssh -tp1122 sysuser@192.168.122.245 ssh cisco@192.168.255.100
cisco@192.168.255.100's password: 
Welcome to Alpine!

The Alpine Wiki contains a large amount of how-to guides and general
information about administrating Alpine systems.
See <http://wiki.alpinelinux.org/>.

You can setup the system with the command: setup-alpine

You may change this message by editing /etc/motd.

dns-host:~$ telnet r1
Connected to r1

Entering character mode
Escape character is '^]'.


**************************************************************************
* IOSv is strictly limited to use for evaluation, demonstration and IOS  *
* education. IOSv is provided as-is and is not supported by Cisco's      *
* Technical Advisory Center. Any use or disclosure, in whole or in part, *
* of the IOSv Software or Documentation to any third party for any       *
* purposes is expressly prohibited except as otherwise authorized by     *
* Cisco in writing.                                                      *
**************************************************************************

User Access Verification

Username: cisco
Password: 
**************************************************************************
* IOSv is strictly limited to use for evaluation, demonstration and IOS  *
* education. IOSv is provided as-is and is not supported by Cisco's      *
* Technical Advisory Center. Any use or disclosure, in whole or in part, *
* of the IOSv Software or Documentation to any third party for any       *
* purposes is expressly prohibited except as otherwise authorized by     *
* Cisco in writing.                                                      *
**************************************************************************
R1#traceroute 192.168.122.1
Type escape sequence to abort.
Tracing the route to 192.168.122.1
VRF info: (vrf in name/id, vrf out name/id)
  1 from-r1-gi0-0-to-r9-gi0-0.virl.lab (172.16.0.2) 3 msec
    from-r1-gi0-1-to-r2-gi0-0.virl.lab (172.16.0.6) 9 msec
    from-r1-gi0-2-to-r4-gi0-0.virl.lab (172.16.0.10) 4 msec
  2 from-r7-gi0-4-to-r9-gi0-2.virl.lab (172.16.0.57) 10 msec
    from-r2-gi0-3-to-r7-gi0-0.virl.lab (172.16.0.22) 18 msec
    from-r4-gi0-2-to-r7-gi0-2.virl.lab (172.16.0.38) 14 msec
  3 172.16.0.77 7 msec 10 msec 11 msec
  4 192.168.255.1 11 msec 14 msec 9 msec
  5 192.168.122.1 13 msec 12 msec 11 msec
R1#
```

## Operations / Ping Sweep

This repo includes a simple IOS/IOS-XE TCL ping sweep script at `DMVPN-ping.tcl`.

To run it on a router:

```text
copy scp://<user>@<host>/DMVPN-ping.tcl flash:

tclsh
source flash:DMVPN-ping.tcl
```

Or, if you just want to paste it into the CLI, open `DMVPN-ping.tcl` and paste the whole script into the router.
