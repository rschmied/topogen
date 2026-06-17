#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-13
#
# - Called by: topogen capture-lab-evidence subcommand
# - Reads from: mgmt_sync.json, ci_report.json, live CML lab
# - Writes to: lab notes, canvas annotations, exported topology YAML
# - Calls into: virl2_client
"""Embed CI test evidence in a live CML lab and export post-run topology YAML."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from topogen.nac_mgmt_sync import _cml_client, _collect_router_nodes

CI_REPORT_MARKER = "TOPOGEN_CI_REPORT="
CI_ANNOTATION_PREFIX = "TopoGen CI"
# CML canvas: serif above the topology; 14pt with matching border reads reliably.
CI_ANNOTATION_FONT = "serif"
CI_ANNOTATION_SIZE = 14
CI_ANNOTATION_TOP_OFFSET = 60
# Keep in sync with render.INTENT_ANNOTATION_PADDING (hidden intent row below topology).
CI_INTENT_ANNOTATION_PADDING = 1500
# Match render.py intent annotation (#FFFFFF 6-digit); #FFFFFFFF renders semi-visible in CML.
CI_HIDDEN_ANNOTATION_COLOR = "#FFFFFF"

_LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_mgmt_sync_report(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Could not read mgmt sync report %s: %s", path, exc)
        return {}


def build_ci_report(
    *,
    jira_key: str,
    lab_id: str,
    lab_title: str,
    status: str,
    mgmt_sync: dict[str, Any] | None = None,
    gates: dict[str, Any] | None = None,
    config_extract: dict[str, Any] | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    mgmt = mgmt_sync or {}
    synced = int(mgmt.get("synced", 0) or 0)
    mapping = mgmt.get("mapping") or {}
    total = len(mapping) if mapping else int(mgmt.get("total_routers", 0) or 0)
    return {
        "schema": "topogen-ci-report-v1",
        "jira_key": jira_key,
        "lab_id": lab_id,
        "lab_title": lab_title,
        "status": status,
        "finished_at": finished_at or _utc_now(),
        "mgmt_sync": {
            "mode": mgmt.get("mode"),
            "synced": synced,
            "total": total,
            "mapping": mapping,
            **(
                {"mapping_ipv4": mgmt.get("mapping_ipv4")}
                if mgmt.get("mapping_ipv4")
                else {}
            ),
            **(
                {"synced_ipv4": int(mgmt.get("synced_ipv4", 0) or 0)}
                if mgmt.get("mapping_ipv4")
                else {}
            ),
        },
        "gates": gates or {},
        "config_extract": config_extract or {},
    }


def _embed_report_in_notes(existing: str, report: dict[str, Any]) -> str:
    payload = CI_REPORT_MARKER + json.dumps(report, separators=(",", ":"), sort_keys=True)
    hidden = (
        '<span style="color: white; font-size: 1pt; opacity: 0;">'
        f"{html.escape(payload)}"
        "</span>"
    )
    base = existing or ""
    if CI_REPORT_MARKER in base:
        base = re.sub(
            r'<span style="color: white; font-size: 1pt; opacity: 0;">'
            r"TOPOGEN_CI_REPORT=.*?</span>",
            "",
            base,
            flags=re.DOTALL,
        )
    if base and not base.endswith("\n"):
        base += "\n"
    return base + hidden


def _annotation_xy(lab) -> tuple[int, int]:
    """Place the visible CI stamp just below the top row of nodes (stays in zoom-to-fit).

    Hidden CI canvas JSON sits on the row below the TopoGen intent annotation;
    TOPOGEN_CI_REPORT also remains in lab.notes.
    """
    coords: list[tuple[int, int]] = []
    for node in lab.nodes():
        x = getattr(node, "x", None)
        y = getattr(node, "y", None)
        if isinstance(x, int) and isinstance(y, int):
            coords.append((x, y))
    if not coords:
        return 600, CI_ANNOTATION_TOP_OFFSET
    min_x = min(x for x, _ in coords)
    min_y = min(y for _, y in coords)
    max_x = max(x for x, _ in coords)
    # Top-center of node bounding box — stays in zoom-to-fit with the routers.
    return (min_x + max_x) // 2, min_y + CI_ANNOTATION_TOP_OFFSET


def _hidden_ci_annotation_xy(lab) -> tuple[int, int]:
    """Same row as TopoGen intent — below topology, clear of link lines."""
    coords: list[tuple[int, int]] = []
    for node in lab.nodes():
        x = getattr(node, "x", None)
        y = getattr(node, "y", None)
        if isinstance(x, int) and isinstance(y, int):
            coords.append((x, y))
    if not coords:
        return 0, CI_INTENT_ANNOTATION_PADDING
    max_x = max(x for x, _ in coords)
    max_y = max(y for _, y in coords)
    return max_x, max_y + CI_INTENT_ANNOTATION_PADDING


def _hidden_canvas_text(report: dict[str, Any]) -> str:
    """Short canvas marker for YAML grep; full JSON stays in lab.notes only."""
    mgmt = report.get("mgmt_sync") or {}
    extract = report.get("config_extract") or {}
    return (
        f"{CI_REPORT_MARKER}{report.get('jira_key', '')}|"
        f"{report.get('status', '')}|"
        f"sync:{mgmt.get('synced', '?')}/{mgmt.get('total', '?')}|"
        f"cfg:{extract.get('extracted', 0)}/{extract.get('routers', 0)}"
    )


def _remove_prior_hidden_ci_annotations(lab) -> int:
    """Drop prior hidden CI canvas rows so re-runs replace rather than stack."""
    removed = 0
    for ann in list(lab.annotations()):
        text = getattr(ann, "text_content", "") or ""
        if CI_REPORT_MARKER in text:
            ann.remove()
            removed += 1
    return removed


def _create_hidden_ci_annotation(lab, report: dict[str, Any]):
    x1, y1 = _hidden_ci_annotation_xy(lab)
    return lab.create_annotation(
        "text",
        x1=x1,
        y1=y1,
        text_content=_hidden_canvas_text(report),
        text_font="monospace",
        text_size=1,
        text_unit="pt",
        text_bold=False,
        text_italic=False,
        color=CI_HIDDEN_ANNOTATION_COLOR,
        border_color=CI_HIDDEN_ANNOTATION_COLOR,
        border_style="",
        thickness=1,
        rotation=0,
        z_index=0,
    )


# Canvas text/border colors for visible CI status annotations.
_ANNOTATION_COLORS: dict[str, str] = {
    "pass": "#1B5E20",  # green
    "fail": "#B71C1C",  # red
    "partial": "#E65100",  # amber
}
_ANNOTATION_COLOR_DEFAULT = "#616161"  # gray for unknown status
# CML 2.x colors are #RRGGBBAA; 6-digit hex is treated as transparent in the UI.
_CML_TRANSPARENT_BORDER = "#00000000"


def _opaque_cml_color(hex_rgb: str) -> str:
    """Return an opaque CML #RRGGBBAA color from a #RRGGBB (or already RGBA) value."""
    value = hex_rgb.strip()
    if value.startswith("#") and len(value) == 7:
        return value + "FF"
    return value


