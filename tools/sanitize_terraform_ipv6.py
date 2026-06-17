#!/usr/bin/env python3
"""Sanitize Terraform files by replacing live IPv6 addresses with safe documentation prefixes.

Usage:
    python sanitize_terraform_ipv6.py [--output-dir DIR] <input-file-or-dir> [...]
    
    Replaces live 2600: addresses with 2001:db8: equivalents.
    Preserves all other content unchanged.
    
Example:
    python sanitize_terraform_ipv6.py main.tf variables.tf --output-dir ./sanitized
    python sanitize_terraform_ipv6.py . --output-dir ../terraform-safe
"""

from __future__ import annotations

import argparse
import re
import sys
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from typing import Generator


# Match live lab prefix (2600:)
LIVE_PREFIX_PATTERN = re.compile(
    r"(?<![0-9A-Fa-f:])"  # not preceded by hex or colon
    r"(2600:[0-9A-Fa-f:]+(?:/\d+)?)"  # capture 2600: address with optional CIDR
    r"(?![0-9A-Fa-f:])",  # not followed by hex or colon
    re.IGNORECASE,
)

# Safe documentation prefix
DOC_PREFIX = "2001:db8:"


def sanitize_ipv6_address(addr: str) -> str:
    """Replace 2600: prefix with 2001:db8: equivalent."""
    if not addr.lower().startswith("2600:"):
        return addr
    
    # Extract CIDR if present
    cidr = None
    if "/" in addr:
        addr_part, cidr = addr.split("/", 1)
    else:
        addr_part = addr
    
    # Parse and reconstruct with doc prefix
    try:
        parsed = ip_address(addr_part)
        # Replace 2600: with 2001:db8:
        hex_str = parsed.exploded.lstrip(":")
        sanitized = f"{DOC_PREFIX}{hex_str[5:]}"  # skip original prefix
        if cidr:
            sanitized = f"{sanitized}/{cidr}"
        return sanitized
    except ValueError:
        # If not a valid address, return unchanged
        return addr


def sanitize_line(line: str) -> tuple[str, bool]:
    """Sanitize one line, return (sanitized_line, was_changed)."""
    original = line
    
    def replace_func(match):
        return sanitize_ipv6_address(match.group(1))
    
    sanitized = LIVE_PREFIX_PATTERN.sub(replace_func, line)
    return sanitized, sanitized != original


def sanitize_file(input_path: Path, output_path: Path) -> int:
    """Sanitize a single file. Return count of lines changed."""
    try:
        content = input_path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"ERROR reading {input_path}: {exc}", file=sys.stderr)
        return 0
    
    lines = content.splitlines(keepends=True)
    changed_count = 0
    output_lines = []
    
    for line in lines:
        sanitized, was_changed = sanitize_line(line)
        output_lines.append(sanitized)
        if was_changed:
            changed_count += 1
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text("".join(output_lines), encoding="utf-8")
    except Exception as exc:
        print(f"ERROR writing {output_path}: {exc}", file=sys.stderr)
        return 0
    
    if changed_count > 0:
        print(f"{input_path.name}: {changed_count} line(s) sanitized → {output_path.name}")
    else:
        print(f"{input_path.name}: no changes needed")
    
    return changed_count


def find_terraform_files(root: Path) -> Generator[Path, None, None]:
    """Recursively find .tf and .tfvars files."""
    for suffix in ("*.tf", "*.tfvars", "*.json"):
        yield from root.rglob(suffix)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitize Terraform files by replacing live 2600: IPv6 with 2001:db8: documentation prefix."
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Input file(s) or directory/directories to sanitize",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "sanitized",
        help="Output directory (default: ./sanitized)",
    )
    args = parser.parse_args()

    total_changed = 0
    total_files = 0

    for input_path in args.inputs:
        if input_path.is_dir():
            files = list(find_terraform_files(input_path))
            if not files:
                print(f"No .tf/.tfvars files found in {input_path}", file=sys.stderr)
                continue
            for file_path in files:
                rel_path = file_path.relative_to(input_path)
                output_path = args.output_dir / rel_path
                changed = sanitize_file(file_path, output_path)
                total_changed += changed
                total_files += 1
        elif input_path.is_file():
            output_path = args.output_dir / input_path.name
            changed = sanitize_file(input_path, output_path)
            total_changed += changed
            total_files += 1
        else:
            print(f"Not found: {input_path}", file=sys.stderr)

    print(f"\nSummary: {total_files} file(s) processed, {total_changed} line(s) sanitized")
    print(f"Output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
