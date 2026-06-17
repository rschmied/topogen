# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-13
#
# Purpose: TG-192 — unit tests for CML lab CI evidence capture (dual-stack mgmt TG-190).
# Blast Radius: Test-only.

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.cml_lab_evidence import (  # noqa: E402
    CI_ANNOTATION_TOP_OFFSET,
    CI_ANNOTATION_FONT,
    CI_ANNOTATION_SIZE,
    CI_INTENT_ANNOTATION_PADDING,
    CI_REPORT_MARKER,
    annotation_colors,
    build_ci_report,
    capture_lab_evidence,
    embed_ci_evidence,
    extract_working_configs,
    _annotation_xy,
    _canvas_summary_text,
    _embed_report_in_notes,
    _hidden_canvas_text,
    _hidden_ci_annotation_xy,
)

LAB_ID = "016b048b-b232-4929-b4cb-6774f63bd263"


class TestBuildCiReport(unittest.TestCase):
    def test_includes_mgmt_sync_counts(self):
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="TG-192-smoke",
            status="pass",
            mgmt_sync={"mode": "slaac", "synced": 4, "mapping": {"iosv-01": "2001:db8::1"}},
        )
        self.assertEqual(report["schema"], "topogen-ci-report-v1")
        self.assertEqual(report["mgmt_sync"]["synced"], 4)
        self.assertEqual(report["mgmt_sync"]["total"], 1)

    def test_includes_mapping_ipv4_when_present(self):
        report = build_ci_report(
            jira_key="TG-190",
            lab_id=LAB_ID,
            lab_title="TG-190-dual",
            status="pass",
            mgmt_sync={
                "mode": "slaac",
                "synced": 2,
                "synced_ipv4": 2,
                "mapping": {"iosv-01": "2001:db8::1"},
                "mapping_ipv4": {"iosv-01": "192.168.1.10"},
            },
        )
        self.assertEqual(report["mgmt_sync"]["mapping_ipv4"]["iosv-01"], "192.168.1.10")
        self.assertEqual(report["mgmt_sync"]["synced_ipv4"], 2)


class TestEmbedNotes(unittest.TestCase):
    def test_appends_hidden_marker(self):
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="pass",
        )
        notes = _embed_report_in_notes("existing", report)
        self.assertIn("existing", notes)
        self.assertIn(CI_REPORT_MARKER, notes)
        self.assertIn("topogen-ci-report-v1", notes)

    def test_replaces_prior_report(self):
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="fail",
        )
        first = _embed_report_in_notes("", report)
        report["status"] = "pass"
        second = _embed_report_in_notes(first, report)
        self.assertEqual(second.count(CI_REPORT_MARKER), 1)
        self.assertIn("status&quot;:&quot;pass", second)


class TestExtractWorkingConfigs(unittest.TestCase):
    def test_extracts_booted_routers(self):
        lab = MagicMock()
        booted = MagicMock(label="R1", state="BOOTED")
        stopped = MagicMock(label="R2", state="STOPPED")
        with patch(
            "topogen.cml_lab_evidence._collect_router_nodes",
            return_value=[(1, booted), (2, stopped)],
        ):
            result = extract_working_configs(lab)
        self.assertEqual(result["routers"], 2)
        self.assertEqual(result["extracted"], 1)
        booted.extract_configuration.assert_called_once()
        self.assertTrue(result["nodes"]["R1"]["ok"])
        self.assertIn("error", result["nodes"]["R2"])


class TestAnnotationColors(unittest.TestCase):
    def test_status_colors(self):
        self.assertEqual(annotation_colors("pass"), ("#1B5E20FF", "#00000000"))
        self.assertEqual(annotation_colors("fail"), ("#B71C1CFF", "#00000000"))
        self.assertEqual(annotation_colors("partial"), ("#E65100FF", "#00000000"))
        self.assertEqual(annotation_colors("unknown")[0], "#616161FF")


class TestAnnotationPlacement(unittest.TestCase):
    def test_places_visible_near_top_of_topology(self):
        lab = MagicMock()
        lab.nodes.return_value = [
            MagicMock(x=0, y=0),
            MagicMock(x=600, y=1200),
        ]
        x1, y1 = _annotation_xy(lab)
        self.assertEqual(x1, 300)
        self.assertEqual(y1, CI_ANNOTATION_TOP_OFFSET)

    def test_places_hidden_on_intent_row(self):
        lab = MagicMock()
        lab.nodes.return_value = [
            MagicMock(x=0, y=0),
            MagicMock(x=600, y=1200),
        ]
        x1, y1 = _hidden_ci_annotation_xy(lab)
        self.assertEqual(x1, 600)
        self.assertEqual(y1, 1200 + CI_INTENT_ANNOTATION_PADDING)


class TestHiddenCanvasText(unittest.TestCase):
    def test_short_marker_full_json_in_notes_only(self):
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="pass",
            mgmt_sync={"synced": 6, "mapping": {f"r{i}": f"addr{i}" for i in range(6)}},
            config_extract={"extracted": 6, "routers": 6},
        )
        text = _hidden_canvas_text(report)
        self.assertTrue(text.startswith(CI_REPORT_MARKER))
        self.assertIn("TG-192|pass", text)
        self.assertIn("sync:6/6", text)
        self.assertIn("cfg:6/6", text)
        self.assertNotIn("2001:db8:", text)
        notes = _embed_report_in_notes("", report)
        self.assertIn("topogen-ci-report-v1", notes)