def annotation_colors(status: str) -> tuple[str, str]:
    """Return (text_color, border_color) for a CI report status."""
    key = str(status or "").lower()
    color = _opaque_cml_color(_ANNOTATION_COLORS.get(key, _ANNOTATION_COLOR_DEFAULT))
    # Text uses ``color``; leave outline transparent (CML default).
    return color, _CML_TRANSPARENT_BORDER


def _canvas_summary_text(report: dict[str, Any]) -> str:
    """Short canvas label; full timestamp stays in lab.notes / ci_report.json."""
    mgmt = report.get("mgmt_sync") or {}
    synced = mgmt.get("synced", "?")
    total = mgmt.get("total", "?")
    extract = report.get("config_extract") or {}
    ok = extract.get("extracted", 0)
    routers = extract.get("routers", 0)
    return (
        f"{CI_ANNOTATION_PREFIX} {report.get('status', 'unknown').upper()} | "
        f"{report.get('jira_key', '')} | sync {synced}/{total} | cfg {ok}/{routers}"
    )


def extract_working_configs(lab, *, dry_run: bool = False) -> dict[str, Any]:
    """Pull running configs into each router node's lab definition (CML extract_configuration)."""
    results: dict[str, Any] = {"routers": 0, "extracted": 0, "nodes": {}}
    for _index, node in _collect_router_nodes(lab):
        label = node.label
        results["routers"] += 1
        entry: dict[str, Any] = {"state": str(getattr(node, "state", "")), "ok": False}
        results["nodes"][label] = entry
        if str(getattr(node, "state", "")) != "BOOTED":
            entry["error"] = f"node state {entry['state']}, expected BOOTED"
            continue
        if dry_run:
            entry["ok"] = True
            entry["dry_run"] = True
            results["extracted"] += 1
            continue
        try:
            node.extract_configuration()
            entry["ok"] = True
            results["extracted"] += 1
        except Exception as exc:
            entry["error"] = str(exc) or type(exc).__name__
            _LOGGER.warning("extract_configuration failed for %s: %s", label, entry["error"])
    return results


