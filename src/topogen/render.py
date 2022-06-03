import importlib.resources as pkg_resources
import logging
import math
import os
from argparse import Namespace
from ipaddress import IPV4LENGTH, IPv4Interface, IPv4Network
from typing import List, Optional, Set, Union

import enlighten
import networkx as nx
from jinja2 import (
    Environment,
    PackageLoader,
    Template,
    TemplateNotFound,
    select_autoescape,
)
from requests.exceptions import ConnectionError, HTTPError
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
    coords_generator,
)

_LOGGER = logging.getLogger(__name__)

EXT_CON_NAME = "ext-conn-0"
DNS_HOST_NAME = "dns-host"


def get_templates() -> List[str]:
    return [
        t[: -len(Renderer.J2SUFFIX)]
        for t in pkg_resources.contents(templates)
        if t.endswith(Renderer.J2SUFFIX)
    ]


def disable_pcl_loggers():
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    for logger in loggers:
        if logger.name.startswith("virl2_client"):
            logger.setLevel(logging.WARN)


def format_dns_entry(desc: str) -> str:

    t = {
        ord("/"): "-",
        ord(" "): "-",
    }

    # these must be sorted by key length
    interface_names = {
        "TenGigabitEthernet": "ten",
        "GigabitEthernet": "gi",
        "Ethernet": "e",
    }

    for long, short in interface_names.items():
        if long in desc:
            desc = desc.replace(long, short)
            break

    return desc.translate(t).lower()


