<!--
File Chain (see DEVELOPER.md):
Doc Version: v1.1.1
Date Modified: 2026-02-16

- Called by: Contributors (developers, AI assistants), GitHub PR reviewers, project maintainers
- Reads from: Project conventions, team decisions, best practices
- Writes to: None (documentation only, but enforces contribution standards)
- Calls into: References DEVELOPER.md, README.md for context

Purpose: Contribution guidelines for branching, commits, PRs, and code standards.
         Ensures consistency across contributions from humans and AI assistants.

Blast Radius: None (documentation only, but enforces workflow and quality standards)
-->

# Contributing to Topogen

Thanks for contributing! This document describes how to propose changes and the repository's working conventions.

## Branching strategy
- Create a feature branch from the default branch (main):
  - feature/<short-topic>
  - bugfix/<short-topic>
  - refactor/<short-topic>
- Keep branches focused and short-lived. Rebase regularly on main to avoid drift.

## Merge policy
- Default: Squash merge PRs into main.
  - Rationale: clean history (one commit per PR), simpler revert, easier bisect.
- Exceptions (must be called out in the PR):
  - Rebase-merge when you need to preserve a carefully crafted commit series (e.g., large refactors, bisectable steps).
  - Merge commit for coordinated integration/release branches.

## Commit messages
- Use Conventional Commits where practical
  - feat: add multi-hub DMVPN config generation
  - fix: correct flat mode port guard for access/core
  - refactor: split renderer responsibilities
  - docs: add README usage examples
  - chore: bump dependencies / tooling
- Keep the first line ≤ 72 chars; include context in the body if needed.
- **Doc Version**: If you change a file that has a File Chain header with Doc Version, include the version change in the commit message (e.g. `README.md: v1.3.4 → v1.3.5` in subject or body; one per file). See DEVELOPER.md → Commit Messages and Doc Versioning.

## Pull requests
- One logical change per PR. If it’s large, consider splitting into stacked PRs.
- Include:
  - What/why: problem statement, approach, alternatives considered.
  - Scope of impact: flags, templates, data model, compatibility.
  - Testing notes: how you validated locally; any edge cases.
- Keep the PR title suitable for the squash commit message.

## CI and quality gates
- CI runs on push for multiple Python versions. Make sure it’s green locally before opening a PR.
- Lint/type check locally (matches CI):
  - uv run ruff check
  - uv run mypy --check-untyped-def src
- Style/formatting should satisfy ruff; types should be reasonable for public APIs.

## Testing
- Add or update tests when fixing bugs or adding features (where applicable).
- Prefer small, focused tests over broad end-to-end when possible.

## Releases
- Releases are built from tags via GitHub Actions.
- Coordinate version bumps and changelog updates in PRs that are intended for release.

## Security
- Do not include secrets in code, configs, or CI.
- Report suspected vulnerabilities privately if applicable.

## Communication
- Be respectful and constructive.
- Prefer discussion in PRs for design tradeoffs; summarize decisions in the description.
