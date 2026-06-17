#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.0
# Date Modified: 2026-06-13
#
# Purpose: TG-195 live CML validation — import, CML2 terraform, NaC / NaC+bootstrap.
# Blast Radius: Writes under out/TG-195-cml/; deploys labs to configured CML.

"""Run TG-195 test matrix against live CML (import or cml2/terraform)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from offline_flag_matrix import CML2_SCAFFOLD_FILES  # noqa: E402
from tg195_cml_matrix import TG195_CML_MATRIX, Tg195CmlCase  # noqa: E402

ARTIFACT_ROOT = REPO / "out" / "TG-195-cml"
REPORT_NAME = "cml_import_report.json"

PLAN_ADD_RE = re.compile(r"Plan: \d+ to add, 0 to change, 0 to destroy\.")


@dataclass
class CaseResult:
    case_id: str
    kind: str
    matrix_ids: list[str]
    description: str
    passed: bool
    generate_rc: int | None = None
    import_rc: int | None = None
    terraform_init_rc: int | None = None
    terraform_apply_rc: int | None = None
    lab_id: str | None = None
    yaml_path: str | None = None
    cml2_path: str | None = None
    nac_path: str | None = None
    detail: str = ""
    stderr_tail: str = ""


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO / "src")
    cache = env.get("TF_PLUGIN_CACHE_DIR")
    if not cache:
        cache_dir = REPO / "out" / ".tf-plugin-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        env["TF_PLUGIN_CACHE_DIR"] = str(cache_dir)
    return env


def _missing_cml_creds() -> list[str]:
    missing = []
    for key in ("VIRL2_URL", "VIRL2_USER", "VIRL2_PASS"):
        if not os.environ.get(key):
            missing.append(key)
    return missing


def _terraform_binary() -> str | None:
    return shutil.which("terraform")


def _run_topogen(argv: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "topogen", *argv]
    proc = subprocess.run(
        cmd,
        cwd=REPO,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, combined


def _stderr_matches(text: str, needles: tuple[str, ...]) -> bool:
    if not needles:
        return True
    lower = text.lower()
    for needle in needles:
        if needle.lower() in lower:
            return True
    return False


def _case_root(case: Tg195CmlCase, root: Path) -> Path:
    path = root / case.case_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _yaml_path(case: Tg195CmlCase, root: Path) -> Path:
    return _case_root(case, root) / f"{case.case_id}.yaml"


def _artifact_paths(case: Tg195CmlCase, root: Path) -> tuple[Path, Path | None, Path | None]:
    """Resolve YAML, cml2/, and nac/ after generation."""
    yaml_path = _yaml_path(case, root)
    case_root = yaml_path.parent
    cml2_root = case_root / "cml2" if case.kind == "cml2" else None
    nac_root = case_root / "nac" if case.with_nac else None
    return yaml_path, cml2_root, nac_root


def _terraform_apply_vars(*, wait: bool) -> list[str]:
    address = os.environ.get("VIRL2_URL", "")
    user = os.environ.get("VIRL2_USER", "")
    password = os.environ.get("VIRL2_PASS", "")
    return [
        f"-var=address={address}",
        f"-var=username={user}",
        f"-var=password={password}",
        "-var=skip_verify=true",
        f"-var=wait={'true' if wait else 'false'}",
        "-var=lab_state=DEFINED_ON_CORE",
    ]


def _terraform_plan_vars() -> list[str]:
    return [
        "-var=address=https://127.0.0.1",
        "-var=skip_verify=true",
        "-var=token=plan-only",
    ]


def _run_terraform(
    cml2_root: Path,
    args: list[str],
) -> tuple[int, str]:
    terraform = _terraform_binary()
    if not terraform:
        return 127, "terraform binary not found on PATH"
    proc = subprocess.run(
        [terraform, *args],
        cwd=cml2_root,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _read_lab_id(cml2_root: Path) -> str | None:
    rc, out = _run_terraform(cml2_root, ["output", "-raw", "lab_id"])
    if rc != 0:
        return None
    lab_id = out.strip()
    return lab_id or None


def _run_import_case(
    case: Tg195CmlCase,
    root: Path,
    *,
    start: bool,
    import_only: bool,
) -> CaseResult:
    yaml_path, _, nac_root = _artifact_paths(case, root)
    gen_rc: int | None = None
    gen_out = ""

    if not import_only:
        gen_argv = [
            *case.topogen_argv,
            "--offline-yaml",
            str(yaml_path),
            "-L",
            case.lab_title(),
        ]
        gen_rc, gen_out = _run_topogen(gen_argv)
        if gen_rc != 0:
            return CaseResult(
                case_id=case.case_id,
                kind=case.kind,
                matrix_ids=list(case.matrix_ids),
                description=case.description,
                passed=False,
                generate_rc=gen_rc,
                yaml_path=str(yaml_path),
                nac_path=str(nac_root) if nac_root else None,
                detail="generate failed",
                stderr_tail=gen_out[-1200:],
            )
        if not yaml_path.is_file():
            return CaseResult(
                case_id=case.case_id,
                kind=case.kind,
                matrix_ids=list(case.matrix_ids),
                description=case.description,
                passed=False,
                generate_rc=gen_rc,
                detail="generate rc=0 but YAML missing",
                stderr_tail=gen_out[-1200:],
            )
        if case.with_nac and (nac_root is None or not nac_root.is_dir()):
            return CaseResult(
                case_id=case.case_id,
                kind=case.kind,
                matrix_ids=list(case.matrix_ids),
                description=case.description,
                passed=False,
                generate_rc=gen_rc,
                yaml_path=str(yaml_path),
                detail="expected nac/ directory missing",
                stderr_tail=gen_out[-1200:],
            )

    import_argv = [
        "--insecure",
        "--import-yaml",
        str(yaml_path),
        "--import",
        "-L",
        case.lab_title(),
    ]
    if start:
        import_argv.append("--start")
    imp_rc, imp_out = _run_topogen(import_argv)
    combined = gen_out + imp_out
    passed = imp_rc == 0 and "Lab URL:" in combined
    return CaseResult(
        case_id=case.case_id,
        kind=case.kind,
        matrix_ids=list(case.matrix_ids),
        description=case.description,
        passed=passed,
        generate_rc=gen_rc,
        import_rc=imp_rc,
        yaml_path=str(yaml_path),
        nac_path=str(nac_root) if nac_root and nac_root.is_dir() else None,
        detail="import ok" if passed else "import failed",
        stderr_tail=combined[-1200:],
    )


def _run_cml2_case(
    case: Tg195CmlCase,
    root: Path,
    *,
    plan_only: bool,
    wait: bool,
) -> CaseResult:
    yaml_path, cml2_root, nac_root = _artifact_paths(case, root)
    assert cml2_root is not None

    gen_argv = [
        *case.topogen_argv,
        "--offline-yaml",
        str(yaml_path),
        "-L",
        case.lab_title(),
    ]
    gen_rc, gen_out = _run_topogen(gen_argv)
    if gen_rc != 0:
        return CaseResult(
            case_id=case.case_id,
            kind=case.kind,
            matrix_ids=list(case.matrix_ids),
            description=case.description,
            passed=False,
            generate_rc=gen_rc,
            yaml_path=str(yaml_path),
            cml2_path=str(cml2_root),
            detail="generate failed",
            stderr_tail=gen_out[-1200:],
        )

    if not yaml_path.is_file():
        return CaseResult(
            case_id=case.case_id,
            kind=case.kind,
            matrix_ids=list(case.matrix_ids),
            description=case.description,
            passed=False,
            generate_rc=gen_rc,
            detail="YAML missing after generate",
            stderr_tail=gen_out[-1200:],
        )

    yaml_text = yaml_path.read_text(encoding="utf-8")
    if "--terraform-cml2" not in yaml_text:
        return CaseResult(
            case_id=case.case_id,
            kind=case.kind,
            matrix_ids=list(case.matrix_ids),
            description=case.description,
            passed=False,
            generate_rc=gen_rc,
            yaml_path=str(yaml_path),
            detail="provenance missing --terraform-cml2",
            stderr_tail=gen_out[-1200:],
        )

    for name in CML2_SCAFFOLD_FILES:
        if not (cml2_root / name).is_file():
            return CaseResult(
                case_id=case.case_id,
                kind=case.kind,
                matrix_ids=list(case.matrix_ids),
                description=case.description,
                passed=False,
                generate_rc=gen_rc,
                yaml_path=str(yaml_path),
                cml2_path=str(cml2_root),
                detail=f"missing cml2/{name}",
                stderr_tail=gen_out[-1200:],
            )

    if case.with_nac:
        if nac_root is None or not (nac_root / "nac.yaml").is_file():
            return CaseResult(
                case_id=case.case_id,
                kind=case.kind,
                matrix_ids=list(case.matrix_ids),
                description=case.description,
                passed=False,
                generate_rc=gen_rc,
                yaml_path=str(yaml_path),
                cml2_path=str(cml2_root),
                detail="expected nac/nac.yaml missing",
                stderr_tail=gen_out[-1200:],
            )

    init_rc, init_out = _run_terraform(cml2_root, ["init", "-input=false", "-no-color"])
    if init_rc != 0:
        return CaseResult(
            case_id=case.case_id,
            kind=case.kind,
            matrix_ids=list(case.matrix_ids),
            description=case.description,
            passed=False,
            generate_rc=gen_rc,
            terraform_init_rc=init_rc,
            yaml_path=str(yaml_path),
            cml2_path=str(cml2_root),
            nac_path=str(nac_root) if nac_root else None,
            detail="terraform init failed",
            stderr_tail=init_out[-1200:],
        )

    if plan_only:
        plan_rc, plan_out = _run_terraform(
            cml2_root,
            ["plan", "-input=false", "-no-color", *_terraform_plan_vars()],
        )
        passed = plan_rc == 0 and PLAN_ADD_RE.search(plan_out) is not None
        if passed:
            passed = "cml2_lifecycle.lab" in plan_out
        return CaseResult(
            case_id=case.case_id,
            kind=case.kind,
            matrix_ids=list(case.matrix_ids),
            description=case.description,
            passed=passed,
            generate_rc=gen_rc,
            terraform_init_rc=init_rc,
            terraform_apply_rc=plan_rc,
            yaml_path=str(yaml_path),
            cml2_path=str(cml2_root),
            nac_path=str(nac_root) if nac_root else None,
            detail="terraform plan ok" if passed else "terraform plan failed",
            stderr_tail=plan_out[-1200:],
        )

    apply_rc, apply_out = _run_terraform(
        cml2_root,
        ["apply", "-auto-approve", "-input=false", "-no-color", *_terraform_apply_vars(wait=wait)],
    )
    lab_id = _read_lab_id(cml2_root) if apply_rc == 0 else None
    passed = apply_rc == 0 and lab_id is not None
    return CaseResult(
        case_id=case.case_id,
        kind=case.kind,
        matrix_ids=list(case.matrix_ids),
        description=case.description,
        passed=passed,
        generate_rc=gen_rc,
        terraform_init_rc=init_rc,
        terraform_apply_rc=apply_rc,
        lab_id=lab_id,
        yaml_path=str(yaml_path),
        cml2_path=str(cml2_root),
        nac_path=str(nac_root) if nac_root else None,
        detail="terraform apply ok" if passed else "terraform apply failed",
        stderr_tail=apply_out[-1200:],
    )


def _run_generate_fail_case(case: Tg195CmlCase, root: Path) -> CaseResult:
    yaml_path = _yaml_path(case, root)
    if yaml_path.is_file():
        yaml_path.unlink()

    argv = [
        *case.topogen_argv,
        "--offline-yaml",
        str(yaml_path),
        "--insecure",
        "--import",
        "-L",
        case.lab_title(),
    ]
    rc, out = _run_topogen(argv)
    yaml_created = yaml_path.is_file()
    stderr_ok = _stderr_matches(out, case.expect_stderr)
    passed = rc != 0 and not yaml_created and stderr_ok
    detail_parts = []
    if rc == 0:
        detail_parts.append("expected generate failure but rc=0")
    if yaml_created:
        detail_parts.append("YAML was created unexpectedly")
    if not stderr_ok:
        detail_parts.append("stderr missing expected guardrail message")
    return CaseResult(
        case_id=case.case_id,
        kind=case.kind,
        matrix_ids=list(case.matrix_ids),
        description=case.description,
        passed=passed,
        generate_rc=rc,
        import_rc=None,
        yaml_path=str(yaml_path) if yaml_created else None,
        detail="; ".join(detail_parts) if detail_parts else "CLI rejected before import",
        stderr_tail=out[-1200:],
    )


def _run_cml2_generate_fail_case(case: Tg195CmlCase, root: Path) -> CaseResult:
    yaml_path = _yaml_path(case, root)
    if yaml_path.is_file():
        yaml_path.unlink()

    argv = [
        *case.topogen_argv,
        "--offline-yaml",
        str(yaml_path),
        "--insecure",
        "--import",
        "-L",
        case.lab_title(),
    ]
    rc, out = _run_topogen(argv)
    yaml_created = yaml_path.is_file()
    cml2_created = (yaml_path.parent / "cml2").exists()
    stderr_ok = _stderr_matches(out, case.expect_stderr)
    passed = rc != 0 and not yaml_created and not cml2_created and stderr_ok
    detail_parts = []
    if rc == 0:
        detail_parts.append("expected failure but rc=0")
    if yaml_created or cml2_created:
        detail_parts.append("artifacts created unexpectedly")
    if not stderr_ok:
        detail_parts.append("stderr missing expected guardrail message")
    return CaseResult(
        case_id=case.case_id,
        kind=case.kind,
        matrix_ids=list(case.matrix_ids),
        description=case.description,
        passed=passed,
        generate_rc=rc,
        yaml_path=str(yaml_path) if yaml_created else None,
        cml2_path=str(yaml_path.parent / "cml2") if cml2_created else None,
        detail="; ".join(detail_parts) if detail_parts else "cml2/import mutual exclusion ok",
        stderr_tail=out[-1200:],
    )


def _run_import_fail_case(case: Tg195CmlCase, root: Path) -> CaseResult:
    lab_dir = _case_root(case, root)
    yaml_path = lab_dir / f"{case.case_id}.yaml"
    yaml_path.write_text(case.stub_yaml_text or "", encoding="utf-8")

    argv = [
        "--insecure",
        "--import-yaml",
        str(yaml_path),
        "--import",
        "-L",
        case.lab_title(),
    ]
    rc, out = _run_topogen(argv)
    passed = rc != 0
    return CaseResult(
        case_id=case.case_id,
        kind=case.kind,
        matrix_ids=list(case.matrix_ids),
        description=case.description,
        passed=passed,
        generate_rc=None,
        import_rc=rc,
        yaml_path=str(yaml_path),
        detail="CML rejected stub YAML" if passed else "import unexpectedly succeeded",
        stderr_tail=out[-1200:],
    )


def _run_case(
    case: Tg195CmlCase,
    root: Path,
    *,
    start: bool,
    import_only: bool,
    generate_only: bool,
    plan_only: bool,
    wait: bool,
) -> CaseResult:
    if case.kind == "generate_fail":
        return _run_generate_fail_case(case, root)
    if case.kind == "cml2_generate_fail":
        return _run_cml2_generate_fail_case(case, root)
    if case.kind == "import_fail":
        return _run_import_fail_case(case, root)
    if case.kind == "cml2":
        if generate_only:
            result = _run_cml2_case(case, root, plan_only=True, wait=False)
            if result.generate_rc == 0 and result.passed:
                result.detail = "generate + terraform plan ok"
            return result
        return _run_cml2_case(case, root, plan_only=plan_only, wait=wait)

    result = _run_import_case(case, root, start=start, import_only=import_only)
    if generate_only and result.generate_rc == 0:
        result.passed = True
        result.detail = "generate-only ok"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="TG-195 CML matrix runner (import + cml2)")
    parser.add_argument(
        "--artifact-root",
        default=str(ARTIFACT_ROOT),
        help="Output root (default: out/TG-195-cml)",
    )
    parser.add_argument("--case", action="append", help="Run only case id(s), e.g. CML2-NAC")
    parser.add_argument("--start", action="store_true", help="Start lab after direct import")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="CML2 apply: wait for BOOTED (default: lab_state only, no wait)",
    )
    parser.add_argument("--generate-only", action="store_true", help="Generate (+ plan for cml2); no deploy")
    parser.add_argument("--plan-only", action="store_true", help="CML2: terraform plan only (no apply)")
    parser.add_argument("--import-only", action="store_true", help="Direct import existing YAML only")
    parser.add_argument("--dry-run", action="store_true", help="Print planned steps and exit")
    args = parser.parse_args()

    root = Path(args.artifact_root)
    root.mkdir(parents=True, exist_ok=True)

    cases = list(TG195_CML_MATRIX)
    if args.case:
        wanted = {c.strip() for c in args.case}
        cases = [c for c in cases if c.case_id in wanted]
        missing = wanted - {c.case_id for c in cases}
        if missing:
            print(f"Unknown case id(s): {', '.join(sorted(missing))}")
            return 2

    if args.dry_run:
        for case in cases:
            yaml_path = _yaml_path(case, root)
            print(f"[{case.kind}] {case.case_id} — {case.description}")
            if case.kind == "import":
                print(f"  generate: topogen ... -L {case.lab_title()} --offline-yaml {yaml_path}")
                print(
                    f"  import:   topogen --insecure --import-yaml {yaml_path} "
                    f"--import -L {case.lab_title()}"
                )
            elif case.kind == "cml2":
                print(f"  generate: topogen ... -L {case.lab_title()} --offline-yaml {yaml_path}")
                print(f"  deploy:   terraform -chdir={yaml_path.parent / 'cml2'} init apply")
            elif case.kind in ("generate_fail", "cml2_generate_fail"):
                print(f"  expect fail: topogen ... --offline-yaml {yaml_path} --insecure --import")
            else:
                print(f"  stub import fail: {yaml_path}")
        return 0

    needs_cml = not args.generate_only and not args.plan_only
    if needs_cml or any(c.kind == "cml2" for c in cases):
        missing = _missing_cml_creds()
        if missing and not args.generate_only:
            print("ERROR: CML credentials required:", ", ".join(missing))
            return 1

    if any(c.kind == "cml2" for c in cases) and not _terraform_binary():
        print("ERROR: terraform binary not found on PATH (required for cml2 cases)")
        return 1

    results: list[CaseResult] = []
    for case in cases:
        result = _run_case(
            case,
            root,
            start=args.start,
            import_only=args.import_only,
            generate_only=args.generate_only,
            plan_only=args.plan_only,
            wait=args.wait,
        )
        results.append(result)
        status = "PASS" if result.passed else "FAIL"
        extra = f" lab_id={result.lab_id}" if result.lab_id else ""
        print(f"[{status}] {case.case_id} ({case.kind}) — {result.detail}{extra}")

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "artifact_root": str(root),
        "options": {
            "start": args.start,
            "wait": args.wait,
            "generate_only": args.generate_only,
            "plan_only": args.plan_only,
            "import_only": args.import_only,
        },
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
        "results": [asdict(r) for r in results],
    }
    report_path = root / REPORT_NAME
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}")
    print(
        f"Summary: {report['summary']['passed']}/{report['summary']['total']} passed, "
        f"{report['summary']['failed']} failed"
    )
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
