# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.0
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py offline renderer
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main
#
# Purpose: Verify TG-134 NaC-only IOS-XE day0 RESTCONF/netconf-yang injection.
# Blast Radius: Test-only; no runtime behavior changes.

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position


class TestNacDay0Restconf(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def test_nac_injects_transport_before_final_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-simple.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            yaml_file = Path(tmp) / "out" / "two-router-simple" / "two-router-simple.yaml"
            content = yaml_file.read_text(encoding="utf-8")
            self.assertIn(
                "\n      ip http secure-server\n"
                "      restconf\n"
                "      netconf-yang\n"
                "      end\n",
                content,
            )

    def test_non_nac_output_has_no_transport_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-simple.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            content = out_file.read_text(encoding="utf-8")
            self.assertNotIn("ip http secure-server", content)
            self.assertNotIn("restconf", content)
            self.assertNotIn("netconf-yang", content)


if __name__ == "__main__":
    unittest.main()
