from __future__ import annotations

import pytest

from topogen.node_definitions import interface_labels


@pytest.mark.parametrize(
    ("node_definition", "count", "expected"),
    [
        ("iosv", 2, ("GigabitEthernet0/0", "GigabitEthernet0/1")),
        (
            "iol-xe",
            5,
            ("Ethernet0/0", "Ethernet0/1", "Ethernet0/2", "Ethernet0/3", "Ethernet1/0"),
        ),
        ("alpine", 4, ("eth0", "eth1", "eth2", "eth3")),
        ("frr", 16, tuple(f"eth{slot}" for slot in range(16))),
    ],
)
def test_interface_labels(node_definition, count, expected):
    assert interface_labels(node_definition, count) == expected


def test_interface_labels_rejects_unknown_or_over_capacity_definition():
    with pytest.raises(ValueError, match="unsupported"):
        interface_labels("unknown", 1)
    with pytest.raises(ValueError, match="at most 16"):
        interface_labels("iosv", 17)