def embed_ci_evidence(
    lab,
    report: dict[str, Any],
    *,
    dry_run: bool = False,
    add_visible_annotation: bool = True,
) -> dict[str, Any]:
    """Write CI report into lab notes and add visible + hidden canvas annotations."""
    notes = _embed_report_in_notes(getattr(lab, "notes", "") or "", report)
    result: dict[str, Any] = {
        "notes_updated": False,
        "annotation_id": None,
        "hidden_annotation_id": None,
        "hidden_annotations_removed": 0,
    }
    if dry_run:
        result["notes_preview_chars"] = min(len(notes), 200)
        result["hidden_canvas_preview"] = _hidden_canvas_text(report)[:120]
        return result

    lab.notes = notes
    result["notes_updated"] = True
    result["hidden_annotations_removed"] = _remove_prior_hidden_ci_annotations(lab)
    hidden = _create_hidden_ci_annotation(lab, report)
    result["hidden_annotation_id"] = getattr(hidden, "id", None)

    if add_visible_annotation:
        x1, y1 = _annotation_xy(lab)
        text_color, border_color = annotation_colors(str(report.get("status", "")))
        annotation = lab.create_annotation(
            "text",
            x1=x1,
            y1=y1,
            text_content=_canvas_summary_text(report),
            text_font=CI_ANNOTATION_FONT,
            text_size=CI_ANNOTATION_SIZE,
            text_unit="pt",
            text_bold=True,
            text_italic=False,
            color=text_color,
            border_color=border_color,
            border_style="",
            thickness=1,
            rotation=0,
            z_index=100,
        )
        result["annotation_id"] = getattr(annotation, "id", None)
        result["annotation_color"] = text_color
    return result


def download_lab_yaml(lab, *, dry_run: bool = False) -> str:
    if dry_run:
        return ""
    return lab.download()


def capture_lab_evidence(
    *,
    lab_id: str,
    evidence_dir: Path,
    jira_key: str = "TG-192",
    lab_title: str | None = None,
    mgmt_sync_path: Path | None = None,
    status: str = "pass",
    gates: dict[str, Any] | None = None,
    dry_run: bool = False,
    client=None,
) -> dict[str, Any]:
    """Extract working configs, embed CI report in lab, export YAML to evidence_dir."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    client = client or _cml_client()
    lab = client.join_existing_lab(lab_id)
    title = lab_title or getattr(lab, "title", None) or lab_id

    mgmt_sync = load_mgmt_sync_report(mgmt_sync_path)
    config_extract = extract_working_configs(lab, dry_run=dry_run)
    report = build_ci_report(
        jira_key=jira_key,
        lab_id=lab_id,
        lab_title=title,
        status=status,
        mgmt_sync=mgmt_sync,
        gates=gates,
        config_extract=config_extract,
    )
    embed_result = embed_ci_evidence(lab, report, dry_run=dry_run)
    yaml_text = download_lab_yaml(lab, dry_run=dry_run)

    report_path = evidence_dir / "ci_report.json"
    yaml_name = f"{title}-post-run.yaml"
    yaml_path = evidence_dir / yaml_name

    if not dry_run:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if yaml_text:
            yaml_path.write_text(yaml_text, encoding="utf-8")
            if CI_REPORT_MARKER not in yaml_text:
                _LOGGER.warning(
                    "Exported lab YAML does not contain %s; notes may not have synced yet",
                    CI_REPORT_MARKER,
                )

    return {
        "lab_id": lab_id,
        "lab_title": title,
        "status": status,
        "ci_report": str(report_path),
        "lab_yaml": str(yaml_path) if yaml_text or dry_run else None,
        "config_extract": config_extract,
        "embed": embed_result,
        "dry_run": dry_run,
    }


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Embed CI evidence in a live CML lab: extract working configs, "
            "stamp lab notes/annotation, download post-run topology YAML."
        )
    )
    parser.add_argument("--lab-id", required=True, help="CML lab UUID")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="Directory for ci_report.json and <lab>-post-run.yaml",
    )
    parser.add_argument("--jira-key", default="TG-192", help="Jira ticket key")
    parser.add_argument("--lab-title", help="Lab title for filenames (default: from CML)")
    parser.add_argument(
        "--mgmt-sync",
        type=Path,
        help="Path to nac/mgmt_sync.json (default: evidence-dir/../nac/mgmt_sync.json)",
    )
    parser.add_argument(
        "--status",
        default="pass",
        choices=("pass", "fail", "partial"),
        help="Overall CI status stamped into the lab",
    )
    parser.add_argument(
        "--gates-json",
        type=Path,
        help="Optional JSON object of gate name -> pass/fail for the report",
    )
    parser.add_argument("--dry-run", action="store_true", help="Build report without CML writes")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argparser()
    args = parser.parse_args(argv)

    mgmt_sync = args.mgmt_sync
    if mgmt_sync is None:
        candidate = args.evidence_dir.parent / "nac" / "mgmt_sync.json"
        if candidate.is_file():
            mgmt_sync = candidate

    gates: dict[str, Any] | None = None
    if args.gates_json and args.gates_json.is_file():
        gates = json.loads(args.gates_json.read_text(encoding="utf-8"))

    try:
        result = capture_lab_evidence(
            lab_id=args.lab_id,
            evidence_dir=args.evidence_dir,
            jira_key=args.jira_key,
            lab_title=args.lab_title,
            mgmt_sync_path=mgmt_sync,
            status=args.status,
            gates=gates,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
