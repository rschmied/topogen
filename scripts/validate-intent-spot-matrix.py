#!/usr/bin/env python3
# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-06-07
#
# Purpose: TG-167 offline validation — --intent-spot matrix with --nac --cml2.
# Blast Radius: Validation script only (writes under out/intent-spot-matrix/).

"""Validate --intent-spot matrix: all modes x iosv/csr x flag on/off with --nac --cml2."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = REPO / "out" / "intent-spot-matrix"
MODES = ("simple", "nx", "flat", "flat-pair", "dmvpn")
DEVICES = ("iosv", "csr1000v")
INTENT_FLAGS = (
    ("no-spot", ()),
    ("intent-spot", ("--intent-spot",)),
)


def main() -> int:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    passed = 0

    for mode in MODES:
        for device in DEVICES:
            for flag_name, flag_args in INTENT_FLAGS:
                lab = f"{mode}-4-{device}-{flag_name}"
                yaml_path = ARTIFACT_ROOT / lab / f"{lab}.yaml"
                cmd = [
                    sys.executable,
                    "-m",
                    "topogen",
                    "4",
                    "-m",
                    mode,
                    "--device-template",
                    device,
                    "--nac",
                    "--cml2",
                    "--cml-version",
                    "0.3.1",
                    "--overwrite",
                    "-q",
                    "--offline-yaml",
                    str(yaml_path),
                    *flag_args,
                ]
                if mode == "dmvpn":
                    cmd.extend(["--dmvpn-hubs", "1"])

                rc = subprocess.run(cmd, cwd=REPO, check=False).returncode
                want_spot = flag_name == "intent-spot"

                def gate(name: str, ok: bool, detail: str = "") -> None:
                    nonlocal passed
                    if ok:
                        passed += 1
                        print(f"[PASS] {lab} {name}")
                    else:
                        failed.append(f"{lab}: {name}" + (f" ({detail})" if detail else ""))
                        print(f"[FAIL] {lab} {name}" + (f" ({detail})" if detail else ""))

                gate("generate", rc == 0, f"rc={rc}")
                if not yaml_path.is_file():
                    continue

                text = yaml_path.read_text(encoding="utf-8")
                gate("annotations", "annotations:" in text)
                gate("notes", bool(re.search(r"^\s*notes:", text, re.M)))
                gate("version 0.3.1", bool(re.search(r"version:\s*'?0\.3\.1'?", text)))
                gate("no -9999", "-9999" not in text)
                has_marker = "label: INTENT-SPOT" in text
                gate("INTENT-SPOT marker", has_marker == want_spot)
                if want_spot:
                    gate(
                        f"{lab} INTENT-SPOT is unmanaged_switch",
                        "node_definition: unmanaged_switch"
                        in text.split("INTENT-SPOT", 1)[1].split("links:", 1)[0],
                    )
                gate("nac/", (ARTIFACT_ROOT / lab / "nac").is_dir())
                gate("cml2/main.tf", (ARTIFACT_ROOT / lab / "cml2" / "main.tf").is_file())
                prov_has_flag = "--intent-spot" in text
                gate("provenance flag", prov_has_flag == want_spot)

    print(f"\n=== Summary ===")
    print(f"Passed gates: {passed}")
    print(f"Failed gates: {len(failed)}")
    print(f"Artifacts: {ARTIFACT_ROOT}")
    if failed:
        for item in failed:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
