"""topology renderer"""

import importlib.resources as pkg_resources
import logging
import math
import os
from argparse import Namespace
from ipaddress import IPV4LENGTH, IPv4Interface, IPv4Network
from typing import Any, List, Set, Tuple, Union

import enlighten
import networkx as nx
from jinja2 import (
    Environment,
    PackageLoader,
    Template,
    TemplateNotFound,
    select_autoescape,
)
from requests.exceptions import ConnectionError, HTTPError  # pylint: disable=W0622
from virl2_client import ClientLibrary, InitializationError
from virl2_client.models import Lab

from topogen import templates
from topogen.config import Config
from topogen.dnshost import dnshostconfig
from topogen.models import (
    DNShost,
    Interface,
    Node,
    Point,
    TopogenError,
    CoordsGenerator,
)

_LOGGER = logging.getLogger(__name__)

EXT_CON_NAME = "ext-conn-0"
DNS_HOST_NAME = "dns-host"


def get_templates() -> List[str]:
    """get all available templates in the package"""
    return [
        t[: -len(Renderer.J2SUFFIX)]
        for t in pkg_resources.contents(templates)
        if t.endswith(Renderer.J2SUFFIX)
    ]


def disable_pcl_loggers():
    """set all virl python client library loggers to WARN, too much output"""
    loggers = [
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict  # pylint disable=E1101
    ]
    for logger in loggers:
        if logger.name.startswith("virl2_client"):
            logger.setLevel(logging.WARN)


def order_iface_pair(iface_pair: dict, this: int) -> Tuple[Any, Any]:
    """order the interface pair so that the first one is the one with the
    given index "this", and the second one is the other one.
    """
    (src_idx, src_iface), (_, dst_iface) = iface_pair.items()
    if this == src_idx:
        return src_iface, dst_iface
    return dst_iface, src_iface


def format_dns_entry(iface_pair: dict, this: int) -> str:
    """format the interface pair labels suitable for a DNS entry"""
    table = {
        ord("/"): "_",
        ord(" "): "-",
    }

    # these must be sorted by key length
    interface_names = {
        "TenGigabitEthernet": "ten",
        "GigabitEthernet": "gi",
        "Ethernet": "e",
    }

    src, dst = order_iface_pair(iface_pair, this)
    desc = f"{src.node.label}-{src.label}--{dst.node.label}-{dst.label}"

    for long, short in interface_names.items():
        if long in desc:
            desc = desc.replace(long, short)
            break

    return desc.translate(table).lower()


def format_interface_description(iface_pair: dict, this: int) -> str:
    """this puts the interface description together which gets inserted
    into the router configuration."""

    _, dst = order_iface_pair(iface_pair, this)
    # return f"from {src.node.label} {src.label} to {dst.node.label} {dst.label}"
    return f"to {dst.node.label} {dst.label}"


