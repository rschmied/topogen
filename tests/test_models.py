from __future__ import annotations

from ipaddress import IPv4Address, IPv4Interface

from topogen.models import (
    CoordsGenerator,
    DNShost,
    Point,
    TopogenInterface,
    TopogenNode,
)


def test_coords_generator_first_sequence():
    gen = iter(CoordsGenerator(distance=10))
    got = [next(gen) for _ in range(4)]
    assert got[0] == Point(0, 0)


def test_coords_generator_reuse_points_are_distinct():
    gen = iter(CoordsGenerator(distance=10))
    a = next(gen)
    b = next(gen)
    assert a is not b
    assert a != b


def test_topogen_dataclasses():
    iface = TopogenInterface(
        address=IPv4Interface("10.0.0.1/32"), description="x", slot=1
    )
    node = TopogenNode(
        hostname="r1", loopback=IPv4Interface("10.0.0.1/32"), interfaces=[iface]
    )
    host = DNShost(name="r1", ipv4=IPv4Address("10.0.0.1"))
    assert node.hostname == "r1"
    assert host.name == "r1"
    assert node.interfaces[0].slot == 1
