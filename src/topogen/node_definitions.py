"""Static router definitions copied from CML node definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    interfaces: tuple[str, ...]
    template: str | None = None
    provisioner: str | None = None
    minimum_interfaces: int = 0
    interface_increment: int = 1

    @property
    def capacity(self) -> int:
        return len(self.interfaces)


def _ethernet_slots(count: int) -> tuple[str, ...]:
    return tuple(f"Ethernet{slot // 4}/{slot % 4}" for slot in range(count))


NODE_DEFINITIONS = {
    "iosv": NodeDefinition(
        tuple(f"GigabitEthernet0/{slot}" for slot in range(16)),
        template="iosv.jinja2",
        provisioner="ios",
        minimum_interfaces=4,
    ),
    "iol-xe": NodeDefinition(
        _ethernet_slots(32),
        template="iol-xe.jinja2",
        provisioner="ios",
        minimum_interfaces=4,
        interface_increment=4,
    ),
    "alpine": NodeDefinition(tuple(f"eth{slot}" for slot in range(4))),
    "frr": NodeDefinition(
        tuple(f"eth{slot}" for slot in range(32)),
        template="frr.jinja2",
        provisioner="frr",
        minimum_interfaces=4,
    ),
    "external_connector": NodeDefinition(("port",)),
}

ROUTER_DEFINITIONS = {
    name: definition
    for name, definition in NODE_DEFINITIONS.items()
    if definition.template and definition.provisioner
}


def router_definition(name: str) -> NodeDefinition:
    try:
        return ROUTER_DEFINITIONS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported router definition: {name}") from exc


def provisioned_interface_count(node_definition: str, linked_count: int) -> int:
    """Return the node-definition interface count needed for linked ports."""
    definition = router_definition(node_definition)
    count = max(linked_count, definition.minimum_interfaces)
    increment = definition.interface_increment
    return ((count + increment - 1) // increment) * increment


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
