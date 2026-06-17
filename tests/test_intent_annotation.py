# File Chain (see DEVELOPER.md):
# Doc Version: v1.1.1
# Date Modified: 2026-06-07
#
# Purpose: TG-167 — scaled intent annotation placement (offline + online).
# Blast Radius: Test-only.

"""Unit tests for scaled intent annotation placement."""

from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import ANY, MagicMock

from topogen.render import (
    INTENT_ANNOTATION_PADDING,
    Renderer,
    _build_intent_description,
    _finalize_offline_yaml_with_intent,
    _intent_notes_html,
    _node_coords_from_cml_lab,
    _node_coords_from_offline_lines,
    _scaled_intent_annotation_xy,
)


class IntentAnnotationScalingTests(unittest.TestCase):
    def test_scaled_xy_down_only_no_x_padding(self) -> None:
        coords = [(0, 0), (600, 200), (600, 4000)]
        x1, y1 = _scaled_intent_annotation_xy(coords, padding=1500)
        self.assertEqual(x1, 600)
        self.assertEqual(y1, 4000 + INTENT_ANNOTATION_PADDING)

    def test_scaled_xy_empty_defaults_to_down_padding(self) -> None:
        self.assertEqual(
            _scaled_intent_annotation_xy([]),
            (0, INTENT_ANNOTATION_PADDING),
        )

    def test_node_coords_from_offline_lines_ignores_links(self) -> None:
        lines = [
            "lab:",
            "  title: t",
            "nodes:",
            "  - id: n0",
            "    x: 10",
            "    y: 20",
            "  - id: n1",
            "    x: 600",
            "    y: 3800",
            "links:",
            "  - id: l0",
        ]
        self.assertEqual(
            _node_coords_from_offline_lines(lines),
            [(10, 20), (600, 3800)],
        )

    def test_finalize_without_intent_spot_omits_marker_node(self) -> None:
        lines = [
            "nodes:",
            "  - id: n0",
            "    x: 10",
            "    y: 20",
            "links:",
        ]
        args = Namespace(intent_spot=False)
        out = _finalize_offline_yaml_with_intent(lines, "intent text", "0.3.1", args)
        text = "\n".join(out)
        self.assertIn("annotations:", text)
        self.assertNotIn("INTENT-SPOT", text)

    def test_finalize_with_intent_spot_adds_marker_node(self) -> None:
        lines = [
            "nodes:",
            "  - id: n0",
            "    x: 10",
            "    y: 20",
            "links:",
        ]
        args = Namespace(intent_spot=True)
        out = _finalize_offline_yaml_with_intent(lines, "intent text", "0.3.1", args)
        text = "\n".join(out)
        self.assertIn("INTENT-SPOT", text)
        self.assertIn("node_definition: unmanaged_switch", text)
        self.assertNotIn("node_definition: iosv", text.split("INTENT-SPOT")[1].split("links:")[0])

    def test_build_intent_description_online_context(self) -> None:
        args = Namespace(
            nodes=4,
            mode="simple",
            template="iosv",
            dev_template="iosv",
            enable_vrf=False,
            enable_mgmt=False,
            start_lab=False,
            cml_version="0.3.1",
            staging=False,
            yaml_output=None,
            labname="lab1",
            offline_yaml=None,
            remark=None,
            intent_spot=True,
            nac=False,
            terraform_cml2=False,
            cafile=None,
            pki_enabled=False,
            flat_group_size=20,
            loopback_255=False,
            gi0_zero=False,
            ntp_server=None,
            ntp_vrf=None,
            mgmt_vrf=None,
            mgmt_bridge=False,
            pair_vrf=None,
        )
        desc = _build_intent_description(args, context="online, simple")
        self.assertIn("(online, simple)", desc)
        self.assertIn("--intent-spot", desc)
        self.assertIn("--cml-version 0.3.1", desc)

    def test_intent_notes_html_escapes_markup(self) -> None:
        html = _intent_notes_html('say "hello" & <tag>')
        self.assertIn("&lt;tag&gt;", html)
        self.assertIn("&amp;", html)
        self.assertIn("opacity: 0", html)

    def test_node_coords_from_cml_lab(self) -> None:
        lab = MagicMock()
        n0 = MagicMock(x=10, y=200)
        n1 = MagicMock(x=600, y=3800)
        lab.nodes.return_value = [n0, n1]
        self.assertEqual(_node_coords_from_cml_lab(lab), [(10, 200), (600, 3800)])

    def test_apply_online_lab_intent_sets_metadata_and_marker(self) -> None:
        lab = MagicMock()
        n0 = MagicMock(x=0, y=200)
        lab.nodes.return_value = [n0]
        marker = MagicMock()
        renderer = MagicMock(spec=Renderer)
        renderer.args = Namespace(
            nodes=2,
            mode="simple",
            template="iosv",
            dev_template="iosv",
            enable_vrf=False,
            enable_mgmt=False,
            start_lab=False,
            cml_version=None,
            staging=False,
            yaml_output=None,
            labname="t",
            offline_yaml=None,
            remark=None,
            intent_spot=True,
            nac=False,
            terraform_cml2=False,
            cafile=None,
            pki_enabled=False,
            flat_group_size=20,
            loopback_255=False,
            gi0_zero=False,
            ntp_server=None,
            ntp_vrf=None,
            mgmt_vrf=None,
            mgmt_bridge=False,
            pair_vrf=None,
        )
        renderer.lab = lab
        renderer.create_node.return_value = marker

        Renderer._apply_online_lab_intent(renderer)

        self.assertTrue(lab.description)
        self.assertIn("opacity: 0", lab.notes)
        lab.create_annotation.assert_called_once()
        ann_kwargs = lab.create_annotation.call_args.kwargs
        self.assertEqual(ann_kwargs["x1"], 0)
        self.assertEqual(ann_kwargs["y1"], 200 + INTENT_ANNOTATION_PADDING)
        self.assertEqual(ann_kwargs["color"], "#FFFFFF")
        renderer.create_node.assert_called_once_with("INTENT-SPOT", "unmanaged_switch", ANY)

    def test_apply_online_lab_intent_skips_marker_without_flag(self) -> None:
        lab = MagicMock()
        lab.nodes.return_value = [MagicMock(x=0, y=0)]
        renderer = MagicMock(spec=Renderer)
        renderer.args = Namespace(
            nodes=2,
            mode="simple",
            template="iosv",
            dev_template="iosv",
            enable_vrf=False,
            enable_mgmt=False,
            start_lab=False,
            cml_version=None,
            staging=False,
            yaml_output=None,
            labname="t",
            offline_yaml=None,
            remark=None,
            intent_spot=False,
            nac=False,
            terraform_cml2=False,
            cafile=None,
            pki_enabled=False,
            flat_group_size=20,
            loopback_255=False,
            gi0_zero=False,
            ntp_server=None,
            ntp_vrf=None,
            mgmt_vrf=None,
            mgmt_bridge=False,
            pair_vrf=None,
        )
        renderer.lab = lab

        Renderer._apply_online_lab_intent(renderer)

        lab.create_annotation.assert_called_once()
        renderer.create_node.assert_not_called()


if __name__ == "__main__":
    unittest.main()
