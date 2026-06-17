#!/usr/bin/env python3
"""Per-ticket CML user provisioning (lab_view + lab_exec, admin: false)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import sys
from typing import Any

LAB_PERMISSIONS = ("lab_view", "lab_exec")

_LOGGER = logging.getLogger(__name__)


def _cml_client():
    try:
        from virl2_client import ClientLibrary
    except ImportError as exc:
        raise RuntimeError("virl2_client is required") from exc
    url = os.environ.get("VIRL2_URL", "https://192.168.1.183")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    return ClientLibrary(url, user, password, ssl_verify=False)


def resolve_password(
    password: str | None = None,
    *,
    password_env: str = "CUSTOMER_CML_PASSWORD",
) -> str:
    if password:
        return password
    from_env = os.environ.get(password_env, "").strip()
    if from_env:
        return from_env
    return secrets.token_urlsafe(24)


def _lab_association(lab_id: str) -> dict[str, Any]:
    return {"id": lab_id, "permissions": list(LAB_PERMISSIONS)}


def provision_cml_user(
    *,
    lab_id: str,
    username: str,
    password: str | None = None,
    password_env: str = "CUSTOMER_CML_PASSWORD",
    description: str | None = None,
    dry_run: bool = False,
    client=None,
) -> dict[str, Any]:
    """Create a lab-scoped CML user (admin=false, lab_view+lab_exec)."""
    pwd = resolve_password(password, password_env=password_env)
    payload = {
        "username": username,
        "admin": False,
        "associations": [_lab_association(lab_id)],
        "description": description or f"TopoGen scoped user for lab {lab_id}",
    }
    if dry_run:
        return {
            "dry_run": True,
            "username": username,
            "lab_id": lab_id,
            "admin": False,
            "permissions": list(LAB_PERMISSIONS),
            "password": pwd,
        }

    client = client or _cml_client()
    user_obj = client.user_management.create_user(
        username,
        pwd,
        admin=False,
        description=payload["description"],
        associations=payload["associations"],
    )
    user_id = user_obj.get("id") or user_obj.get("uuid")
    result = {
        "username": username,
        "user_id": user_id,
        "lab_id": lab_id,
        "admin": False,
        "permissions": list(LAB_PERMISSIONS),
        "password": pwd,
    }
    _LOGGER.debug("Provisioned CML user %s for lab %s", username, lab_id)
    return result


def revoke_cml_user(
    *,
    username: str,
    dry_run: bool = False,
    client=None,
) -> dict[str, Any]:
    """Delete a CML user by username."""
    if dry_run:
        return {"dry_run": True, "username": username, "revoked": True}

    client = client or _cml_client()
    user_id = client.user_management.user_id(username)
    client.user_management.delete_user(user_id)
    _LOGGER.debug("Revoked CML user %s (%s)", username, user_id)
    return {"username": username, "user_id": user_id, "revoked": True}


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision or revoke per-ticket CML users (lab_view+lab_exec, admin=false)."
    )
    parser.add_argument("--lab-id", help="CML lab UUID (required unless --revoke)")
    parser.add_argument("--username", required=True, help="Customer CML username")
    parser.add_argument(
        "--password-env",
        default="CUSTOMER_CML_PASSWORD",
        help="Env var for customer password (default: CUSTOMER_CML_PASSWORD); CSPRNG if unset",
    )
    parser.add_argument("--description", help="Optional user description")
    parser.add_argument(
        "--output-json",
        type=argparse.FileType("w", encoding="utf-8"),
        help="Write provision result JSON (includes password once)",
    )
    parser.add_argument(
        "--revoke",
        action="store_true",
        help="Delete user by username (teardown; --lab-id not required)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without calling CML API",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)

    try:
        if args.revoke:
            result = revoke_cml_user(
                username=args.username,
                dry_run=args.dry_run,
            )
        else:
            if not args.lab_id:
                parser.error("--lab-id is required unless --revoke")
            result = provision_cml_user(
                lab_id=args.lab_id,
                username=args.username,
                password_env=args.password_env,
                description=args.description,
                dry_run=args.dry_run,
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.output_json:
        json.dump(result, args.output_json, indent=2)
        args.output_json.write("\n")

    print(json.dumps({k: v for k, v in result.items() if k != "password"}, indent=2))
    if not args.revoke and "password" in result:
        print(f"password: {result['password']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
