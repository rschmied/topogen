# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-10
#
# - Called by: Developers/CI via pytest -m cml2_terraform (TOPOGEN_CML2_TERRAFORM_PLAN=1)
# - Reads from: tests/offline_flag_matrix.py, src/topogen/main.py, terraform CLI
# - Writes to: Short-path temporary directories only
# - Calls into: topogen.main.main, terraform init/plan
#
# Purpose: Contract-test generated CML2 workspaces via terraform plan (40-case matrix).
# Blast Radius: Test-only; no runtime behavior changes.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from offline_flag_matrix import (  # pylint: disable=wrong-import-position
    CML2_OFFLINE_MATRIX,
    CML2_SCAFFOLD_FILES,
    SECRET_FORBIDDEN_IN_TF,
    OfflineFlagCase as Cml2OfflineCase,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position


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


def short_temp_base() -> Path:
    if sys.platform == "win32":
        for candidate in (Path("C:/t"), Path("C:/tmp")):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue
    return Path(tempfile.gettempdir())


def _run_topogen(argv: list[str]) -> int:
    with patch.object(sys, "argv", ["topogen", *argv]):
        return main()


def _assert_plan_output(combined: str) -> None:
    for pattern in FAIL_PATTERNS:
        match = pattern.search(combined)
        assert match is None, f"terraform plan failure pattern {pattern.pattern!r}: {match.group(0)}"
    assert PLAN_ADD_RE.search(combined), f"expected 'Plan: N to add' in output:\n{combined[-4000:]}"
    assert "cml2_lifecycle.lab" in combined, (
        f"expected cml2_lifecycle.lab in plan output:\n{combined[-4000:]}"
    )


def _assert_generation_artifacts(case: Cml2OfflineCase, lab_root: Path) -> None:
    yaml_path = lab_root / f"{case.case_id}.yaml"
    cml2_root = lab_root / "cml2"
    nac_root = lab_root / "nac"

    assert yaml_path.is_file(), f"missing YAML for {case.case_id}"
    for name in CML2_SCAFFOLD_FILES:
        assert (cml2_root / name).is_file(), f"missing cml2/{name} for {case.case_id}"

    if case.with_nac:
        assert nac_root.is_dir(), f"expected nac/ for {case.case_id}"
        assert (nac_root / "nac.yaml").is_file()
    else:
        assert not nac_root.exists(), f"unexpected nac/ for {case.case_id}"

    yaml_text = yaml_path.read_text(encoding="utf-8")
    # --cml2 is a CLI alias for --terraform-cml2; provenance records the canonical flag.
    assert "--terraform-cml2" in yaml_text, (
        f"expected --terraform-cml2 in provenance for {case.case_id}"
    )

    for tf_file in cml2_root.glob("*.tf"):
        content = tf_file.read_text(encoding="utf-8")
        lowered = content.lower()
        for forbidden in SECRET_FORBIDDEN_IN_TF:
            assert forbidden not in lowered, (
                f"forbidden pattern {forbidden!r} in {tf_file.name} for {case.case_id}"
            )


def _terraform_run(
    cml2_dir: Path,
    args: list[str],
    *,
    env: dict[str, str],
    terraform_binary: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [terraform_binary, *args],
        cwd=cml2_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def terraform_binary() -> str:
    path = shutil.which("terraform")
    if not path:
        pytest.skip("terraform binary not found on PATH")
    return path


@pytest.fixture(scope="session")
def tf_plugin_cache_dir() -> Path:
    cache = short_temp_base() / "topogen-cml2-tf-plugin-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


@pytest.mark.cml2_terraform
@pytest.mark.parametrize("case", CML2_OFFLINE_MATRIX, ids=lambda item: item.case_id)
def test_cml2_workspace_terraform_plan(
    case: Cml2OfflineCase,
    terraform_binary: str,
    tf_plugin_cache_dir: Path,
) -> None:
    work_root = Path(tempfile.mkdtemp(dir=str(short_temp_base()), prefix="cml2-matrix-"))
    try:
        out_yaml = work_root / f"{case.case_id}.yaml"
        rc = _run_topogen(case.topogen_argv(str(out_yaml)))
        assert rc == 0, f"topogen failed for {case.case_id}"

        lab_root = work_root / case.case_id
        _assert_generation_artifacts(case, lab_root)

        cml2_dir = lab_root / "cml2"
        env = os.environ.copy()
        env["TF_PLUGIN_CACHE_DIR"] = str(tf_plugin_cache_dir)

        init = _terraform_run(
            cml2_dir,
            ["init", "-input=false", "-no-color"],
            env=env,
            terraform_binary=terraform_binary,
        )
        init_out = init.stdout + init.stderr
        assert init.returncode == 0, f"terraform init failed for {case.case_id}:\n{init_out}"

        plan = _terraform_run(
            cml2_dir,
            ["plan", "-input=false", "-no-color", *CML2_PLAN_VARS],
            env=env,
            terraform_binary=terraform_binary,
        )
        plan_out = plan.stdout + plan.stderr
        assert plan.returncode == 0, f"terraform plan failed for {case.case_id}:\n{plan_out}"
        _assert_plan_output(plan_out)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
