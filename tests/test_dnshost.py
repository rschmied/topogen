from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface

from topogen.config import Config
from topogen.dnshost import dnshostconfig
from topogen.models import DNShost, TopogenInterface, TopogenNode


def test_dnshostconfig_renders_expected_core_lines():
    cfg = Config(domainname="lab.local", username="alice", password="secret")
    node = TopogenNode(
        hostname="dns-host",
        loopback=None,
        interfaces=[
            TopogenInterface(address=IPv4Interface("172.16.0.10/30"), slot=0),
            TopogenInterface(address=IPv4Interface("172.16.0.9/30"), slot=1),
        ],
    )
    hosts = [
        DNShost(name="r1", ipv4=IPv4Address("10.0.0.1")),
        DNShost(name="r2", ipv4=IPv4Address("10.0.0.2")),
    ]

    out = dnshostconfig(cfg, node, hosts)

    assert "hostname dns-host" in out
    assert "USERNAME=alice" in out
    assert "PASSWORD=secret" in out
    assert "local=/lab.local/" in out
    assert "ip address add 172.16.0.10/30 dev eth1" in out
    assert "ip route add 10.0.0.0/8 via 172.16.0.9" in out
    assert "r1.lab.local" in out
    assert "r2.lab.local" in out
    assert "\n\n" not in out


def test_dnshostconfig_handles_empty_hosts():
    cfg = Config()
    node = TopogenNode(
        hostname="dns-host",
        loopback=None,
        interfaces=[
            TopogenInterface(address=IPv4Interface("172.16.0.10/30"), slot=0),
            TopogenInterface(address=IPv4Interface("172.16.0.9/30"), slot=1),
        ],
    )

    out = dnshostconfig(cfg, node, [])

    assert "echo -e" not in out
    assert "service dnsmasq start" in out
