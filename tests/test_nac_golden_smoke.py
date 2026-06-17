# File Chain (see DEVELOPER.md):
# Doc Version: v1.0.1
# Date Modified: 2026-06-03
#
# - Called by: Developers/CI via unittest/pytest discovery
# - Reads from: tests/fixtures/nac committed golden outputs
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main, yaml.safe_load, optional ansible-inventory
#
# Purpose: Lock TG-143 NaC smoke/golden outputs through the real offline CLI path.
# Blast Radius: Test-only; no runtime behavior changes.

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.main import main  # pylint: disable=wrong-import-position


FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "nac"
EXPECTED_NAC_FILES = (
    "nac.yaml",
    "main.tf",
    "versions.tf",
    "terraform.tfvars.example",
    ".gitignore",
    "inventory.yaml",
    "ansible.cfg",
    "group_vars/all.yaml",
    "host_vars/iosv-01.yaml",
    "host_vars/iosv-02.yaml",
    "verify_reachability.yaml",
    "devices.yaml",
    "nac_metadata.yaml",
)
NAC_TOKENS = (
    r"\bconfiguration:",
    r"\bsystem:",
    r"\bhostname:",
    r"\bethernets:",
    r"\bloopbacks:",
    r"\baddress:",
    r"\baddress_mask:",
    r"\bhost:\s+\S+",
)
SECRET_PATTERNS = (
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"gh[pousr]_[0-9A-Za-z_]{20,}",
    r"sk_(?:live|test)_[0-9A-Za-z]{16,}",
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    r"mongodb://[^:\s]+:[^@\s]+@",
)


class TestNacGoldenSmoke(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def _generate_flat_nac(self, tmp: str, name: str, *, mgmt: bool = False, device_template: str = "iosv") -> Path:
        out_file = Path(tmp) / "out" / name / f"{name}.yaml"
        argv = [
            "2",
            "--nac",
            "--offline-yaml",
            str(out_file),
            "--mode",
            "flat",
            "--device-template",
            device_template,
            "--overwrite",
        ]
        if mgmt:
            argv.insert(-1, "--mgmt")
        rc = self._run_main(argv)
        self.assertEqual(rc, 0)
        return Path(tmp) / "out" / name / "nac"

    def _assert_full_tree_exists(self, nac_root: Path):
        for relative in EXPECTED_NAC_FILES:
            self.assertTrue((nac_root / relative).exists(), relative)

    def _assert_fixture_tree_bytes_match(self, fixture_name: str, generated_nac: Path):
        fixture_dir = FIXTURE_ROOT / fixture_name
        self._assert_full_tree_exists(fixture_dir)
        self._assert_full_tree_exists(generated_nac)
        for relative in EXPECTED_NAC_FILES:
            self.assertEqual(
                (fixture_dir / relative).read_bytes(),
                (generated_nac / relative).read_bytes(),
                relative,
            )

    def _assert_nac_smoke(self, nac_root: Path, *, mgmt_enabled: bool):
        nac_yaml = nac_root / "nac.yaml"
        text = nac_yaml.read_text(encoding="utf-8")
        payload = yaml.safe_load(text)
        self.assertIn("iosxe", payload)
        self.assertEqual(len(payload["iosxe"]["devices"]), 2)
        for token in NAC_TOKENS:
            self.assertRegex(text, token)
        for pattern in SECRET_PATTERNS:
            self.assertIsNone(re.search(pattern, text), pattern)

        # TG-163: the OOB management interface is provisioned out-of-band (DHCP)
        # by the CML day-0 template and must never be Terraform-managed. So with
        # or without --mgmt the managed config carries no Mgmt-vrf and no OOB
        # Management interface; --mgmt only changes the connection host.
        self.assertNotIn("vrf_forwarding", text)
        self.assertNotIn("OOB Management", text)
        for device in payload["iosxe"]["devices"]:
            config = device["configuration"]
            self.assertNotIn("vrfs", config)
            for iface in config["interfaces"]["ethernets"]:
                self.assertNotEqual(iface.get("description"), "OOB Management")
                self.assertFalse(iface.get("shutdown"))

        if mgmt_enabled:
            self.assertEqual(
                [device["host"] for device in payload["iosxe"]["devices"]],
                ["10.254.0.1", "10.254.0.2"],
            )

    def _assert_ansible_inventory_parses_when_available(self, nac_root: Path):
        ansible_inventory = shutil.which("ansible-inventory")
        if ansible_inventory is None:
            self.skipTest("ansible-inventory is not available on PATH")
        result = subprocess.run(
            [ansible_inventory, "--list", "-i", str(nac_root / "inventory.yaml")],
            cwd=nac_root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertIn("all", parsed)

    def test_golden_flat_no_mgmt_matches_real_cli_and_smokes(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_nac = self._generate_flat_nac(tmp, "golden-flat-no-mgmt")
            self._assert_fixture_tree_bytes_match("golden-flat-no-mgmt", generated_nac)
            self._assert_nac_smoke(generated_nac, mgmt_enabled=False)

    def test_golden_flat_mgmt_matches_real_cli_and_smokes(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_nac = self._generate_flat_nac(tmp, "golden-flat-mgmt", mgmt=True)
            self._assert_fixture_tree_bytes_match("golden-flat-mgmt", generated_nac)
            self._assert_nac_smoke(generated_nac, mgmt_enabled=True)

    def test_ansible_inventory_parses_no_mgmt(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_nac = self._generate_flat_nac(tmp, "golden-flat-no-mgmt")
            self._assert_ansible_inventory_parses_when_available(generated_nac)

    def test_ansible_inventory_parses_mgmt(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_nac = self._generate_flat_nac(tmp, "golden-flat-mgmt", mgmt=True)
            self._assert_ansible_inventory_parses_when_available(generated_nac)

    def test_csr_flat_slot_mapping_uses_csr_interface_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_nac = self._generate_flat_nac(tmp, "csr-flat", device_template="csr1000v")
            payload = yaml.safe_load((generated_nac / "nac.yaml").read_text(encoding="utf-8"))
            for device in payload["iosxe"]["devices"]:
                ethernet = device["configuration"]["interfaces"]["ethernets"][0]
                self.assertEqual(ethernet["type"], "GigabitEthernet")
                self.assertEqual(ethernet["id"], "1")
                self.assertNotEqual(ethernet["id"], "0/0")

    def test_flat_two_node_generation_has_no_empty_stub_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            generated_nac = self._generate_flat_nac(tmp, "flat-null-safety")
            text = (generated_nac / "nac.yaml").read_text(encoding="utf-8")
            payload = yaml.safe_load(text)
            self.assertNotIn("vrfs: []", text)
            self.assertNotIn("ethernets: []", text)
            self.assertNotIn("loopbacks: []", text)
            for device in payload["iosxe"]["devices"]:
                self.assertTrue(device["host"])
                self.assertTrue(device["configuration"]["interfaces"]["ethernets"])
                self.assertTrue(device["configuration"]["interfaces"]["loopbacks"])


if __name__ == "__main__":
    unittest.main()
