#!/usr/bin/env python3
"""Generate the offline flag matrix (1000+ guardrail-valid cases)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
sys.path.insert(0, str(TESTS))

from offline_flag_matrix import OFFLINE_FLAG_MATRIX, matrix_summary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate offline flag matrix artifacts.")
    parser.add_argument(
        "artifact_root",
        nargs="?",
        default=str(REPO / "out" / "offline-flag-matrix"),
        help="Output root (one subdirectory per case)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Generate at most N cases (0=all)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N matrix cases")
    parser.add_argument("--summary-only", action="store_true", help="Print matrix dimensions and exit")
    args = parser.parse_args()

    summary = matrix_summary()
    print(f"Matrix: {summary['total_cases']} valid cases (after guardrail pruning)")
    if args.summary_only:
        return 0

    dest = Path(args.artifact_root)
    dest.mkdir(parents=True, exist_ok=True)
    cases = OFFLINE_FLAG_MATRIX[args.offset :]
    if args.limit > 0:
        cases = cases[: args.limit]
    print(f"Slice: offset={args.offset} count={len(cases)}")

    failed: list[str] = []
    for case in cases:
        lab_root = dest / case.case_id
        yaml_path = lab_root / f"{case.case_id}.yaml"
        lab_root.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "topogen", *case.topogen_argv(str(yaml_path))]
        env = __import__("os").environ.copy()
        env["PYTHONPATH"] = str(REPO / "src")
        rc = subprocess.run(cmd, cwd=REPO, env=env, check=False).returncode
        status = "OK" if rc == 0 else f"FAIL rc={rc}"
        print(f"{status} {case.case_id}")
        if rc != 0:
            failed.append(case.case_id)

    print(f"\nGenerated {len(cases) - len(failed)}/{len(cases)} under {dest}")
    if failed:
        print("Failed:", ", ".join(failed[:20]), ("..." if len(failed) > 20 else ""))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
