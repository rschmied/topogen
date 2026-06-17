#!/usr/bin/env python3
"""Jira webhook → GitHub repository_dispatch for TG-192 CML pipeline.

Usage (operator / automation host):
  python scripts/jira-cml-webhook.py --payload webhook.json
  python scripts/jira-cml-webhook.py --jira-key TG-192 --event provision
  python scripts/jira-cml-webhook.py --jira-key TG-192 --event ready-comment \\
      --lab-id <uuid> --lab-title TG-192-smoke --synced 4 --total 4

Environment:
  GITHUB_TOKEN          PAT with repo dispatch (or Actions workflow scope)
  GITHUB_REPOSITORY     owner/repo (default: rohosfor/topogen on Cisco GitHub)
  JIRA_WEBHOOK_SECRET   Optional shared secret to validate inbound webhooks
  JIRA_BASE_URL         e.g. https://<your-instance>.atlassian.net
  JIRA_EMAIL / JIRA_API_TOKEN  For READY comments via REST (optional)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def _ready_comment(
    *,
    jira_key: str,
    lab_title: str,
    lab_id: str,
    cml_base: str,
    customer_user: str,
    synced: int,
    total: int,
    nac_ok: bool,
) -> str:
    url = f"{cml_base.rstrip('/')}/lab/{lab_id}"
    nac_status = "success" if nac_ok else "failed"
    return f"""CML lab READY — {jira_key}
- Lab: {lab_title} ({lab_id})
- URL: {url}
- Customer user: {customer_user} (password: vault link / operator handoff — not in this comment)
- Sync: {synced}/{total} routers in mgmt_sync.json
- NaC apply: {nac_status}
"""


def dispatch_github_event(
    event_type: str,
    client_payload: dict[str, Any],
    *,
    token: str | None = None,
    repository: str | None = None,
) -> None:
    token = token or os.environ.get("GITHUB_TOKEN", "")
    repository = repository or os.environ.get("GITHUB_REPOSITORY", "rohosfor/topogen")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required for repository_dispatch")

    url = f"https://api.github.com/repos/{repository}/dispatches"
    body = json.dumps({"event_type": event_type, "client_payload": client_payload}).encode()
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status not in (204, 200):
                raise RuntimeError(f"GitHub dispatch failed: HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"GitHub dispatch failed: HTTP {exc.code}: {detail}") from exc


def add_jira_comment(jira_key: str, body: str) -> None:
    base = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
    email = os.environ.get("JIRA_EMAIL", "")
    api_token = os.environ.get("JIRA_API_TOKEN", "")
    if not all([base, email, api_token]):
        print("JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN not set; skipping comment", file=sys.stderr)
        print(body)
        return

    import base64

    auth = base64.b64encode(f"{email}:{api_token}".encode()).decode()
    url = f"{base}/rest/api/3/issue/{jira_key}/comment"
    payload = json.dumps({"body": {"type": "doc", "version": 1, "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": line}]}
        for line in body.splitlines()
    ]}}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30):
        pass


def parse_jira_webhook(payload: dict[str, Any]) -> tuple[str, str]:
    """Return (jira_key, action) from Jira webhook JSON."""
    issue = payload.get("issue") or {}
    jira_key = issue.get("key", "")
    labels = {lbl.get("name", "") for lbl in (issue.get("fields", {}).get("labels") or [])}
    changelog = payload.get("changelog") or {}
    status_to = ""
    for item in changelog.get("items") or []:
        if item.get("field") == "status":
            status_to = item.get("toString", "")

    if status_to.lower() == "done":
        return jira_key, "teardown"
    if "cml-lab" in labels:
        return jira_key, "provision"
    return jira_key, "ignore"


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Jira ↔ GitHub CML pipeline bridge (TG-192)")
    parser.add_argument("--payload", type=argparse.FileType("r", encoding="utf-8"), help="Jira webhook JSON file")
    parser.add_argument("--jira-key", help="Explicit Jira key (bypass payload parse)")
    parser.add_argument(
        "--event",
        choices=("provision", "teardown", "ready-comment"),
        help="Explicit action",
    )
    parser.add_argument("--lab-id", help="Lab UUID (ready-comment)")
    parser.add_argument("--lab-title", help="Lab title (ready-comment)")
    parser.add_argument("--customer-user", help="Customer CML username")
    parser.add_argument("--cml-base", default=os.environ.get("TF_VAR_address", "https://..."))
    parser.add_argument("--synced", type=int, default=0)
    parser.add_argument("--total", type=int, default=0)
    parser.add_argument("--nac-ok", action="store_true", help="NaC apply succeeded")
    parser.add_argument("--node-count", default="4")
    parser.add_argument("--mode", default="flat")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)

    if args.event == "ready-comment":
        if not args.jira_key or not args.lab_id:
            parser.error("--jira-key and --lab-id required for ready-comment")
        customer = args.customer_user or f"tg-{args.jira_key}"
        body = _ready_comment(
            jira_key=args.jira_key,
            lab_title=args.lab_title or args.jira_key,
            lab_id=args.lab_id,
            cml_base=args.cml_base,
            customer_user=customer,
            synced=args.synced,
            total=args.total,
            nac_ok=args.nac_ok,
        )
        if args.dry_run:
            print(body)
            return 0
        add_jira_comment(args.jira_key, body)
        return 0

    jira_key = args.jira_key or ""
    action = args.event or ""
    if args.payload:
        payload = json.load(args.payload)
        jira_key, action = parse_jira_webhook(payload)
        if action == "ignore" and not args.event:
            print(f"No cml-lab label or Done transition for {jira_key}; ignoring")
            return 0

    if not jira_key:
        parser.error("Could not determine jira_key from payload; pass --jira-key")
    if not action:
        parser.error("Could not determine event; pass --event")

    customer_user = args.customer_user or f"tg-{jira_key}"
    if action == "provision":
        event_type = "cml-lab-provision"
        client_payload = {
            "jira_key": jira_key,
            "node_count": args.node_count,
            "mode": args.mode,
            "customer_username": customer_user,
        }
    elif action == "teardown":
        event_type = "cml-lab-teardown"
        client_payload = {
            "jira_key": jira_key,
            "customer_username": customer_user,
        }
    else:
        parser.error(f"Unsupported event: {action}")

    if args.dry_run:
        print(json.dumps({"event_type": event_type, "client_payload": client_payload}, indent=2))
        return 0

    dispatch_github_event(event_type, client_payload)
    print(json.dumps({"dispatched": event_type, "jira_key": jira_key}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