class Renderer:

    J2SUFFIX = ".jinja2"

    def __init__(self, args: Namespace, cfg: Config):
        self.args = args
        self.config = cfg

        self.template: Optional[Template]
        self.client: Optional[ClientLibrary]
        self.lab: Optional[Lab]

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

        self.coords = iter(coords_generator(distance=args.distance))

    def load_template(self) -> Template:
        name = self.args.template
        env = Environment(
            loader=PackageLoader("topogen"), autoescape=select_autoescape()
        )
        try:
            return env.get_template(f"{name}{Renderer.J2SUFFIX}")
        except TemplateNotFound as exc:
            raise TopogenError(f"template does not exist: {name}") from exc

    def initialize_client(self) -> ClientLibrary:
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
        iface = cmlnode.next_available_interface()
        if iface is None:
            iface = cmlnode.create_interface()
        return iface

    def create_nx_network(self):
        size = int(self.args.nodes / 4)
        if size < 20:
            size = 20

        clusters = int(self.args.nodes / size)
        remain = self.args.nodes - clusters * size
        dimensions = int(math.sqrt(self.args.nodes) * self.args.distance)

        constructor = [
            (size, size * 2, 0.999) if a < clusters else (remain, remain * 2, 0.999)
            for a in range(clusters + (1 if remain > 0 else 0))
        ]

        G = nx.random_shell_graph(constructor)

        # for testing/troubleshooting, this is quite useful
        # G = nx.barbell_graph(5, 0)

        if not nx.is_connected(G):
            complement = list(nx.k_edge_augmentation(G, k=1))
            G.add_edges_from(complement)
        pos = nx.kamada_kawai_layout(G, scale=dimensions)
        for k, v in pos.items():
            G.nodes[k]["pos"] = Point(int(v[0]), int(v[1]))
        return G

    def create_node(self, label: str, node_def: str, c: Point = None):
        if c is None:
            c = next(self.coords)
        try:
            return self.lab.create_node(
                label=label,
                node_definition=node_def,
                x=c.x,
                y=c.y,
                populate_interfaces=True,
            )
        except HTTPError as exc:
            raise TopogenError("API error") from exc

    def create_ext_conn(self, c: Point = None):
        return self.create_node(EXT_CON_NAME, "external_connector", c)

    def create_dns_host(self, c: Point = None):
        node = self.create_node(DNS_HOST_NAME, "alpine", c)
        self.lab.sync(topology_only=True)
        node.create_interface()  # this is eth1
        return node

    def create_router(self, label: str, c: Point = None):
        return self.create_node(label, self.args.template, c)

    def next_network(self) -> Set[IPv4Interface]:
        p2pnet = next(self.p2pnets)
        return (IPv4Interface(f"{i}/{p2pnet.netmask}") for i in p2pnet.hosts())

    def render_node_network(self) -> int:

        disable_pcl_loggers()
        _LOGGER.warn("Creating network")
        g = self.create_nx_network()

        if self.args.progress:
            manager = enlighten.get_manager()
            eprog = manager.counter(
                total=g.number_of_edges() + g.number_of_nodes(),
                desc="topology",
                unit="elements",
                leave=False,
                color="cyan",
            )

        _LOGGER.warn("Creating edges and nodes")
        for e in g.edges:
            src, dst = e
            prefix = next(self.p2pnets)
            g.edges[e]["prefix"] = prefix
            g.edges[e]["hosts"] = iter(prefix.hosts())
            for n in [src, dst]:
                node = g.nodes[n]
                if node.get("cml2node") is None:
                    cml2node = self.create_router(f"R{n+1}", node["pos"])
                    _LOGGER.info("router: %s", cml2node.label)
                    node["cml2node"] = cml2node
                    # this is needed, otherwise the default interfaces which
                    # are created might be missing locally
                    self.lab.sync(topology_only=True)
                    if self.args.progress:
                        eprog.update()
            src_iface = self.new_interface(g.nodes[src]["cml2node"])
            dst_iface = self.new_interface(g.nodes[dst]["cml2node"])
            self.lab.create_link(src_iface, dst_iface)

            desc = f"from {src_iface.node.label} {src_iface.label} to {dst_iface.node.label} {dst_iface.label}"
            _LOGGER.info("link: %s", desc)
            g.edges[e]["desc"] = desc
            g.edges[e]["order"] = {
                src: src_iface.slot,
                dst: dst_iface.slot,
            }

            if self.args.progress:
                eprog.update()

        nprog = manager.counter(
            total=g.number_of_nodes(),
            replace=eprog,
            desc="configs ",
            unit=" configs",
            leave=False,
            color="cyan",
        )

        # create the external connector
        ext_con = self.create_ext_conn(c=Point(0, 0))
        _LOGGER.warn("External connector: %s", ext_con.label)

        # create the DNS host
        dns_addr, dns_via = self.next_network()
        dns_host = self.create_dns_host(c=Point(self.args.distance, 0))
        _LOGGER.warn("DNS host: %s", dns_host.label)
        dns_iface = dns_host.get_interface_by_slot(1)

        # prepare DNS configuration
        self.config.nameserver = str(dns_addr.ip)
        dns_zone: List[DNShost] = []

        # link the two
        self.lab.create_link(
            ext_con.get_interface_by_slot(0),
            dns_host.get_interface_by_slot(0),
        )
        _LOGGER.warn("Creating ext-conn link")

        core = sorted(
            nx.degree_centrality(g).items(), key=lambda e: e[1], reverse=True
        )[0][0]
        _LOGGER.warn("Identified core node is R%s", core + 1)

        _LOGGER.warn("Creating node configurations")
        for n, nbrs in g.adj.items():
            interfaces: List[Interface] = []

            for _, eattr in nbrs.items():
                prefix = eattr["prefix"]
                hosts = eattr["hosts"]
                desc = eattr["desc"]
                order = eattr["order"]

                addr = IPv4Interface(f"{next(hosts)}/{prefix.netmask}")
                interfaces.append(Interface(desc, addr, slot=order[n]))
                dns_zone.append(DNShost(format_dns_entry(desc), addr.ip))

            if n == core:
                core_iface = self.new_interface(g.nodes[n]["cml2node"])
                self.lab.create_link(
                    dns_iface,
                    core_iface,
                )
                label = f"from {core_iface.node.label} {core_iface.label} to {DNS_HOST_NAME} eth1"
                interfaces.append(Interface(label, dns_via, slot=core_iface.slot))
                dns_zone.append(DNShost(format_dns_entry(label), dns_via.ip))
                _LOGGER.warn("DNS host link")

            # need to sort interface list by slot
            interfaces.sort(key=lambda x: x.slot)

            loopback = IPv4Interface(next(self.loopbacks))
            node = Node(
                hostname=f"R{n+1}",
                loopback=loopback,
                interfaces=interfaces,
            )
            # "origin" identifies the default gateway on the node connecting
            # to the DNS host
            config = self.template.render(
                config=self.config,
                node=node,
                origin="" if n != core else dns_addr,
            )
            g.nodes[n]["cml2node"].config = config
            self.lab.sync(topology_only=True)

            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            _LOGGER.warn("Config created for %s", node.hostname)
            if self.args.progress:
                nprog.update()

        # finalize the DNS host configuration
        node = Node(
            hostname=DNS_HOST_NAME, loopback=None, interfaces=[dns_addr, dns_via]
        )
        dns_zone.append(DNShost(f"{DNS_HOST_NAME}-eth1", dns_addr))
        dns_host.config = dnshostconfig(self.config, node, dns_zone)
        self.lab.sync(topology_only=True)
        _LOGGER.warn("Config created for DNS host")
        _LOGGER.warn("Done")

        if self.args.progress:
            nprog.close()
            manager.stop()

        return

    def render_node_sequence(self):

        disable_pcl_loggers()
        prev_iface = None
        prev_cml2iface = None

        if self.args.progress:
            manager = enlighten.get_manager()
            ticks = manager.counter(
                total=self.args.nodes, desc="Progress", unit="nodes", color="cyan"
            )

        # create the external connector
        cml2_node = self.create_ext_conn()
        _LOGGER.info("external connector: %s", cml2_node.label)

        # create the DNS host
        dns_iface, prev_iface = self.next_network()
        dns_via = prev_iface
        dns_host = self.create_dns_host()
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
                Interface("", src_iface),
                Interface("", prev_iface),
            ]
            node = Node(
                hostname=f"R{idx+1}",
                loopback=loopback,
                interfaces=interfaces,
            )
            config = self.template.render(config=self.config, node=node)
            cml2_node = self.create_node(node.hostname, self.args.template)
            cml2_node.config = config
            self.lab.sync(topology_only=True)
            _LOGGER.info("node: %s", cml2_node.label)
            self.lab.create_link(prev_cml2iface, cml2_node.get_interface_by_slot(1))
            _LOGGER.info("link %s", prev_cml2iface.label)
            prev_cml2iface = cml2_node.get_interface_by_slot(0)
            dns_zone.append(DNShost(node.hostname.lower(), loopback.ip))
            prev_iface = dst_iface
            if self.args.progress:
                ticks.update()

        # finalize the DNS host configuration
        node = Node(
            hostname=DNS_HOST_NAME, loopback=None, interfaces=[dns_iface, dns_via]
        )
        dns_host.config = dnshostconfig(self.config, node, dns_zone)
        self.lab.sync(topology_only=True)

        if self.args.progress:
            ticks.close()
            manager.stop()

        return 0
