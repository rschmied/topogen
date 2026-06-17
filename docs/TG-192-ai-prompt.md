# TG-192 — AI implementation prompt
# CML CI/CD pipeline + per-ticket scoped CML users
# Copy everything below this line into Jira TG-192 or a fresh Cursor agent chat.

You are implementing **TG-192** in the topogen repo.

- **Canonical remote:** `https://wwwin-github.cisco.com/rohosfor/topogen.git` (`cisco` remote)
- **Parent epic:** TG-189 (IPv6 on OOB management plane)
- **Prerequisite:** TG-191 merged to `cisco/main` — PR #47, merge commit `a5acfd7`
  - Emits `nac/sync-nac-mgmt.py`, `nac/NAC-WORKFLOW.md`, `mgmt_sync.json` with every `--nac` tree
  - Library: `src/topogen/nac_mgmt_sync.py`; CLI: `topogen sync-nac-mgmt`
- **Related (Done):** TG-190 (PR #46, IPv6 SLAAC OOB + sync logic), TG-150 (`cml2/` scaffold), TG-161 (NaC terraform plan CI)
- **Labels:** `bootstrap`, `cicd`, `cml`, `jira`, `nac`, `security`
- **Branch from:** `cisco/main` (e.g. `TG-192-cml-cicd-pipeline`)

**Git policy:** Push, PR, and merge **only** to `cisco`. **NEVER** push/PR/merge to `origin` (public `github.com/QB4DEVOPS/topogen` mirror).

---

## Problem

NaC bootstrap labs (`--nac --bootstrap --terraform-cml2`) are deployable end-to-end, but the workflow is manual and credential-unsafe:

1. Operators run generate → `cml2/` apply → mgmt sync → `nac/` apply by hand.
2. Sync helpers now live in the **emitted** `out/<lab>/nac/` tree (TG-191), but CI/CD scripts like `scripts/validate-tg162-dmvpn-live.ps1` still hunt `scripts/sync-nac-mgmt-*.py`.
3. There is no documented runbook for **admin vs customer** credential separation.
4. Customers today would receive shared admin CML credentials — unacceptable for security.
5. No automation ties Jira tickets to lab lifecycle (provision on trigger, READY handoff, teardown on Done).

TG-191 unblocked the sync step. TG-192 wires the **full pipeline** and **per-ticket scoped CML users** (`lab_view` + `lab_exec`, `admin: false`).

---

## Goal

Deliver an end-to-end **Jira → generate → cml2 deploy → sync mgmt → NaC apply → verify → provision customer → READY comment** pipeline, with **teardown on ticket Done**.

Automation uses a **service account** (admin creds in CI secrets / vault only). Customers receive **per-ticket CML logins** scoped to their lab — never shared admin credentials.

Canonical workflow (large labs — prefer `cml2/` over `topogen --up`):

```
Jira trigger → topogen generate → terraform apply (cml2/) → wait BOOTED
  → python nac/sync-nac-mgmt.py → terraform apply (nac/) → verify gates
  → provision-cml-user (lab_view+lab_exec) → Jira READY comment
On ticket Done → delete customer user → terraform destroy (cml2/)
```

---

## Deliverables

### 1. DEVELOPER.md runbook (Phase 1)

Add a **"CML CI/CD pipeline (TG-192)"** section documenting:

| Topic | Content |
|-------|---------|
| Credential tiers | **Service account** (`TF_VAR_*`, `VIRL2_*`, `IOSXE_*` in CI/vault) vs **customer account** (`tg-<ticket>-<suffix>`, lab-scoped only) |
| Trigger | Jira ticket with label `cml-lab` (or equivalent); ticket key becomes lab title suffix |
| Generate | Full command for reference lab shape (see below) |
| Deploy | `terraform -chdir=out/<lab>/cml2 init` + `apply -var=wait=true` |
| Sync | **Emitted** `python out/<lab>/nac/sync-nac-mgmt.py --lab-id <uuid> --nac-root out/<lab>/nac` (or `topogen sync-nac-mgmt`); **do not** document `scripts/` as primary path |
| NaC apply | `terraform -chdir=out/<lab>/nac init` + `apply` with `IOSXE_*` |
| Verify | Minimal gates: `mgmt_sync.json` synced count, terraform apply exit 0, optional `ansible-playbook verify_reachability.yaml` or `ssh-fanout.py` for IPv6 SLAAC labs |
| Handoff | `topogen provision-cml-user` or MCP `create_cml_user`; Jira READY comment template |
| Teardown | On Jira **Done**: `delete_cml_user` + `terraform destroy` in `cml2/`; document opt-in / manual approval for destroy |
| Env vars | `TF_VAR_address`, `TF_VAR_username`, `TF_VAR_password` (or `TF_VAR_token`), `TF_VAR_skip_verify`; `VIRL2_URL`, `VIRL2_USER`, `VIRL2_PASS`; `IOSXE_USERNAME`, `IOSXE_PASSWORD`, `IOSXE_URL` |
| Scale note | 16+ routers with `--mgmt` require `--mgmt-ipv6-mode slaac` (see `docs/TG-190-checkpoint-1.md`) |

Reference generate command (300-node IPv6 SLAAC — matches live lab `TG-190-flat-300-nac-v6`):

```bash
topogen --cml-version 0.3.1 -L "TG-190-flat-300-nac-v6" \
  300 --mode flat -T iosv --device-template iosv \
  --offline-yaml out/TG-190-flat-300-nac-v6.yaml \
  --nac --bootstrap --terraform-cml2 \
  --mgmt --mgmt-vrf Mgmt-vrf --mgmt-ipv6-mode slaac --mgmt-bridge \
  --mgmt-ipv6-cidr fd00:10:254::/64 \
  --overwrite
```

### 2. GitHub Actions skeleton (Phase 2)

Add workflow (e.g. `.github/workflows/cml-nac-pipeline.yml`) or extend `.github/workflows/python-package.yml`:

- **Trigger:** `workflow_dispatch` with inputs (`jira_key`, `node_count`, `mode`) + optional `repository_dispatch` for Jira webhook
- **Secrets (document names, never values):** `CML_TF_ADDRESS`, `CML_TF_USERNAME`, `CML_TF_PASSWORD`, `CML_TF_SKIP_VERIFY`, `VIRL2_URL`, `VIRL2_USER`, `VIRL2_PASS`, `IOSXE_USERNAME`, `IOSXE_PASSWORD`
- **Steps (skeleton — live apply behind `if: inputs.live_apply == true` or manual dispatch):**
  1. `uv sync --all-extras --dev`
  2. `topogen ... --offline-yaml --nac --bootstrap --terraform-cml2 --mgmt ...`
  3. `terraform init` + `apply` in `out/<lab>/cml2/`
  4. Capture `lab_id` from `terraform output -raw lab_id`
  5. `python out/<lab>/nac/sync-nac-mgmt.py --lab-id $LAB_ID --nac-root out/<lab>/nac --cml-snoop-only` (SLAAC) or `--mode dhcp` (IPv4)
  6. `terraform init` + `apply` in `out/<lab>/nac/`
  7. Verify gates (parse `mgmt_sync.json`, check apply exit code)
  8. `topogen provision-cml-user --lab-id $LAB_ID --username tg-$JIRA_KEY ...`
  9. Upload evidence artifacts (`mgmt_sync.json`, terraform logs) — **not** `out/` to git
- **Offline CI gate (always runs):** reuse patterns from `nac-terraform-plan` and `cml2-terraform-plan` jobs; add unit tests for new subcommand
- Follow existing conventions: `hashicorp/setup-terraform@v3`, `TF_PLUGIN_CACHE_DIR`, path filters

Add validation script: `scripts/validate-tg192-pipeline.ps1` (offline gates + optional `-LiveApply`), modeled on `scripts/validate-tg162-dmvpn-live.ps1` but using **emitted** `nac/sync-nac-mgmt.py`.

### 3. Jira webhook integration (Phase 3)

Document + implement webhook handler (GitHub `repository_dispatch` or lightweight script in `scripts/jira-cml-webhook.py`):

| Event | Action |
|-------|--------|
| Issue labeled `cml-lab` or moved to "In Progress" with pipeline label | Dispatch CI workflow with `jira_key`, parsed generate params from ticket description/custom fields |
| Pipeline success | `addCommentToJiraIssue` with structured READY block: lab title, lab UUID, CML URL (`$TF_VAR_address/lab/$lab_id`), customer username, password delivery note ("retrieve from vault / 1Password — not in comment") |
| Issue transitioned to **Done** | Dispatch teardown job: `delete_cml_user`, `terraform destroy` in `cml2/` |

READY comment template (example):

```
CML lab READY — TG-xxx
- Lab: <title> (<lab_uuid>)
- URL: <cml_base>/lab/<lab_uuid>
- Customer user: tg-TG-xxx-<suffix> (password: vault link / operator handoff)
- Sync: <N>/<N> routers in mgmt_sync.json
- NaC apply: success
```

Use Atlassian MCP (`addCommentToJiraIssue`, `getJiraIssue`, `transitionJiraIssue`) or Jira REST API. Webhook auth via shared secret in GitHub Actions secrets.

### 4. `topogen provision-cml-user` subcommand (Phase 4)

Add CLI subcommand (mirror `sync-nac-mgmt` dispatch in `main.py`):

```
topogen provision-cml-user \
  --lab-id <uuid> \
  --username tg-TG-192-demo \
  [--password-env CUSTOMER_CML_PASSWORD] \
  [--description "TG-192 scoped user"] \
  [--dry-run]
```

Behavior:

- Connect via `virl2_client` using `VIRL2_*` env vars (same pattern as `nac_mgmt_sync._cml_client()`)
- Create user with `admin: false`
- Associate user to lab with permissions **`lab_view`** + **`lab_exec`** only (no `lab_admin`, no `lab_edit`)
- Generate password from env var or CSPRNG; print username + password to stdout **once** (or write to file path from `--output-json`); never log password at INFO level
- Support `--revoke` / teardown mode: delete user by username (wraps MCP-equivalent `delete_cml_user` semantics)
- Unit tests with mocked CML client

Reference API shape: CML MCP `create_cml_user` tool (`user.associations[].permissions: ["lab_view","lab_exec"]`, `user.admin: false`).

---

## Reference implementation (on `cisco/main` after TG-191)

| Artifact | Purpose |
|----------|---------|
| `src/topogen/nac.py` → `write_nac_mgmt_sync_scaffold()` | Emits `sync-nac-mgmt.py`, `NAC-WORKFLOW.md` |
| `src/topogen/nac_mgmt_sync.py` | Shared sync logic; `sync_nac_mgmt()`, `build_argparser()` |
| `src/topogen/cml2.py` | `cml2/` Terraform scaffold (`lab_id` output) |
| `src/topogen/main.py` | `sync-nac-mgmt` subcommand pattern to copy |
| `scripts/validate-tg162-dmvpn-live.ps1` | Multi-stage live pipeline pattern (update sync step to emitted path) |
| `.github/workflows/python-package.yml` | `nac-terraform-plan`, `cml2-terraform-plan` CI jobs |
| `tests/test_cml2_terraform_plan.py` | Offline cml2 plan contract (40 cases) |
| `tests/test_nac_terraform_plan.py` | Offline nac plan contract (9 cases) |
| `docs/TG-190-checkpoint-1.md` | IPv6 SLAAC OOB context; scale requirements |
| CML MCP `create_cml_user` / `delete_cml_user` | User provisioning API reference |

**Reference lab (live-validated shape):**

- Title: `TG-190-flat-300-nac-v6`
- Lab ID: `2be6f617-cf45-4bff-8970-2c9f28ac01d3`
- Artifacts: `out/TG-190-flat-300-nac-v6/{cml2/,nac/,*.yaml}`

---

## Integration points

- `src/topogen/main.py` — `provision-cml-user` subcommand dispatch; optional `revoke-cml-user` alias
- `src/topogen/cml_user.py` (new) — user create/delete/associate logic via `virl2_client`
- `DEVELOPER.md` — CML CI/CD runbook section
- `.github/workflows/cml-nac-pipeline.yml` (new) — pipeline skeleton
- `scripts/validate-tg192-pipeline.ps1` (new) — offline + optional live gates
- `scripts/jira-cml-webhook.py` (new, optional) — webhook payload → workflow dispatch
- `CHANGES.md`, `TODO.md` — mark TG-192 done
- Update `scripts/validate-tg162-dmvpn-live.ps1` sync step to prefer emitted `nac/sync-nac-mgmt.py` when present (backward-compatible fallback to `scripts/` wrappers OK)

---

## Acceptance criteria

```bash
# 0) Branch from cisco/main (TG-191 present)
git fetch cisco && git checkout -b TG-192-cml-cicd-pipeline cisco/main
git log -1 --oneline   # expect a5acfd7 or later with TG-191

# 1) Offline: generate reference-shaped lab (small matrix for CI; 4-node smoke)
topogen 4 --mode flat -T iosv --offline-yaml out/TG-192-smoke.yaml \
  --nac --bootstrap --terraform-cml2 \
  --mgmt --mgmt-vrf Mgmt-vrf --mgmt-ipv6-mode slaac --mgmt-bridge --overwrite

test -f out/TG-192-smoke/nac/sync-nac-mgmt.py
test -f out/TG-192-smoke/nac/NAC-WORKFLOW.md
test -f out/TG-192-smoke/cml2/main.tf

# 2) Offline: provision-cml-user unit tests
pytest tests/test_cml_user_provision.py -q

# 3) Offline: pipeline validation script (no live CML)
# PowerShell:
.\scripts\validate-tg192-pipeline.ps1
# → exit 0; offline gates PASS

# 4) Offline: existing CI contracts still green
pytest tests/test_nac_writer.py tests/test_cml2_lifecycle.py -q
TOPOGEN_TERRAFORM_PLAN=1 pytest tests/test_nac_terraform_plan.py -m terraform -q
TOPOGEN_CML2_TERRAFORM_PLAN=1 pytest tests/test_cml2_terraform_plan.py -m cml2_terraform -q

# 5) Live (manual / workflow_dispatch with secrets) — against existing or new lab
export TF_VAR_address=... TF_VAR_username=... TF_VAR_password=... TF_VAR_skip_verify=true
export VIRL2_URL=... VIRL2_USER=... VIRL2_PASS=...
export IOSXE_USERNAME=... IOSXE_PASSWORD=...

terraform -chdir=out/TG-192-smoke/cml2 init
terraform -chdir=out/TG-192-smoke/cml2 apply -auto-approve -var=wait=true
LAB_ID=$(terraform -chdir=out/TG-192-smoke/cml2 output -raw lab_id)

python out/TG-192-smoke/nac/sync-nac-mgmt.py \
  --lab-id "$LAB_ID" --nac-root out/TG-192-smoke/nac --cml-snoop-only
# → mgmt_sync.json shows synced > 0

terraform -chdir=out/TG-192-smoke/nac init
terraform -chdir=out/TG-192-smoke/nac apply -auto-approve

topogen provision-cml-user --lab-id "$LAB_ID" --username "tg-TG-192-smoke" \
  --description "TG-192 acceptance"
# → user created; admin=false; lab_view+lab_exec on lab only

# 6) Teardown (only when explicitly running acceptance teardown)
topogen provision-cml-user --lab-id "$LAB_ID" --username "tg-TG-192-smoke" --revoke
terraform -chdir=out/TG-192-smoke/cml2 destroy -auto-approve
```

---

## Constraints

- **NEVER** hardcode credentials, tokens, or CML URLs in source, workflows, or docs examples (use `...` placeholders)
- **NEVER** push/PR/merge to `origin` (public mirror) — **cisco only**
- **NEVER** commit `out/` lab artifacts, `terraform.tfvars`, `*.tfstate*`, or probe logs
- **NEVER** delete CML labs or users unless explicitly running teardown acceptance or operator requests it
- **NEVER** put customer passwords in Jira comments — username + vault handoff only
- Customer CML users: **`admin: false`**, permissions **`lab_view` + `lab_exec`** only
- Service account retains admin for deploy/verify; customer creds are post-READY handoff only
- Use **emitted** `out/<lab>/nac/sync-nac-mgmt.py` (or `topogen sync-nac-mgmt`) for sync — not `scripts/` as the documented primary path
- Large labs: **`cml2/` Terraform apply**, not `topogen --up` (see DEVELOPER.md)
- IPv6 SLAAC mgmt addresses are **discovered at runtime** — sync must not assume static addressing
- Minimal diff; match existing topogen conventions (`validate-tg162` script style, pytest mocks, file-chain headers)

---

## Out of scope

- Re-implementing mgmt sync (TG-191 Done)
- IPv6 OOB render / template work (TG-190 Done)
- dnsmasq DHCPv6 server on DNS host (TG-87 / future)
- Full production vault integration (document secret **names**; implement handoff contract only)
- Automatic 300-node CI apply on every PR (live apply is `workflow_dispatch` / webhook only)
- Customer self-service portal or multi-tenant CML controller setup
- Rewriting `netascode/nac-iosxe` module or NaC schema gaps

---

## Definition of done

- [ ] DEVELOPER.md documents full CML CI/CD runbook with admin vs customer credential separation
- [ ] GitHub Actions pipeline skeleton runs offline gates; live apply behind manual/webhook trigger
- [ ] Jira webhook → workflow dispatch → READY comment documented and implemented (or scripted with clear operator steps)
- [ ] `topogen provision-cml-user` creates lab-scoped users (`lab_view`+`lab_exec`, `admin: false`); revoke/teardown path exists
- [ ] `scripts/validate-tg192-pipeline.ps1` passes offline; live path documented
- [ ] Pipeline uses emitted `nac/sync-nac-mgmt.py` (not `scripts/` hunt)
- [ ] Tests pass; `CHANGES.md` updated; `TODO.md` marks TG-192 done
- [ ] PR opened and merged on **cisco** (`wwwin-github.cisco.com`); TG-192 closed in Jira

---

## Jira summary (paste into TG-192 description header)

End-to-end CML CI/CD: Jira trigger → `topogen --nac --bootstrap --terraform-cml2` → `cml2/` apply → emitted `nac/sync-nac-mgmt.py` → `nac/` apply → verify → `provision-cml-user` (`lab_view`+`lab_exec`, no admin) → READY Jira comment; teardown user + lab on Done. Phases: DEVELOPER.md runbook, GitHub Actions skeleton, Jira webhook, `provision-cml-user` CLI. Unblocked by TG-191 (PR #47). Reference lab: `TG-190-flat-300-nac-v6` (`2be6f617-cf45-4bff-8970-2c9f28ac01d3`). Cisco remote canonical.