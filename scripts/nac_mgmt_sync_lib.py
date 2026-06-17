#!/usr/bin/env python3
"""Backward-compatible shim — use topogen.nac_mgmt_sync instead."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.nac_mgmt_sync import (  # noqa: F401
    ROUTER_NODE_DEFINITIONS,
    canonical_name,
    dump_yaml,
    load_yaml,
    mgmt_interface_name,
    parse_mgmt_ipv6,
    patch_nac_files,
    pick_preferred_global,
)
