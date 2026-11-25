from __future__ import annotations

from ipaddress import IPv4Network

import pytest
import yaml

from topogen.config import Config
from topogen.offline import export_plan, main, nx_plan, simple_plan


def test_simple_mode_creates_spiral_router_chain(tmp_path):
    plan = simple_plan(3, 100, "lab", "frr")
    routers = plan.nodes[:3]
    router_links = plan.links[:2]
    assert [(node.x, node.y) for node in routers] == [(0, 0), (0, 100), (100, 100)]
    assert [(link.n1, link.n2) for link in router_links] == [("n0", "n1"), ("n1", "n2")]
    out = export_plan(plan, tmp_path / "lab.yaml")
    data = yaml.safe_load(out.read_text())
    assert data["lab"]["title"] == "lab"
    assert data["nodes"][0]["node_definition"] == "frr"


@pytest.mark.parametrize(
    ("template", "labels"),
    [
        ("frr", ["eth0", "eth1", "eth2"]),
        ("iosv", ["GigabitEthernet0/0", "GigabitEthernet0/1", "GigabitEthernet0/2"]),
        ("iol-xe", ["Ethernet0/0", "Ethernet0/1", "Ethernet0/2"]),
    ],
)
def test_nx_mode_uses_selected_device_interfaces(template, labels):
    plan = nx_plan(3, 100, "lab", template)
    router = plan.nodes[0]
    assert [interface.label for interface in router.interfaces[:3]] == labels
    assert router.node_definition == template
    assert labels[0] in router.configuration[0]["content"]
    assert router.configuration[0]["name"] == (
        "node.cfg" if template == "frr" else "ios_config.txt"
    )


def test_nx_mode_configures_dns_host():
    plan = nx_plan(3, 100, "lab", "frr")
    dns = next(node for node in plan.nodes if node.label == "dns-host")
    assert dns.configuration[0]["name"] == "node.cfg"
    assert "hostname dns-host" in dns.configuration[0]["content"]
    assert "ip address add 172.16.0.14/30 dev eth1" in dns.configuration[0]["content"]


def test_offline_topology_uses_configured_networks_and_credentials():
    cfg = Config(
        loopbacks=IPv4Network("192.0.2.0/24"),
        p2pnets=IPv4Network("198.51.100.0/24"),
        domainname="example.test",
        username="admin",
        password="secret",
    )
    plan = nx_plan(3, 100, "lab", "frr", cfg)
    router_config = plan.nodes[0].configuration[0]["content"]
    boot_config = plan.nodes[0].configuration[1]["content"]
    dns_config = next(
        node for node in plan.nodes if node.label == "dns-host"
    ).configuration[0]["content"]
    assert "192.0.2.1/32" in router_config
    assert "198.51.100.1/30" in router_config
    assert "search example.test" in boot_config
    assert "USERNAME=admin" in dns_config
    assert "PASSWORD=secret" in dns_config


def test_dns_host_config_contains_router_interface_records():
    plan = nx_plan(3, 100, "lab", "frr")
    dns = next(node for node in plan.nodes if node.label == "dns-host")
    config = dns.configuration[0]["content"]
    assert "172.16.0.1\\t" in config
    assert "r1-eth0--r2-eth0.virl.lab" in config
    assert "172.16.0.13\\t" in config
    assert "r1-eth2--dns-host-eth1.virl.lab" in config


def test_nx_mode_adds_interfaces_for_high_degree_router():
    plan = nx_plan(5, 100, "lab", "frr")
    routers = [node for node in plan.nodes if node.node_definition == "frr"]
    for link in plan.links:
        for node_id, interface_id in ((link.n1, link.i1), (link.n2, link.i2)):
            router = next((node for node in routers if node.id == node_id), None)
            if router:
                assert interface_id in {interface.id for interface in router.interfaces}


def test_reference_graph_is_deterministic():
    first = nx_plan(3, 100, "lab", "frr")
    second = nx_plan(3, 100, "lab", "frr")
    assert [(link.n1, link.n2) for link in first.links] == [
        (link.n1, link.n2) for link in second.links
    ]


def test_nx_rejects_undersized_address_pools():
    cfg = Config(
        loopbacks=IPv4Network("192.0.2.0/30"),
        p2pnets=IPv4Network("198.51.100.0/30"),
    )
    with pytest.raises(
        ValueError, match="p2pnets provides 1 /30 networks; 4 are required"
    ):
        nx_plan(3, 100, "lab", "frr", cfg)


def test_nx_rejects_undersized_loopback_pool():
    cfg = Config(loopbacks=IPv4Network("192.0.2.0/30"))
    with pytest.raises(
        ValueError, match="loopbacks provides 2 addresses; 3 are required"
    ):
        nx_plan(3, 100, "lab", "frr", cfg)


def test_nx_coordinates_honor_distance():
    near = nx_plan(20, 100, "lab", "frr")
    far = nx_plan(20, 1_000, "lab", "frr")
    assert max(abs(node.x) for node in far.nodes[:20]) > max(
        abs(node.x) for node in near.nodes[:20]
    )


def test_nx_mode_is_not_full_mesh_for_large_topology():
    router_count = 20
    plan = nx_plan(router_count, 100, "lab", "frr")
    router_links = [
        link
        for link in plan.links
        if link.n1.startswith("n")
        and link.n2.startswith("n")
        and int(link.n1[1:]) < router_count
        and int(link.n2[1:]) < router_count
    ]
    assert len(router_links) < router_count * (router_count - 1) // 2


def test_nx_mode_rejects_unknown_template():
    with pytest.raises(ValueError, match="unsupported"):
        nx_plan(3, 100, "lab", "unknown")


def test_main_uses_mode(monkeypatch, tmp_path):
    out = tmp_path / "lab.yaml"
    captured = {}

    def fake_export(plan, output):
        captured["title"] = plan.lab.title
        captured["output"] = str(output)
        return out

    monkeypatch.setattr("topogen.offline.export_plan", fake_export)
    args = type(
        "Args",
        (),
        {
            "nodes": 3,
            "distance": 100,
            "labname": "lab",
            "template": "frr",
            "mode": "nx",
            "output": str(out),
        },
    )()
    assert main(args) == 0
    assert captured == {"title": "lab", "output": str(out)}
