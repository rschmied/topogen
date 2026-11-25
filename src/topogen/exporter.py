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
    boot_disk_size: int | None = None
    interfaces: list[ExportInterface] = field(default_factory=list)
    configuration: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    hide_links: bool = False
    cpu_limit: None = None
    cpus: None = None
    data_volume: None = None
    image_definition: None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    priority: None = None
    pyats: dict[str, None] = field(
        default_factory=lambda: {
            "username": None,
            "password": None,
            "enable_password": None,
        }
    )
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
    node_staging: dict[str, bool] | None = None


@dataclass(slots=True)
class ExportTopology:
    lab: ExportLab
    nodes: list[ExportNode] = field(default_factory=list)
    links: list[ExportLink] = field(default_factory=list)
    annotations: list[dict[str, Any]] = field(default_factory=list)
    smart_annotations: list[dict[str, Any]] = field(default_factory=list)


class TopologyExportError(TopogenError):
    pass


def validate_topology(topology: ExportTopology) -> None:
    if not topology.lab.version:
        raise TopologyExportError("lab.version is required")
    if not topology.lab.title:
        raise TopologyExportError("lab.title is required")

    node_interfaces: dict[str, set[str]] = {}
    node_ids: set[str] = set()
    for node in topology.nodes:
        if not node.id:
            raise TopologyExportError("node id is required")
        if not node.node_definition:
            raise TopologyExportError(f"node {node.id} node_definition is required")
        if node.id in node_ids:
            raise TopologyExportError(f"duplicate node id: {node.id}")
        node_ids.add(node.id)
        interface_ids: set[str] = set()
        interface_slots: set[int] = set()
        for interface in node.interfaces:
            if not interface.id:
                raise TopologyExportError(f"node {node.id} interface id is required")
            if not interface.label:
                raise TopologyExportError(
                    f"node {node.id} interface {interface.id} label is required"
                )
            if interface.slot < 0:
                raise TopologyExportError(
                    f"node {node.id} interface {interface.id} slot must be >= 0"
                )
            if interface.id in interface_ids:
                raise TopologyExportError(
                    f"node {node.id} duplicate interface id: {interface.id}"
                )
            if interface.slot in interface_slots:
                raise TopologyExportError(
                    f"node {node.id} duplicate interface slot: {interface.slot}"
                )
            interface_ids.add(interface.id)
            interface_slots.add(interface.slot)
        node_interfaces[node.id] = interface_ids

    link_ids: set[str] = set()
    used_interfaces: set[tuple[str, str]] = set()
    for link in topology.links:
        if not link.id:
            raise TopologyExportError("link id is required")
        if link.id in link_ids:
            raise TopologyExportError(f"duplicate link id: {link.id}")
        link_ids.add(link.id)
        if link.n1 not in node_interfaces:
            raise TopologyExportError(
                f"link {link.id} references missing node {link.n1}"
            )
        if link.n2 not in node_interfaces:
            raise TopologyExportError(
                f"link {link.id} references missing node {link.n2}"
            )
        if link.n1 == link.n2:
            raise TopologyExportError(f"link {link.id} self-links node {link.n1}")
        for node_id, interface_id in ((link.n1, link.i1), (link.n2, link.i2)):
            if interface_id not in node_interfaces[node_id]:
                raise TopologyExportError(
                    f"link {link.id} references missing interface {node_id}:{interface_id}"
                )
            endpoint = (node_id, interface_id)
            if endpoint in used_interfaces:
                raise TopologyExportError(
                    f"link {link.id} reuses interface {node_id}:{interface_id}"
                )
            used_interfaces.add(endpoint)


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
    validate_topology(topology)
    return {
        "annotations": topology.annotations,
        "smart_annotations": topology.smart_annotations,
        "nodes": [
            {
                "boot_disk_size": node.boot_disk_size,
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
                "priority": node.priority,
                "pyats": node.pyats,
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
            **(
                {"node_staging": topology.lab.node_staging}
                if topology.lab.node_staging
                else {}
            ),
        },
    }


class _YamlDumper(yaml.SafeDumper):
    pass


def _represent_multiline_string(dumper: yaml.SafeDumper, value: str):
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_YamlDumper.add_representer(str, _represent_multiline_string)


def to_yaml(topology: ExportTopology) -> str:
    return yaml.dump(
        to_dict(topology), Dumper=_YamlDumper, sort_keys=False, allow_unicode=True
    )


def write_yaml(topology: ExportTopology, path: str | Path) -> Path:
    target = Path(path)
    target.write_text(to_yaml(topology), encoding="utf-8")
    return target
