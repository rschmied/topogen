#!/usr/bin/env python3
"""Validate offline flag matrix generation gates."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
sys.path.insert(0, str(TESTS))

from offline_flag_matrix import (  # noqa: E402
    CML2_SCAFFOLD_FILES,
    NAC_FILES,
    OFFLINE_FLAG_MATRIX,
    matrix_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate offline flag matrix generation.")
    parser.add_argument(
        "artifact_root",
        nargs="?",
        default=str(REPO / "out" / "offline-flag-matrix"),
        help="Matrix artifact root",
    )
    parser.add_argument("--generate", action="store_true", help="Run topogen before gating")
    parser.add_argument("--limit", type=int, default=0, help="Validate at most N cases (0=all)")
    args = parser.parse_args()

    dest = Path(args.artifact_root)
    cases = OFFLINE_FLAG_MATRIX if args.limit <= 0 else OFFLINE_FLAG_MATRIX[: args.limit]
    print(f"Validating {len(cases)} of {matrix_summary()['total_cases']} matrix cases")

    failed: list[str] = []
    passed = 0

    def gate(name: str, ok: bool, detail: str = "") -> None:
        nonlocal passed
        if ok:
            passed += 1
        else:
            failed.append(name + (f" ({detail})" if detail else ""))

    for case in cases:
        lab = case.case_id
        lab_root = dest / lab
        yaml_path = lab_root / f"{lab}.yaml"

        if args.generate:
            lab_root.mkdir(parents=True, exist_ok=True)
            cmd = [sys.executable, "-m", "topogen", *case.topogen_argv(str(yaml_path))]
            env = __import__("os").environ.copy()
            env["PYTHONPATH"] = str(REPO / "src")
            rc = subprocess.run(cmd, cwd=REPO, env=env, check=False).returncode
            gate(f"{lab} generate", rc == 0, f"rc={rc}")
            if rc != 0:
                continue

        if not yaml_path.is_file():
            gate(f"{lab} yaml", False, "missing")
            continue

        text = yaml_path.read_text(encoding="utf-8")
        gate(f"{lab} yaml", True)
        gate(f"{lab} version", bool(re.search(rf"version:\s*'?{re.escape(case.cml_version)}'?", text)))
        want_spot = case.intent_spot
        gate(f"{lab} intent-spot", ("label: INTENT-SPOT" in text) == want_spot)

        has_cml2 = case.cml2_label != "no-cml2"
        if has_cml2:
            for name in CML2_SCAFFOLD_FILES:
                gate(f"{lab} cml2/{name}", (lab_root / "cml2" / name).is_file())
        else:
            gate(f"{lab} no cml2/", not (lab_root / "cml2").exists())

        nac_dir = lab_root / "nac"
        if case.with_nac:
            gate(f"{lab} nac/", nac_dir.is_dir())
            for name in NAC_FILES:
                gate(f"{lab} nac/{name}", (nac_dir / name).is_file())
        else:
            gate(f"{lab} no nac/", not nac_dir.exists())

        if case.with_nac:
            gate(f"{lab} provenance --nac", "--nac" in text)
        if has_cml2:
            gate(f"{lab} provenance cml2", "--terraform-cml2" in text or "--cml2" in text)

    print(f"\n=== Summary ===")
    print(f"Passed gates: {passed}")
    print(f"Failed gates: {len(failed)}")
    print(f"Artifacts: {dest}")
    if failed:
        for item in failed[:30]:
            print(f"  - {item}")
        if len(failed) > 30:
            print(f"  ... and {len(failed) - 30} more")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
