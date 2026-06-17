<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.0.1
Date Modified: 2026-02-16

Purpose: Report and recommendations for Doc Version enforcement (CI, hooks, commit message).
-->

# Doc Version Enforcement — Report and Recommendations

**Context**: Multiple LLMs were asked how to fix the recurring issue where AI (and sometimes humans) forget to bump **Doc Version** when editing docs, or accidentally roll back version numbers. This report synthesizes those suggestions and recommends what to do in the topogen repo.

---

## 1. Consensus from the four suggestions

All four responses agreed on the following:

| Idea | Summary |
|------|--------|
| **Enforce, don’t rely on discipline** | Manual “remember to bump” is unreliable for both humans and AI. Make the rule checkable (CI and/or hooks). |
| **CI check when docs change** | If a file that has a Doc Version header is changed in a PR, require that the `Doc Version:` line also changed in that same PR (and optionally: no decrease, valid format). |
| **Pre-commit hook** | Same logic locally: block commits that touch versioned files but don’t bump (or optionally auto-bump). |
| **Bump tool** | A script or command (e.g. `bump-doc-version README.md patch`) so “bump” is one step, not manual editing. |
| **Single source of truth (optional)** | A manifest (e.g. `docs/versions.toml`) listing each file and its version; CI checks in-file headers match the manifest. |
| **Document the rules** | CONTRIBUTING.md and/or DEVELOPER.md: “Never decrease Doc Version”, “Any PR that changes a doc must bump in the same commit”, “If unsure, bump PATCH”. |
| **Predictable location** | Standardize where the version lives (e.g. “Doc Version on line 2” or “in first 15 lines”) so tools and AI can find it reliably. |

Differences were mainly in **how** to enforce (check-only vs auto-bump in hooks) and whether to add a **manifest** or keep versions only in file headers.

---

## 2. Current state in topogen

- **Doc Version** is already defined in **DEVELOPER.md** (Document Versioning section): format `v{major}.{minor}.{patch}`, MAJOR/MINOR/PATCH rules, and workflow (change doc → bump → commit).
- **Many files** carry a File Chain header with `Doc Version: vX.Y.Z`: README, DEVELOPER, CHANGES, TODO, CONTRIBUTING, TESTED, `render.py`, `main.py`, templates, examples, `.gitignore`, etc. Placement varies (line 2–3 in most files; in comments or `{# #}` in code/templates).
- **CONTRIBUTING.md** does **not** yet mention Doc Version; DEVELOPER.md is the only place that spells out the rule.
- **CI** (`.github/workflows/python-package.yml`) runs lint/typecheck only; there is **no** doc-version check.
- **No** pre-commit hook or `pre-commit` config for doc version.
- **No** bump script or manifest file.

So the problem is exactly what the LLMs described: the rule exists on paper (DEVELOPER.md) but nothing enforces it, so AI and humans often forget or revert versions.

---

## 3. Recommended approach for topogen

Aim for **high benefit, low ongoing cost**, and **no magic** (no auto-editing of files in hooks unless you explicitly want it).

### Tier 1 — Do first (high leverage)

1. **CI check: “If a versioned file changed, its Doc Version must change”**
   - **Versioned file**: Any file that contains a `Doc Version:` line in the base branch or in the PR (covers existing and newly versioned files). Only these files are checked; others (e.g. `config.sample.toml`, binaries) do not trigger the rule.
   - In GitHub Actions (e.g. in `python-package.yml` after lint/typecheck):
     - Get files that changed vs base (e.g. `main`) and that have a `Doc Version:` line (anywhere in first ~20 lines; marker can be in `#`, `<!-- -->`, or `{# #}`).
     - For each such file: compare the `Doc Version:` line on base vs HEAD.
     - **Fail** if: (a) file was changed but Doc Version line is identical (no bump); (b) version **decreased** (e.g. v1.2.0 → v1.1.0); (c) `Doc Version:` line was **removed**; (d) line does not match strict format (e.g. `Doc Version:\s*v\d+\.\d+\.\d+` — no suffixes like "TODO" or "v1.0.next").
     - Require **exactly one** `Doc Version:` line per versioned file (no duplicates or commented-out copies).
   - **Same commit**: The version change must appear in the diff for the commit(s) in the PR — i.e. bump and content change in the same commit, not “I’ll bump in a follow-up.”
   - Example CI failure message:
     ```
     Doc Version check failed:
     File: src/topogen/render.py — modified but Doc Version unchanged (v1.0.4).
     Fix: Bump in the same commit, e.g. # Doc Version: v1.0.4 → v1.0.5
     ```
   - This catches every PR that touches versioned files but forgets to bump, including AI-generated ones.