class Renderer:
    """A class to render (random) network topologies with templated configuration
    generation."""

    J2SUFFIX = ".jinja2"

    def __init__(self, args: Namespace, cfg: Config):
        self.args = args
        self.config = cfg

        self.template: Template
        self.client: ClientLibrary
        self.lab: Lab

        if args.nodes is None:
            raise TopogenError("need to provide number of nodes!")

        self.template = self.load_template()
        self.client = self.initialize_client()

        self.lab = self.client.create_lab(args.labname)
        _LOGGER.info("lab: %s", self.lab.id)

        # these will be /32 addresses
        self.loopbacks = IPv4Network(cfg.loopbacks).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.loopbacks.prefixlen
        )

        # these will be /30 addresses (4 addresses, 1 network, 1 broadcast, 2
        # hosts) e.g. 2 bits (hence the -2)
        self.p2pnets = IPv4Network(cfg.p2pnets).subnets(
            prefixlen_diff=IPV4LENGTH - cfg.p2pnets.prefixlen - 2
        )

        self.coords = iter(CoordsGenerator(distance=args.distance))

    def load_template(self) -> Template:
        """load the template"""
        name = self.args.template
        env = Environment(
            loader=PackageLoader("topogen"), autoescape=select_autoescape()
        )
        try:
            return env.get_template(f"{name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(f"template does not exist: {name}") from exc

    def initialize_client(self) -> ClientLibrary:
        """initialize the PCL"""
        cainfo: Union[bool, str] = self.args.cafile
        try:
            os.stat(self.args.cafile)
        except FileNotFoundError:
            cainfo = not self.args.insecure

        try:
            client = ClientLibrary(ssl_verify=cainfo)
            if not client.is_system_ready():
                raise TopogenError("system is not ready")
            return client
        except ConnectionError as exc:
            raise TopogenError("no connection: " + str(exc)) from None
        except InitializationError as exc:
            raise TopogenError(
                "no env provided, need VIRL2_URL, VIRL2_USER and VIRL2_PASS"
            ) from exc

    @staticmethod
    def new_interface(cmlnode):
        """create a new CML interface for the given node"""
        iface = cmlnode.next_available_interface()
        if iface is None:
            iface = cmlnode.create_interface()
        return iface

    def create_nx_network(self):
        """create a new random network using NetworkX"""

        # cluster size
        size = int(self.args.nodes / 4)
        size = max(size, 20)

        # how many clusters? ensure at least one
        clusters = int(self.args.nodes / size)
        remain = self.args.nodes - clusters * size
        dimensions = int(math.sqrt(self.args.nodes) * self.args.distance)

        constructor = [
            (size, size * 2, 0.999) if a < clusters else (remain, remain * 2, 0.999)
            for a in range(clusters + (1 if remain > 0 else 0))
        ]

        graph = nx.random_shell_graph(constructor)

        # for testing/troubleshooting, this is quite useful
        # graph = nx.barbell_graph(5, 0)

        if not nx.is_connected(graph):
            complement = list(nx.k_edge_augmentation(graph, k=1))
            graph.add_edges_from(complement)
        pos = nx.kamada_kawai_layout(graph, scale=dimensions)
        for key, value in pos.items():
            graph.nodes[key]["pos"] = Point(int(value[0]), int(value[1]))
        return graph

    def create_node(self, label: str, node_def: str, coords=Point(0, 0)):
        """create a CML2 node with the given attributes"""

        try:
            node = self.lab.create_node(
                label=label,
                node_definition=node_def,
                x=coords.x,
                y=coords.y,
                populate_interfaces=True,
            )
            # this is needed, otherwise the default interfaces which are created
            # might be missing locally
            self.lab.sync(topology_only=True)
            return node
        except HTTPError as exc:
            raise TopogenError("API error") from exc

    def create_ext_conn(self, coords=Point(0, 0)):
        """create an external connector node"""
        return self.create_node(EXT_CON_NAME, "external_connector", coords)

    def create_dns_host(self, coords=Point(0, 0)):
        """create the DNS host node"""
        node = self.create_node(DNS_HOST_NAME, "alpine", coords)
        node.create_interface()  # this is eth1
        return node

    def create_router(self, label: str, coords=Point(0, 0)):
        """create a router node (this uses the template given, e.g. iosv)"""
        return self.create_node(label, self.args.template, coords)

    def next_network(self) -> Set[IPv4Interface]:
        """return the next point-to-point network"""
        p2pnet = next(self.p2pnets)
        return set(IPv4Interface(f"{i}/{p2pnet.netmask}") for i in p2pnet.hosts())

    def render_node_network(self) -> int:
        """render the NX random network"""

        disable_pcl_loggers()
        _LOGGER.warning("Creating network")
        graph = self.create_nx_network()

        if self.args.progress:
            manager = enlighten.get_manager()
            eprog = manager.counter(
                total=graph.number_of_edges() + graph.number_of_nodes(),
                desc="topology",
                unit="elements",
                leave=False,
                color="cyan",
            )

        _LOGGER.warning("Creating edges and nodes")
        for edge in graph.edges:
            src, dst = edge
            prefix = next(self.p2pnets)
            graph.edges[edge]["prefix"] = prefix
            graph.edges[edge]["hosts"] = iter(prefix.hosts())
            for node_index in [src, dst]:
                node = graph.nodes[node_index]
                if node.get("cml2node") is None:
                    cml2node = self.create_router(f"R{node_index+1}", node["pos"])
                    _LOGGER.info("router: %s", cml2node.label)
                    node["cml2node"] = cml2node
                    if self.args.progress:
                        eprog.update()  # type:ignore
            src_iface = self.new_interface(graph.nodes[src]["cml2node"])
            dst_iface = self.new_interface(graph.nodes[dst]["cml2node"])
            self.lab.create_link(src_iface, dst_iface)

            desc = (
                f"{src_iface.node.label} {src_iface.label} -> "
                + f"{dst_iface.node.label} {dst_iface.label}"
            )
            _LOGGER.info("link: %s", desc)
            graph.edges[edge]["order"] = {
                src: src_iface,
                dst: dst_iface,
            }

            if self.args.progress:
                eprog.update()  # type: ignore

        if self.args.progress:
            nprog = manager.counter(  # type: ignore
                total=graph.number_of_nodes(),
                replace=eprog,  # type: ignore
                desc="configs ",
                unit=" configs",
                leave=False,
                color="cyan",
            )

        # create the external connector
        ext_con = self.create_ext_conn(coords=Point(0, 0))
        _LOGGER.warning("External connector: %s", ext_con.label)

        # create the DNS host
        dns_addr, dns_via = self.next_network()
        dns_host = self.create_dns_host(coords=Point(self.args.distance, 0))
        _LOGGER.warning("DNS host: %s", dns_host.label)
        dns_iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_addr.ip)
        dns_zone: List[DNShost] = []

        # link the two
        self.lab.create_link(
            ext_con.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.warning("Creating ext-conn link")

        core = sorted(
            nx.degree_centrality(graph).items(), key=lambda e: e[1], reverse=True
        )[0][0]
        _LOGGER.warning("Identified core node is R%s", core + 1)

        _LOGGER.warning("Creating node configurations")
        for node_index, nbrs in graph.adj.items():
            interfaces: List[Interface] = []

            for _, eattr in nbrs.items():
                prefix = eattr["prefix"]
                hosts = eattr["hosts"]
                order = eattr["order"]

                addr = IPv4Interface(f"{next(hosts)}/{prefix.netmask}")
                label = format_interface_description(order, node_index)
                interfaces.append(Interface(addr, label, slot=order[node_index].slot))
                dns_zone.append(DNShost(format_dns_entry(order, node_index), addr.ip))

            if node_index == core:
                core_iface = self.new_interface(graph.nodes[node_index]["cml2node"])
                self.lab.create_link(
                    dns_iface,
                    core_iface,
                )

                pair = {core: core_iface, 0: dns_iface}
                label = format_interface_description(pair, node_index)
                interfaces.append(Interface(dns_via, label, slot=core_iface.slot))
                dns_zone.append(DNShost(format_dns_entry(pair, node_index), dns_via.ip))

                _LOGGER.warning("DNS host link")

            # need to sort interface list by slot
            interfaces.sort(key=lambda x: x.slot)

            loopback = IPv4Interface(next(self.loopbacks))
            node = Node(
                hostname=f"R{node_index+1}",
                loopback=loopback,
                interfaces=interfaces,
            )
            # "origin" identifies the default gateway on the node connecting
            # to the DNS host
            config = self.template.render(
                config=self.config,
                node=node,
                origin="" if node_index != core else dns_addr,
            )
            graph.nodes[node_index]["cml2node"].config = config

            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            _LOGGER.warning("Config created for %s", node.hostname)
            if self.args.progress:
                nprog.update()  # type: ignore

        # finalize the DNS host configuration
        node = Node(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                Interface(dns_addr),
                Interface(dns_via),
            ],
        )
        dns_zone.append(DNShost(f"{DNS_HOST_NAME}-eth1", dns_addr.ip))
        dns_host.config = dnshostconfig(self.config, node, dns_zone)
        _LOGGER.warning("Config created for DNS host")
        _LOGGER.warning("Done")

        if self.args.progress:
            nprog.close()  # type: ignore
            manager.stop()  # type: ignore

        return 0

    def render_node_sequence(self):
        """render the square spiral / node sequence network. Note: due to TTL
        limitations, it does not make a lot of sense to have this larger than
        32 or so hosts if end-to-end connectivity is required... One can still
        hop hop-by-hop, but DNS won't work all the way back to the DNS host!
        """

        disable_pcl_loggers()
        prev_iface = None
        prev_cml2iface = None

        if self.args.progress:
            manager = enlighten.get_manager(coords=next(self.coords))
            ticks = manager.counter(
                total=self.args.nodes,
                desc="Progress",
                unit="nodes",
                color="cyan",
                leave=False,
            )

        # create the external connector
        cml2_node = self.create_ext_conn()
        _LOGGER.info("external connector: %s", cml2_node.label)

        # create the DNS host
        dns_iface, prev_iface = self.next_network()
        dns_via = prev_iface
        dns_host = self.create_dns_host(coords=next(self.coords))
        _LOGGER.info("DNS host: %s", dns_host.label)
        prev_cml2iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_iface.ip)
        dns_zone: List[DNShost] = []

        # link the two
        self.lab.create_link(
            cml2_node.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.info("ext-conn link")

        for idx in range(self.args.nodes):
            loopback = IPv4Interface(next(self.loopbacks))
            src_iface, dst_iface = self.next_network()
            interfaces = [
                Interface(src_iface),
                Interface(prev_iface),
            ]
            node = Node(
                hostname=f"R{idx+1}",
                loopback=loopback,
                interfaces=interfaces,
            )
            config = self.template.render(config=self.config, node=node)
            cml2_node = self.create_node(
                node.hostname, self.args.template, next(self.coords)
            )
            cml2_node.config = config
            _LOGGER.info("node: %s", cml2_node.label)
            self.lab.create_link(prev_cml2iface, cml2_node.get_interface_by_slot(1))
            _LOGGER.info("link %s", prev_cml2iface.label)
            prev_cml2iface = cml2_node.get_interface_by_slot(0)
            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            prev_iface = dst_iface
            if self.args.progress:
                ticks.update()  # type: ignore

        # finalize the DNS host configuration
        node = Node(
            hostname=DNS_HOST_NAME,
            loopback=None,
            interfaces=[
                Interface(dns_iface),
                Interface(dns_via),
            ],
        )
        dns_host.config = dnshostconfig(self.config, node, dns_zone)

        if self.args.progress:
            ticks.close()  # type: ignore
            manager.stop()  # type: ignore

        return 0
