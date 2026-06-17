<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.5
Date Modified: 2026-02-21

- Called by: Users and automation that consume the shared PKI
- Reads from: (none — this file is documentation only)
- Writes to: None
- Calls into: References docs/MANUAL-PKI-IMPORT-TEST.md, PKI.md

Purpose: Directory for certificates that have been proven to load and sign successfully.
         Only certs that work in the lab go into the repo; use them as the canonical set
         for hundreds of labs / thousands of routers.
-->

# Proven certs

> **⚠️ WARNING — LAB USE ONLY**  
> **NEVER use these keys or certificates in production.** They are **ONLY** for isolated labs in CML (Cisco Modeling Lab). Do not use them for any production network, service, or environment.

This directory defines a **fixed trust anchor** used to make large-scale labs deterministic and automatable. The root CA is generated once and reused so that certificate fingerprints, trustpoints, and router configurations remain stable across hundreds of labs.

**Production vs. lab PKI.** In production, PKI is fundamentally different. Long-lived endpoint certificates (for example, 10–20 years) are not acceptable. Production PKI is typically structured as a policy-segmented hierarchy: **CA-ROOT → CA-POLICY → CA-SIGN → endpoint certificates**, with a Registration Authority (RA) responsible for identity verification and enrollment control.

In this model, the root CA is kept offline in an HSM, policy CAs enforce constraints, signing CAs issue short-lived certificates, and the RA validates device or user identity before certificates are issued. Endpoint certificates are expected to rotate frequently, and revocation and compromise containment are first-class concerns.

For labs, these concerns are intentionally out of scope. We collapse the hierarchy, eliminate the RA, and use a long-lived root CA solely to provide a stable trust anchor for repeatable automation. **This PKI model is for lab use only and must not be copied into production.**

Production PKI optimizes for compromise containment and policy enforcement; lab PKI optimizes for determinism and reproducibility.

---

Certificates in this directory have been **proven**: loaded on devices and used to sign (or used as a trust anchor) successfully. If it works in the lab, it goes here and into the repo.

## What to put here

- **Root CA cert and key** (e.g. `rootCA.pem`, `rootCA.key`) so you can recreate and sign router certs for PKI labs anytime.
- Optionally router certs or other proven certs. Use this as the canonical, frozen set for TopoGen labs and shared PKI (one CA across hundreds of labs).

**Security note:** This directory is committed to the repo and may contain private keys. Restrict repo access to people who are allowed to use the lab CA. Lab use only — do not use in production.

## Workflow

1. Generate the Root CA **once** (e.g. with `tools/gen_pki_openssl.sh` or the one-time OpenSSL commands in [MANUAL-PKI-IMPORT-TEST.md](docs/MANUAL-PKI-IMPORT-TEST.md)).
2. Load and use it (import on a router, sign router certs). If it works, copy the **certificate and key** (e.g. `rootCA.pem`, `rootCA.key`) into `proven_certs/`.
3. Commit both. You need the key here to recreate PKI labs and sign new router certs; the same CA stays stable everywhere.

See [docs/MANUAL-PKI-IMPORT-TEST.md](docs/MANUAL-PKI-IMPORT-TEST.md) for stable fingerprint and golden cert-chain workflow.
