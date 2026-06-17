"""
File Chain (see DEVELOPER.md):
Doc Version: v1.0.1
Date Modified: 2026-02-16

- Called by: render.py
- Purpose: LXC FRR boot script generator for FRRouting containers

TopoGen LXC FRR Configuration - FRRouting Container Boot Script Generator

PURPOSE:
    Generates boot configuration script for LXC-based FRRouting containers.
    Enables specified routing protocols (OSPF, BGP, etc.) and configures
    DNS resolution for the container.

WHO READS ME:
    - render.py: Calls lxcfrr_bootconfig() when using FRR-based templates

WHO I READ:
    - config.py: Config class for domain name
    - models.py: TopogenNode data model

DEPENDENCIES:
    - jinja2: Template rendering (Environment, BaseLoader)
    - textwrap: dedent() for inline template formatting

KEY EXPORTS:
    - lxcfrr_bootconfig(cfg, node, protocols, nameserver, dhcp): Returns boot script

GENERATED SCRIPT:
    - Enables DHCP on eth0 if requested
    - Enables specified FRR daemons (ospfd, bgpd, etc.) in /etc/frr/daemons
    - Configures DNS nameserver and search domain in /etc/resolv.conf
    - Increases MAX_FDS limit for FRR

PROTOCOLS:
    - Common values: ["ospf"], ["bgp"], ["ospf", "bgp"]
    - Maps to FRR daemon names: ospfd, bgpd, etc.
"""

from textwrap import dedent

from jinja2 import BaseLoader, Environment

from topogen.config import Config
from topogen.models import TopogenNode


def lxcfrr_bootconfig(
    cfg: Config, node: TopogenNode, protocols: list[str], nameserver: str, dhcp: bool
) -> str:
    """renders the LXC FRR boot.sh config"""
    basic_config = dedent(
        r"""
        #/bin/bash
        {%- if dhcp %}
        /sbin/udhcpc -i eth0
        {%- endif %}
        sed -r -e 's/^#(MAX_FDS=1024)$/\1/' -i /etc/frr/daemons
        {%- for proto in protocols %}
        sed -r -e 's/^({{ proto }}d=)no$/\1yes/' -i /etc/frr/daemons
        {%- endfor %}
        echo "nameserver {{ nameserver }}" >/etc/resolv.conf
        echo "search {{ config.domainname }}" >>/etc/resolv.conf
        """
    ).lstrip("\n")

    template = Environment(loader=BaseLoader).from_string(basic_config)  # type: ignore
    return template.render(
        node=node, config=cfg, protocols=protocols, nameserver=nameserver, dhcp=dhcp
    )
