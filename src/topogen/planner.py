"""offline topology planning for TopoGen"""

from __future__ import annotations

from dataclasses import dataclass, field

from topogen.models import Point, TopogenError


@dataclass(slots=True)
class PlannedInterface:
    label: str
    slot: int


@dataclass(slots=True)
class PlannedNode:
    id: str
    label: str
    node_definition: str
    pos: Point
    interfaces: list[PlannedInterface] = field(default_factory=list)


@dataclass(slots=True)
class PlannedLinkEnd:
    node_id: str
    iface_slot: int


@dataclass(slots=True)
class PlannedLink:
    id: str
    left: PlannedLinkEnd
    right: PlannedLinkEnd
    label: str = ""


@dataclass(slots=True)
class TopologyPlan:
    title: str
    version: str = "0.3.0"
    description: str = ""
    notes: str = ""
    nodes: list[PlannedNode] = field(default_factory=list)
    links: list[PlannedLink] = field(default_factory=list)


class TopologyPlanError(TopogenError):
    pass


def validate_plan(plan: TopologyPlan) -> None:
    if not plan.title:
        raise TopologyPlanError("title is required")
    node_ids: set[str] = set()
    for node in plan.nodes:
        if not node.node_definition:
            raise TopologyPlanError(f"node {node.id} node_definition is required")
        if node.id in node_ids:
            raise TopologyPlanError(f"duplicate node id: {node.id}")
        node_ids.add(node.id)
    for link in plan.links:
        if link.left.node_id not in node_ids:
            raise TopologyPlanError(
                f"link {link.id} references missing node {link.left.node_id}"
            )
        if link.right.node_id not in node_ids:
            raise TopologyPlanError(
                f"link {link.id} references missing node {link.right.node_id}"
            )
        if link.left.node_id == link.right.node_id:
            raise TopologyPlanError(
                f"link {link.id} self-links node {link.left.node_id}"
            )


def build_text_ids(count: int, prefix: str) -> list[str]:
    if count < 0:
        raise TopologyPlanError("count must be >= 0")
    if not prefix:
        raise TopologyPlanError("prefix is required")
    return [f"{prefix}{idx}" for idx in range(count)]
