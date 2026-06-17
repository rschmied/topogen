#!/usr/bin/env python3
"""Sync NaC mgmt hosts from live CML bridge DHCP addresses on OOB Gi."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.nac_mgmt_sync import main  # noqa: E402


def _argv_with_dhcp_mode() -> list[str]:
    argv = list(sys.argv[1:])
    if not any(arg == "--mode" or arg.startswith("--mode=") for arg in argv):
        argv = ["--mode", "dhcp", *argv]
    return argv


if __name__ == "__main__":
    raise SystemExit(main(_argv_with_dhcp_mode()))
