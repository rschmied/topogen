"""Day-zero configuration for the FRR Docker node."""

from textwrap import dedent

from jinja2 import BaseLoader, Environment

from topogen.config import Config


def frr_bootconfig(cfg: Config, nameserver: str, dhcp: bool) -> str:
    """Render the FRR Docker node's boot.sh file."""
    basic_config = dedent(
        r"""
        #!/bin/bash
        {%- if dhcp %}
        /sbin/udhcpc -i eth0
        {%- endif %}
        echo "nameserver {{ nameserver }}" >/etc/resolv.conf
        echo "search {{ config.domainname }}" >>/etc/resolv.conf
        exit 0
        """
    ).lstrip("\n")

    template = Environment(loader=BaseLoader).from_string(basic_config)  # type: ignore
    return template.render(config=cfg, nameserver=nameserver, dhcp=dhcp)
