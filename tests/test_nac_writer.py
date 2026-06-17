# File Chain (see DEVELOPER.md):
# Doc Version: v1.17.1
# Date Modified: 2026-06-13
#
# - Called by: Developers/CI via unittest discovery
# - Reads from: src/topogen/main.py, src/topogen/nac.py
# - Writes to: Temporary test directories only
# - Calls into: topogen.main.main, yaml.safe_load
#
# Purpose: Verify canonical NaC writer output layout, keys, deterministic rerun behavior, and DMVPN artifact paths.
# Blast Radius: Test-only; no runtime behavior changes.

import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from ipaddress import IPv4Interface
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from jinja2 import Environment, PackageLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from topogen.config import Config  # pylint: disable=wrong-import-position
from topogen.main import main  # pylint: disable=wrong-import-position
from topogen.models import TopogenInterface, TopogenNode  # pylint: disable=wrong-import-position
from topogen.nac import (  # pylint: disable=wrong-import-position
    DMVPN_IPSEC_PROFILE,
    _select_host,
    build_canonical_nac_model,
    project_nac_yaml,
    write_ansible_cfg,
    write_devices_yaml,
    write_nac_metadata_yaml,
    write_nac_yaml,
    write_nac_tree,
    write_terraform_scaffold,
    write_verify_reachability_yaml,
)


def _extract_day0_config(node: dict) -> str:
    cfg = node.get("configuration", "")
    if isinstance(cfg, list):
        return cfg[0].get("content", "") if cfg else ""
    return cfg


def _interface_names(config: str) -> list[str]:
    return re.findall(r"^interface (GigabitEthernet\S+)$", config, re.MULTILINE)


def _interface_stanza(config: str, iface_name: str) -> str:
    pattern = rf"^interface {re.escape(iface_name)}$(.*?)(?=^interface |\nend\n|\Z)"
    match = re.search(pattern, config, re.MULTILINE | re.DOTALL)
    return match.group(0) if match else ""


