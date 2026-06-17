# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-10
#
# Purpose: Offline flag matrix size and guardrail sanity checks.

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS))

from offline_flag_matrix import (  # pylint: disable=wrong-import-position
    CML2_OFFLINE_MATRIX,
    OFFLINE_FLAG_MATRIX,
    is_valid_offline_case,
    matrix_summary,
)


class TestOfflineFlagMatrix(unittest.TestCase):
    def test_matrix_has_at_least_1000_cases(self):
        self.assertGreaterEqual(len(OFFLINE_FLAG_MATRIX), 1000)

    def test_cml2_subset_is_40_cases(self):
        self.assertEqual(len(CML2_OFFLINE_MATRIX), 40)

    def test_case_ids_unique(self):
        ids = [case.case_id for case in OFFLINE_FLAG_MATRIX]
        self.assertEqual(len(ids), len(set(ids)))

    def test_bootstrap_guardrail_pruned(self):
        for case in OFFLINE_FLAG_MATRIX:
            if "--bootstrap" in case.extra_args:
                self.assertTrue(case.with_nac)
                self.assertIn("--mgmt", case.mgmt_args)

    def test_blank_guardrail_pruned(self):
        for case in OFFLINE_FLAG_MATRIX:
            if "--blank" in case.extra_args:
                self.assertFalse(case.with_nac)
                self.assertNotEqual(case.mode, "dmvpn")

    def test_summary_matches_build(self):
        summary = matrix_summary()
        self.assertEqual(summary["total_cases"], len(OFFLINE_FLAG_MATRIX))

    def test_is_valid_offline_case_rejects_nac_blank(self):
        self.assertFalse(
            is_valid_offline_case(
                mode="flat",
                with_nac=True,
                cml_version="0.3.1",
                mgmt_args=(),
                extra_args=("--blank",),
            )
        )

    def test_is_valid_offline_case_rejects_dmvpn_blank(self):
        self.assertFalse(
            is_valid_offline_case(
                mode="dmvpn",
                with_nac=False,
                cml_version="0.3.1",
                mgmt_args=(),
                extra_args=("--blank",),
            )
        )

    def test_matrix_case_count_after_dmvpn_blank_prune(self):
        self.assertEqual(len(OFFLINE_FLAG_MATRIX), 2832)


if __name__ == "__main__":
    unittest.main()
