"""configuration template for a LXC frr host"""

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
