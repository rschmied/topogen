"""Offline YAML topology generation."""

from __future__ import annotations

import logging
import random
from argparse import Namespace
from collections.abc import Iterator
from dataclasses import replace
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
from topogen.node_definitions import interface_labels, router_definition

DEFAULT_TEMPLATE = "iosv"

_LOGGER = logging.getLogger(__name__)


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
    provisioner: str, config: str, nameserver: str, cfg: Config
) -> list[dict[str, str]]:
    if provisioner != "frr":
        return [{"name": "ios_config.txt", "content": config.rstrip("\n")}]
    return [
        {"name": "node.cfg", "content": config.rstrip("\n")},
        {
            "name": "boot.sh",
            "content": frr_bootconfig(cfg, nameserver, False).rstrip("\n"),
        },
        {"name": "protocols", "content": "ospfd\nbgpd"},
    ]


def _nx_graph(router_count: int, distance: int, seed: int | None = None) -> nx.Graph:
    if router_count < 2:
        raise ValueError("at least two routers are required")
    _LOGGER.info("Creating random-shell router graph")
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
        _LOGGER.debug("Random-shell constructor: %s", constructor)
        graph = nx.random_shell_graph(constructor, seed=seed)
        if not nx.is_connected(graph):
            augmentation = list(nx.k_edge_augmentation(graph, k=1))
            _LOGGER.warning(
                "Adding %s links to connect the router graph", len(augmentation)
            )
            graph.add_edges_from(augmentation)
    if router_count == 3:
        graph.nodes[0]["pos"] = Point(346, 0)
        graph.nodes[1]["pos"] = Point(-173, 299)
        graph.nodes[2]["pos"] = Point(-172, -299)
    else:
        positions = nx.kamada_kawai_layout(graph, scale=sqrt(router_count) * distance)
        for node_id, pos in positions.items():
            graph.nodes[node_id]["pos"] = Point(int(pos[0]), int(pos[1]))
    _LOGGER.info(
        "Router graph has %s nodes and %s links",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    _LOGGER.debug("Router positions: %s", nx.get_node_attributes(graph, "pos"))
    return graph


def _simple_graph(router_count: int, distance: int) -> nx.Graph:
    if router_count < 2:
        raise ValueError("at least two routers are required")
    _LOGGER.info("Creating router chain")
    graph = nx.path_graph(router_count)
    coords = iter(CoordsGenerator(distance))
    for node_id in graph.nodes:
        graph.nodes[node_id]["pos"] = next(coords)
    _LOGGER.info(
        "Router graph has %s nodes and %s links",
        graph.number_of_nodes(),
        graph.number_of_edges(),
    )
    _LOGGER.debug("Router positions: %s", nx.get_node_attributes(graph, "pos"))
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
    _LOGGER.info(
        "Validated address pools for %s routers and %s /30 networks",
        graph.number_of_nodes(),
        required_p2p_networks,
    )


def _router_mix(router_count: int, router_types: list[str], seed: int | None) -> dict[int, str]:
    if not router_types:
        return {}
    percentages: dict[str, int] = {}
    for value in router_types:
        try:
            name, percent = value.split("=", 1)
            percent_value = int(percent)
        except ValueError as exc:
            raise ValueError(f"invalid router type: {value}; expected NAME=PERCENT") from exc
        if name in percentages or percent_value < 1:
            raise ValueError(f"invalid router type: {value}")
        router_definition(name)
        percentages[name] = percent_value
    if sum(percentages.values()) != 100:
        raise ValueError("router type percentages must total 100")
    counts = {name: router_count * percent // 100 for name, percent in percentages.items()}
    remaining = router_count - sum(counts.values())
    for name in sorted(percentages, key=lambda name: (router_count * percentages[name] % 100, name), reverse=True)[:remaining]:
        counts[name] += 1
    names = [name for name, count in counts.items() for _ in range(count)]
    random.Random(seed).shuffle(names)
    return dict(enumerate(names))


def _topology(
    graph: nx.Graph, labname: str, template_name: str, cfg: Config,
    router_types: list[str] | None = None, seed: int | None = None,
) -> ExportTopology:
    """Build an offline router graph with DNS and an external connector."""
    router_definition(template_name)
    _validate_address_capacity(graph, cfg)
    router_count = graph.number_of_nodes()
    templates = _router_mix(router_count, router_types or [], seed)
    if not templates:
        templates = {node_id: template_name for node_id in graph.nodes}
    _LOGGER.info("Router types: %s", ", ".join(templates.values()))
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
        left_template = templates[left]
        right_template = templates[right]
        left_label = interface_labels(left_template, left_slot + 1)[left_slot]
        right_label = interface_labels(right_template, right_slot + 1)[right_slot]
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
        _LOGGER.debug(
            "Allocated %s: R%s %s %s <-> R%s %s %s",
            network,
            left + 1,
            left_label,
            left_addr,
            right + 1,
            right_label,
            right_addr,
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
    _LOGGER.info("Selected R%s as DNS core router", core + 1)
    dns_network = next(p2p_networks)
    core_addr, dns_addr = (
        IPv4Interface(f"{host}/{dns_network.prefixlen}") for host in dns_network.hosts()
    )
    core_slot = len(router_interfaces[core])
    dns_label = interface_labels("alpine", 2)[1]
    core_label = interface_labels(templates[core], core_slot + 1)[core_slot]
    router_interfaces[core].append(
        TopogenInterface(core_addr, f"to dns-host {dns_label}", core_slot)
    )
    dns_name = _dns_name(f"R{core + 1}", core_label, "dns-host", dns_label)
    dns_zone.extend([DNShost(dns_name, core_addr.ip), DNShost(dns_name, dns_addr.ip)])

    loopback_addresses = [IPv4Interface(f"{next(loopbacks)}/32") for _ in graph.nodes]
    nameserver = str(dns_addr.ip)
    router_cfg = replace(cfg, nameserver=nameserver)
    environment = Environment(loader=PackageLoader("topogen", "templates"))
    routers: list[ExportNode] = []
    _LOGGER.info("Rendering configuration for %s routers", router_count)
    for node_id in graph.nodes:
        node_template = templates[node_id]
        definition = router_definition(node_template)
        assert definition.template is not None
        assert definition.provisioner is not None
        config_template = environment.get_template(definition.template)
        node = TopogenNode(
            hostname=f"R{node_id + 1}",
            loopback=loopback_addresses[node_id],
            interfaces=router_interfaces[node_id],
        )
        config = config_template.render(
            config=router_cfg,
            node=node,
            date=datetime.now(UTC),
            origin=dns_addr if node_id == core else "",
        )
        pos = graph.nodes[node_id]["pos"]
        routers.append(
            ExportNode(
                id=f"n{node_id}",
                label=node.hostname,
                node_definition=node_template,
                x=pos.x,
                y=pos.y,
                interfaces=_router_interfaces(
                    node_template, len(router_interfaces[node_id])
                ),
                configuration=_config_files(definition.provisioner, config, nameserver, router_cfg),
            )
        )
        assert node.loopback is not None
        dns_zone.append(DNShost(node.hostname.lower(), node.loopback.ip))
        _LOGGER.debug("Rendered %s using %s", node.hostname, node_template)

    dns_zone.append(DNShost("dns-host-eth1", dns_addr.ip))
    _LOGGER.info("Rendering DNS host configuration with %s DNS records", len(dns_zone))
    _LOGGER.debug("DNS records: %s", dns_zone)
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
    router_types: list[str] | None = None,
    seed: int | None = None,
) -> ExportTopology:
    return _topology(
        _nx_graph(router_count, distance, seed), labname, template_name, cfg or Config(), router_types, seed
    )


def nx_plan(
    nodes: int,
    distance: int,
    labname: str,
    template: str = DEFAULT_TEMPLATE,
    cfg: Config | None = None,
    router_types: list[str] | None = None,
    seed: int | None = None,
) -> ExportTopology:
    return nx_topology(nodes, distance, labname, template, cfg, router_types, seed)


def simple_plan(
    nodes: int,
    distance: int,
    labname: str,
    template: str = DEFAULT_TEMPLATE,
    cfg: Config | None = None,
    router_types: list[str] | None = None,
    seed: int | None = None,
) -> ExportTopology:
    return _topology(_simple_graph(nodes, distance), labname, template, cfg or Config(), router_types, seed)


def export_plan(plan: ExportTopology, output: str | Path) -> Path:
    _LOGGER.info("Writing topology to %s", output)
    target = write_yaml(plan, output)
    _LOGGER.info(
        "Wrote topology with %s nodes and %s links to %s",
        len(plan.nodes),
        len(plan.links),
        target,
    )
    return target


def main(args: Namespace) -> int:
    _LOGGER.info(
        "Generating %s topology with %s %s routers",
        args.mode,
        args.nodes,
        args.template,
    )
    cfg = getattr(args, "topogen_config", None)
    plan = (
        nx_plan(args.nodes, args.distance, args.labname, args.template, cfg, args.router_type, args.seed)
        if args.mode == "nx"
        else simple_plan(args.nodes, args.distance, args.labname, args.template, cfg, args.router_type, args.seed)
    )
    export_plan(plan, args.output)
    return 0


def reference_json() -> dict:
    """Return the deterministic three-router FRR reference object."""
    return to_dict(nx_topology(3, 200, "topogen-reference", "frr"))
