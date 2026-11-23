"""offline CLI path for YAML export."""

from __future__ import annotations

from argparse import Namespace
from collections import defaultdict
from pathlib import Path

import networkx as nx

from topogen.exporter import (
    ExportInterface,
    ExportLab,
    ExportLink,
    ExportNode,
    ExportTopology,
    write_yaml,
)
from topogen.models import Point
from topogen.planner import (
    PlannedInterface,
    PlannedLink,
    PlannedLinkEnd,
    PlannedNode,
    TopologyPlan,
    build_text_ids,
)

SUPPORTED_TEMPLATES = {"iosv", "iol-xe", "frr"}


def _validate_template(template: str) -> None:
    if template not in SUPPORTED_TEMPLATES:
        raise ValueError(f"unsupported template: {template}")


def _build_nodes(node_ids: list[str], distance: int, template: str, interface_counts: dict[str, int]) -> list[PlannedNode]:
    planned_nodes = []
    for idx, node_id in enumerate(node_ids):
        count = interface_counts[node_id]
        interfaces = [PlannedInterface(label="eth0", slot=slot) for slot in range(count)]
        planned_nodes.append(
            PlannedNode(
                id=node_id,
                label=f"R{idx + 1}",
                node_definition=template,
                pos=Point(idx * distance, 0),
                interfaces=interfaces,
            )
        )
    return planned_nodes


def simple_plan(nodes: int, distance: int, labname: str, template: str) -> TopologyPlan:
    _validate_template(template)
    node_ids = build_text_ids(nodes, "n")
    interface_counts: dict[str, int] = defaultdict(int)
    for idx in range(1, len(node_ids)):
        interface_counts[node_ids[idx - 1]] += 1
        interface_counts[node_ids[idx]] += 1
    planned_nodes = _build_nodes(node_ids, distance, template, interface_counts)
    slot_used: dict[str, int] = defaultdict(int)
    planned_links = []
    for idx in range(1, len(node_ids)):
        left = node_ids[idx - 1]
        right = node_ids[idx]
        left_slot = slot_used[left]
        right_slot = slot_used[right]
        slot_used[left] += 1
        slot_used[right] += 1
        planned_links.append(
            PlannedLink(
                id=f"l{idx - 1}",
                left=PlannedLinkEnd(node_id=left, iface_slot=left_slot),
                right=PlannedLinkEnd(node_id=right, iface_slot=right_slot),
                label=f"R{idx}--R{idx + 1}",
            )
        )
    return TopologyPlan(title=labname, nodes=planned_nodes, links=planned_links)


def export_plan(plan: TopologyPlan, output: str | Path) -> Path:
    topology = ExportTopology(
        lab=ExportLab(
            version=plan.version,
            title=plan.title,
            description=plan.description,
            notes=plan.notes,
        ),
        nodes=[
            ExportNode(
                id=node.id,
                label=node.label,
                node_definition=node.node_definition,
                x=node.pos.x,
                y=node.pos.y,
                interfaces=[
                    ExportInterface(
                        id=f"i{node.id[1:]}{iface.slot}",
                        label=iface.label,
                        slot=iface.slot,
                    )
                    for iface in node.interfaces
                ],
            )
            for node in plan.nodes
        ],
        links=[
            ExportLink(
                id=link.id,
                n1=link.left.node_id,
                n2=link.right.node_id,
                i1=f"i{link.left.node_id[1:]}{link.left.iface_slot}",
                i2=f"i{link.right.node_id[1:]}{link.right.iface_slot}",
                label=link.label,
            )
            for link in plan.links
        ],
    )
    return write_yaml(topology, output)


def nx_plan(nodes: int, distance: int, labname: str, template: str) -> TopologyPlan:
    _validate_template(template)
    node_ids = build_text_ids(nodes, "n")
    graph = nx.random_shell_graph([(len(node_ids), len(node_ids) * 2, 0.999)])
    if not nx.is_connected(graph):
        graph.add_edges_from(nx.k_edge_augmentation(graph, k=1))
    interface_counts: dict[str, int] = defaultdict(int)
    for src, dst in graph.edges:
        interface_counts[node_ids[src]] += 1
        interface_counts[node_ids[dst]] += 1
    planned_nodes = _build_nodes(node_ids, distance, template, interface_counts)
    slot_used: dict[str, int] = defaultdict(int)
    planned_links = []
    for idx, (src, dst) in enumerate(graph.edges):
        left = node_ids[src]
        right = node_ids[dst]
        left_slot = slot_used[left]
        right_slot = slot_used[right]
        slot_used[left] += 1
        slot_used[right] += 1
        planned_links.append(
            PlannedLink(
                id=f"l{idx}",
                left=PlannedLinkEnd(node_id=left, iface_slot=left_slot),
                right=PlannedLinkEnd(node_id=right, iface_slot=right_slot),
                label=f"R{src + 1}--R{dst + 1}",
            )
        )
    return TopologyPlan(title=labname, nodes=planned_nodes, links=planned_links)


def main(args: Namespace) -> int:
    mode = getattr(args, "mode", "simple")
    if mode == "nx":
        plan = nx_plan(args.nodes, args.distance, args.labname, args.template)
    else:
        plan = simple_plan(args.nodes, args.distance, args.labname, args.template)
    export_plan(plan, getattr(args, "output", "topogen_lab.yaml"))
    return 0
