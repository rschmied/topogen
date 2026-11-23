# Testing

TopoGen currently has static checks and build validation, but no automated test
suite. This document describes the current validation commands, the code's
present testability, and a practical plan for adding tests.

## Current validation

Install the locked runtime, optional, and development dependencies:

```bash
make sync
```

Run all static checks:

```bash
make check
```

This runs:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy --check-untyped-def src
```

Build the source distribution and wheel:

```bash
make build
```

There is no `make test` target because the repository has no tests and does not
yet declare `pytest` as a development dependency.

## Testability assessment

The code is moderately testable. Pure configuration and rendering helpers can
be tested directly. The main `Renderer` orchestration is tightly coupled to a
live CML controller and requires mocks or a small design change.

### Directly testable code

The following code is deterministic or mostly free of external side effects:

- `valid_node_count()`
- `get_log_level()`
- `CoordsGenerator`
- `Config.load()` and `Config.save()`
- `frr_bootconfig()`
- `dnshostconfig()`
- Jinja templates
- `get_templates()`
- `order_iface_pair()`
- interface-description formatting
- DNS-entry formatting
- argument-parser defaults and validation

Tests for these functions can run without a CML controller.

### Code that is harder to test

`Renderer` creates external resources during initialization. Its constructor:

1. loads a template;
2. initializes `ClientLibrary`;
3. checks CML controller readiness; and
4. creates a CML lab.

This makes isolated tests for address allocation and graph generation dependent
on CML API mocks.

The two rendering methods also combine several responsibilities:

- topology generation;
- address allocation;
- CML node and interface creation;
- link creation;
- device configuration rendering;
- DNS generation; and
- progress reporting.

These methods can be tested with extensive mocks, but such tests are likely to
be brittle.

## Recommended test seam

The smallest useful design change is to allow injection of the CML client:

```python
class Renderer:
    def __init__(
        self,
        args: Namespace,
        cfg: Config,
        client: ClientLibrary | None = None,
    ):
        self.client = client or self.initialize_client()
```

A test could then provide a fake client and lab without network access.

A later refactor should separate the workflow into three layers:

```text
Topology plan generation
        ↓
Configuration rendering
        ↓
CML API application
```

Topology planning and configuration rendering would then use normal unit tests.
Only the CML API application layer would require mocks or live integration
tests.

## Recommended initial test suite

A focused initial suite should cover the following behavior:

1. configuration defaults;
2. TOML configuration save/load round trips;
3. valid node-count boundaries;
4. invalid node-count errors;
5. log-level mapping;
6. coordinate-generator sequences;
7. template discovery;
8. missing-template errors;
9. FRR `boot.sh` rendering;
10. FRR native configuration rendering;
11. FRR provisioning filenames and daemon list;
12. IOSv template rendering;
13. IOL-XE template rendering;
14. DNS host configuration rendering;
15. interface-pair ordering;
16. interface-description formatting;
17. DNS-name normalization;
18. point-to-point subnet allocation;
19. CML client failure mapping with mocks; and
20. simple topology rendering with a fake lab.

Approximately 15 to 25 focused tests should cover most pure logic and the main
failure-prone boundaries.

## Test levels

### Unit tests

Unit tests should not contact a CML controller. They should cover models,
configuration, templates, formatting helpers, and topology planning.

### Mocked integration tests

Mocked integration tests should exercise `Renderer` with fake client, lab, node,
interface, and link objects. They should verify the calls and generated
configuration payloads sent to CML.

### Live integration tests

Live tests should be optional and explicitly enabled. They should use a
disposable CML lab and must not run in normal CI.

Potential live checks include:

- create a two-node topology;
- verify expected node-definition IDs;
- verify provisioned configuration filenames;
- start nodes only when explicitly requested;
- verify node boot state and basic connectivity; and
- delete the disposable lab during cleanup.

Credentials and controller URLs must come from environment variables or a
secret store. They must never be committed.

## Adding pytest

When the first tests are added, add `pytest` to the development dependency
group:

```bash
uv add --dev pytest
```

Then add this Makefile target:

```make
test: ## Run unit tests
	$(UV) run pytest
```

Include it in the aggregate check target:

```make
check: lint format-check typecheck test
```

CI should run unit tests on every supported Python version. Live integration
tests should use a separate manually triggered workflow or an explicitly
protected environment.
