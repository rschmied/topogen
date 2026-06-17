# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-08
#
# - Called by: pytest (tests/test_nac_terraform_plan.py)
# - Reads from: TOPOGEN_TERRAFORM_PLAN env, pytest -m selection
# - Writes to: None
#
# Purpose: Opt-in collection rules for NaC/CML2 terraform plan contract tests.
# Blast Radius: Test-only.

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "terraform: NaC terraform init/plan contract (needs terraform binary + network)",
    )
    config.addinivalue_line(
        "markers",
        "cml2_terraform: CML2 terraform init/plan contract (needs terraform binary + network)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    markexpr = config.getoption("-m", default="")
    run_nac = os.environ.get("TOPOGEN_TERRAFORM_PLAN") == "1"
    run_cml2 = os.environ.get("TOPOGEN_CML2_TERRAFORM_PLAN") == "1"

    skip_nac = pytest.mark.skip(
        reason=(
            "NaC terraform plan gate is opt-in: set TOPOGEN_TERRAFORM_PLAN=1 "
            "or run pytest -m terraform"
        )
    )
    skip_cml2 = pytest.mark.skip(
        reason=(
            "CML2 terraform plan gate is opt-in: set TOPOGEN_CML2_TERRAFORM_PLAN=1 "
            "or run pytest -m cml2_terraform"
        )
    )

    for item in items:
        if "cml2_terraform" in item.keywords:
            if run_cml2 or (markexpr and "cml2_terraform" in markexpr):
                continue
            item.add_marker(skip_cml2)
        elif "terraform" in item.keywords:
            if run_nac or (markexpr and markexpr == "terraform"):
                continue
            item.add_marker(skip_nac)
