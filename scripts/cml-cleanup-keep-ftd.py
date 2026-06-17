#!/usr/bin/env python3
"""Delete all CML labs except FTD-RAVPN-Lab; remove tg-TG-192* test users.

Requires VIRL2_URL, VIRL2_USER, VIRL2_PASS in the environment (admin).
"""
from __future__ import annotations

import os
import sys

KEEP_LAB_TITLE = "FTD-RAVPN-Lab"
TEST_USER_PREFIX = "tg-TG-192"


def main() -> int:
    url = os.environ.get("VIRL2_URL", "")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    if not all([url, user, password]):
        print("Set VIRL2_URL, VIRL2_USER, VIRL2_PASS", file=sys.stderr)
        return 1

    from virl2_client import ClientLibrary

    client = ClientLibrary(url, user, password, ssl_verify=False)
    labs = client.get_lab_list()
    for lab in labs:
        title = lab.get("lab_title") or lab.get("title") or ""
        lid = lab.get("id") or lab.get("uuid")
        if title == KEEP_LAB_TITLE:
            print(f"KEEP lab: {title} ({lid})")
            continue
        print(f"DELETE lab: {title} ({lid})")
        client.remove_lab(lid)

    for u in client.user_management.users():
        uname = u.get("username", "")
        if uname.startswith(TEST_USER_PREFIX):
            uid = u.get("id")
            print(f"DELETE user: {uname} ({uid})")
            client.user_management.delete_user(uid)

    print("Done. Remaining labs:")
    for lab in client.get_lab_list():
        print(f"  - {lab.get('lab_title') or lab.get('title')} ({lab.get('id')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
