# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-13
#
# Purpose: TG-195 CML matrix — direct import, CML2 terraform, NaC / NaC+bootstrap.
# Blast Radius: Test/automation only.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CaseKind = Literal["import", "cml2", "generate_fail", "import_fail", "cml2_generate_fail"]


@dataclass(frozen=True)
class Tg195CmlCase:
    case_id: str
    kind: CaseKind
    matrix_ids: tuple[str, ...]
    description: str
    topogen_argv: tuple[str, ...] = ()
    stub_yaml_text: str | None = None
    expect_stderr: tuple[str, ...] = ()
    with_nac: bool = False
    with_bootstrap: bool = False

    def lab_title(self) -> str:
        return f"TG195-{self.case_id}"


_IOSV_BASE: tuple[str, ...] = (
    "2",
    "--mode",
    "flat",
    "-T",
    "iosv",
    "--device-template",
    "iosv",
    "--mgmt",
    "--mgmt-vrf",
    "Mgmt-vrf",
    "--cml-server",
    "2.10",
    "--overwrite",
    "-q",
)

_CSR_BASE: tuple[str, ...] = (
    "2",
    "--mode",
    "flat",
    "-T",
    "csr1000v",
    "--device-template",
    "csr1000v",
    "--mgmt",
    "--mgmt-vrf",
    "Mgmt-vrf",
    "--cml-server",
    "2.10",
    "--overwrite",
    "-q",
)

_STATIC_FD80: tuple[str, ...] = (
    *_IOSV_BASE,
    "--mgmt-ipv6-static",
    "--mgmt-ipv6-cidr",
    "fd80::/64",
)

_STATIC_FD80_LL: tuple[str, ...] = (
    *_IOSV_BASE,
    "--mgmt-ipv6-static",
    "--mgmt-ipv6-static-link-local",
    "--mgmt-ipv6-cidr",
    "fd80::/64",
)


def _static_fd80(*extra: str) -> tuple[str, ...]:
    return (*_STATIC_FD80, *extra)


def _cml2(*argv: str) -> tuple[str, ...]:
    return (*argv, "--terraform-cml2")