class TestNacWriter(unittest.TestCase):
    def _run_main(self, argv):
        with patch.object(sys, "argv", ["topogen", *argv]):
            return main()

    def test_nac_yaml_created_at_expected_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "iosv-test.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "iosv-test"
            cml_yaml = lab_root / "iosv-test.yaml"
            nac_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac.yaml"
            tfvars_json = Path(tmp) / "out" / "iosv-test" / "nac" / "terraform.tfvars.json"
            inventory_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "inventory.yaml"
            group_all_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "group_vars" / "all.yaml"
            host_vars_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "host_vars" / "iosv-01.yaml"
            ansible_cfg = Path(tmp) / "out" / "iosv-test" / "nac" / "ansible.cfg"
            verify_reachability_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "verify_reachability.yaml"
            devices_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "devices.yaml"
            metadata_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac_metadata.yaml"
            main_tf = Path(tmp) / "out" / "iosv-test" / "nac" / "main.tf"
            versions_tf = Path(tmp) / "out" / "iosv-test" / "nac" / "versions.tf"
            tfvars_example = Path(tmp) / "out" / "iosv-test" / "nac" / "terraform.tfvars.example"
            terraform_gitignore = Path(tmp) / "out" / "iosv-test" / "nac" / ".gitignore"
            self.assertTrue(cml_yaml.exists())
            self.assertTrue(nac_yaml.exists())
            self.assertFalse(tfvars_json.exists())
            self.assertTrue(inventory_yaml.exists())
            self.assertTrue(group_all_yaml.exists())
            self.assertTrue(host_vars_yaml.exists())
            self.assertTrue(ansible_cfg.exists())
            self.assertTrue(verify_reachability_yaml.exists())
            self.assertTrue(devices_yaml.exists())
            self.assertTrue(metadata_yaml.exists())
            self.assertTrue(main_tf.exists())
            self.assertTrue(versions_tf.exists())
            self.assertTrue(tfvars_example.exists())
            self.assertTrue(terraform_gitignore.exists())
            self.assertFalse((lab_root / "nac.yaml").exists())
            self.assertFalse((lab_root / "main.tf").exists())
            self.assertFalse((lab_root / "versions.tf").exists())
            self.assertFalse((lab_root / "inventory.yaml").exists())
            self.assertFalse((lab_root / "ansible.cfg").exists())
            self.assertFalse((lab_root / "verify_reachability.yaml").exists())
            self.assertFalse((lab_root / "group_vars").exists())
            self.assertFalse((lab_root / "host_vars").exists())

            data = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            self.assertIn("iosxe", data)
            self.assertIn("devices", data["iosxe"])
            self.assertEqual(len(data["iosxe"]["devices"]), 1)
            device = data["iosxe"]["devices"][0]
            self.assertEqual(list(device.keys()), ["name", "host", "configuration"])
            self.assertEqual(device["configuration"]["system"]["hostname"], "R1")
            for forbidden in (
                "hostname",
                "platform",
                "role",
                "template",
                "device_template",
                "mgmt",
                "metadata",
                "loopbacks",
                "interfaces",
            ):
                self.assertNotIn(forbidden, device)
            config = device["configuration"]
            self.assertNotIn("vrfs", config)
            ethernet = config["interfaces"]["ethernets"][0]
            self.assertEqual(
                list(ethernet.keys()),
                ["type", "id", "shutdown", "cdp", "ipv4", "description"],
            )
            self.assertFalse(ethernet["shutdown"])
            self.assertTrue(ethernet["cdp"])
            routing = config["routing"]["ospf_processes"][0]
            self.assertEqual(routing["id"], 1)
            self.assertEqual(
                routing["passive_interfaces"][0],
                {"interface_type": "Loopback", "interface_id": "0"},
            )
            self.assertEqual(ethernet["type"], "GigabitEthernet")
            self.assertEqual(ethernet["id"], "0/0")
            self.assertEqual(list(ethernet["ipv4"].keys()), ["address", "address_mask"])
            loopback = config["interfaces"]["loopbacks"][0]
            self.assertEqual(list(loopback.keys()), ["id", "ipv4"])
            self.assertEqual(loopback["id"], "0")
            self.assertEqual(list(loopback["ipv4"].keys()), ["address", "address_mask"])

            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertIn("all", inv)
            self.assertIn("hosts", inv["all"])
            self.assertIn("iosv-01", inv["all"]["hosts"])
            self.assertIn("ansible_host", inv["all"]["hosts"]["iosv-01"])
            self.assertIn("platform", inv["all"]["hosts"]["iosv-01"])

            grp = yaml.safe_load(group_all_yaml.read_text(encoding="utf-8"))
            self.assertIn("nac_platform", grp)
            self.assertIn("nac_device_count", grp)
            self.assertEqual(grp["ansible_connection"], "ansible.netcommon.network_cli")
            self.assertEqual(grp["ansible_network_os"], "cisco.ios.ios")
            self.assertEqual(grp["ansible_user"], "{{ lookup('env', 'IOSXE_USERNAME') }}")
            self.assertEqual(grp["ansible_password"], "{{ lookup('env', 'IOSXE_PASSWORD') }}")

            host_vars = yaml.safe_load(host_vars_yaml.read_text(encoding="utf-8"))
            for key in ("hostname", "role", "template", "device_template", "loopbacks", "interfaces"):
                self.assertIn(key, host_vars)

            ansible_cfg_text = ansible_cfg.read_text(encoding="utf-8")
            self.assertIn("[defaults]", ansible_cfg_text)
            self.assertIn("inventory = inventory.yaml", ansible_cfg_text)
            self.assertIn("host_key_checking = False", ansible_cfg_text)
            self.assertIn("LAB ONLY", ansible_cfg_text)

            reachability = yaml.safe_load(verify_reachability_yaml.read_text(encoding="utf-8"))
            self.assertEqual(len(reachability), 1)
            play = reachability[0]
            self.assertEqual(play["hosts"], "all")
            self.assertIs(play["gather_facts"], False)
            self.assertNotIn("connection", play)
            self.assertEqual(len(play["tasks"]), 1)
            task = play["tasks"][0]
            self.assertIn("cisco.ios.ios_facts", task)
            self.assertEqual(task["cisco.ios.ios_facts"]["gather_subset"], ["min"])
            self.assertNotIn("cisco.ios.ios_config", verify_reachability_yaml.read_text(encoding="utf-8"))

            devices_doc = yaml.safe_load(devices_yaml.read_text(encoding="utf-8"))
            self.assertIs(devices_doc["terraform_input"], False)
            self.assertIn("NOT a Terraform input", devices_doc["note"])
            self.assertIn("nac.yaml", devices_doc["note"])
            self.assertIn("yaml_files", devices_doc["note"])
            self.assertEqual(list(devices_doc.keys()), ["terraform_input", "note", "devices"])
            self.assertIn("devices", devices_doc)
            self.assertEqual(len(devices_doc["devices"]), 1)
            dev = devices_doc["devices"][0]
            for key in ("name", "hostname", "platform", "role", "mgmt_ip"):
                self.assertIn(key, dev)

            meta = yaml.safe_load(metadata_yaml.read_text(encoding="utf-8"))
            self.assertIs(meta["terraform_input"], False)
            self.assertIn("NOT a Terraform input", meta["note"])
            self.assertIn("nac.yaml", meta["note"])
            self.assertIn("yaml_files", meta["note"])
            self.assertEqual(list(meta.keys())[:2], ["terraform_input", "note"])
            for key in (
                "schema",
                "schema_version",
                "canonical_root",
                "contract",
                "epic_ref",
                "module",
                "provider",
                "generator",
                "mode",
                "template",
                "device_template",
                "device_count",
                "generated_artifacts",
            ):
                self.assertIn(key, meta)
            self.assertEqual(meta["schema"], "iosxe-devices-configuration-mvp")
            self.assertEqual(meta["schema_version"], "3.0.0")
            self.assertEqual(meta["canonical_root"], "iosxe.devices[]")
            self.assertEqual(meta["contract"], "lean iosxe.devices[].configuration.*")
            self.assertEqual(meta["epic_ref"], "TG-131")
            self.assertEqual(meta["module"], "netascode/nac-iosxe/iosxe 0.1.0")
            self.assertEqual(meta["provider"], "CiscoDevNet/iosxe 0.15.0")
            self.assertEqual(meta["generator"], "topogen")
            self.assertEqual(meta["mode"], "simple")
            self.assertEqual(meta["template"], "iosv")
            self.assertEqual(meta["device_template"], "iosv")
            self.assertEqual(meta["device_count"], 1)
            self.assertNotIn("ticket_ref", meta)
            self.assertEqual(
                meta["generated_artifacts"],
                [
                    "nac.yaml",
                    "main.tf",
                    "versions.tf",
                    "terraform.tfvars.example",
                    ".gitignore",
                    "inventory.yaml",
                    "ansible.cfg",
                    "group_vars/all.yaml",
                    "host_vars/iosv-01.yaml",
                    "verify_reachability.yaml",
                    "devices.yaml",
                    "sync-nac-mgmt.py",
                    "NAC-WORKFLOW.md",
                    "nac_metadata.yaml",
                ],
            )

    def test_dmvpn_flat_nac_writes_cml_yaml_and_nac_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "dmvpn-flat"
            cml_yaml = lab_root / "dmvpn-flat.yaml"
            nac_root = lab_root / "nac"
            nac_yaml = nac_root / "nac.yaml"
            self.assertTrue(cml_yaml.exists())
            self.assertTrue(nac_yaml.exists())
            self.assertTrue((nac_root / "inventory.yaml").exists())
            self.assertTrue((nac_root / "host_vars" / "iosv-01.yaml").exists())
            self.assertFalse((lab_root / "nac.yaml").exists())

            data = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            devices = data["iosxe"]["devices"]
            self.assertEqual([device["name"] for device in devices], ["iosv-01", "iosv-02", "iosv-03"])
            self.assertEqual(
                [device["configuration"]["system"]["hostname"] for device in devices],
                ["R1", "R2", "R3"],
            )
            for device in devices:
                ethernets = device["configuration"]["interfaces"]["ethernets"]
                tunnels = device["configuration"]["interfaces"]["tunnels"]
                self.assertEqual(ethernets[0]["description"], "dmvpn nbma")
                self.assertEqual(tunnels[0]["id"], "0")
                self.assertEqual(tunnels[0]["name"], "0")
                self.assertEqual(tunnels[0]["description"], "dmvpn tunnel")
                self.assertEqual(tunnels[0]["tunnel_source"], "GigabitEthernet0/0")
                self.assertIs(tunnels[0]["ipv4"]["redirects"], False)
            for host_name in ("iosv-01", "iosv-02", "iosv-03"):
                host_vars = nac_root / "host_vars" / f"{host_name}.yaml"
                self.assertTrue(host_vars.exists())

    def test_dmvpn_flat_pair_nac_writes_cml_yaml_and_nac_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-pair.yaml"
            rc = self._run_main(
                [
                    "4",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-underlay",
                    "flat-pair",
                    "--template",
                    "iosv-dmvpn",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "dmvpn-flat-pair"
            cml_yaml = lab_root / "dmvpn-flat-pair.yaml"
            nac_root = lab_root / "nac"
            nac_yaml = nac_root / "nac.yaml"
            self.assertTrue(cml_yaml.exists())
            self.assertTrue(nac_yaml.exists())
            expected_nac_files = [
                "nac.yaml",
                "main.tf",
                "versions.tf",
                "terraform.tfvars.example",
                ".gitignore",
                "ansible.cfg",
                "inventory.yaml",
                "group_vars/all.yaml",
                "host_vars/iosv-01.yaml",
                "host_vars/iosv-02.yaml",
                "host_vars/iosv-03.yaml",
                "host_vars/iosv-04.yaml",
                "verify_reachability.yaml",
                "devices.yaml",
                "nac_metadata.yaml",
            ]
            for rel_path in expected_nac_files:
                self.assertTrue((nac_root / rel_path).exists(), rel_path)
            self.assertFalse((lab_root / "nac.yaml").exists())

            cml_text = cml_yaml.read_text(encoding="utf-8")
            self.assertIn("restconf", cml_text)
            self.assertIn("netconf-yang", cml_text)

            main_tf = (nac_root / "main.tf").read_text(encoding="utf-8")
            tfvars_example = (nac_root / "terraform.tfvars.example").read_text(encoding="utf-8")
            self.assertIn("IOSXE_URL", main_tf)
            self.assertIn("IOSXE_USERNAME", main_tf)
            self.assertIn("IOSXE_PASSWORD", main_tf)
            self.assertIn('IOSXE_URL="https://<lab-device-url>"', tfvars_example)
            self.assertNotIn("password =", tfvars_example)
            self.assertNotIn("cisco", main_tf.lower().replace("ciscodevnet", ""))

            data = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            devices = data["iosxe"]["devices"]
            self.assertEqual(
                [device["name"] for device in devices],
                ["iosv-01", "iosv-02", "iosv-03", "iosv-04"],
            )
            self.assertEqual(
                [device["configuration"]["system"]["hostname"] for device in devices],
                ["R1", "R2", "R3", "R4"],
            )
            self.assertEqual(
                [iface["description"] for iface in devices[0]["configuration"]["interfaces"]["ethernets"]],
                ["dmvpn nbma", "pair link"],
            )
            self.assertEqual(
                [(iface["id"], iface["description"]) for iface in devices[0]["configuration"]["interfaces"]["ethernets"]],
                [("0/0", "dmvpn nbma"), ("0/1", "pair link")],
            )
            self.assertEqual(
                [(iface["id"], iface["description"]) for iface in devices[0]["configuration"]["interfaces"]["tunnels"]],
                [("0", "dmvpn tunnel")],
            )
            self.assertEqual(
                [(iface["name"], iface["description"]) for iface in devices[0]["configuration"]["interfaces"]["tunnels"]],
                [("0", "dmvpn tunnel")],
            )
            hub_tunnel = devices[0]["configuration"]["interfaces"]["tunnels"][0]
            self.assertEqual(hub_tunnel["tunnel_source"], "GigabitEthernet0/0")
            self.assertIs(hub_tunnel["ipv4"]["redirects"], False)
            self.assertEqual(
                [iface["description"] for iface in devices[1]["configuration"]["interfaces"]["ethernets"]],
                ["pair link"],
            )
            self.assertEqual(
                [(iface["id"], iface["description"]) for iface in devices[1]["configuration"]["interfaces"]["ethernets"]],
                [("0/0", "pair link")],
            )
            self.assertNotIn("tunnels", devices[1]["configuration"]["interfaces"])

    def test_dmvpn_flat_nac_with_mgmt_uses_oob_hosts_and_tunnel_interfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-mgmt.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--mgmt",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            nac_root = Path(tmp) / "out" / "dmvpn-flat-mgmt" / "nac"
            nac_yaml = nac_root / "nac.yaml"
            inventory_yaml = nac_root / "inventory.yaml"
            data = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            inventory = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            devices = data["iosxe"]["devices"]
            self.assertEqual([device["name"] for device in devices], ["iosv-01", "iosv-02", "iosv-03"])
            self.assertEqual([device["host"] for device in devices], ["10.254.0.1", "10.254.0.2", "10.254.0.3"])
            self.assertEqual(
                [inventory["all"]["hosts"][device["name"]]["ansible_host"] for device in devices],
                ["10.254.0.1", "10.254.0.2", "10.254.0.3"],
            )

            hub_interfaces = devices[0]["configuration"]["interfaces"]
            self.assertEqual(
                [(iface["id"], iface["description"]) for iface in hub_interfaces["tunnels"]],
                [("0", "dmvpn tunnel")],
            )
            self.assertEqual(
                [(iface["name"], iface["description"]) for iface in hub_interfaces["tunnels"]],
                [("0", "dmvpn tunnel")],
            )
            # TG-163: the OOB management interface is provisioned out-of-band
            # (DHCP) by the CML day-0 template and must never be emitted as a
            # Terraform-managed interface. It only drives connection-host
            # selection (asserted via device["host"] above).
            self.assertFalse(
                any(
                    iface.get("description") == "OOB Management"
                    for iface in hub_interfaces["ethernets"]
                )
            )
            self.assertNotIn("vrfs", devices[0]["configuration"])

            host_vars = yaml.safe_load((nac_root / "host_vars" / "iosv-01.yaml").read_text(encoding="utf-8"))
            self.assertEqual(host_vars["hostname"], "R1")
            self.assertTrue(
                any(iface.get("name") == "Tunnel0" and iface.get("description") == "dmvpn tunnel"
                    for iface in host_vars["interfaces"])
            )
            self.assertTrue(
                any(iface.get("description") == "OOB Management" for iface in host_vars["interfaces"])
            )

    def test_dmvpn_flat_pair_without_nac_keeps_original_output_path_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-pair.yaml"
            rc = self._run_main(
                [
                    "4",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-underlay",
                    "flat-pair",
                    "--template",
                    "iosv-dmvpn",
                    "--offline-yaml",
                    str(out_file),
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "dmvpn-flat-pair"
            self.assertTrue(out_file.exists())
            self.assertFalse((lab_root / "dmvpn-flat-pair.yaml").exists())
            self.assertFalse((lab_root / "nac").exists())

            cml_text = out_file.read_text(encoding="utf-8")
            self.assertIn("label: R1", cml_text)
            self.assertIn("label: R4", cml_text)
            self.assertIn("label: GigabitEthernet0/1", cml_text)
            self.assertNotIn("restconf", cml_text)
            self.assertNotIn("netconf-yang", cml_text)

    def test_dmvpn_flat_without_nac_keeps_original_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--offline-yaml",
                    str(out_file),
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out_file.exists())
            self.assertFalse((Path(tmp) / "out" / "dmvpn-flat" / "dmvpn-flat.yaml").exists())
            self.assertFalse((Path(tmp) / "out" / "dmvpn-flat" / "nac").exists())

    def test_ansible_stub_content_is_parseable_read_only_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                ],
            )
            nac_root = Path(tmp) / "nac"
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="iosv",
                mode="simple",
                overwrite=True,
            )

            ansible_cfg = (nac_root / "ansible.cfg").read_text(encoding="utf-8")
            self.assertIn("[defaults]", ansible_cfg)
            self.assertIn("inventory = inventory.yaml", ansible_cfg)
            self.assertIn("host_key_checking = False", ansible_cfg)

            group_vars_path = nac_root / "group_vars" / "all.yaml"
            group_vars_text = group_vars_path.read_text(encoding="utf-8")
            group_vars = yaml.safe_load(group_vars_text)
            self.assertEqual(group_vars["ansible_connection"], "ansible.netcommon.network_cli")
            self.assertEqual(group_vars["ansible_network_os"], "cisco.ios.ios")
            self.assertEqual(group_vars["ansible_user"], "{{ lookup('env', 'IOSXE_USERNAME') }}")
            self.assertEqual(group_vars["ansible_password"], "{{ lookup('env', 'IOSXE_PASSWORD') }}")
            self.assertIn("IOSXE_USERNAME", group_vars_text)
            self.assertIn("IOSXE_PASSWORD", group_vars_text)
            for forbidden in ("admin", "cisco123", "lab-password", "<lab-password>", "secret_value"):
                self.assertNotIn(forbidden, group_vars_text.lower())

            playbook_path = nac_root / "verify_reachability.yaml"
            playbook_text = playbook_path.read_text(encoding="utf-8")
            playbook = yaml.safe_load(playbook_text)
            self.assertIsInstance(playbook, list)
            self.assertEqual(len(playbook), 1)
            self.assertEqual(playbook[0]["hosts"], "all")
            self.assertIs(playbook[0]["gather_facts"], False)
            self.assertEqual(len(playbook[0]["tasks"]), 1)
            self.assertIn("cisco.ios.ios_facts", playbook[0]["tasks"][0])
            self.assertEqual(playbook[0]["tasks"][0]["cisco.ios.ios_facts"]["gather_subset"], ["min"])
            self.assertNotIn("ios_config", playbook_text)
            self.assertNotIn("config:", playbook_text)
            self.assertNotIn("username", playbook_text.lower())
            self.assertNotIn("password", playbook_text.lower())

    def test_ansible_stub_refuses_clobber_and_reemit_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            ansible_cfg = Path(tmp) / "ansible.cfg"
            verify_yaml = Path(tmp) / "verify_reachability.yaml"
            write_ansible_cfg(ansible_cfg, overwrite=True)
            write_verify_reachability_yaml(verify_yaml, overwrite=True)
            first_cfg = ansible_cfg.read_text(encoding="utf-8")
            first_verify = verify_yaml.read_text(encoding="utf-8")

            with self.assertRaises(Exception) as cfg_cm:
                write_ansible_cfg(ansible_cfg, overwrite=False)
            self.assertIn("Refusing to overwrite existing file", str(cfg_cm.exception))
            with self.assertRaises(Exception) as verify_cm:
                write_verify_reachability_yaml(verify_yaml, overwrite=False)
            self.assertIn("Refusing to overwrite existing file", str(verify_cm.exception))

            write_ansible_cfg(ansible_cfg, overwrite=True)
            write_verify_reachability_yaml(verify_yaml, overwrite=True)
            self.assertEqual(first_cfg, ansible_cfg.read_text(encoding="utf-8"))
            self.assertEqual(first_verify, verify_yaml.read_text(encoding="utf-8"))

    def test_terraform_scaffold_content_is_pinned_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            nac_root = Path(tmp) / "lab" / "nac"
            write_terraform_scaffold(nac_root, overwrite=True)

            main_tf = (nac_root / "main.tf").read_text(encoding="utf-8")
            self.assertIn('source     = "netascode/nac-iosxe/iosxe"', main_tf)
            self.assertIn('version    = "0.1.0"', main_tf)
            self.assertIn('yaml_files = ["nac.yaml"]', main_tf)
            self.assertIn("terraform -chdir=<lab>/nac", main_tf)
            self.assertIn("Run Terraform from this nac/ directory", main_tf)
            self.assertIn("IOSXE_URL", main_tf)
            self.assertIn("IOSXE_USERNAME", main_tf)
            self.assertIn("IOSXE_PASSWORD", main_tf)
            self.assertIn("LAB ONLY", main_tf)
            self.assertIn("insecure disables TLS certificate verification", main_tf)
            self.assertIn("throwaway lab gear", main_tf)
            self.assertIn("insecure = true", main_tf)

            versions_tf = (nac_root / "versions.tf").read_text(encoding="utf-8")
            self.assertIn('required_version = ">= 1.8.0"', versions_tf)
            self.assertIn('source  = "CiscoDevNet/iosxe"', versions_tf)
            self.assertIn('version = "0.15.0"', versions_tf)
            self.assertNotIn("0.18.0", versions_tf)

            tfvars_example = (nac_root / "terraform.tfvars.example").read_text(encoding="utf-8")
            self.assertIn('yaml_files = ["nac.yaml"]', tfvars_example)
            self.assertIn('IOSXE_URL="https://<lab-device-url>"', tfvars_example)
            self.assertIn('IOSXE_USERNAME="<lab-username>"', tfvars_example)
            self.assertIn('IOSXE_PASSWORD="<lab-password>"', tfvars_example)
            self.assertNotIn("url =", tfvars_example)
            self.assertNotIn("username =", tfvars_example)
            self.assertNotIn("password =", tfvars_example)

            gitignore_lines = (nac_root / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertEqual(gitignore_lines, [".terraform/", "*.tfstate*", "terraform.tfvars"])

            for content in (main_tf, versions_tf, tfvars_example):
                self.assertNotIn("10.", content)
                self.assertNotIn("172.", content)
                self.assertNotIn("192.168.", content)
                self.assertNotIn("admin", content.lower())
                self.assertNotIn("cisco", content.lower().replace("ciscodevnet", ""))

    def test_terraform_scaffold_refuses_clobber_and_reemit_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            nac_root = Path(tmp) / "nac"
            write_terraform_scaffold(nac_root, overwrite=True)
            first = {
                path.name: path.read_text(encoding="utf-8")
                for path in (
                    nac_root / "main.tf",
                    nac_root / "versions.tf",
                    nac_root / "terraform.tfvars.example",
                    nac_root / ".gitignore",
                )
            }

            with self.assertRaises(Exception) as cm:
                write_terraform_scaffold(nac_root, overwrite=False)
            self.assertIn("Refusing to overwrite existing file", str(cm.exception))

            write_terraform_scaffold(nac_root, overwrite=True)
            second = {
                path.name: path.read_text(encoding="utf-8")
                for path in (
                    nac_root / "main.tf",
                    nac_root / "versions.tf",
                    nac_root / "terraform.tfvars.example",
                    nac_root / ".gitignore",
                )
            }
            self.assertEqual(first, second)

    def test_nac_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "iosv-test.yaml"
            argv = [
                "1",
                "--mode",
                "simple",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)

            nac_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac.yaml"
            tfvars_json = Path(tmp) / "out" / "iosv-test" / "nac" / "terraform.tfvars.json"
            inventory_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "inventory.yaml"
            group_all_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "group_vars" / "all.yaml"
            host_vars_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "host_vars" / "iosv-01.yaml"
            ansible_cfg = Path(tmp) / "out" / "iosv-test" / "nac" / "ansible.cfg"
            verify_reachability_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "verify_reachability.yaml"
            devices_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "devices.yaml"
            metadata_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac_metadata.yaml"
            main_tf = Path(tmp) / "out" / "iosv-test" / "nac" / "main.tf"
            versions_tf = Path(tmp) / "out" / "iosv-test" / "nac" / "versions.tf"
            tfvars_example = Path(tmp) / "out" / "iosv-test" / "nac" / "terraform.tfvars.example"
            terraform_gitignore = Path(tmp) / "out" / "iosv-test" / "nac" / ".gitignore"
            nested_bad = Path(tmp) / "out" / "iosv-test" / "iosv-test" / "nac" / "nac.yaml"
            self.assertTrue(nac_yaml.exists())
            self.assertFalse(tfvars_json.exists())
            self.assertTrue(inventory_yaml.exists())
            self.assertTrue(group_all_yaml.exists())
            self.assertTrue(host_vars_yaml.exists())
            self.assertTrue(ansible_cfg.exists())
            self.assertTrue(verify_reachability_yaml.exists())
            self.assertTrue(devices_yaml.exists())
            self.assertTrue(metadata_yaml.exists())
            self.assertTrue(main_tf.exists())
            self.assertTrue(versions_tf.exists())
            self.assertTrue(tfvars_example.exists())
            self.assertTrue(terraform_gitignore.exists())
            self.assertFalse(nested_bad.exists())

            content_a = nac_yaml.read_text(encoding="utf-8")
            content_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(content_a, content_b)
            inv_a = inventory_yaml.read_text(encoding="utf-8")
            inv_b = inventory_yaml.read_text(encoding="utf-8")
            self.assertEqual(inv_a, inv_b)
            grp_a = group_all_yaml.read_text(encoding="utf-8")
            grp_b = group_all_yaml.read_text(encoding="utf-8")
            self.assertEqual(grp_a, grp_b)
            hv_a = host_vars_yaml.read_text(encoding="utf-8")
            hv_b = host_vars_yaml.read_text(encoding="utf-8")
            self.assertEqual(hv_a, hv_b)
            ansible_cfg_a = ansible_cfg.read_text(encoding="utf-8")
            ansible_cfg_b = ansible_cfg.read_text(encoding="utf-8")
            self.assertEqual(ansible_cfg_a, ansible_cfg_b)
            verify_a = verify_reachability_yaml.read_text(encoding="utf-8")
            verify_b = verify_reachability_yaml.read_text(encoding="utf-8")
            self.assertEqual(verify_a, verify_b)
            devices_a = devices_yaml.read_text(encoding="utf-8")
            devices_b = devices_yaml.read_text(encoding="utf-8")
            self.assertEqual(devices_a, devices_b)
            meta_a = metadata_yaml.read_text(encoding="utf-8")
            meta_b = metadata_yaml.read_text(encoding="utf-8")
            self.assertEqual(meta_a, meta_b)
            main_a = main_tf.read_text(encoding="utf-8")
            main_b = main_tf.read_text(encoding="utf-8")
            self.assertEqual(main_a, main_b)
            versions_a = versions_tf.read_text(encoding="utf-8")
            versions_b = versions_tf.read_text(encoding="utf-8")
            self.assertEqual(versions_a, versions_b)
            example_a = tfvars_example.read_text(encoding="utf-8")
            example_b = tfvars_example.read_text(encoding="utf-8")
            self.assertEqual(example_a, example_b)
            gitignore_a = terraform_gitignore.read_text(encoding="utf-8")
            gitignore_b = terraform_gitignore.read_text(encoding="utf-8")
            self.assertEqual(gitignore_a, gitignore_b)

    def test_write_nac_tree_does_not_emit_auto_loaded_tfvars_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                ],
            )
            nac_root = Path(tmp) / "nac"
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="iosv",
                mode="simple",
                overwrite=True,
            )
            self.assertFalse((nac_root / "terraform.tfvars.json").exists())
            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertNotIn("terraform.tfvars.json", metadata["generated_artifacts"])

    def test_informational_yaml_writers_refuse_clobber_and_reemit_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                ],
            )
            model = build_canonical_nac_model(
                node,
                device_template="iosv",
                template="iosv",
                mode="simple",
            )
            devices_path = Path(tmp) / "devices.yaml"
            metadata_path = Path(tmp) / "nac_metadata.yaml"
            write_devices_yaml(model, devices_path, overwrite=True)
            write_nac_metadata_yaml(model, metadata_path, overwrite=True)
            first_devices = devices_path.read_text(encoding="utf-8")
            first_metadata = metadata_path.read_text(encoding="utf-8")

            with self.assertRaises(Exception) as devices_cm:
                write_devices_yaml(model, devices_path, overwrite=False)
            self.assertIn("Refusing to overwrite existing file", str(devices_cm.exception))
            with self.assertRaises(Exception) as metadata_cm:
                write_nac_metadata_yaml(model, metadata_path, overwrite=False)
            self.assertIn("Refusing to overwrite existing file", str(metadata_cm.exception))

            write_devices_yaml(model, devices_path, overwrite=True)
            write_nac_metadata_yaml(model, metadata_path, overwrite=True)
            self.assertEqual(first_devices, devices_path.read_text(encoding="utf-8"))
            self.assertEqual(first_metadata, metadata_path.read_text(encoding="utf-8"))

    def test_write_nac_tree_emits_mgmt_sync_scaffold_dhcp_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                ],
            )
            args = SimpleNamespace(
                enable_mgmt=True,
                mgmt_slot=5,
                mgmt_vrf="Mgmt-vrf",
                mgmt_ipv6_mode=None,
                mgmt_bridge=True,
            )
            nac_root = Path(tmp) / "nac"
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="iosv",
                mode="simple",
                args=args,
                overwrite=True,
            )
            sync_script = nac_root / "sync-nac-mgmt.py"
            workflow = nac_root / "NAC-WORKFLOW.md"
            self.assertTrue(sync_script.is_file())
            self.assertTrue(workflow.is_file())
            self.assertIn("topogen.nac_mgmt_sync", sync_script.read_text(encoding="utf-8"))
            self.assertIn("mgmt_sync.json", workflow.read_text(encoding="utf-8"))
            self.assertFalse((nac_root / "ssh-fanout.py").exists())

            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual(metadata["mgmt_mode"], "dhcp")
            self.assertEqual(metadata["mgmt_vrf"], "Mgmt-vrf")
            self.assertEqual(metadata["mgmt_interface"], "GigabitEthernet0/5")
            self.assertIn("sync-nac-mgmt.py", metadata["generated_artifacts"])

    def test_write_nac_tree_emits_slaac_ipv6_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                ],
            )
            args = SimpleNamespace(
                enable_mgmt=True,
                mgmt_slot=5,
                mgmt_vrf="Mgmt-vrf",
                mgmt_ipv6_mode="slaac",
                mgmt_bridge=True,
            )
            nac_root = Path(tmp) / "nac"
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="iosv",
                mode="simple",
                args=args,
                overwrite=True,
            )
            self.assertTrue((nac_root / "ssh-fanout.py").is_file())
            self.assertTrue((nac_root / "router-hosts.csv").is_file())
            hosts_csv = (nac_root / "router-hosts.csv").read_text(encoding="utf-8")
            self.assertIn("label,canonical,hostname,ipv6_mgmt", hosts_csv)
            self.assertIn("R1,iosv-01,R1", hosts_csv)

            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual(metadata["mgmt_mode"], "slaac")
            self.assertEqual(metadata["mgmt_ipv6_mode"], "slaac")
            self.assertTrue(metadata["mgmt_ipv6_only"])
            sync_script = nac_root / "sync-nac-mgmt.py"
            self.assertIn('DEFAULT_MODE = "slaac"', sync_script.read_text(encoding="utf-8"))

    def test_inventory_ansible_host_uses_host_ip_for_cidr(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "iosv-test.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            inventory_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "inventory.yaml"
            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            nac_yaml = Path(tmp) / "out" / "iosv-test" / "nac" / "nac.yaml"
            nac = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            self.assertEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], nac["iosxe"]["devices"][0]["host"])
            self.assertNotEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], "10.0.0.1")

    def test_write_nac_yaml_projects_fat_model_without_mutating_other_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                ],
            )
            model = build_canonical_nac_model(
                node,
                device_template="iosv",
                template="iosv",
                mode="simple",
            )
            fat_device = model["iosxe"]["devices"][0]
            for key in ("hostname", "platform", "role", "template", "mgmt", "metadata", "interfaces", "loopbacks"):
                self.assertIn(key, fat_device)

            nac_path = Path(tmp) / "nac.yaml"
            write_nac_yaml(model, nac_path, overwrite=True)
            lean_device = yaml.safe_load(nac_path.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            self.assertEqual(list(lean_device.keys()), ["name", "host", "configuration"])
            self.assertEqual(list(project_nac_yaml(model)["iosxe"]["devices"][0].keys()), ["name", "host", "configuration"])

            devices_path = Path(tmp) / "devices.yaml"
            write_devices_yaml(model, devices_path, overwrite=True)
            devices_doc = yaml.safe_load(devices_path.read_text(encoding="utf-8"))
            self.assertIs(devices_doc["terraform_input"], False)
            self.assertIn("NOT a Terraform input", devices_doc["note"])
            self.assertEqual(list(devices_doc["devices"][0].keys()), ["name", "hostname", "platform", "role", "mgmt_ip"])

    def test_nac_yaml_dump_is_byte_identical_across_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(
                hostname="R1",
                loopback=IPv4Interface("10.0.0.1/32"),
                interfaces=[
                    TopogenInterface(address=IPv4Interface("172.16.0.6/30"), vrf="tenant", slot=1),
                ],
            )
            model = build_canonical_nac_model(
                node,
                device_template="iosv",
                template="iosv",
                mode="flat-pair",
            )
            first = Path(tmp) / "first.yaml"
            second = Path(tmp) / "second.yaml"
            write_nac_yaml(model, first, overwrite=True)
            write_nac_yaml(model, second, overwrite=True)
            self.assertEqual(first.read_text(encoding="utf-8"), second.read_text(encoding="utf-8"))

    def test_nac_yaml_projection_omits_empty_stub_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(hostname="R1", loopback=None, interfaces=[{"description": "no-address"}])
            model = build_canonical_nac_model(
                node,
                device_template="iosv",
                template="iosv",
                mode="simple",
            )
            nac_path = Path(tmp) / "nac.yaml"
            write_nac_yaml(model, nac_path, overwrite=True)
            device = yaml.safe_load(nac_path.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            self.assertEqual(list(device.keys()), ["name", "configuration"])
            self.assertNotIn("host", device)
            self.assertNotIn("interfaces", device["configuration"])
            self.assertNotIn("vrfs", device["configuration"])

    def test_devices_yaml_mgmt_ip_uses_host_ip_for_cidr(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = {
                "iosxe": {
                    "devices": [
                        {
                            "name": "iosv-01",
                            "hostname": "iosv-01",
                            "platform": "iosxe",
                            "role": "router",
                            "mgmt": {"ipv4": "10.254.0.11/24"},
                        }
                    ]
                }
            }
            out_path = Path(tmp) / "devices.yaml"
            write_devices_yaml(model, out_path, overwrite=True)
            devices_doc = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            self.assertIs(devices_doc["terraform_input"], False)
            self.assertIn("NOT a Terraform input", devices_doc["note"])
            self.assertEqual(devices_doc["devices"][0]["mgmt_ip"], "10.254.0.11")

    def test_missing_interfaces_emits_empty_list_without_crash(self):
        node = TopogenNode(hostname="r1", loopback=None, interfaces=[])
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="x",
            mode="simple",
        )
        device = model["iosxe"]["devices"][0]
        self.assertEqual(device["interfaces"], [])

    def test_missing_loopback_uses_deterministic_empty_fallbacks(self):
        node = TopogenNode(hostname="r1", loopback=None, interfaces=[])
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="x",
            mode="simple",
        )
        device = model["iosxe"]["devices"][0]
        self.assertEqual(device["mgmt"]["ipv4"], "")
        self.assertEqual(device["loopbacks"], [])

    def test_select_host_uses_slot_zero_data_without_mgmt(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                TopogenInterface(address=IPv4Interface("172.16.0.10/30"), slot=1),
            ],
        )
        self.assertEqual(_select_host(node, SimpleNamespace(enable_mgmt=False)), "172.16.0.6")

    def test_select_host_uses_oob_mgmt_when_enabled(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
                TopogenInterface(
                    address=IPv4Interface("10.254.0.1/16"),
                    vrf="Mgmt-vrf",
                    description="OOB Management",
                    slot=5,
                ),
            ],
        )
        self.assertEqual(_select_host(node, SimpleNamespace(enable_mgmt=True)), "10.254.0.1")

    def test_select_host_has_no_loopback_fallback(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[],
        )
        self.assertEqual(_select_host(node, SimpleNamespace(enable_mgmt=False)), "")

    def test_vrf_mapping_emits_forwarding_and_vrf_definition(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), vrf="tenant", slot=1),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="flat-pair",
        )
        config = model["iosxe"]["devices"][0]["configuration"]
        self.assertEqual(config["interfaces"]["ethernets"][0]["vrf_forwarding"], "tenant")
        self.assertEqual(config["vrfs"], [{"name": "tenant"}])

    def test_global_table_omits_vrf_keys(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="simple",
        )
        config = model["iosxe"]["devices"][0]["configuration"]
        self.assertNotIn("vrfs", config)
        self.assertNotIn("vrf_forwarding", config["interfaces"]["ethernets"][0])

    def test_csr_mgmt_emits_post_oob_data_interfaces(self):
        """CSR Gi6+ data links must be Terraform-managed; only OOB Gi5 is excluded."""
        node = TopogenNode(
            hostname="R5",
            loopback=IPv4Interface("10.0.0.5/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.14/30"), slot=0, description="to R1"),
                TopogenInterface(
                    address=None,
                    vrf="Mgmt-vrf",
                    description="OOB Management",
                    slot=4,
                ),
                TopogenInterface(address=IPv4Interface("172.16.0.73/30"), slot=5, description="to R12"),
                TopogenInterface(address=IPv4Interface("172.16.0.65/30"), slot=6, description="to R16"),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="csr1000v",
            template="csr-eigrp",
            mode="nx",
            args=SimpleNamespace(enable_mgmt=True, mgmt_slot=5, mgmt_bridge=True),
        )
        ethernets = model["iosxe"]["devices"][0]["configuration"]["interfaces"]["ethernets"]
        self.assertEqual(
            [(iface["id"], iface.get("description")) for iface in ethernets],
            [
                ("1", "to R1"),
                ("6", "to R12"),
                ("7", "to R16"),
            ],
        )
        self.assertFalse(any(iface.get("description") == "OOB Management" for iface in ethernets))

    def _high_degree_csr_node(self) -> TopogenNode:
        return TopogenNode(
            hostname="R5",
            loopback=IPv4Interface("10.0.0.5/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.14/30"), slot=0, description="to R1"),
                TopogenInterface(
                    address=None,
                    vrf="Mgmt-vrf",
                    description="OOB Management",
                    slot=4,
                ),
                TopogenInterface(address=IPv4Interface("172.16.0.73/30"), slot=5, description="to R12"),
                TopogenInterface(address=IPv4Interface("172.16.0.65/30"), slot=6, description="to R16"),
            ],
        )

    def test_csr_day0_uses_topo_slot_not_loop_index(self):
        """TG-169: CSR data-plane Gi numbers must follow iface.slot + 1 after mgmt skip."""
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        tpl = env.get_template("csr-ospf.jinja2")
        node = self._high_degree_csr_node()
        rendered = tpl.render(
            config=Config(),
            node=node,
            date=datetime.now(timezone.utc),
            mgmt={"enabled": True, "slot": 5, "vrf": "Mgmt-vrf", "gw": None, "ipv4_dhcp": True},
        )
        names = _interface_names(rendered)
        self.assertEqual(names.count("GigabitEthernet5"), 1)
        gi5 = _interface_stanza(rendered, "GigabitEthernet5")
        self.assertIn("ip address dhcp", gi5)
        self.assertIn("no cdp enable", gi5)
        self.assertIn("OOB Management", gi5)
        gi6 = _interface_stanza(rendered, "GigabitEthernet6")
        self.assertIn("172.16.0.73", gi6)
        self.assertIn("to R12", gi6)
        gi7 = _interface_stanza(rendered, "GigabitEthernet7")
        self.assertIn("172.16.0.65", gi7)
        self.assertIn("network 172.16.0.73 0.0.0.0 area 0", rendered)
        self.assertIn("network 172.16.0.65 0.0.0.0 area 0", rendered)
        self.assertNotRegex(rendered, r"interface GigabitEthernet5\n.*ip address 172\.16")

    def test_iosv_day0_uses_topo_slot_not_loop_index(self):
        """TG-169: IOSv data-plane Gi numbers must follow iface.slot after mgmt skip."""
        env = Environment(loader=PackageLoader("topogen"), autoescape=select_autoescape())
        tpl = env.get_template("iosv.jinja2")
        node = TopogenNode(
            hostname="R5",
            loopback=IPv4Interface("10.0.0.5/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.14/30"), slot=0, description="to R1"),
                TopogenInterface(
                    address=None,
                    vrf="Mgmt-vrf",
                    description="OOB Management",
                    slot=5,
                ),
                TopogenInterface(address=IPv4Interface("172.16.0.73/30"), slot=6, description="to R12"),
            ],
        )
        rendered = tpl.render(
            config=Config(),
            node=node,
            date=datetime.now(timezone.utc),
            mgmt={"enabled": True, "slot": 5, "vrf": "Mgmt-vrf", "gw": None, "ipv4_dhcp": True},
        )
        names = _interface_names(rendered)
        self.assertEqual(names.count("GigabitEthernet0/5"), 1)
        gi5 = _interface_stanza(rendered, "GigabitEthernet0/5")
        self.assertIn("ip address dhcp", gi5)
        gi6 = _interface_stanza(rendered, "GigabitEthernet0/6")
        self.assertIn("172.16.0.73", gi6)
        self.assertNotRegex(rendered, r"interface GigabitEthernet0/5\n.*ip address 172\.16")

    def test_nx_mgmt_bridge_offline_yaml_no_duplicate_csr_gi5(self):
        """TG-169: nx + mgmt-bridge CSR day-0 must not double-book Gi5 on high-degree nodes."""
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "nx-mgmt-bridge-csr.yaml"
            rc = self._run_main(
                [
                    "10",
                    "--mode",
                    "nx",
                    "-T",
                    "csr-ospf",
                    "--device-template",
                    "csr1000v",
                    "--offline-yaml",
                    str(out_file),
                    "--mgmt",
                    "--mgmt-bridge",
                    "--mgmt-slot",
                    "5",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            lab = yaml.safe_load(out_file.read_text(encoding="utf-8"))
            routers = [
                node
                for node in lab["nodes"]
                if node.get("node_definition") == "csr1000v"
                and node.get("label", "").startswith("R")
            ]
            self.assertGreaterEqual(len(routers), 10)
            for router in routers:
                config = _extract_day0_config(router)
                names = _interface_names(config)
                self.assertEqual(len(names), len(set(names)), router["label"])
                self.assertLessEqual(names.count("GigabitEthernet5"), 1, router["label"])
                if "GigabitEthernet5" in names:
                    gi5 = _interface_stanza(config, "GigabitEthernet5")
                    self.assertIn("ip address dhcp", gi5, router["label"])
                    self.assertNotRegex(
                        config,
                        r"interface GigabitEthernet5\n.*ip address 172\.16",
                        router["label"],
                    )
                busy = [name for name in names if name not in {"GigabitEthernet5", "Loopback0"}]
                if len(busy) >= 5:
                    self.assertIn("GigabitEthernet6", names, router["label"])

    def test_flat_pair_cli_vrf_reaches_nac_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-pair-vrf.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--vrf",
                    "--pair-vrf",
                    "tenant",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "flat-pair-vrf" / "nac" / "nac.yaml"
            devices = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"]
            r1_config = devices[0]["configuration"]
            self.assertEqual(r1_config["vrfs"], [{"name": "tenant"}])
            self.assertTrue(
                any(
                    iface.get("vrf_forwarding") == "tenant"
                    for iface in r1_config["interfaces"]["ethernets"]
                )
            )

    def test_mgmt_cli_sets_oob_host_but_does_not_manage_mgmt_interface(self):
        # TG-163: --mgmt selects the OOB management address as the connection
        # host, but the OOB interface (DHCP, day-0 owned) must NOT appear as a
        # Terraform-managed interface, and its Mgmt-vrf must not be emitted.
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "mgmt-simple.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--mgmt",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "mgmt-simple" / "nac" / "nac.yaml"
            inventory_yaml = Path(tmp) / "out" / "mgmt-simple" / "nac" / "inventory.yaml"
            device = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertEqual(device["host"], "10.254.0.1")
            self.assertEqual(inv["all"]["hosts"]["iosv-01"]["ansible_host"], "10.254.0.1")
            self.assertNotIn("vrfs", device["configuration"])
            self.assertFalse(
                any(
                    iface.get("description") == "OOB Management"
                    for iface in device["configuration"]["interfaces"]["ethernets"]
                )
            )

    def test_mgmt_global_vrf_does_not_manage_mgmt_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "mgmt-global.yaml"
            rc = self._run_main(
                [
                    "1",
                    "--mode",
                    "simple",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--mgmt",
                    "--mgmt-vrf",
                    "global",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "mgmt-global" / "nac" / "nac.yaml"
            device = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            config = device["configuration"]
            self.assertEqual(device["host"], "10.254.0.1")
            self.assertNotIn("vrfs", config)
            self.assertFalse(
                any(
                    iface.get("description") == "OOB Management"
                    for iface in config["interfaces"]["ethernets"]
                )
            )

    def test_name_and_hostname_sources_are_distinct(self):
        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.0.0.1/32"),
            interfaces=[
                TopogenInterface(address=IPv4Interface("172.16.0.6/30"), slot=0),
            ],
        )
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="simple",
        )
        device = model["iosxe"]["devices"][0]
        self.assertEqual(device["name"], "iosv-01")
        self.assertEqual(device["configuration"]["system"]["hostname"], "R1")

    def test_optional_interface_keys_absent_writer_still_succeeds(self):
        class PartialIface:
            pass

        iface = PartialIface()
        node = TopogenNode(hostname="r1", loopback=None, interfaces=[iface])
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="x",
            mode="simple",
        )
        iface_entry = model["iosxe"]["devices"][0]["interfaces"][0]
        self.assertEqual(iface_entry["slot"], 0)
        self.assertEqual(iface_entry["name"], "GigabitEthernet0/0")
        self.assertNotIn("ipv4", iface_entry)
        self.assertNotIn("description", iface_entry)

    def test_missing_metadata_sections_in_model_do_not_crash_writers(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = {
                "iosxe": {
                    "devices": [
                        {
                            "name": "iosv-01",
                            "hostname": "iosv-01",
                            "platform": "iosxe",
                            "role": "router",
                        }
                    ]
                }
            }
            out_path = Path(tmp) / "devices.yaml"
            write_devices_yaml(model, out_path, overwrite=True)
            devices_doc = yaml.safe_load(out_path.read_text(encoding="utf-8"))
            self.assertIs(devices_doc["terraform_input"], False)
            self.assertEqual(devices_doc["devices"][0]["mgmt_ip"], "")

    def test_rerun_stability_with_fallback_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = TopogenNode(hostname="r1", loopback=None, interfaces=[{"description": "uplink"}])
            nac_root = Path(tmp) / "nac"
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="x",
                mode="simple",
                overwrite=True,
            )
            first = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            write_nac_tree(
                nac_root=nac_root,
                node=node,
                device_template="iosv",
                template="x",
                mode="simple",
                overwrite=True,
            )
            second = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_two_router_flat_nac_outputs_include_both_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat" / "nac"
            nac_yaml = nac_root / "nac.yaml"
            devices_yaml = nac_root / "devices.yaml"
            tfvars_json = nac_root / "terraform.tfvars.json"
            inventory_yaml = nac_root / "inventory.yaml"
            group_all_yaml = nac_root / "group_vars" / "all.yaml"
            host_vars_1 = nac_root / "host_vars" / "iosv-01.yaml"
            host_vars_2 = nac_root / "host_vars" / "iosv-02.yaml"
            metadata_yaml = nac_root / "nac_metadata.yaml"
            for path in (
                nac_yaml,
                devices_yaml,
                inventory_yaml,
                group_all_yaml,
                host_vars_1,
                host_vars_2,
                metadata_yaml,
            ):
                self.assertTrue(path.exists())

            canonical = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            self.assertEqual(len(canonical["iosxe"]["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in canonical["iosxe"]["devices"]],
                ["iosv-01", "iosv-02"],
            )

            devices_doc = yaml.safe_load(devices_yaml.read_text(encoding="utf-8"))
            self.assertEqual(len(devices_doc["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in devices_doc["devices"]],
                ["iosv-01", "iosv-02"],
            )
            self.assertFalse(tfvars_json.exists())

            inv = yaml.safe_load(inventory_yaml.read_text(encoding="utf-8"))
            self.assertIn("iosv-01", inv["all"]["hosts"])
            self.assertIn("iosv-02", inv["all"]["hosts"])
            self.assertIn("ansible_host", inv["all"]["hosts"]["iosv-01"])
            self.assertIn("ansible_host", inv["all"]["hosts"]["iosv-02"])

            grp = yaml.safe_load(group_all_yaml.read_text(encoding="utf-8"))
            self.assertEqual(grp["nac_device_count"], 2)

            metadata = yaml.safe_load(metadata_yaml.read_text(encoding="utf-8"))
            self.assertIs(metadata["terraform_input"], False)
            self.assertEqual(metadata["epic_ref"], "TG-131")
            self.assertEqual(metadata["module"], "netascode/nac-iosxe/iosxe 0.1.0")
            self.assertEqual(metadata["provider"], "CiscoDevNet/iosxe 0.15.0")
            self.assertEqual(metadata["device_count"], 2)
            self.assertIn("host_vars/iosv-01.yaml", metadata["generated_artifacts"])
            self.assertIn("host_vars/iosv-02.yaml", metadata["generated_artifacts"])
            self.assertNotIn("terraform.tfvars.json", metadata["generated_artifacts"])

    def test_two_router_flat_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat.yaml"
            argv = [
                "2",
                "--mode",
                "flat",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat" / "nac"
            nested_bad = Path(tmp) / "out" / "two-router-flat" / "two-router-flat" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())

            files = [
                nac_root / "nac.yaml",
                nac_root / "devices.yaml",
                nac_root / "inventory.yaml",
                nac_root / "group_vars" / "all.yaml",
                nac_root / "host_vars" / "iosv-01.yaml",
                nac_root / "host_vars" / "iosv-02.yaml",
                nac_root / "nac_metadata.yaml",
            ]
            for path in files:
                self.assertTrue(path.exists())
                a = path.read_text(encoding="utf-8")
                b = path.read_text(encoding="utf-8")
                self.assertEqual(a, b)

    def test_two_router_simple_nac_outputs_include_both_devices(self):
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
            nac_root = Path(tmp) / "out" / "two-router-simple" / "nac"
            host_vars_1 = nac_root / "host_vars" / "iosv-01.yaml"
            host_vars_2 = nac_root / "host_vars" / "iosv-02.yaml"
            self.assertTrue((nac_root / "nac.yaml").exists())
            self.assertTrue((nac_root / "devices.yaml").exists())
            self.assertTrue((nac_root / "inventory.yaml").exists())
            self.assertTrue(host_vars_1.exists())
            self.assertTrue(host_vars_2.exists())

            canonical = yaml.safe_load((nac_root / "nac.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(canonical["iosxe"]["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in canonical["iosxe"]["devices"]],
                ["iosv-01", "iosv-02"],
            )

            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual(metadata["device_count"], 2)

    def test_two_router_simple_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-simple.yaml"
            argv = [
                "2",
                "--mode",
                "simple",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            second = self._run_main(argv)
            self.assertEqual(first, 0)
            self.assertEqual(second, 0)
            nac_root = Path(tmp) / "out" / "two-router-simple" / "nac"
            nested_bad = Path(tmp) / "out" / "two-router-simple" / "two-router-simple" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())
            data_a = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            data_b = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            self.assertEqual(data_a, data_b)

    def test_two_router_flat_pair_nac_outputs_include_both_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat-pair.yaml"
            rc = self._run_main(
                [
                    "2",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat-pair" / "nac"
            self.assertTrue((nac_root / "nac.yaml").exists())
            self.assertTrue((nac_root / "devices.yaml").exists())
            self.assertTrue((nac_root / "inventory.yaml").exists())
            self.assertTrue((nac_root / "host_vars" / "iosv-01.yaml").exists())
            self.assertTrue((nac_root / "host_vars" / "iosv-02.yaml").exists())

            canonical = yaml.safe_load((nac_root / "nac.yaml").read_text(encoding="utf-8"))
            self.assertEqual(len(canonical["iosxe"]["devices"]), 2)
            self.assertEqual(
                [d["name"] for d in canonical["iosxe"]["devices"]],
                ["iosv-01", "iosv-02"],
            )

            metadata = yaml.safe_load((nac_root / "nac_metadata.yaml").read_text(encoding="utf-8"))
            self.assertEqual(metadata["device_count"], 2)

    def test_four_router_flat_pair_nac_uses_layout_without_dmvpn_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "flat-pair.yaml"
            rc = self._run_main(
                [
                    "4",
                    "--mode",
                    "flat-pair",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)

            lab_root = Path(tmp) / "out" / "flat-pair"
            cml_yaml = lab_root / "flat-pair.yaml"
            nac_root = lab_root / "nac"
            nac_yaml = nac_root / "nac.yaml"
            self.assertTrue(cml_yaml.exists())
            self.assertTrue(nac_yaml.exists())
            self.assertTrue((nac_root / "inventory.yaml").exists())
            self.assertTrue((nac_root / "host_vars" / "iosv-04.yaml").exists())
            self.assertFalse(out_file.exists())
            self.assertFalse((lab_root / "nac.yaml").exists())

            canonical = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))
            devices = canonical["iosxe"]["devices"]
            self.assertEqual(
                [device["name"] for device in devices],
                ["iosv-01", "iosv-02", "iosv-03", "iosv-04"],
            )
            self.assertEqual(
                [device["configuration"]["system"]["hostname"] for device in devices],
                ["R1", "R2", "R3", "R4"],
            )

    def test_two_router_flat_pair_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "two-router-flat-pair.yaml"
            argv = [
                "2",
                "--mode",
                "flat-pair",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            first = self._run_main(argv)
            self.assertEqual(first, 0)
            nac_root = Path(tmp) / "out" / "two-router-flat-pair" / "nac"
            data_a = (nac_root / "nac.yaml").read_text(encoding="utf-8")

            second = self._run_main(argv)
            self.assertEqual(second, 0)
            nested_bad = Path(tmp) / "out" / "two-router-flat-pair" / "two-router-flat-pair" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())
            data_b = (nac_root / "nac.yaml").read_text(encoding="utf-8")
            self.assertEqual(data_a, data_b)

    def test_dmvpn_flat_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat.yaml"
            argv = [
                "3",
                "--mode",
                "dmvpn",
                "--dmvpn-hubs",
                "1",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            self.assertEqual(self._run_main(argv), 0)
            lab_root = Path(tmp) / "out" / "dmvpn-flat"
            nac_yaml = lab_root / "nac" / "nac.yaml"
            data_a = nac_yaml.read_text(encoding="utf-8")

            self.assertEqual(self._run_main(argv), 0)
            nested_bad = lab_root / "dmvpn-flat" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())
            data_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(data_a, data_b)

    def test_dmvpn_flat_pair_rerun_is_deterministic_and_not_nested(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-pair.yaml"
            argv = [
                "4",
                "--mode",
                "dmvpn",
                "--dmvpn-underlay",
                "flat-pair",
                "--template",
                "iosv-dmvpn",
                "--offline-yaml",
                str(out_file),
                "--nac",
                "--overwrite",
            ]
            self.assertEqual(self._run_main(argv), 0)
            lab_root = Path(tmp) / "out" / "dmvpn-flat-pair"
            nac_yaml = lab_root / "nac" / "nac.yaml"
            data_a = nac_yaml.read_text(encoding="utf-8")

            self.assertEqual(self._run_main(argv), 0)
            nested_bad = lab_root / "dmvpn-flat-pair" / "nac" / "nac.yaml"
            self.assertFalse(nested_bad.exists())
            data_b = nac_yaml.read_text(encoding="utf-8")
            self.assertEqual(data_a, data_b)

    def test_dmvpn_csr_nac_tunnel_uses_gigabitethernet1_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-csr.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "-T",
                    "csr-dmvpn",
                    "--device-template",
                    "csr1000v",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            nac_yaml = Path(tmp) / "out" / "dmvpn-flat-csr" / "nac" / "nac.yaml"
            hub_tunnel = yaml.safe_load(nac_yaml.read_text(encoding="utf-8"))["iosxe"]["devices"][0]
            tunnel = hub_tunnel["configuration"]["interfaces"]["tunnels"][0]
            self.assertEqual(tunnel["tunnel_source"], "GigabitEthernet1")
            self.assertEqual(
                hub_tunnel["configuration"]["interfaces"]["ethernets"][0]["id"],
                "1",
            )

    def test_dmvpn_ikev2_psk_nac_projects_crypto_and_tunnel_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-psk.yaml"
            rc = self._run_main(
                [
                    "3",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-hubs",
                    "1",
                    "--dmvpn-security",
                    "ikev2-psk",
                    "--dmvpn-psk",
                    "lab-psk-test",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            device = yaml.safe_load(
                (Path(tmp) / "out" / "dmvpn-psk" / "nac" / "nac.yaml").read_text(encoding="utf-8")
            )["iosxe"]["devices"][0]
            crypto = device["configuration"]["crypto"]
            self.assertIn("ikev2", crypto)
            self.assertEqual(crypto["ipsec_profiles"][0]["name"], DMVPN_IPSEC_PROFILE)
            self.assertEqual(
                device["configuration"]["interfaces"]["tunnels"][0]["tunnel_protection_ipsec_profile"],
                DMVPN_IPSEC_PROFILE,
            )

    def test_dmvpn_pair_vrf_reaches_tunnel_and_loopback_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "dmvpn-flat-pair-vrf.yaml"
            rc = self._run_main(
                [
                    "4",
                    "--mode",
                    "dmvpn",
                    "--dmvpn-underlay",
                    "flat-pair",
                    "--template",
                    "iosv-dmvpn",
                    "--offline-yaml",
                    str(out_file),
                    "--nac",
                    "--vrf",
                    "--pair-vrf",
                    "tenant",
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            device = yaml.safe_load(
                (Path(tmp) / "out" / "dmvpn-flat-pair-vrf" / "nac" / "nac.yaml").read_text(encoding="utf-8")
            )["iosxe"]["devices"][0]
            config = device["configuration"]
            self.assertEqual(config["vrfs"], [{"name": "tenant"}])
            self.assertEqual(
                config["interfaces"]["tunnels"][0]["vrf_forwarding"],
                "tenant",
            )
            self.assertEqual(
                config["interfaces"]["loopbacks"][0]["vrf_forwarding"],
                "tenant",
            )
            self.assertEqual(
                config["interfaces"]["ethernets"][1]["vrf_forwarding"],
                "tenant",
            )

    def _static_nac_argv(self, *, link_local: bool = False) -> list[str]:
        argv = [
            "2",
            "--mode",
            "flat",
            "-T",
            "iosv",
            "--device-template",
            "iosv",
            "--mgmt",
            "--mgmt-vrf",
            "Mgmt-vrf",
            "--mgmt-ipv6-static",
            "--mgmt-ipv6-cidr",
            "fd80::/64",
            "--nac",
            "--overwrite",
        ]
        if link_local:
            argv.append("--mgmt-ipv6-static-link-local")
        return argv

    def test_nac_static_ansible_host_global(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "static-nac.yaml"
            rc = self._run_main([*self._static_nac_argv(), "--offline-yaml", str(out_file)])
            self.assertEqual(rc, 0)
            nac_root = Path(tmp) / "out" / "static-nac" / "nac"
            inv = yaml.safe_load((nac_root / "inventory.yaml").read_text(encoding="utf-8"))
            host = inv["all"]["hosts"]["iosv-01"]["ansible_host"]
            self.assertIn("fd80", host)
            self.assertNotIn("fe80::", host)

    def test_nac_static_mgmt_ipv6_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "static-nac.yaml"
            rc = self._run_main([*self._static_nac_argv(), "--offline-yaml", str(out_file)])
            self.assertEqual(rc, 0)
            inv = yaml.safe_load(
                (Path(tmp) / "out" / "static-nac" / "nac" / "inventory.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIn("fd80", inv["all"]["hosts"]["iosv-01"]["ansible_host"].lower())
            self.assertIn("ff10", inv["all"]["hosts"]["iosv-01"]["ansible_host"].lower())

    def test_nac_static_link_local_metadata(self):
        from topogen.render import _append_nac_mgmt_interface

        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.20.0.1/32"),
            interfaces=[],
        )
        args = SimpleNamespace(
            enable_mgmt=True,
            mgmt_cidr="10.254.0.0/16",
            mgmt_slot=5,
            dev_template="iosv",
            template="iosv",
            mgmt_vrf="Mgmt-vrf",
            mgmt_bridge=False,
            mgmt_ipv4_dhcp=False,
            mgmt_ipv6_mode="static",
            mgmt_ipv6_cidr="fd80::/64",
            mgmt_ipv6_static_link_local=True,
        )
        _append_nac_mgmt_interface(node, args, 1)
        model = build_canonical_nac_model(
            node,
            device_template="iosv",
            template="iosv",
            mode="flat",
            args=args,
        )
        self.assertEqual(
            model["iosxe"]["devices"][0]["mgmt"]["ipv6_link_local"],
            "fe80::FF10:20:0:1",
        )

    def test_nac_metadata_mode_static(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "out" / "static-nac.yaml"
            rc = self._run_main([*self._static_nac_argv(), "--offline-yaml", str(out_file)])
            self.assertEqual(rc, 0)
            metadata = yaml.safe_load(
                (Path(tmp) / "out" / "static-nac" / "nac" / "nac_metadata.yaml").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata["mgmt_ipv6_mode"], "static")

    def test_select_host_prefers_global_not_ll(self):
        from topogen.render import _append_nac_mgmt_interface

        node = TopogenNode(
            hostname="R1",
            loopback=IPv4Interface("10.20.0.1/32"),
            interfaces=[],
        )
        args = SimpleNamespace(
            enable_mgmt=True,
            mgmt_cidr="10.254.0.0/16",
            mgmt_slot=5,
            dev_template="iosv",
            template="iosv",
            mgmt_vrf="Mgmt-vrf",
            mgmt_bridge=False,
            mgmt_ipv4_dhcp=False,
            mgmt_ipv6_mode="static",
            mgmt_ipv6_cidr="fd80::/64",
            mgmt_ipv6_static_link_local=True,
        )
        _append_nac_mgmt_interface(node, args, 1)
        host = _select_host(node, args)
        self.assertIn("fd80", host)
        self.assertNotIn("fe80", host)


if __name__ == "__main__":
    unittest.main()
