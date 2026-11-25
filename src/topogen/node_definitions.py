"""Static physical-interface maps copied from CML node definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    interfaces: tuple[str, ...]

    @property
    def capacity(self) -> int:
        return len(self.interfaces)


def _ethernet_slots(count: int) -> tuple[str, ...]:
    return tuple(f"Ethernet{slot // 4}/{slot % 4}" for slot in range(count))


NODE_DEFINITIONS = {
    "iosv": NodeDefinition(tuple(f"GigabitEthernet0/{slot}" for slot in range(16))),
    "iol-xe": NodeDefinition(_ethernet_slots(32)),
    "alpine": NodeDefinition(tuple(f"eth{slot}" for slot in range(4))),
    "frr": NodeDefinition(tuple(f"eth{slot}" for slot in range(32))),
    "external_connector": NodeDefinition(("port",)),
}


def interface_labels(node_definition: str, count: int) -> tuple[str, ...]:
    """Return physical labels for *count* interfaces or fail before export."""
    try:
        definition = NODE_DEFINITIONS[node_definition]
    except KeyError as exc:
        raise ValueError(f"unsupported node definition: {node_definition}") from exc
    if count > definition.capacity:
        raise ValueError(
            f"{node_definition} supports at most {definition.capacity} physical interfaces; requested {count}"
        )
    return definition.interfaces[:count]