2. **Short, explicit rules in CONTRIBUTING.md**
   - Add a **“Doc Version”** subsection that states:
     - Any change to a file that has a File Chain header with Doc Version must include a Doc Version bump in the **same** commit/PR.
     - **Include the version change in the commit message** (e.g. `README.md: v1.3.4 → v1.3.5` in subject or body; one per file). This gives traceability in `git log` and forces intent at commit time.
     - Never decrease a Doc Version.
     - If unsure, use a PATCH bump.
     - Point to DEVELOPER.md for full rules (MAJOR/MINOR/PATCH).
   - This sets expectations for humans and gives AIs a clear, short rule to follow.

3. **Tighten DEVELOPER.md with “AI-proof” bullets**
   - In the Document Versioning section, add:
     - **“Never decrease Doc Version.”**
     - **“Any PR that changes a versioned doc must include the Doc Version bump in the same commit (version change must appear in the commit diff).”**
     - **“If unsure, bump PATCH.”**
     - **“Do not remove the Doc Version line from a versioned file.”**
     - **“Include the doc version change in the commit message”** — e.g. `<file>: vOLD → vNEW` in subject or body (one per file). Enables `git log --grep 'README.md: v'` and forces version awareness at commit time.
   - Add a **“Commit Messages and Doc Versioning (Mandatory)”** subsection: when it applies, required format (`<file>: vOLD → vNEW`), examples, prohibited (changing versioned file without mentioning bump in message; mentioning bump not in diff; rollback). Verification step for AI: (1) diff shows version change, (2) commit message includes `<file>: vOLD → vNEW`. Enforcement can start normative; CI may enforce later.
   - Optionally add a “Doc Version Rules (copy-paste for automation)” block with these lines.
   - **AI verification**: Add a short note for AI assistants: *“After editing a versioned file, verify the bump appears in the diff: `git diff HEAD -- <file> | grep 'Doc Version:'` should show both the old and new line. If only one line appears, the version was not bumped. Also include the version change in the commit message (e.g. README.md: v1.3.4 → v1.3.5).”*

Together these give **three aligned layers**: (1) **File invariant** — Doc Version must bump, same commit, no decrease (CI-enforced); (2) **Process invariant** — version in diff, one line per file, valid format (CI + docs); (3) **Intent signal** — commit message must name the version change (`<file>: vOLD → vNEW`) so `git log` is searchable and AI declares intent at commit time.

### Tier 2 — Do when you have time

4. **Pre-commit hook (check-only)**
   - Script that: if any staged file contains a `Doc Version:` line and that file’s staged diff touches content other than only that line, then require that the `Doc Version:` line also changed in the staged diff; else exit 1 with a message.
   - Same “no decrease” and “valid format” checks as CI if you want.
   - **Check-only** (no auto-edit) keeps behavior predictable and avoids surprises. Optional: document `git commit --no-verify` for rare overrides.

5. **Bump script**
   - e.g. `tools/bump-doc-version.py` or `topogen-util bump <file> [patch|minor|major]`:
     - Finds the `Doc Version:` line in the given file (in first N lines or via regex).
     - Replaces with next version by patch/minor/major.
     - Optionally appends a line to CHANGES.md (Unreleased) with “Files: <file> (rev vX.Y.Z)”.
     - Suggests including the rev in the commit message (e.g. “README.md: v1.3.4 → v1.3.5”).
   - Reduces manual editing and gives AI a single command to run (“run the bump script for README patch”).

### Tier 3 — Optional

6. **Central manifest (e.g. `docs/versions.toml`)**
   - One file listing each versioned file and its current version. CI (and optionally the pre-commit hook) checks that every in-file `Doc Version:` matches the manifest, and that any changed file has an updated manifest entry.
   - Pros: single place for “current version of everything”; good for AI and scripts. Cons: one more thing to update on every doc change; need to keep manifest and headers in sync (CI can enforce that).

7. **Auto-bump in pre-commit**
   - Hook that, when a versioned file is staged and its Doc Version wasn’t bumped, increments PATCH and amends the staged file. Some people prefer this; others dislike hooks that change content. Recommendation: start with **check-only** (Tier 2); add auto-bump only if you explicitly want it.

