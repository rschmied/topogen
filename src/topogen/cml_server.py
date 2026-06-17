# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-13
#
# Purpose: Map operator-facing --cml-server to CML lab YAML schema (--cml-version).
# Blast Radius: src/topogen/main.py, src/topogen/render.py (provenance).

"""CML controller version → lab YAML schema resolution for --cml-server (TG-194)."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

_LOGGER = logging.getLogger(__name__)

# Validated CML release → lab schema version (see DEVELOPER.md).
CML_SERVER_SCHEMA_MAP: dict[tuple[int, int], str] = {
    (2, 5): "0.2.0",
    (2, 6): "0.2.1",
    (2, 7): "0.2.2",
    (2, 8): "0.3.0",
    (2, 9): "0.3.0",
    (2, 10): "0.3.1",
}

HIGHEST_KNOWN_CML_SCHEMA = max(
    CML_SERVER_SCHEMA_MAP.values(),
    key=lambda v: tuple(int(x) for x in v.split(".")),
)


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def _format_server(server: tuple[int, int]) -> str:
    return f"{server[0]}.{server[1]}"


def parse_cml_server(value: str) -> tuple[int, int]:
    """Parse MAJOR.MINOR CML server version from CLI input."""
    parts = value.split(".")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise argparse.ArgumentTypeError(
            f"invalid CML server version {value!r}; expected MAJOR.MINOR (e.g. 2.10)"
        )
    return int(parts[0]), int(parts[1])


def valid_cml_server(value: str) -> str:
    """argparse type: validate and return normalized CML server string."""
    parse_cml_server(value)
    return value


def schema_for_cml_server(server_str: str) -> tuple[str, str | None]:
    """Return (schema_version, optional_info_log_message) for a CML server version."""
    server = parse_cml_server(server_str)
    if server in CML_SERVER_SCHEMA_MAP:
        return CML_SERVER_SCHEMA_MAP[server], None

    sorted_servers = sorted(CML_SERVER_SCHEMA_MAP)
    max_server = sorted_servers[-1]

    if server > max_server:
        return (
            HIGHEST_KNOWN_CML_SCHEMA,
            f"--cml-server {server_str}: no mapping; using highest known schema "
            f"{HIGHEST_KNOWN_CML_SCHEMA}",
        )

    lower = [s for s in sorted_servers if s <= server]
    anchor = max(lower) if lower else sorted_servers[0]
    schema = CML_SERVER_SCHEMA_MAP[anchor]
    return (
        schema,
        f"--cml-server {server_str}: no mapping; using schema from CML "
        f"{_format_server(anchor)} ({schema})",
    )


def resolve_cml_server_version(args: object, argv: Sequence[str] | None = None) -> None:
    """Apply --cml-server schema default when --cml-version was not passed explicitly."""
    server = getattr(args, "cml_server", None)
    if not server:
        return

    if argv is None:
        argv = sys.argv

    if "--cml-version" in argv:
        return

    schema, log_msg = schema_for_cml_server(server)
    if log_msg:
        _LOGGER.info(log_msg)
    args.cml_version = schema


def append_cml_schema_provenance_args(args_bits: list[str], args: object) -> None:
    """Append --cml-server / --cml-version flags for intent and regenerate strings."""
    server = getattr(args, "cml_server", None)
    if server:
        args_bits.append(f"--cml-server {server}")
    version = getattr(args, "cml_version", None)
    if version:
        args_bits.append(f"--cml-version {version}")
