"""offline topology export for CML/simple YAML"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from topogen.models import TopogenError
from topogen.planner import TopologyPlan, validate_plan


@dataclass(slots=True)
class ExportInterface:
    id: str
    label: str
    slot: int
    type: str = "physical"
    mac_address: None = None


@dataclass(slots=True)
class ExportNode:
    id: str
    label: str
    node_definition: str
    x: int
    y: int
    interfaces: list[ExportInterface] = field(default_factory=list)
    configuration: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    hide_links: bool = False
    cpu_limit: None = None
    cpus: None = None
    data_volume: None = None
    image_definition: None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    ram: None = None


@dataclass(slots=True)
class ExportLink:
    id: str
    n1: str
    n2: str
    i1: str
    i2: str
    label: str
    conditioning: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExportLab:
    version: str
    title: str
    description: str = ""
    notes: str = ""


@dataclass(slots=True)
class ExportTopology:
    lab: ExportLab
    nodes: list[ExportNode] = field(default_factory=list)
    links: list[ExportLink] = field(default_factory=list)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    smart_annotations: list[dict[str, Any]] = field(default_factory=list)


class TopologyExportError(TopogenError):
    pass


def from_plan(plan: TopologyPlan) -> ExportTopology:
    validate_plan(plan)
    nodes = [
        ExportNode(
            id=node.id,
            label=node.label,
            node_definition=node.node_definition,
            x=node.pos.x,
            y=node.pos.y,
            interfaces=[
                ExportInterface(
                    id=f"i{node.id[1:]}{iface.slot}", label=iface.label, slot=iface.slot
                )
                for iface in node.interfaces
            ],
        )
        for node in plan.nodes
    ]
    links = [
        ExportLink(
            id=link.id,
            n1=link.left.node_id,
            n2=link.right.node_id,
            i1=f"i{link.left.node_id[1:]}{link.left.iface_slot}",
            i2=f"i{link.right.node_id[1:]}{link.right.iface_slot}",
            label=link.label,
        )
        for link in plan.links
    ]
    return ExportTopology(
        lab=ExportLab(plan.version, plan.title, plan.description, plan.notes),
        nodes=nodes,
        links=links,
    )


def to_dict(topology: ExportTopology) -> dict[str, Any]:
    if not topology.lab.version:
        raise TopologyExportError("lab.version is required")
    if not topology.lab.title:
        raise TopologyExportError("lab.title is required")
    return {
        "annotations": topology.annotations,
        "smart_annotations": topology.smart_annotations,
        "nodes": [
            {
                "boot_disk_size": node.cpu_limit,
                "configuration": node.configuration,
                "cpu_limit": node.cpu_limit,
                "cpus": node.cpus,
                "data_volume": node.data_volume,
                "hide_links": node.hide_links,
                "id": node.id,
                "image_definition": node.image_definition,
                "label": node.label,
                "node_definition": node.node_definition,
                "parameters": node.parameters,
                "ram": node.ram,
                "tags": node.tags,
                "x": node.x,
                "y": node.y,
                "interfaces": [
                    {
                        "id": iface.id,
                        "label": iface.label,
                        "mac_address": iface.mac_address,
                        "slot": iface.slot,
                        "type": iface.type,
                    }
                    for iface in node.interfaces
                ],
            }
            for node in topology.nodes
        ],
        "links": [
            {
                "id": link.id,
                "n1": link.n1,
                "n2": link.n2,
                "i1": link.i1,
                "i2": link.i2,
                "conditioning": link.conditioning,
                "label": link.label,
            }
            for link in topology.links
        ],
        "lab": {
            "version": topology.lab.version,
            "title": topology.lab.title,
            "description": topology.lab.description,
            "notes": topology.lab.notes,
        },
    }


def to_yaml(topology: ExportTopology) -> str:
    return yaml.safe_dump(to_dict(topology), sort_keys=False, allow_unicode=True)


def write_yaml(topology: ExportTopology, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(to_yaml(topology), encoding="utf-8")
    return target
