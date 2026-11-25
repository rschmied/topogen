"""Offline YAML topology generation."""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterator
from datetime import UTC, datetime
from ipaddress import IPv4Interface, IPv4Network, ip_network
from math import sqrt
from pathlib import Path
from typing import cast

import networkx as nx
from jinja2 import Environment, PackageLoader

from topogen.config import Config
from topogen.dnshost import dnshostconfig
from topogen.exporter import (
    ExportInterface,
    ExportLab,
    ExportLink,
    ExportNode,
    ExportTopology,
    to_dict,
    write_yaml,
)
from topogen.frr import frr_bootconfig
from topogen.models import (
    CoordsGenerator,
    DNShost,
    Point,
    TopogenInterface,
    TopogenNode,
)
from topogen.node_definitions import interface_labels

ROUTER_TEMPLATES = {"frr", "iosv", "iol-xe"}
DEFAULT_TEMPLATE = "iosv"


def _router_interfaces(template: str, count: int) -> list[ExportInterface]:
    labels = interface_labels(template, max(count, 4))
    return [
        ExportInterface(id=f"i{slot}", label=label, slot=slot)
        for slot, label in enumerate(labels)
    ]


def _dns_name(left: str, left_interface: str, right: str, right_interface: str) -> str:
    replacements = {
        "TenGigabitEthernet": "ten",
        "GigabitEthernet": "gi",
        "Ethernet": "e",
        "/": "_",
        " ": "-",
    }
    name = f"{left}-{left_interface}--{right}-{right_interface}"
    for old, new in replacements.items():
        name = name.replace(old, new)
    return name.lower()


def _config_files(
    template: str, config: str, nameserver: str, cfg: Config
) -> list[dict[str, str]]:
    if template != "frr":
        return [{"name": "ios_config.txt", "content": config.rstrip("\n")}]
    return [
        {"name": "node.cfg", "content": config.rstrip("\n")},
        {
            "name": "boot.sh",
            "content": frr_bootconfig(cfg, nameserver, False).rstrip("\n"),
        },
        {"name": "protocols", "content": "ospfd\nbgpd"},
    ]


