<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.2
Date Modified: 2026-03-24

- Called by: Users and developers using or troubleshooting TopoGen PKI (--pki, DMVPN IKEv2 PKI)
- Reads from: README.md, TODO.md, CHANGES.md, examples/eem-*.txt, render.py PKI helpers
- Writes to: None (documentation only)
- Calls into: References README, TODO, CHANGES, DEVELOPER

Purpose: Single reference for TopoGen PKI: flags, CA-ROOT and client behavior, EEM applets,
         boot order requirements, known issues, and troubleshooting (including auto-deploy certs).

Blast Radius: None (documentation only)
-->

# TopoGen PKI

This document describes TopoGen’s PKI (Public Key Infrastructure) support: the CA-ROOT node, client trustpoints, EEM applets for clock and enrollment, and how to troubleshoot cert auto-deploy.

## Overview

- **`--pki`** adds a single root CA router (**CA-ROOT**) to the lab and injects PKI client config (trustpoint **CA-ROOT-SELF**) on non-CA routers.
- **`--dmvpn-security ikev2-pki`** (requires `--pki`) protects DMVPN with IKEv2 and certificate-based auth: IKEv2 profile uses `authentication local rsa-sig` / `authentication remote rsa-sig` and `pki trustpoint CA-ROOT-SELF`.
- CA-ROOT runs the IOS-XE PKI server; clients authenticate and (optionally) enroll via SCEP or manual steps. EEM applets set clock on CA and clients and can drive `crypto pki authenticate` / enrollment.
- For **manual or pre-generated PKI**: generating Root CA and router certs with OpenSSL (or the `tools/gen_pki_manual_test.py` script) and importing via `crypto pki import ... pem terminal` is described in [docs/MANUAL-PKI-IMPORT-TEST.md](docs/MANUAL-PKI-IMPORT-TEST.md). That doc includes both the Python workflow and a pure OpenSSL command sequence.

## CLI flags

| Flag | Purpose |
|------|---------|
| `--pki` | Add CA-ROOT node; inject trustpoint CA-ROOT-SELF on non-CA routers (flat, flat-pair, DMVPN). |
| `--dmvpn-security ikev2-pki` | Use IKEv2 with RSA-sig and trustpoint CA-ROOT-SELF for DMVPN (requires `--pki`). |

CA IP is derived from the NBMA/addressing (e.g. last usable in NBMA CIDR). See [README](README.md) for full CLI and examples.

## CA-ROOT and clients

- **CA-ROOT**: Node definition is CSR1000v; template `csr-pki-ca.jinja2`. Connects to the NBMA (and OOB switch if `--mgmt`). Self-signed trustpoint **CA-ROOT-SELF**; PKI server enabled; EEM **CA-ROOT-SET-CLOCK** sets clock so the CA cert is valid.
- **Clients**: Each non-CA router gets `crypto pki trustpoint CA-ROOT-SELF` (and related config) injected by `render.py`; IKEv2 profile references the same trustpoint when using `--dmvpn-security ikev2-pki`. EEM applets **CLIENT-PKI-SET-CLOCK**, **CLIENT-PKI-AUTHENTICATE**, **CLIENT-PKI-ENROLL**, etc. run on clients to set clock and attempt authenticate/enroll.

