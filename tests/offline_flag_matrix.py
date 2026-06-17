# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-10
#
# - Called by: scripts/generate-offline-flag-matrix.py, scripts/validate-offline-flag-matrix.py
# - Reads from: None
# - Writes to: None
#
# Purpose: 1000+ case offline YAML flag matrix (guardrail-aware cross-product).
# Blast Radius: Test/automation only.

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

MODES = ("simple", "nx", "flat", "flat-pair", "dmvpn")
DEVICES = ("iosv", "csr1000v")
NODE_COUNT = "4"

CML2_OPTIONS = (
    ("no-cml2", ()),
    ("cml2", ("--cml2",)),
    ("terraform-cml2", ("--terraform-cml2",)),
)

NAC_OPTIONS = (
    ("no-nac", False),
    ("nac", True),
)

INTENT_OPTIONS = (
    ("no-spot", False),
    ("intent-spot", True),
)

CML_VERSIONS = ("0.3.0", "0.3.1")

MGMT_OPTIONS = (
    ("no-mgmt", ()),
    ("mgmt", ("--mgmt",)),
    ("mgmt-bridge", ("--mgmt", "--mgmt-bridge")),
)

# Mutually-scoped offline feature profiles (not a full cross-product of every flag).
EXTRA_PROFILES = (
    ("base", ()),
    ("archive", ("--archive",)),
    ("vrf", ("--vrf",)),
    ("pki", ("--pki",)),
    ("pki-no-staging", ("--pki", "--no-staging")),
    ("bootstrap", ("--bootstrap",)),
    ("blank", ("--blank",)),
    ("print-up", ("--print-up-cmd",)),
)

CML2_SCAFFOLD_FILES = ("main.tf", "versions.tf", "variables.tf", "outputs.tf", ".gitignore")
NAC_FILES = ("nac.yaml", "main.tf")


@dataclass(frozen=True)
class OfflineFlagCase:
    case_id: str
    mode: str
    device: str
    cml2_label: str
    cml2_args: tuple[str, ...]
    with_nac: bool
    intent_spot: bool
    cml_version: str
    mgmt_label: str
    mgmt_args: tuple[str, ...]
    extra_label: str
    extra_args: tuple[str, ...]

    def topogen_argv(self, offline_yaml: str) -> list[str]:
        argv: list[str] = [
            NODE_COUNT,
            "-m",
            self.mode,
            "--device-template",
            self.device,
            *self.cml2_args,
            "--cml-version",
            self.cml_version,
            "--overwrite",
            "-q",
            "--offline-yaml",
            offline_yaml,
            *self.mgmt_args,
            *self.extra_args,
        ]
        if self.with_nac:
            argv.insert(argv.index("--cml-version"), "--nac")
        if self.intent_spot:
            argv.insert(argv.index("--cml-version"), "--intent-spot")
        if self.mode == "dmvpn":
            insert_at = argv.index("--cml-version")
            argv[insert_at:insert_at] = ["--dmvpn-hubs", "1"]
        return argv


def _mgmt_has_oob(mgmt_args: tuple[str, ...]) -> bool:
    return "--mgmt" in mgmt_args


def is_valid_offline_case(
    *,
    mode: str,
    with_nac: bool,
    cml_version: str,
    mgmt_args: tuple[str, ...],
    extra_args: tuple[str, ...],
) -> bool:
    """Mirror topogen offline guardrails from main.py (subset for matrix pruning)."""
    has_blank = "--blank" in extra_args
    has_bootstrap = "--bootstrap" in extra_args
    has_pki = "--pki" in extra_args
    has_vrf = "--vrf" in extra_args
    has_archive = "--archive" in extra_args
    has_mgmt = _mgmt_has_oob(mgmt_args)

    if has_blank and with_nac:
        return False
    if has_blank and mode == "dmvpn":
        return False
    if has_bootstrap:
        if not with_nac or not has_mgmt or has_blank or has_pki:
            return False
    if "--mgmt-bridge" in mgmt_args and not has_mgmt:
        return False
    if has_vrf and mode != "flat-pair":
        return False
    if has_archive and mode not in ("flat", "flat-pair"):
        return False
    if has_pki and mode not in ("flat", "flat-pair", "dmvpn"):
        return False
    if has_pki and cml_version != "0.3.1":
        return False
    if mode == "dmvpn" and has_pki and with_nac:
        # DMVPN+PKI offline NaC projection is a known gap; keep matrix to YAML/scaffold coverage.
        pass
    return True


