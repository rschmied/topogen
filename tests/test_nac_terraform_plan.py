# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-08
#
# - Called by: Developers/CI via pytest -m terraform (TG-161)
# - Reads from: src/topogen/main.py offline renderer, terraform CLI
# - Writes to: Short-path temporary directories only
# - Calls into: topogen.main.main, terraform init/plan
#
# Purpose: Contract-test generated NaC workspaces against netascode/nac-iosxe via terraform plan.
# Blast Radius: Test-only; no runtime behavior changes.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

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

DUMMY_IOSXE_ENV = {
    "IOSXE_USERNAME": "lab",
    "IOSXE_PASSWORD": "lab",
    "IOSXE_URL": "https://127.0.0.1",
}


@dataclass(frozen=True)
class NacTerraformCase:
    case_id: str
    argv: tuple[str, ...]
    plan_must_match: tuple[str, ...] = ()


NAC_TERRAFORM_MATRIX: tuple[NacTerraformCase, ...] = (
    NacTerraformCase("flat-iosv", ("2", "--mode", "flat")),
    NacTerraformCase("flat-pair-iosv", ("2", "--mode", "flat-pair")),
    NacTerraformCase(
        "dmvpn-flat-iosv",
        ("3", "--mode", "dmvpn", "--dmvpn-hubs", "1"),
        (
            "iosxe_interface_tunnel.tunnel",
            "tunnel_source",
            "ip_redirects",
        ),
    ),
    NacTerraformCase(
        "dmvpn-flat-pair-iosv",
        (
            "4",
            "--mode",
            "dmvpn",
            "--dmvpn-underlay",
            "flat-pair",
            "--template",
            "iosv-dmvpn",
        ),
        (
            "iosxe_interface_tunnel.tunnel",
            "tunnel_source",
        ),
    ),
    NacTerraformCase(
        "flat-csr",
        ("2", "--mode", "flat", "-T", "csr-ospf", "--device-template", "csr1000v"),
    ),
    NacTerraformCase(
        "flat-pair-csr",
        ("2", "--mode", "flat-pair", "-T", "csr-ospf", "--device-template", "csr1000v"),
    ),
    NacTerraformCase(
        "dmvpn-flat-csr",
        (
            "3",
            "--mode",
            "dmvpn",
            "--dmvpn-hubs",
            "1",
            "-T",
            "csr-ospf",
            "--device-template",
            "csr1000v",
        ),
        (
            "iosxe_interface_tunnel.tunnel",
            'tunnel_source     = "GigabitEthernet1"',
        ),
    ),
    NacTerraformCase(
        "dmvpn-flat-pair-csr",
        (
            "4",
            "--mode",
            "dmvpn",
            "--dmvpn-underlay",
            "flat-pair",
            "--template",
            "csr-dmvpn",
            "--device-template",
            "csr1000v",
        ),
        (
            "iosxe_interface_tunnel.tunnel",
            'tunnel_source     = "GigabitEthernet1"',
        ),
    ),
    NacTerraformCase(
        "dmvpn-flat-psk-iosv",
        (
            "3",
            "--mode",
            "dmvpn",
            "--dmvpn-hubs",
            "1",
            "--dmvpn-security",
            "ikev2-psk",
            "--dmvpn-psk",
            "lab-psk-test",
        ),
        (
            "iosxe_interface_tunnel.tunnel",
            "tunnel_protection_ipsec_profile",
            "iosxe_crypto_ikev2_proposal.crypto_ikev2_proposal",
            "iosxe_crypto_ipsec_profile.crypto_ipsec_profile",
        ),
    ),
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


def _assert_plan_output(combined: str, *, required_patterns: tuple[str, ...] = ()) -> None:
    for pattern in FAIL_PATTERNS:
        match = pattern.search(combined)
        assert match is None, f"terraform plan failure pattern {pattern.pattern!r}: {match.group(0)}"
    assert PLAN_ADD_RE.search(combined), f"expected 'Plan: N to add' in output:\n{combined[-4000:]}"
    for snippet in required_patterns:
        assert snippet in combined, (
            f"expected terraform plan output to include {snippet!r}:\n{combined[-4000:]}"
        )


def _terraform_run(
    nac_dir: Path,
    args: list[str],
    *,
    env: dict[str, str],
    terraform_binary: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [terraform_binary, *args],
        cwd=nac_dir,
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
    cache = short_temp_base() / "topogen-tf-plugin-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


@pytest.mark.terraform
@pytest.mark.parametrize("case", NAC_TERRAFORM_MATRIX, ids=lambda item: item.case_id)
def test_nac_workspace_terraform_plan(
    case: NacTerraformCase,
    terraform_binary: str,
    tf_plugin_cache_dir: Path,
) -> None:
    work_root = Path(tempfile.mkdtemp(dir=str(short_temp_base()), prefix="tg161-"))
    try:
        lab_name = case.case_id
        out_yaml = work_root / f"{lab_name}.yaml"
        argv = [
            *case.argv,
            "--offline-yaml",
            str(out_yaml),
            "--nac",
            "--overwrite",
        ]
        rc = _run_topogen(argv)
        assert rc == 0, f"topogen failed for {case.case_id}"

        nac_dir = work_root / lab_name / "nac"
        assert (nac_dir / "main.tf").is_file(), f"missing terraform scaffold for {case.case_id}"
        assert (nac_dir / "nac.yaml").is_file(), f"missing nac.yaml for {case.case_id}"

        env = os.environ.copy()
        env.update(DUMMY_IOSXE_ENV)
        env["TF_PLUGIN_CACHE_DIR"] = str(tf_plugin_cache_dir)

        init = _terraform_run(
            nac_dir,
            ["init", "-input=false", "-no-color"],
            env=env,
            terraform_binary=terraform_binary,
        )
        init_out = init.stdout + init.stderr
        assert init.returncode == 0, f"terraform init failed for {case.case_id}:\n{init_out}"

        plan = _terraform_run(
            nac_dir,
            ["plan", "-input=false", "-no-color"],
            env=env,
            terraform_binary=terraform_binary,
        )
        plan_out = plan.stdout + plan.stderr
        assert plan.returncode == 0, f"terraform plan failed for {case.case_id}:\n{plan_out}"
        _assert_plan_output(plan_out, required_patterns=case.plan_must_match)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