8. **Conventional Commits → bump level**
   - e.g. `docs(readme):` → require at least PATCH; `feat(developer):` → MINOR. Can be encoded in CI or in the bump script. Nice-to-have, not required for solving “forgot to bump” and “rollback”.

9. **CI enforcement of commit message (optional, later)**
   - If a versioned file changed in a commit, CI can require the commit message (or PR body) to contain `<file>: vOLD → vNEW` (parse old/new from diff). Start as normative (DEVELOPER.md + CONTRIBUTING.md); add CI check later if desired.

---

## 4. What to avoid

- **Relying only on documentation** without CI or a hook — that’s the current situation and it’s why the issue keeps happening.
- **Only a pre-commit hook** without CI — contributors can bypass with `--no-verify` or use UIs that skip hooks; CI is the hard gate.
- **Auto-bump by default** in hooks without team buy-in — it can surprise people; better to start with “fail the commit and tell them to bump”.

---

## 5. Suggested implementation order

1. Add the **CI check** (Tier 1.1) so that no PR can merge with “doc changed, version not bumped.”
2. Add **CONTRIBUTING.md** and **DEVELOPER.md** bullets (Tier 1.2 and 1.3).
3. Optionally add a **pre-commit check** (Tier 2) and a **bump script** (Tier 2) when convenient.
4. Consider a **manifest** (Tier 3) only if you want a single source of truth for tooling or AI.

---

## 6. Summary

- **Root cause**: Doc Version is documented but not enforced, so both AI and humans forget or revert it; commit messages often omit version changes, so history is not searchable.
- **Fix**: Enforce in **CI** (“if versioned file changed, Doc Version must change; no decrease; valid format”), plus **short, explicit rules** in CONTRIBUTING and DEVELOPER, including **commit message must include version change** (`<file>: vOLD → vNEW`). Optionally add a **check-only pre-commit** and a **bump script**.
- **Three layers**: (1) File invariant — bump in same commit (CI); (2) Process invariant — no decrease, one line, valid format (CI + docs); (3) Intent signal — version in commit message (docs now; CI-enforceable later).
- **Result**: “AI never bumps” and “AI rolls back version” are caught before merge; `git log --grep 'README.md: v'` works; AI is onboarded to declare version at commit time.

If you want, the next step is to add the CI job/step and the CONTRIBUTING/DEVELOPER wording to the repo (I can propose exact patches).

---

## 7. Refinements from review (optional but high-value)

These additions came from follow-up LLM review of this report; they close loopholes and align with topogen’s setup.

- **Define “versioned file” explicitly** (see Tier 1.1 above): “Any file that contains a `Doc Version:` line in base or in the PR.” Only those files are checked; others (e.g. `config.sample.toml`, binaries) do not trigger the rule.
- **Forbid removing the line**: CI fails if a `Doc Version:` line is removed from an existing versioned file (prevents bypass by deleting the header).
- **One line per file**: Versioned files must have exactly one `Doc Version:` line (no duplicates or commented copies).
- **Strict format**: Enforce via regex (e.g. `Doc Version:\s*v\d+\.\d+\.\d+`); no suffixes, prefixes, or placeholders like `v1.0.next` or `TODO`.
- **Same-commit clarification**: The version change must appear in the **commit diff** for the commit that changes the doc (not a separate follow-up commit in the same PR).
- **CI implementation detail**: Detection should work across comment styles — `#` (Python, TOML), `<!-- -->` (Markdown), `{# #}` (Jinja2). Use a flexible grep (e.g. `grep -oP 'Doc Version:\s*v\K\d+\.\d+\.\d+'` or equivalent) over the first N lines of each file.
- **Bump script (Tier 2)**: If you add a bump script, make it Conventional-Commit aware (e.g. `docs:` → default patch, `feat:` → default minor) to match CONTRIBUTING.md.
- **Smoke test**: After implementing CI, document in DEVELOPER.md: “To verify: change a versioned file without bumping, push a PR — CI should fail; then bump and re-push — CI should pass.”
- **Before enabling CI**: Do a one-time pass: ensure every file that has a `Doc Version:` header is internally consistent (e.g. CHANGES.md and file headers agree). Fix any existing violations so CI starts from a clean slate.