class TestCanvasSummaryText(unittest.TestCase):
    def test_omits_timestamp(self):
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="pass",
            mgmt_sync={"synced": 6, "mapping": {f"r{i}": f"addr{i}" for i in range(6)}},
            config_extract={"extracted": 6, "routers": 6},
            finished_at="2026-06-12T18:00:00+00:00",
        )
        text = _canvas_summary_text(report)
        self.assertIn("TopoGen CI PASS", text)
        self.assertIn("sync 6/6", text)
        self.assertIn("cfg 6/6", text)
        self.assertNotIn("2026-06-12", text)


class TestEmbedCiEvidence(unittest.TestCase):
    def test_sets_notes_visible_and_hidden_annotations(self):
        lab = MagicMock()
        lab.notes = ""
        lab.nodes.return_value = [MagicMock(x=100, y=200)]
        lab.annotations.return_value = []
        lab.create_annotation.side_effect = [
            MagicMock(id="ann-hidden"),
            MagicMock(id="ann-visible"),
        ]
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="pass",
            config_extract={"extracted": 4, "routers": 4},
        )
        result = embed_ci_evidence(lab, report)
        self.assertTrue(result["notes_updated"])
        self.assertEqual(result["hidden_annotation_id"], "ann-hidden")
        self.assertEqual(result["annotation_id"], "ann-visible")
        self.assertEqual(result["annotation_color"], "#1B5E20FF")
        self.assertEqual(lab.create_annotation.call_count, 2)
        hidden_kwargs = lab.create_annotation.call_args_list[0].kwargs
        visible_kwargs = lab.create_annotation.call_args_list[1].kwargs
        self.assertIn(CI_REPORT_MARKER, hidden_kwargs["text_content"])
        self.assertEqual(hidden_kwargs["text_size"], 1)
        self.assertEqual(hidden_kwargs["color"], "#FFFFFF")
        self.assertEqual(hidden_kwargs["border_color"], "#FFFFFF")
        self.assertIn("TopoGen CI PASS", visible_kwargs["text_content"])
        self.assertEqual(visible_kwargs["text_font"], CI_ANNOTATION_FONT)
        self.assertEqual(visible_kwargs["text_size"], CI_ANNOTATION_SIZE)
        self.assertTrue(visible_kwargs["text_bold"])
        self.assertEqual(visible_kwargs["color"], "#1B5E20FF")
        self.assertEqual(visible_kwargs["border_color"], "#00000000")
        self.assertEqual(visible_kwargs["z_index"], 100)

    def test_replaces_prior_hidden_canvas_rows(self):
        lab = MagicMock()
        lab.notes = ""
        lab.nodes.return_value = [MagicMock(x=100, y=200)]
        stale = MagicMock()
        stale.text_content = CI_REPORT_MARKER + "{}"
        lab.annotations.return_value = [stale]
        lab.create_annotation.side_effect = [
            MagicMock(id="ann-hidden"),
            MagicMock(id="ann-visible"),
        ]
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="pass",
        )
        result = embed_ci_evidence(lab, report)
        stale.remove.assert_called_once()
        self.assertEqual(result["hidden_annotations_removed"], 1)

    def test_fail_annotation_is_red(self):
        lab = MagicMock()
        lab.notes = ""
        lab.nodes.return_value = [MagicMock(x=100, y=200)]
        lab.annotations.return_value = []
        lab.create_annotation.side_effect = [
            MagicMock(id="ann-hidden"),
            MagicMock(id="ann-fail"),
        ]
        report = build_ci_report(
            jira_key="TG-192",
            lab_id=LAB_ID,
            lab_title="smoke",
            status="fail",
        )
        result = embed_ci_evidence(lab, report)
        self.assertEqual(result["annotation_color"], "#B71C1CFF")
        visible_kwargs = lab.create_annotation.call_args_list[1].kwargs
        self.assertEqual(visible_kwargs["color"], "#B71C1CFF")
        self.assertIn("TopoGen CI FAIL", visible_kwargs["text_content"])


class TestCaptureLabEvidence(unittest.TestCase):
    def test_writes_artifacts(self):
        with patch("topogen.cml_lab_evidence._cml_client") as mock_client_factory:
            lab = MagicMock()
            lab.title = "TG-192-smoke"
            lab.notes = ""
            lab.nodes.return_value = []
            lab.download.return_value = f"lab:\n  title: smoke\n  notes: {CI_REPORT_MARKER}{{}}"
            client = MagicMock()
            client.join_existing_lab.return_value = lab
            mock_client_factory.return_value = client

            with patch(
                "topogen.cml_lab_evidence._collect_router_nodes",
                return_value=[],
            ):
                with tempfile.TemporaryDirectory() as tmp:
                    evidence = Path(tmp)
                    mgmt = evidence.parent / "nac" / "mgmt_sync.json"
                    mgmt.parent.mkdir(parents=True, exist_ok=True)
                    mgmt.write_text(
                        json.dumps({"synced": 4, "mapping": {"a": "b", "c": "d"}}),
                        encoding="utf-8",
                    )
                    result = capture_lab_evidence(
                        lab_id=LAB_ID,
                        evidence_dir=evidence,
                        mgmt_sync_path=mgmt,
                    )
                    self.assertTrue(Path(result["ci_report"]).is_file())
                    self.assertTrue(Path(result["lab_yaml"]).is_file())
                    loaded = json.loads(Path(result["ci_report"]).read_text(encoding="utf-8"))
                    self.assertEqual(loaded["mgmt_sync"]["synced"], 4)


if __name__ == "__main__":
    unittest.main()