def _nx_graph(router_count: int, distance: int) -> nx.Graph:
    if router_count < 2:
        raise ValueError("at least two routers are required")
    if router_count == 3:
        graph = nx.complete_graph(router_count)
    else:
        size = max(router_count // 8, 20)
        clusters = router_count // size
        remaining = router_count - clusters * size
        constructor = [
            (size, size * 2, 0.999)
            if index < clusters
            else (remaining, remaining * 2, 0.999)
            for index in range(clusters + (1 if remaining else 0))
        ]
        graph = nx.random_shell_graph(constructor)
        if not nx.is_connected(graph):
            graph.add_edges_from(nx.k_edge_augmentation(graph, k=1))
    if router_count == 3:
        graph.nodes[0]["pos"] = Point(346, 0)
        graph.nodes[1]["pos"] = Point(-173, 299)
        graph.nodes[2]["pos"] = Point(-172, -299)
    else:
        positions = nx.kamada_kawai_layout(graph, scale=sqrt(router_count) * distance)
        for node_id, pos in positions.items():
            graph.nodes[node_id]["pos"] = Point(int(pos[0]), int(pos[1]))
    return graph


def _simple_graph(router_count: int, distance: int) -> nx.Graph:
    if router_count < 2:
        raise ValueError("at least two routers are required")
    graph = nx.path_graph(router_count)
    coords = iter(CoordsGenerator(distance))
    for node_id in graph.nodes:
        graph.nodes[node_id]["pos"] = next(coords)
    return graph


def _validate_address_capacity(graph: nx.Graph, cfg: Config) -> None:
    required_p2p_networks = graph.number_of_edges() + 1
    if cfg.p2pnets.prefixlen > 30:
        raise ValueError("p2pnets must be a /30 or larger network")
    available_p2p_networks = cfg.p2pnets.num_addresses // 4
    if available_p2p_networks < required_p2p_networks:
        raise ValueError(
            f"p2pnets provides {available_p2p_networks} /30 networks; "
            f"{required_p2p_networks} are required"
        )
    if cfg.loopbacks.prefixlen <= 30:
        available_loopbacks = cfg.loopbacks.num_addresses - 2
    else:
        available_loopbacks = cfg.loopbacks.num_addresses
    if available_loopbacks < graph.number_of_nodes():
        raise ValueError(
            f"loopbacks provides {available_loopbacks} addresses; "
            f"{graph.number_of_nodes()} are required"
        )


def _topology(
    graph: nx.Graph, labname: str, template_name: str, cfg: Config
) -> ExportTopology:
    """Build an offline router graph with DNS and an external connector."""
    if template_name not in ROUTER_TEMPLATES:
        raise ValueError(f"unsupported template: {template_name}")
    _validate_address_capacity(graph, cfg)
    router_count = graph.number_of_nodes()
    p2p_networks = cast(
        Iterator[IPv4Network], ip_network(cfg.p2pnets).subnets(new_prefix=30)
    )
    loopbacks = ip_network(cfg.loopbacks).hosts()
    router_interfaces: dict[int, list[TopogenInterface]] = {
        node_id: [] for node_id in graph.nodes
    }
    links: list[ExportLink] = []
    dns_zone: list[DNShost] = []

    for link_id, (left, right) in enumerate(graph.edges):
        network = next(p2p_networks)
        left_addr, right_addr = (
            IPv4Interface(f"{host}/{network.prefixlen}") for host in network.hosts()
        )
        left_slot = len(router_interfaces[left])
        right_slot = len(router_interfaces[right])
        left_label = interface_labels(template_name, left_slot + 1)[left_slot]
        right_label = interface_labels(template_name, right_slot + 1)[right_slot]
        router_interfaces[left].append(
            TopogenInterface(left_addr, f"to R{right + 1} {right_label}", left_slot)
        )
        router_interfaces[right].append(
            TopogenInterface(right_addr, f"to R{left + 1} {left_label}", right_slot)
        )
        dns_name = _dns_name(f"R{left + 1}", left_label, f"R{right + 1}", right_label)
        dns_zone.extend(
            [DNShost(dns_name, left_addr.ip), DNShost(dns_name, right_addr.ip)]
        )
        links.append(
            ExportLink(
                id=f"l{link_id}",
                n1=f"n{left}",
                n2=f"n{right}",
                i1=f"i{left_slot}",
                i2=f"i{right_slot}",
                label=f"R{left + 1}-{left_label}<->R{right + 1}-{right_label}",
            )
        )

    core = max(graph.degree, key=lambda item: item[1])[0]
    dns_network = next(p2p_networks)
    core_addr, dns_addr = (
        IPv4Interface(f"{host}/{dns_network.prefixlen}") for host in dns_network.hosts()
    )
    core_slot = len(router_interfaces[core])
    dns_label = interface_labels("alpine", 2)[1]
    core_label = interface_labels(template_name, core_slot + 1)[core_slot]
    router_interfaces[core].append(
        TopogenInterface(core_addr, f"to dns-host {dns_label}", core_slot)
    )
    dns_name = _dns_name(f"R{core + 1}", core_label, "dns-host", dns_label)
    dns_zone.extend([DNShost(dns_name, core_addr.ip), DNShost(dns_name, dns_addr.ip)])

    loopback_addresses = [IPv4Interface(f"{next(loopbacks)}/32") for _ in graph.nodes]
    nameserver = str(dns_addr.ip)
    environment = Environment(loader=PackageLoader("topogen", "templates"))
    config_template = environment.get_template(f"{template_name}.jinja2")
    routers: list[ExportNode] = []
    for node_id in graph.nodes:
        node = TopogenNode(
            hostname=f"R{node_id + 1}",
            loopback=loopback_addresses[node_id],
            interfaces=router_interfaces[node_id],
        )
        config = config_template.render(
            config=cfg,
            node=node,
            date=datetime.now(UTC),
            origin=dns_addr if node_id == core else "",
        )
        pos = graph.nodes[node_id]["pos"]
        routers.append(
            ExportNode(
                id=f"n{node_id}",
                label=node.hostname,
                node_definition=template_name,
                x=pos.x,
                y=pos.y,
                interfaces=_router_interfaces(
                    template_name, len(router_interfaces[node_id])
                ),
                configuration=_config_files(template_name, config, nameserver, cfg),
            )
        )
        assert node.loopback is not None
        dns_zone.append(DNShost(node.hostname.lower(), node.loopback.ip))

    dns_zone.append(DNShost("dns-host-eth1", dns_addr.ip))
    dns_model = TopogenNode(
        hostname="dns-host",
        loopback=None,
        interfaces=[TopogenInterface(dns_addr), TopogenInterface(core_addr)],
    )
    dns = ExportNode(
        id=f"n{router_count + 1}",
        label="dns-host",
        node_definition="alpine",
        x=200,
        y=0,
        interfaces=[
            ExportInterface(id="i0", label="eth0", slot=0),
            ExportInterface(id="i1", label="eth1", slot=1),
        ],
        configuration=[
            {
                "name": "node.cfg",
                "content": dnshostconfig(cfg, dns_model, dns_zone).rstrip("\n"),
            }
        ],
    )
    ext = ExportNode(
        id=f"n{router_count}",
        label="ext-conn-0",
        node_definition="external_connector",
        x=0,
        y=0,
        interfaces=[ExportInterface(id="i0", label="port", slot=0)],
    )
    links.extend(
        [
            ExportLink(
                id=f"l{len(links)}",
                n1=ext.id,
                n2=dns.id,
                i1="i0",
                i2="i0",
                label="ext-conn-0-port<->dns-host-eth0",
            ),
            ExportLink(
                id=f"l{len(links) + 1}",
                n1=dns.id,
                n2=f"n{core}",
                i1="i1",
                i2=f"i{core_slot}",
                label=f"dns-host-eth1<->R{core + 1}-{core_label}",
            ),
        ]
    )
    return ExportTopology(
        lab=ExportLab(
            version="0.3.2",
            title=labname,
            node_staging={
                "enabled": False,
                "start_remaining": True,
                "abort_on_failure": False,
            },
        ),
        nodes=routers + [ext, dns],
        links=links,
    )


def nx_topology(
    router_count: int,
    distance: int,
    labname: str,
    template_name: str,
    cfg: Config | None = None,
) -> ExportTopology:
    return _topology(
        _nx_graph(router_count, distance), labname, template_name, cfg or Config()
    )


def nx_plan(
    nodes: int,
    distance: int,
    labname: str,
    template: str = DEFAULT_TEMPLATE,
    cfg: Config | None = None,
) -> ExportTopology:
    return nx_topology(nodes, distance, labname, template, cfg)


def simple_plan(
    nodes: int,
    distance: int,
    labname: str,
    template: str = DEFAULT_TEMPLATE,
    cfg: Config | None = None,
) -> ExportTopology:
    return _topology(_simple_graph(nodes, distance), labname, template, cfg or Config())


def export_plan(plan: ExportTopology, output: str | Path) -> Path:
    return write_yaml(plan, output)


def main(args: Namespace) -> int:
    cfg = getattr(args, "topogen_config", None)
    plan = (
        nx_plan(args.nodes, args.distance, args.labname, args.template, cfg)
        if args.mode == "nx"
        else simple_plan(args.nodes, args.distance, args.labname, args.template, cfg)
    )
    export_plan(plan, args.output)
    return 0


def reference_json() -> dict:
    """Return the deterministic three-router FRR reference object."""
    return to_dict(nx_topology(3, 200, "topogen-reference", "frr"))
