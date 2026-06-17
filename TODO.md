<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.6.58
Date Modified: 2026-06-13

- Called by: Developers planning features, LLMs adding work items, project management
- Reads from: Developer input, user requests, issue tracker
- Writes to: None (documentation only, but drives development decisions)
- Calls into: References README.md, CHANGES.md, DEVELOPER.md for completed work

Purpose: Living document tracking current work, future ideas, and issue candidates.
         Organizes feature development roadmap and TODO items for developers and LLMs.

Blast Radius: Medium (guides development priorities but doesn't affect code execution)
              Moving items from "Current work" to "Done" signals feature completion.
-->

# TODO

**Maintainers:** Internal backlog and sprint planning live in Jira ([TG project](https://roberthosford.atlassian.net/jira/software/projects/TG)). This file is optional context for contributors and LLMs — not the source of truth for what ships next.

This file tracks in-progress work and future ideas for TopoGen.

## Conventions

- Offline YAML output files should be written under `out/`.
- `out/` is in `.gitignore`.
- Prefer filename = lab name:
  - Lab name: `IOSXE-DMVPN-FLAT-PAIR-3H-P2-EIGRP-N63`
  - Offline YAML: `out\IOSXE-DMVPN-FLAT-PAIR-3H-P2-EIGRP-N63.yaml`

- TODO buckets (to avoid confusion):
  - `## Current work` = items for the feature currently being worked on.
  - `## Future ideas` = new ideas not being worked on yet.
  - `## Promote to Issues` = issue-worthy items that should become GitHub Issues when running the workflow.

- When asking an LLM to add something, prefer:
  - "Add to Current work: ..." or "Add to Future ideas: ..." or "Promote to Issues: ..."

## Feature roadmap (ordered)

1. Decide/implement least-astonishment semantics for DMVPN `--dmvpn-underlay flat-pair` node counts

## Current work

### EEM scripts (PKI) — working status

Script bodies live in `examples/`. Check off when confirmed working on device.

| Script name | Example file | Working |
|-------------|--------------|---------|
| CA-ROOT-SET-CLOCK | `examples/eem-ca-root-set-clock.txt` | [x] |
| CLIENT-PKI-SET-CLOCK | `examples/eem-client-pki-set-clock.txt` | [x] |
| CLIENT-PKI-AUTHENTICATE | `examples/eem-client-pki-authenticate.txt` | [ ] (structurally fixed v1.0.9; timing-dependent — fires at 305 s; manual `authc` if CA-ROOT misses window) |
| CLIENT-PKI-CHAIN | `examples/eem-client-pki-chain.txt` | [ ] |
| AUTO-AUTH | `examples/eem-auto-auth.txt` | [ ] |
| CLIENT-PKI-ENROLL | `examples/eem-client-pki-enroll.txt` | [ ] |
| do-ssh | `examples/eem-do-ssh.txt` | [ ] |

### Feature: Auto-deploy PKI/certs (fix)

**Goal:** CA and client certificates deploy and enroll automatically after lab start — no manual `crypto pki authenticate` and no reliance on CA-ROOT timing. Current state: manual `authc` is a workaround when CA-ROOT misses the auto-enrollment window; CA-ROOT boot has EEM and CVAC ordering issues; online flat lacks CA clock EEM.

**Work items** (details in Promote to Issues):

- [ ] **Fix CA-ROOT boot: EEM "end" action outside conditional block** — indent `end` actions in CA-ROOT-SET-CLOCK and CLIENT-PKI-SET-CLOCK so parser associates them with the correct if block (`_pki_ca_clock_eem_lines`, `_pki_client_clock_eem_lines` in render.py).
- [x] **Fix CA-ROOT boot: CVAC rejects `ip http secure-trustpoint CA-ROOT-SELF`** — reordered `csr-pki-ca.jinja2` so CA server starts before trustpoint with auto-enroll; added CA-ROOT-AUTHENTICATE EEM applet; added `pki_clock_set` context to online render path (TG-60, see CHANGES.md).
- [ ] **Fix next: CA-ROOT time EEM missing when lab created online** — offline flat/DMVPN/flat-pair get `_pki_ca_clock_eem_lines()`; online flat builds CA from csr-pki-ca.jinja2 only. Add CA clock EEM to online flat CA build in `render_flat_network()` (e.g. append `_pki_ca_clock_eem_lines()` before assigning `ca_router.configuration`).

- [x] **Add cert-check alias to PKI client routers** — add `alias exec checkcert show crypto pki certificates CA-ROOT-SELF` to client routers (similar to CA-ROOT's `alias exec servcerts`). Makes it easy to verify a client got its certificate from the CA. (TG-106, done)

- [x] **Add `--dmvpn-ipsec-mode` flag for transport/tunnel mode selection** — add `--dmvpn-ipsec-mode {transport,tunnel}` (default: transport) to control the IPsec transform-set mode. Previously hardcoded to `mode transport`; some Cisco reference designs use `mode tunnel`. (TG-110, done)

**Related:** EEM scripts (PKI) table above (CLIENT-PKI-AUTHENTICATE, CLIENT-PKI-ENROLL, etc.). **Future:** `--pki-ca-fingerprint` (Future ideas) for non-interactive CA auth and auto-enroll at scale.

**Note — Clock and cert validity lag (fixed):** Previously, CA and clients used the same `do clock set` date, causing `%PKI-3-CERTIFICATE_INVALID_NOT_YET_VALID` errors when clients validated certs before the CA's `notBefore`. Fixed by backdating the CA-ROOT clock by 1 day (`_pki_clock_set_today(backdate_days=1)`). Clients keep today's date. See DEVELOPER.md "PKI CA clock backdate" for the tiered offset design (supports future 3-level PKI hierarchy). Closes GitHub issue #31.

## Promote to Issues

- [x] ~~**Fix: `--cml-version` does not adapt YAML structure for backward compatibility.**~~ Done — `smart_annotations` omitted for schema `<= 0.2.2`; `notes:` confirmed safe on CML 2.5+. See CHANGES.md and `_intent_annotation_lines()` in render.py.

- [x] ~~**Task: Bump `pyproject.toml` version to `0.2.5`.**~~ Done — superseded by TG-147 release `0.3.0` on `main`. Package version is only in `pyproject.toml`; run `pip install -e .` after bump so `topogen -v` and provenance strings match.

- [x] ~~**Task: Determine CML 2.10 lab schema version and add to `--cml-version` choices.**~~ Done — schema is `0.3.1`; `--cml-version` choices updated; DEVELOPER.md has the full field mapping. See DEVELOPER.md "CML lab schema versions."


- [ ] **Fix CA-ROOT boot: EEM "end" action outside conditional block.** Observed: `%HA_EM-6-FMPD_EEM_CONFIG: CA-ROOT-SET-CLOCK: "end" action found outside of conditional block`. EEM applet CA-ROOT-SET-CLOCK (and client CLIENT-PKI-SET-CLOCK) use `action X.Y end` to close if blocks; on some IOS-XE versions the parser reports "end" outside conditional. Fix: ensure `end` actions are indented so the parser associates them with the correct if block (e.g. ` action 1.10 end` → `  action 1.10 end` for CA-ROOT; client has ` action 1.99 end`). See render.py `_pki_ca_clock_eem_lines()` and `_pki_client_clock_eem_lines()`.

- [x] ~~**Fix CA-ROOT boot: CVAC rejects `ip http secure-trustpoint CA-ROOT-SELF`.**~~ Fixed — reordered `csr-pki-ca.jinja2` so CA server starts before trustpoint with auto-enroll; added CA-ROOT-AUTHENTICATE EEM applet to online template; added `pki_clock_set` context variable. See CHANGES.md TG-60 entry.

- [ ] Online lab creation: show lab definition size (X.X KB) when upload succeeds
  - Current: render_flat_network() calls export_lab() after "Flat management network created"; if content is None we log "Lab created - uploaded to controller" (no size). When export_lab returns data we log "Lab created (%.1f KB) - uploaded to controller".
  - Observed: online flat run showed "Lab created - uploaded to controller" (no size), so export_lab returned None or failed. Investigate virl2_client export_lab behavior so size is shown for online create (same UX as offline YAML file size).

- [ ] **Fix next:** CA-ROOT time EEM (CA-ROOT-SET-CLOCK) missing when lab is created online. Offline flat/DMVPN/flat-pair inject _pki_ca_clock_eem_lines() into CA config; online flat builds CA from csr-pki-ca.jinja2 only (no EEM). User expects PKI/clock behavior to work the same whether lab is created offline or online. Add CA clock EEM to online flat CA build in render_flat_network() (e.g. append _pki_ca_clock_eem_lines() before assigning ca_router.configuration).

- [ ] **Fix: `do clock set` must come before CA server starts and before first key generation.** Currently both online (`csr-pki-ca.jinja2`) and offline (`_pki_ca_self_enroll_block_lines` in render.py) place `do clock set` AFTER `crypto pki server CA-ROOT / no shutdown`. The CA root certificate is generated when the server starts with `no shutdown`, so its `notBefore` uses whatever clock the device had at boot (often wrong). Fix: move `do clock set` (backdated 1 day) to before `crypto key generate rsa modulus 2048 label CA-ROOT.server` in the template, and before `pki_config_lines` in the offline assembly. Affects both `csr-pki-ca.jinja2` and all four offline assembly sites in `render.py` that use `pki_config_lines` + `_pki_ca_self_enroll_block_lines`.

- [x] ~~**Fix: Online lab creation missing notes and scaled intent annotation.**~~ Done (TG-167): `_apply_online_lab_intent()` in all online render paths; opt-in `--intent-spot` unmanaged_switch marker; live-validated on CML 2.10.

- [x] ~~**Feature: CML 2.10 node staging (`--staging`) for PKI boot ordering.**~~ Implemented. See `CHANGES.md` Unreleased entry.

- [ ] **Task: Investigate CML 2.10 named-file configuration format.** CML 2.10 exports `configuration` as a list of `{name: "ios_config.txt", content: "..."}` objects instead of a plain string. CML 2.10 accepts the old plain-string format on import (confirmed), so this is not blocking. Future work: when `--cml-version >= 0.3.1`, optionally emit the named-file format for full round-trip fidelity. Low priority — current format works.

- [x] ~~**Bug: Offline NX mode produces flat topology instead of all-to-all NX graph.**~~ Fixed — `offline_nx_yaml()` for NX (random graph) and `offline_simple_yaml()` for simple (chain topology) with ext-conn + dns-host matching online. See CHANGES.md.

## Done

See `CHANGES.md` and `README.md` for completed features.

Recent completions:
- [x] **TG-194: `--cml-server` opt-in flag** — ([TG-194](https://roberthosford.atlassian.net/browse/TG-194), epic TG-189) Operator-facing CML controller version maps to lab YAML schema when `--cml-version` omitted; explicit `--cml-version` wins; provenance records both flags. Validated: 44 unit tests, 6 offline YAML cases, 6 live CML 2.10 imports, gap/negative CLI matrix. Branch `TG-194-cml-server-opt-in`.
- [x] **TG-195: Static IPv6 OOB from prefix** — ([TG-195](https://roberthosford.atlassian.net/browse/TG-195), epic TG-189) `--mgmt-ipv6-static` + `--mgmt-ipv6-cidr /64` with FF10 embedding; optional `--mgmt-ipv6-static-link-local`; NaC inventory without live sync; no `ipv6 unicast-routing` (IPv6 host mode). Spec: `docs/TG-195-ai-prompt.md`.
- [x] DMVPN flat and flat-pair offline NaC artifacts (TG-151): `--nac` now emits the sibling `nac/` tree for DMVPN flat and flat-pair offline YAML generation while preserving the original flat-pair CML YAML path/config when `--nac` is omitted. See CHANGES.md.
- [x] CML2 Terraform lifecycle scaffold (`--terraform-cml2`, alias `--cml2`) for generated offline labs: emits `out/<lab>/cml2/` with `main.tf`, `versions.tf`, `variables.tf`, `outputs.tf`, and `.gitignore` targeting `CiscoDevNet/cml2` and the generated YAML through a relative path. See CHANGES.md TG-150 entry.
- [x] Two-tier OOB management for all online modes: `render_node_network` (NX), `render_node_sequence` (simple), and `render_flat_network` (flat) now use SWoob0 (aggregation) + SWoob1..N (access) matching offline reference. Previously used a single switch that couldn't scale. See CHANGES.md.
- [x] OOB management VRF block added to `iosv.jinja2`, `iosv-eigrp-nonflat.jinja2`, `iosv-eigrp-stub.jinja2`, `iol-xe.jinja2` — these templates previously had no mgmt block so `--mgmt` was silently ignored in the router config. See CHANGES.md.
- [x] NTP bug: added NTP block to `iosv.jinja2`, `iosv-eigrp-stub.jinja2`, `iosv-eigrp-nonflat.jinja2`, `iol-xe.jinja2` — `--ntp` was silently ignored for these templates. See CHANGES.md.
- [x] `--cml-version` backward compat: omit `smart_annotations` for schema `<= 0.2.2` (CML 2.5–2.7); `notes:` safe on all versions. Schema version mapping added to DEVELOPER.md and README.md. See CHANGES.md.
- [x] `--import-yaml` reads `title:` from YAML when `-L` is not provided (PoLA, closes #36; see CHANGES.md)
- [x] NHRP authentication: `ip nhrp authentication DMVPNKEY` added to iosv-dmvpn.jinja2 and csr-dmvpn.jinja2 (hub and spoke, all phases, all security modes)
- [x] CA-ROOT alias: `alias exec servcerts sh crypto pki server CA-ROOT cer` added to csr-pki-ca.jinja2 and all inline CA config paths in render.py (see CHANGES.md)
- [x] TOPOGEN-NOSHUT EEM applet on all CSR1000v templates (supersedes "CSR EEM link-up script" future idea). See CHANGES.md `fix(csr)` entry.
- [x] Archive config in all IOS/IOS-XE templates (feat/archive branch): archive + log config + path flash: + maximum 5 + write-memory; rundiff alias unchanged.
- [x] DMVPN IKEv2 PKI validated (`--dmvpn-security ikev2-pki` + `--pki`): IKEv2 rsa-sig tunnels come up; flat, flat-pair underlays confirmed; EEM applets structurally fixed (injected last, before final `end`); timers 300 s/305 s; manual `authc` is workaround when CA-ROOT timing misses auto-enrollment window (see CHANGES.md v1.2.2–v1.2.4)
- [x] DMVPN with PKI authentication: `--dmvpn-security ikev2-pki` (requires `--pki`); IKEv2 rsa-sig + pki trustpoint CA-ROOT-SELF in iosv-dmvpn/csr-dmvpn; online DMVPN injects PKI client when --pki (see CHANGES.md)
- [x] DMVPN Phase 3 support: `--dmvpn-phase 3` with NHRP redirect on hubs, NHRP shortcut on spokes (see CHANGES.md)
- [x] DMVPN security: IKEv2 + PSK (`--dmvpn-security ikev2-psk`) and IKEv2 + PKI (`--dmvpn-security ikev2-pki`) (see CHANGES.md)
- [x] feat/pki-ca: single root CA router for DMVPN PKI (merged; see CHANGES.md)
- [x] Offline-to-CML import: `--import-yaml`, `--import`, `--up`, `--print-up-cmd`, non-blocking `--start` (see CHANGES.md)
- [x] `--quiet` flag: `-q` / `--quiet` forces log level to ERROR (see CHANGES.md)
- [x] Allow `python -m topogen` via `src/topogen/__main__.py` (see CHANGES.md)
- [x] Add `--mgmt-bridge` support for online NX and simple modes (see CHANGES.md)
- [x] Add `--start` flag for auto-starting labs after creation (see CHANGES.md)
- [x] Add lab URL printing after creation for easy browser access (see CHANGES.md)
- [x] Include all CLI args in lab description for repeatability (see CHANGES.md)
- [x] Add external-connector bridge support for OOB management (offline modes) (see CHANGES.md)
- [x] OOB management network for flat, flat-pair, and DMVPN modes (see CHANGES.md)
- [x] Coordinate scaling bug fix: `offline_flat_yaml` / `offline_flat_pair_yaml` auto-scale x/y to stay within CML's 15000-coordinate limit (see CHANGES.md)
- [x] GET VPN (Group Encrypted Transport VPN) support: `--getvpn` flag with `--getvpn-protocol {gdoi,gikev2}`, KS node (csr-getvpn-ks.jinja2), GM config injection on all routers, requires `--pki`. Works with flat, flat-pair, and dmvpn modes. See CHANGES.md.
- [x] `--blank` flag: topology-only labs with empty configuration on all router nodes; enables CML Bootstrap Lab. Works offline and online for simple, nx, flat, and flat-pair modes. Not supported with DMVPN, `--pki`, `--getvpn`, or config-only flags (`--ntp`, `--archive`, `--eigrp-stub`, `--vrf`, `--pair-vrf`). See CHANGES.md.
- [x] NaC MVP baseline stories reconciled with git/Jira evidence (TG-116/117/118/119/120/121/122/123/124/127/128/129 marked Done).
- [x] **NaC MVP epic TG-131 closed** — TG-132…TG-146 Done; extended by TG-147 (v0.3.0). Post-epic: TG-161 (terraform plan CI) and TG-169 (Gi numbering) done; **TG-162 (DMVPN NaC fidelity)** done on `story/TG-162-dmvpn-nac-fidelity`.
- [x] **Deployable NaC MVP (TG-131, TG-S1–S13)** — `--nac` now emits a deployable workspace: lean `nac.yaml` for `netascode/nac-iosxe/iosxe` 0.1.0 (provider `CiscoDevNet/iosxe` 0.15.0, Terraform `>= 1.8.0`), pinned Terraform scaffold (`main.tf`/`versions.tf`/`terraform.tfvars.example`/`.gitignore`), read-only Ansible stub, and day0 RESTCONF/NETCONF. Removed `terraform.tfvars.json`. Added golden-fixture smoke tests (`tests/fixtures/nac/golden-flat-*`). See CHANGES.md and README "NaC MVP scope".

## Future ideas

### NaC / OOB

- [ ] **NaC: `--nac` help text omits `nx`** — the `nodes` positional `--help` string lists `nodes=2 simple/flat/flat-pair` but omits `nx`, even though the standalone `--nac` help and `validate_nac_mvp_guardrails()` allow `nodes=2 --mode nx`. One-line fix in `src/topogen/main.py` argparse help; then refresh the README `--help` block. (Follow-up from TG-S13.)
- [x] **NaC: Terraform plan deployability gate (TG-161)** — opt-in pytest (`tests/test_nac_terraform_plan.py`, `TOPOGEN_TERRAFORM_PLAN=1` / `-m terraform`) runs `terraform init` + `terraform plan` on a 9-case NaC matrix (includes DMVPN IKEv2-PSK); CI job `NaC Terraform plan contract` when NaC paths change. Supersedes the earlier `validate`-only idea (plan evaluates `nac.yaml` module locals).
- [x] ~~**NaC: extend `--nac` to DMVPN**~~ Done for DMVPN flat and flat-pair offline paths in TG-151; deterministic `nac_router_nodes` feed the shared NaC writer.

- [x] **TG-191: Emit NaC mgmt sync helper with `--nac` scaffold** — ([TG-191](https://roberthosford.atlassian.net/browse/TG-191), under TG-189/TG-190) `nac/sync-nac-mgmt.py` + `NAC-WORKFLOW.md` emitted with every `--nac` tree; unified `src/topogen/nac_mgmt_sync.py`; `topogen sync-nac-mgmt` subcommand; `nac_metadata.yaml` mgmt fields; `mgmt_sync.json` report.

- [x] **TG-192: CML CI/CD pipeline + per-ticket scoped CML users** — ([TG-192](https://roberthosford.atlassian.net/browse/TG-192), epic TG-189) End-to-end Jira → generate → `cml2` deploy → emitted `sync-nac-mgmt` → NaC apply → verify → `topogen provision-cml-user` (lab_view+lab_exec, admin: false) → READY comment; teardown on Done. DEVELOPER.md runbook, `.github/workflows/cml-nac-pipeline.yml`, `scripts/jira-cml-webhook.py`, `scripts/validate-tg192-pipeline.ps1`. Reference lab: TG-190-flat-300-nac-v6 (`2be6f617-cf45-4bff-8970-2c9f28ac01d3`).

- [ ] **TG-109: New feature: FlexVPN** — add FlexVPN (IKEv2-native) hub-and-spoke overlay support
  - FlexVPN is the IKEv2-native replacement for DMVPN (no GRE/NHRP, pure IKEv2 + IPsec with virtual-template and route injection via IKEv2 routing or BGP)
  - **Not a new mode** — reuses existing underlay topologies (flat, flat-pair via `--mode dmvpn --dmvpn-underlay`). Only the overlay config changes (IKEv2 virtual-template instead of GRE/NHRP Tunnel0). All existing underlay, addressing, PKI, NTP, mgmt infrastructure is shared.
  - Approach: new flag on the existing DMVPN mode, e.g. `--dmvpn-type {dmvpn,flexvpn}` or `--vpn-type {dmvpn,flexvpn}`, selecting which overlay to render
  - New templates: `csr-flexvpn` (IOS-XE required; IOSv support is limited)
  - Server/client model: hub = FlexVPN server (virtual-template), spokes = FlexVPN clients
  - Auth: PSK and/or PKI (reuse existing `--pki` and `--dmvpn-security` for cert-based)
  - Blast radius: main.py (new flag), render.py (overlay config selection), new templates, README.md, CHANGES.md
  - Related: CNSA 2.0 readiness — FlexVPN is the recommended IKEv2 VPN architecture for post-quantum migration

- [ ] Add `--clock-set` to opt-in to `do clock set` in PKI configs; default to not using `do` command for time
  - Why: Today PKI injects `do clock set ...` so the clock is authoritative and PKI comes up quickly. Some users prefer NTP or external automation to set time and do not want TopoGen to inject clock-set.
  - Behavior: When `--clock-set` is set, keep current behavior (inject `do clock set` in CA and client PKI blocks). When omitted, do not inject clock-set; time is left to NTP or other automation.
  - Note: At this point, getting PKI and clients stable without injected clock may require other automation (e.g. Ansible, EEM, or out-of-band time sync) to take over. TopoGen would then focus on topology and base PKI config; clock and post-boot auth/save would be handled elsewhere.
  - Blast radius: main.py (argparse), render.py (_pki_ca_self_enroll_block_lines, _inject_pki_client_trustpoint, _pki_ca_clock_eem_lines, _pki_client_clock_eem_lines — gate clock-set on flag), README.
- [ ] Replace `--pki-enroll scep|cli` with `--pki-scep` boolean flag (refactor + feature)
  - `--pki-enroll` is defined in main.py but never read in render.py — it is dead code
  - New design: `--pki` = CA-ROOT node in lab (no change to router configs); `--pki-scep` = non-CA routers get trustpoint + SCEP enrollment pointing at CA-ROOT
  - Dependency: `--pki-scep` requires `--pki` (enforce in main.py)
  - CA IP (`ca_g_addr.ip`) is already computed; pass it to router Jinja context as SCEP enrollment URL
  - Also fix CA name inconsistency: DMVPN render path uses `ROOT-CA`; flat-pair render paths use `CA-ROOT` — standardize all to `CA-ROOT`
  - Blast radius: main.py (remove `--pki-enroll`, add `--pki-scep`), render.py (fix CA name + pass ca_ip to router templates), router templates (add trustpoint block)
- [ ] **New feature: Route leak into TENANT VRF — host route to CA server (10.10.255.254)** so CEs can get a cert
  - Why: In flat-pair (and similar) with VRF, even routers / CEs have no path to the NBMA network where the CA lives; they cannot reach 10.10.255.254 for SCEP enrollment. Leaking a host route for the CA (e.g. 10.10.255.254/32) into the TENANT VRF (or the pair-link VRF) allows CEs to reach the CA and enroll.
  - Scope: When `--pki` and VRF (e.g. `--vrf` / `--pair-vrf` / TENANT) are in use, inject a static route (or route-leak) in the tenant/pair VRF to 10.10.255.254 (CA) via the appropriate next-hop (e.g. odd router's NBMA-facing interface or a shared link). Exact mechanism depends on topology (flat-pair: odd router has NBMA; CE reaches odd; odd needs to advertise or leak CA host route into VRF).
  - Blast radius: render.py (routing/VRF config for flat-pair and any mode with VRF + PKI), templates (iosv-dmvpn, csr-dmvpn, iosv-eigrp, csr-eigrp, etc. when VRF + pki enabled).
- [ ] **New feature: DMVPN + PKI — static routes for CA and tunnel reachability**
  - **On CA-ROOT (root CA):** add `ip route 172.16.0.0 255.255.0.0 10.10.0.1` so the CA can reach the DMVPN tunnel network (172.16.0.0/16) via R1 (hub) at 10.10.0.1.
  - **On R1 (hub):** add `ip route 10.10.255.254 255.255.255.255 10.20.0.1` (host route to CA 10.10.255.254 via next-hop 10.20.0.1) so the hub can reach the CA for SCEP; and **redistribute static** into EIGRP 100 with metric `1 1 255 1 1480` (bandwidth delay reliability load MTU) so spokes learn the CA route. Exact next-hops (10.10.0.1, 10.20.0.1) may need to be derived from topology (NBMA/tunnel addressing).
  - Scope: DMVPN mode with `--pki`; inject these routes and `redistribute static metric 1 1 255 1 1480` in EIGRP 100 on CA-ROOT and R1 when PKI is enabled.
  - **When using VRF:** leak the CA host route (10.10.255.254/32) and any needed tunnel or NBMA routes into the TENANT (or pair-link) VRF so CEs and VRF-aware interfaces can reach the CA; align with the existing "Route leak into TENANT VRF" future idea.
  - Blast radius: render.py (DMVPN + PKI CA and hub config), templates (csr-pki-ca.jinja2, iosv-dmvpn, csr-dmvpn for R1/hub).
  - **Reference (working config)** — when implementing, use these exact patterns:
    - **On R1 (hub, named EIGRP TOPGEN + VRF TENANT):** `show run | sec router|ip route`:
      ```
      router eigrp TOPGEN
       !
       address-family ipv4 unicast vrf TENANT autonomous-system 100
        !
        af-interface default
         passive-interface
        exit-af-interface
        !
        af-interface Tunnel0
         no passive-interface
         no split-horizon
        exit-af-interface
        !
        af-interface GigabitEthernet0/1
         no passive-interface
        exit-af-interface
        !
        topology base
         redistribute static metric 10000 100 255 1 1500
        exit-af-topology
        network 10.20.0.1 0.0.0.0
        network 172.16.0.1 0.0.0.0
        network 172.20.0.1 0.0.0.0
       exit-address-family
      router eigrp 100
      ip route vrf TENANT 10.10.255.254 255.255.255.255 GigabitEthernet0/0 10.10.255.254 global
      ```
    - **On CA-ROOT:** `ip route 172.20.0.0 255.255.0.0 10.10.0.1` (tunnel network via hub).
- [ ] Support IOSv for PKI CA-ROOT (currently CSR1000v only)
  - Why: CA-ROOT is currently hardcoded to csr1000v node definition (see render.py ca_dev_def)
  - Current: csr-pki-ca.jinja2 template uses CSR interface names (GigabitEthernet1, Gi5)
  - Future: Make template adaptable to IOSv (GigabitEthernet0/1, Gi0/5) if PKI server works on IOSv
  - Requires: Pass dev_def to template context, add conditional interface naming in template
  - Blast radius: render.py (CA creation), csr-pki-ca.jinja2 (interface config), offline YAML generation
- [ ] 3-level PKI hierarchy: CA-ROOT → CA-POLICY → router enrollment
  - Why: Simulate enterprise PKI depth with root CA offline, policy/issuing CA online, routers auto-enrolling via SCEP
  - Naming: CA-ROOT (offline root), CA-POLICY (online issuing CA), CA-SIGN reserved for cross-cert scenarios
  - Requires: csr-pki-policy.jinja2 template, CA-POLICY node in render_dmvpn_network(), chained enrollment config
  - Blast radius: render.py (CA-POLICY node creation + links), templates (CA-ROOT signs CA-POLICY cert), main.py (--pki-depth or --pki-policy flag)
- [ ] Add `--pki-ca-fingerprint` and `enrollment fingerprint` to client trustpoint (SCEP TOFU)
  - Why: Lets clients authenticate the CA non-interactively so `crypto pki authenticate` and auto-enroll work on 300 routers without manual "yes".
  - Fallback: If EEM-based authenticate (applet that runs `crypto pki authenticate` and answers "yes" via pattern) cannot be made to work, implement this sooner so clients can authenticate by fingerprint instead.
  - Chicken-and-egg: Fingerprint must be known at lab generation time (to embed in client config). With on-box CA the CA cert does not exist until the lab is created and CA has booted — so fingerprint is unknown when running `topogen --pki ... --offline-yaml out.yaml 300`. With offline/imported root the user generates the root (and cert) before the lab, computes the fingerprint, then runs topogen with `--pki-ca-fingerprint <hex>`; clients get `enrollment fingerprint` in config and can authenticate without prompts.
  - Implication: This feature pairs with "imported root" flow (user builds root offline, imports cert+key onto CA router). Without imported root, fingerprint at gen time is not available.
  - Requires: main.py (--pki-ca-fingerprint), render.py (_inject_pki_client_trustpoint: add enrollment fingerprint when set), docs.
  - Blast radius: main.py, render.py, client config output.
- [ ] Add `--strong` / `--stronger` crypto flags for PKI and IKEv2 (low effort)
  - Why: Default IOS XE RSA 2048 / AES-128 may not match security-conscious lab goals; named profiles simplify selection
  - `--strong`: RSA 2048, AES-256, SHA-256 (NIST current)
  - `--stronger`: RSA 4096, AES-256-GCM, SHA-384 (NIST future-proof)
  - Blast radius: main.py (argparse), templates (crypto profile conditionals)
- [ ] Enable RESTCONF and NETCONF on CSR1000v templates (low effort)
  - Why: With OOB management IPs reachable via external-connector, enabling `netconf-yang`, `restconf`, and `ip http secure-server` unlocks Ansible, Terraform, and pyATS automation against lab nodes
  - Blast radius: csr-dmvpn.jinja2, csr-eigrp.jinja2, csr-ospf.jinja2, csr-pki-ca.jinja2 (add config block before `line vty`)
  - Consider: gate behind `--netconf` / `--restconf` flags or enable unconditionally since lab routers benefit from programmability by default

- [ ] Add NAT mode support for external-connector (in addition to current System Bridge mode)
  - Why: Enable outbound-only connectivity for OOB management networks where devices need to reach external resources but don't need to be reachable from outside
  - Current implementation uses "System Bridge" mode (bidirectional connectivity)
  - NAT mode would be useful for security-focused deployments where management plane should only initiate outbound connections
- [ ] Refactor: deduplicate offline YAML emission for `--mgmt-bridge` (external_connector + SWoob0 port offset + links)
  - Today this logic is repeated across multiple offline renderers in `src/topogen/render.py`
  - Goal: centralize into a shared helper to reduce risk of fixing one mode and missing others
- [ ] Optional: interactive dependency graph / call graph visualization
  - Goal: visualize code relationships (imports/calls) as a movable graph (nodes/edges)
  - Possible outputs: Mermaid graph in Markdown, Graphviz DOT/SVG, or JSON for a web viewer
  - Scope: at least `main.py` -> `render.py` -> `templates/*` plus other core modules
- [ ] Named EIGRP support (feature)
  - Standardize templates to support a named EIGRP config model intentionally (not incidentally)
  - Decide how this interacts with VRF (GRT + VRF address-families) and split-horizon controls

- [ ] Named OSPF support (feature)
  - Add an intentional named OSPF config model (VRF + GRT where applicable)

- [ ] Add CLI to select routing protocol configuration model (named EIGRP / named OSPF vs classic/numeric)
  - Why: avoid mixed-mode confusion; make the chosen model explicit

- [ ] Validate runtime behavior in CML for DMVPN underlay `flat-pair`
  - odd routers are DMVPN endpoints (Tunnel0/NHRP)
  - even routers are EIGRP-only
  - odd router NBMA interface is passive for EIGRP (no neighbors on Gi0/0)

- [ ] Decide/implement least-astonishment semantics for DMVPN `--dmvpn-underlay flat-pair` node counts
  - whether `N` should mean total routers vs DMVPN endpoints
  - or document the doubling behavior clearly

- [ ] Front Door VRF (FVRF) for DMVPN
  - FVRF places Gi0/0 (NBMA) into a transport VRF (e.g. `INTERNET`); Tunnel0, Loopback0, pair link stay in GRT
  - Tunnel0 gets `tunnel vrf INTERNET` to source from the transport VRF
  - **Fix required:** EEM scripts (WAIT-FOR-CA, CLIENT-PKI-AUTHENTICATE, etc.) that ping the CA at 10.10.255.254 must use `ping vrf INTERNET 10.10.255.254` instead of `ping 10.10.255.254` — the CA is on the NBMA network which is in the FVRF, not the GRT
  - Same applies to any SCEP enrollment URL or other config that assumes GRT reachability to the NBMA network
  - `enrollment vrf INTERNET` on trustpoint rejected on IOSv — IOS-XE only (CSR template only)
  - NHRP auth string max 8 characters on IOS/IOSv (tested: `DMVPN-AUTHC` rejected, `DMVPNKEY` accepted)
  - IKEv2 policy needs `match fvrf INTERNET` so IKEv2 matches traffic from the transport VRF; without it, IKEv2 SAs won't form over the FVRF tunnel
  - IKEv2 profile also needs `match fvrf INTERNET` (`crypto ikev2 profile TOPGEN-IKEV2` → `match fvrf INTERNET`)

- [ ] Explore shareable, self-describing lab intents (example lab collection / "marketplace" concept)
- [ ] Formalize serialized intent model (versioned `topogen:` schema embedded in lab YAML)
- [ ] Support regenerating a lab from its embedded intent (`topogen regenerate lab.yaml`)
- [ ] Emit machine-readable inventory alongside offline lab output
- [ ] Add intent-level validation and least-astonishment checks before rendering
- [ ] Support named intent profiles / presets for common lab patterns
- [ ] Curate example offline labs using embedded intent (shareable / regeneratable lab collection)
- [ ] Serialized Intent & Round-Trip Capability:
  - Embed all generation parameters (topology mode, node count, addressing model) directly into the lab YAML under a `topogen:` metadata block.
  - Implement a `topogen regenerate <file.yaml>` command that reads this metadata to deterministically recreate or update the lab.
- [ ] Intent-based lab generation (medium effort)
  - Why: Unlock full round-trip editing and GitOps workflows by making intent the source of truth.

- [ ] TOPOGEN_INTENT invisible annotation contract for CML labs (medium effort)
  - Why: Embed generation parameters as an invisible text annotation inside the CML lab description so any tool (CLI, GUI, script) can recover the original intent directly from the live lab — not just from the offline YAML.
  - Contract: A hidden `TOPOGEN_INTENT={...}` JSON block injected into the lab description/notes field, invisible in the CML UI but parseable by CLI.
  - Data fields: mode, nodes, template, routing protocol, --pki, --mgmt, addressing params, topogen version.
  - On import: `topogen regenerate` reads the annotation from the live CML lab and re-generates or updates deterministically.
  - Complements: "Embed serialized intent in YAML" (above) — YAML embedding covers offline files; this covers live CML labs.
  - Blast radius: render.py (inject annotation on online lab creation), main.py (--regenerate reads annotation from CML API).

- [ ] Automation Inventory Emission:
  - Generate an `inventory.json` (or `.yaml`/`.csv`) artifact during the offline generation phase.
  - Include node names, management IPs, VRF names, and platform types to enable instant tool ingestion (Ansible, Nornir, Netmiko).

- [ ] Offline Validation Sidecar:
  - Emit a standalone `verify_connectivity.py` script alongside the lab YAML.
  - Use the generated inventory to automatically test SSH reachability and protocol health (e.g., DMVPN status, OSPF neighbors) post-boot.

- [ ] Gooey Round-Trip Integration:
  - Add logic to prepopulate Gooey GUI fields by parsing the serialized intent from an existing lab YAML.

- [ ] Embed serialized intent in YAML (`topogen:` block) for regeneration workflows (medium effort).
  - Why: Makes YAML the single source of truth with embedded params (mode, nodes, template, mgmt config); add `topogen regenerate lab.yaml` subcommand to unlock round-trip editing, GitOps, and easy tweaks without re-running full CLI.

- [ ] Post-build automation hooks (low effort).
  - Why: Add --post-hook flag for running scripts after generation (e.g., start lab, poll readiness, or run Ansible from inventory); unlocks "one command to fully configured lab" workflows.

- [ ] Test unmanaged switches in all modes (flat, flat-pair, etc.) for port limits at 300+ nodes (medium effort).
  - Why: Verify no overflows and add warnings/guardrails; builds confidence for huge-scale labs and document results in README for better user guidance.

- [ ] Prepopulate Gooey GUI from existing YAML metadata (low effort).
  - Why: Add "Load from YAML" file chooser to parse `topogen:` block and auto-fill fields; unlocks quick interactive edits/tweaks in GUI without retyping params.

- [ ] Update README with topology diagrams and scale examples (low effort).
  - Why: Add visuals for flat star vs. pair topologies and command examples (e.g., 300-node flat lab); makes the project more approachable and helps users understand scale capabilities.

- [ ] Rework README `--help` output block to prevent CLI drift (low effort).
  - Why: The embedded `topogen --help` block in README can silently drift from `main.py` as new flags are added (e.g., `--pki`, `--mgmt`).
  - Options: (a) Auto-generate from `topogen --help` during release, (b) Replace with "run `topogen --help` for current flags" and link to DEVELOPER.md for flag details, (c) Add a CI check that diffs README help block against actual CLI output.
  - Blast radius: README.md only (documentation, no code changes).

- [ ] Add machine-parsable artifact summary line after offline YAML generation (low effort).
  - Why: Enables CI/CD pipelines and wrapper scripts to grep a single structured line for path, size, mode, and node count.
  - Format: `ARTIFACT_YAML=out/lab.yaml bytes=862312 kind=flat-pair nodes=520`
  - When: Implement when a CI/CD pipeline or automation script needs to consume the output programmatically.
  - Blast radius: render.py (4 offline write paths), no behavior change to existing log lines.

- [ ] Trim and reorganize README.md for readability (low effort).
  - Why: README has grown large with inline help output, detailed examples, and mixed audiences (end-users vs contributors). Makes it harder to scan and find what you need.
  - Options: (a) Move contributor/developer content to DEVELOPER.md, (b) Collapse verbose sections behind summary headings, (c) Replace inline `--help` block with a link (pairs with the help-drift item above).
  - Blast radius: README.md only (documentation, no code changes).