Trustpoint and IKEv2/crypto blocks must be ordered so the trustpoint is defined before any reference (e.g. `ip http secure-trustpoint`, IKEv2 profile). See [Known issues and fixes](#known-issues-and-fixes) below.

## EEM applets (PKI)

Script bodies live in **`examples/`**. Status is tracked in [TODO.md](TODO.md) (Current work → EEM scripts (PKI) — working status).

| Applet | Purpose |
|--------|---------|
| CA-ROOT-SET-CLOCK | On CA-ROOT: sets clock after delay so CA cert is valid; NTP check then clock set / ntp master fallback. |
| CLIENT-PKI-SET-CLOCK | On clients: sets clock (e.g. 305 s) so client can validate CA cert. |
| CLIENT-PKI-AUTHENTICATE | Runs `crypto pki authenticate` and answers prompt (timing-dependent; manual `authc` if CA-ROOT misses window). |
| CLIENT-PKI-ENROLL | Enrollment automation. |
| CLIENT-PKI-CHAIN, AUTO-AUTH, do-ssh | See `examples/` and TODO. |

EEM applets are injected **last** in startup config (before final `end`) so they do not cause later config (interfaces, IKEv2, routing) to be dropped. Timers (e.g. 300 s CA, 305 s client) give CA-ROOT time to boot and start the PKI server before client attempts.

## Known issues and fixes (auto-deploy certs)

Goal: **auto-deploy PKI/certs** — CA and clients deploy and enroll without manual `crypto pki authenticate` and without relying on CA-ROOT timing. Current work is tracked under **Feature: Auto-deploy PKI/certs (fix)** in [TODO.md](TODO.md).

1. **EEM "end" action outside conditional block**  
   On some IOS-XE versions, CA-ROOT-SET-CLOCK and CLIENT-PKI-SET-CLOCK report `"end" action found outside of conditional block`. Fix: indent `action X.Y end` so the parser associates `end` with the correct if block. See `_pki_ca_clock_eem_lines()` and `_pki_client_clock_eem_lines()` in `render.py`.

2. **CVAC rejects `ip http secure-trustpoint CA-ROOT-SELF`**  
   Root cause: wrong command syntax — IOS/IOS-XE uses `ip http secure-trustpoint`, not `ip http secure-server trustpoint`. Also reorder so `crypto key generate rsa` and `crypto pki trustpoint CA-ROOT-SELF` (and subcommands) appear before `ip http secure-trustpoint` in all CA and client PKI blocks; remove duplicate lines from inline pki_config_lines.

3. **CA-ROOT time EEM missing when lab is created online**  
   Offline flat/DMVPN/flat-pair get `_pki_ca_clock_eem_lines()` in the CA config; **online flat** builds CA from `csr-pki-ca.jinja2` only (no EEM). Fix: add CA clock EEM to the online flat CA build in `render_flat_network()` (e.g. append `_pki_ca_clock_eem_lines()` before assigning `ca_router.configuration`).

## Examples (auto-deploy cert fixes)

Concrete before/after or target snippets for the three fixes. Locations: `src/topogen/render.py`.

### Fix 1: EEM "end" indentation (CA-ROOT-SET-CLOCK and CLIENT-PKI-SET-CLOCK)

On some IOS-XE versions the parser reports `"end" action found outside of conditional block` when the `end` that closes an `if` block has only one space before `action`. Use two spaces so the parser associates `end` with the inner `if` block.

**CA-ROOT** (`_pki_ca_clock_eem_lines()`):

- Before: `" action 1.10 end"` (one space)
- After: `"  action 1.10 end"` (two spaces)

Also ensure any other `end` that closes an `if` in that applet uses two leading spaces (e.g. ` action 0.8 end` → `  action 0.8 end`).

**Client** (`_pki_client_clock_eem_lines()`):

- Before: `" action 1.11 end"` (one space)
- After: `"  action 1.11 end"` (two spaces)

Same for any `end` closing an `if` in the client clock applet. In CLIENT-PKI-AUTHENTICATE, ` action 1.8  end` and similar: use two spaces before `action` for the line that closes the `if` block.

### Fix 2: Correct command syntax and ordering for `ip http secure-trustpoint` (CVAC)

The correct IOS/IOS-XE command is `ip http secure-trustpoint` (not `ip http secure-server trustpoint`). The trustpoint and RSA key must also exist before the reference. Reorder blocks so key + trustpoint come first, then HTTP.

**CA self-enroll block** (`_pki_ca_self_enroll_block_lines()`). Current (wrong) order and syntax:

```
do clock set ...
ip http secure-server
ip http secure-server trustpoint CA-ROOT-SELF   ← wrong command
crypto key generate rsa ...
crypto pki trustpoint CA-ROOT-SELF
  enrollment url ...
  ...
```

**Target (correct) order and syntax:**

```
do clock set ...
crypto key generate rsa modulus 2048 label CA-ROOT-SELF
crypto pki trustpoint CA-ROOT-SELF
  enrollment url ...
  rsakeypair CA-ROOT-SELF
  ...
ip http secure-server
ip http secure-trustpoint CA-ROOT-SELF           ← correct command
```

Apply the same order and syntax in any inline CA or client PKI block that emits `ip http secure-trustpoint` (e.g. `_inject_pki_client_trustpoint` trustpoint_block, and any pki_config_lines in render.py that contain that line). Remove duplicate lines so they appear only once, after the trustpoint is defined.

### Fix 3: Online flat — inject CA clock EEM before assigning CA config

In `render_flat_network()`, the CA config is built from `csr-pki-ca.jinja2` and assigned to `ca_router.configuration` with no EEM. Append the CA clock EEM lines before assignment.

**Current (online flat, no EEM):**

```python
ca_config = ca_template.render(...)
ca_router.configuration = ca_config
```

**Target (append CA clock EEM):**

```python
ca_config = ca_template.render(...)
ca_config = ca_config.rstrip() + "\n" + "\n".join(_pki_ca_clock_eem_lines()) + "\n"
ca_router.configuration = ca_config
```

Or build as list of lines and join. Ensure the EEM block is appended before `ca_router.configuration = ...` so online flat CA gets the same CA-ROOT-SET-CLOCK behavior as offline.

## Troubleshooting

- **Manual `authc`**: If CA-ROOT is not ready when the client EEM fires (305 s), run `crypto pki authenticate CA-ROOT-SELF` (and answer the prompt) on the client. See CHANGES.md v1.2.2–v1.2.4.
- **Tunnels / IKEv2**: Ensure trustpoint is defined before the IKEv2 profile that references it; EEM applets must be injected last so interface/crypto/routing config is not lost.
- **Online vs offline**: Online flat currently does not inject CA-ROOT-SET-CLOCK EEM; behavior may differ from offline. Prefer offline YAML + import for consistent PKI/clock behavior until the fix above is applied.

## References

- [README.md](README.md) — CLI, modes, examples (flat, DMVPN, PKI, archive).
- [TODO.md](TODO.md) — EEM status table, Feature: Auto-deploy PKI/certs, Promote to Issues (detailed fix descriptions), Future ideas (`--pki-ca-fingerprint`, `--pki-scep`, etc.).
- [CHANGES.md](CHANGES.md) — Release history (EEM timers, injection order, IKEv2 PKI, feat/pki-ca).
- [DEVELOPER.md](DEVELOPER.md) — File chains, render.py, templates.