def _case_id(
    mode: str,
    device: str,
    cml2_label: str,
    nac_label: str,
    intent_label: str,
    cml_version: str,
    mgmt_label: str,
    extra_label: str,
) -> str:
    cv = cml_version.replace(".", "")
    return f"{mode}-{NODE_COUNT}-{device}-cv{cv}-{cml2_label}-{nac_label}-{intent_label}-{mgmt_label}-{extra_label}"


def build_offline_flag_matrix() -> tuple[OfflineFlagCase, ...]:
    cases: list[OfflineFlagCase] = []
    for mode in MODES:
        for device in DEVICES:
            for cml2_label, cml2_args in CML2_OPTIONS:
                for nac_label, with_nac in NAC_OPTIONS:
                    for intent_label, intent_spot in INTENT_OPTIONS:
                        for cml_version in CML_VERSIONS:
                            for mgmt_label, mgmt_args in MGMT_OPTIONS:
                                for extra_label, extra_args in EXTRA_PROFILES:
                                    if not is_valid_offline_case(
                                        mode=mode,
                                        with_nac=with_nac,
                                        cml_version=cml_version,
                                        mgmt_args=mgmt_args,
                                        extra_args=extra_args,
                                    ):
                                        continue
                                    case_id = _case_id(
                                        mode,
                                        device,
                                        cml2_label,
                                        nac_label,
                                        intent_label,
                                        cml_version,
                                        mgmt_label,
                                        extra_label,
                                    )
                                    cases.append(
                                        OfflineFlagCase(
                                            case_id=case_id,
                                            mode=mode,
                                            device=device,
                                            cml2_label=cml2_label,
                                            cml2_args=cml2_args,
                                            with_nac=with_nac,
                                            intent_spot=intent_spot,
                                            cml_version=cml_version,
                                            mgmt_label=mgmt_label,
                                            mgmt_args=mgmt_args,
                                            extra_label=extra_label,
                                            extra_args=extra_args,
                                        )
                                    )
    return tuple(cases)


OFFLINE_FLAG_MATRIX: tuple[OfflineFlagCase, ...] = build_offline_flag_matrix()

# Subset used by earlier CML2-only scripts (40 cases).
CML2_OFFLINE_MATRIX = tuple(
    case
    for case in OFFLINE_FLAG_MATRIX
    if case.cml_version == "0.3.1"
    and case.mgmt_label == "no-mgmt"
    and case.extra_label == "base"
    and case.intent_spot is False
    and case.cml2_label in ("cml2", "terraform-cml2")
)


def matrix_summary(cases: Iterable[OfflineFlagCase] = OFFLINE_FLAG_MATRIX) -> dict[str, int]:
    items = list(cases)
    return {
        "total_cases": len(items),
        "modes": len(MODES),
        "devices": len(DEVICES),
        "cml2_options": len(CML2_OPTIONS),
        "nac_options": len(NAC_OPTIONS),
        "intent_options": len(INTENT_OPTIONS),
        "cml_versions": len(CML_VERSIONS),
        "mgmt_options": len(MGMT_OPTIONS),
        "extra_profiles": len(EXTRA_PROFILES),
    }


SECRET_FORBIDDEN_IN_TF = ("admin", "cisco123", "10.", "172.", "192.168.")
