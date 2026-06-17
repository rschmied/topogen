# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-13
#
# Purpose: TG-192 — unit tests for finalize-ci-lab / CI alias push (TG-190 console fallback).
# Blast Radius: Test-only.

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.cml_ci_finalize import (  # noqa: E402
    _alias_lines,
    apply_ci_aliases_pyats,
    build_lab_guide_html,
)


class TestCiFinalize(unittest.TestCase):
    def test_alias_lines_include_slaac_uptime_and_address(self):
        lines = _alias_lines(
            "TG-192",
            "GigabitEthernet5",
            "2001:db8:1700:21f8:7ec0:5054:ff:fe58:65c9",
        )
        text = "\n".join(lines)
        self.assertIn("alias exec slaac show ipv6 interface GigabitEthernet5", text)
        self.assertIn("alias exec uptime show version | include uptime", text)
        self.assertIn("2001:db8:1700:21f8:7ec0:5054:ff:fe58:65c9", text)
        self.assertIn("slaac_c05054fffe5865c9", text)

    def test_pyats_push_on_booted_router(self):
        lab = MagicMock()
        node = MagicMock(label="R1", state="BOOTED")
        with patch(
            "topogen.cml_ci_finalize._collect_router_nodes",
            return_value=[(1, node)],
        ):
            result = apply_ci_aliases_pyats(
                lab,
                jira_key="TG-192",
                router_ipv6={"iosv-01": "2001:db8::1"},
            )
        self.assertEqual(result["applied"], 1)
        node.update.assert_called_once()
        node.run_pyats_config_command.assert_called_once()
        node.run_pyats_command.assert_called_once_with("write memory", config=False)

    def test_guide_lists_mgmt(self):
        html_out = build_lab_guide_html(
            "TG-192",
            {"routers": {"R1": {"mgmt_ipv6": "2001:db8::1"}}},
            "GigabitEthernet5",
        )
        self.assertIn("TG-192", html_out)
        self.assertIn("2001:db8::1", html_out)
        self.assertIn("uptime", html_out)
        self.assertIn("slaac", html_out)

    def test_guide_lists_dual_stack(self):
        html_out = build_lab_guide_html(
            "TG-190",
            {
                "routers": {
                    "R1": {
                        "mgmt_ipv6": "2001:db8:1700::1",
                        "mgmt_ipv4": "192.168.1.10",
                    }
                }
            },
            "GigabitEthernet5",
        )
        self.assertIn("IPv6", html_out)
        self.assertIn("IPv4", html_out)
        self.assertIn("192.168.1.10", html_out)


if __name__ == "__main__":
    unittest.main()
