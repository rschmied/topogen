#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-10
#
# Purpose: CML2 offline validation — 40-case matrix with terraform init/plan gates.
# Blast Radius: Validation script only (writes under out/cml2-offline-matrix/).

"""Validate CML2 offline matrix: modes x devices x cml2 flag x nac on/off."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from offline_flag_matrix import (  # noqa: E402
    CML2_OFFLINE_MATRIX,
    CML2_SCAFFOLD_FILES,
    SECRET_FORBIDDEN_IN_TF,
)

ARTIFACT_ROOT = REPO / "out" / "cml2-offline-matrix"

PLAN_ADD_RE = re.compile(r"Plan: \d+ to add, 0 to change, 0 to destroy\.")
FAIL_PATTERNS = (
    re.compile(r"Unsupported attribute", re.IGNORECASE),
    re.compile(r"^Error:", re.MULTILINE),
)

CML2_PLAN_VARS = (
    "-var=address=https://127.0.0.1",
    "-var=skip_verify=true",
    "-var=token=plan-only",
)


def _terraform_binary() -> str | None:
    return shutil.which("terraform")


def _assert_plan_output(combined: str) -> tuple[bool, str]:
    for pattern in FAIL_PATTERNS:
        match = pattern.search(combined)
        if match:
            return False, f"failure pattern {pattern.pattern!r}: {match.group(0)}"
    if not PLAN_ADD_RE.search(combined):
        return False, "missing 'Plan: N to add, 0 to change, 0 to destroy.'"
    if "cml2_lifecycle.lab" not in combined:
        return False, "missing cml2_lifecycle.lab in plan output"
    return True, ""


def main() -> int:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    passed = 0
    terraform = _terraform_binary()
    if not terraform:
        print("ERROR: terraform binary not found on PATH")
        return 1

    env = os.environ.copy()
    cache = env.get("TF_PLUGIN_CACHE_DIR")
    if not cache:
        cache_dir = REPO / "out" / ".tf-plugin-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        env["TF_PLUGIN_CACHE_DIR"] = str(cache_dir)

    def gate(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed.append(name + (f" ({detail})" if detail else ""))
            print(f"[FAIL] {name}" + (f" ({detail})" if detail else ""))

    for case in CML2_OFFLINE_MATRIX:
        lab = case.case_id
        lab_root = ARTIFACT_ROOT / lab
        yaml_path = lab_root / f"{lab}.yaml"
        cml2_root = lab_root / "cml2"
        nac_root = lab_root / "nac"

        cmd = [sys.executable, "-m", "topogen", *case.topogen_argv(str(yaml_path))]
        rc = subprocess.run(cmd, cwd=REPO, check=False).returncode
        gate(f"{lab} generate", rc == 0, f"rc={rc}")

        if not yaml_path.is_file():
            continue

        for name in CML2_SCAFFOLD_FILES:
            gate(f"{lab} cml2/{name}", (cml2_root / name).is_file())

        gate(f"{lab} nac/ rule", nac_root.is_dir() == case.with_nac)
        if case.with_nac:
            gate(f"{lab} nac/nac.yaml", (nac_root / "nac.yaml").is_file())

        yaml_text = yaml_path.read_text(encoding="utf-8")
        gate(f"{lab} provenance", "--terraform-cml2" in yaml_text)

        secret_ok = True
        secret_detail = ""
        for tf_file in cml2_root.glob("*.tf"):
            content = tf_file.read_text(encoding="utf-8").lower()
            for forbidden in SECRET_FORBIDDEN_IN_TF:
                if forbidden in content:
                    secret_ok = False
                    secret_detail = f"{forbidden!r} in {tf_file.name}"
                    break
            if not secret_ok:
                break
        gate(f"{lab} secret-free tf", secret_ok, secret_detail)

        init = subprocess.run(
            [terraform, "init", "-input=false", "-no-color"],
            cwd=cml2_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        init_out = init.stdout + init.stderr
        gate(f"{lab} terraform init", init.returncode == 0, init_out[-500:] if init.returncode else "")

        if init.returncode != 0:
            continue

        plan = subprocess.run(
            [terraform, "plan", "-input=false", "-no-color", *CML2_PLAN_VARS],
            cwd=cml2_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        plan_out = plan.stdout + plan.stderr
        plan_ok, plan_detail = _assert_plan_output(plan_out)
        if plan.returncode != 0:
            plan_ok = False
            plan_detail = plan_out[-500:] or f"rc={plan.returncode}"
        gate(f"{lab} terraform plan", plan_ok, plan_detail)

    print("\n=== Summary ===")
    print(f"Passed gates: {passed}")
    print(f"Failed gates: {len(failed)}")
    print(f"Artifacts: {ARTIFACT_ROOT}")
    if failed:
        for item in failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