TG195_CML_MATRIX: tuple[Tg195CmlCase, ...] = (
    # --- Positive: generate + CML direct import (--insecure --import) ---
    Tg195CmlCase(
        "P01",
        "import",
        ("P01", "R01", "R02", "R07", "R11", "U01", "U02"),
        "IOSv static global fd80::/64",
        _static_fd80(),
    ),
    Tg195CmlCase(
        "P02",
        "import",
        ("P02", "R05", "U05", "U06"),
        "IOSv static doc prefix + link-local",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "2001:db8:1:2::/64",
            "--mgmt-ipv6-static-link-local",
        ),
    ),
    Tg195CmlCase(
        "P03",
        "import",
        ("P03", "R10"),
        "IOSv SLAAC + cidr metadata only (regression)",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-slaac",
            "--mgmt-ipv6-cidr",
            "fd00:10:254::/64",
        ),
    ),
    Tg195CmlCase(
        "P04",
        "import",
        ("P04", "R03", "U03"),
        "IOSv static 2001:db8:1:2::/64",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "2001:db8:1:2::/64",
        ),
    ),
    Tg195CmlCase(
        "R04",
        "import",
        ("R04",),
        "CSR static global fd80::/64",
        (
            *_CSR_BASE,
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "fd80::/64",
        ),
    ),
    Tg195CmlCase(
        "R06",
        "import",
        ("R06", "U07"),
        "IOSv loopback-255 + static link-local",
        (
            *_IOSV_BASE,
            "--loopback-255",
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "fd80::/64",
            "--mgmt-ipv6-static-link-local",
        ),
    ),
    Tg195CmlCase(
        "NAC",
        "import",
        ("NAC01", "NAC02", "NAC03", "NAC04", "NAC05"),
        "IOSv static + NaC inventory (no bootstrap)",
        (
            *_STATIC_FD80_LL,
            "--nac",
        ),
        with_nac=True,
    ),
    Tg195CmlCase(
        "NAC-BOOT",
        "import",
        ("R08", "R09"),
        "IOSv static + NaC + bootstrap (day-0 thin config)",
        (
            *_STATIC_FD80_LL,
            "--nac",
            "--bootstrap",
        ),
        with_nac=True,
        with_bootstrap=True,
    ),
    Tg195CmlCase(
        "R12",
        "import",
        ("R12",),
        "Provenance records static flags",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "2001:db8:1:2::/64",
            "--mgmt-ipv6-static-link-local",
        ),
    ),
    # --- Positive: CML2 terraform apply (no --import) ---
    Tg195CmlCase(
        "CML2",
        "cml2",
        ("cml2-static",),
        "IOSv static + --terraform-cml2 (terraform apply)",
        _cml2(*_STATIC_FD80),
    ),
    Tg195CmlCase(
        "CML2-NAC",
        "cml2",
        ("cml2-nac",),
        "IOSv static + NaC + --terraform-cml2",
        _cml2(*_STATIC_FD80_LL, "--nac"),
        with_nac=True,
    ),
    Tg195CmlCase(
        "CML2-NAC-BOOT",
        "cml2",
        ("cml2-nac-bootstrap",),
        "IOSv static + NaC + bootstrap + --terraform-cml2",
        _cml2(*_STATIC_FD80_LL, "--nac", "--bootstrap"),
        with_nac=True,
        with_bootstrap=True,
    ),
    # --- Negative: CLI must fail (still pass --import --insecure to prove no upload) ---
    Tg195CmlCase(
        "N01",
        "generate_fail",
        ("N01",),
        "static without --mgmt",
        (
            "2",
            "--mode",
            "flat",
            "-T",
            "iosv",
            "--device-template",
            "iosv",
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "fd80::/64",
            "--cml-server",
            "2.10",
            "--overwrite",
            "-q",
        ),
        expect_stderr=("IPv6 OOB", "require --mgmt"),
    ),
    Tg195CmlCase(
        "N03",
        "generate_fail",
        ("N03",),
        "static with --mgmt-vrf global",
        (
            *_IOSV_BASE,
            "--mgmt-vrf",
            "global",
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "fd80::/64",
        ),
        expect_stderr=("named --mgmt-vrf",),
    ),
    Tg195CmlCase(
        "N04",
        "generate_fail",
        ("N04",),
        "static without --mgmt-ipv6-cidr",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static",
        ),
        expect_stderr=("--mgmt-ipv6-cidr",),
    ),
    Tg195CmlCase(
        "N05",
        "generate_fail",
        ("N05",),
        "static with invalid cidr",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "not-an-address",
        ),
        expect_stderr=("Invalid --mgmt-ipv6-cidr",),
    ),
    Tg195CmlCase(
        "N06",
        "generate_fail",
        ("N06",),
        "link-local without static",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static-link-local",
        ),
        expect_stderr=("IPv6 OOB mode",),
    ),
    Tg195CmlCase(
        "N07",
        "generate_fail",
        ("N07",),
        "static + slaac",
        _static_fd80("--mgmt-ipv6-slaac"),
        expect_stderr=("mutually exclusive", "conflicts"),
    ),
    Tg195CmlCase(
        "N08",
        "generate_fail",
        ("N08",),
        "static + dhcp",
        _static_fd80("--mgmt-ipv6-dhcp"),
        expect_stderr=("mutually exclusive", "conflicts"),
    ),
    Tg195CmlCase(
        "N09",
        "generate_fail",
        ("N09",),
        "static + legacy mode slaac",
        _static_fd80("--mgmt-ipv6-mode", "slaac"),
        expect_stderr=("conflicts",),
    ),
    Tg195CmlCase(
        "N10",
        "generate_fail",
        ("N10",),
        "static + legacy mode dhcpv6",
        _static_fd80("--mgmt-ipv6-mode", "dhcpv6"),
        expect_stderr=("conflicts",),
    ),
    Tg195CmlCase(
        "R-N01",
        "generate_fail",
        ("R-N01",),
        "static without cidr at render",
        (
            *_IOSV_BASE,
            "--mgmt-ipv6-static",
        ),
        expect_stderr=("--mgmt-ipv6-cidr",),
    ),
    Tg195CmlCase(
        "R-N02",
        "generate_fail",
        ("R-N02",),
        "static + slaac at render",
        _static_fd80("--mgmt-ipv6-slaac"),
        expect_stderr=("mutually exclusive", "conflicts"),
    ),
    Tg195CmlCase(
        "CML2-N-IMPORT",
        "cml2_generate_fail",
        ("cml2-import-exclusion",),
        "--terraform-cml2 rejects --import",
        _cml2(*_STATIC_FD80),
        expect_stderr=("import workflow flags are not supported",),
    ),
    # --- Negative: CML import must fail (stub YAML) ---
    Tg195CmlCase(
        "IMP-MALFORMED",
        "import_fail",
        ("import-malformed",),
        "Malformed lab YAML rejected by CML API",
        stub_yaml_text="lab:\n  title: TG195-bad\n  version: [\n",
    ),
    Tg195CmlCase(
        "IMP-BADVER",
        "import_fail",
        ("import-bad-version",),
        "Unsupported lab schema version rejected by CML",
        stub_yaml_text=(
            "lab:\n  title: TG195-badver\n  version: '9.9.9'\n"
            "nodes: []\nlinks: []\n"
        ),
    ),
)
