from textwrap import dedent
from typing import List

from jinja2 import BaseLoader, Environment

from topogen.config import Config
from topogen.models import DNShost, Node


def dnshostconfig(cfg: Config, node: Node, hosts: List[DNShost]) -> str:
    basic_config = dedent(
        r"""
        # this is a shell script which will be sourced at boot
        hostname {{ node.hostname }}
        # configurable user account
        USERNAME={{ config.username }}
        PASSWORD={{ config.password }}

        apk update
        apk add dnsmasq

        cat <<EOF >/etc/dnsmasq.conf
        domain-needed
        bogus-priv
        resolv-file=/etc/resolv.dnsmasq
        no-poll
        local=/{{ config.domainname }}/
        interface=eth1
        no-dhcp-interface=eth1
        log-queries
        conf-dir=/etc/dnsmasq.d/,*.conf
        EOF

        ip link set eth1 up
        ip address add {{ node.interfaces[0] }} dev eth1
        ip route add {{ config.loopbacks }} via {{ node.interfaces[1].ip }}

        {%- for host in hosts %}
        echo -e "{{ host.ipv4 }}\t{{ host.name }}.{{ config.domainname }}" >>/etc/hosts
        {%- endfor %}

        cp /etc/resolv.conf /etc/resolv.dnsmasq
        cat <<EOF >/etc/resolv.conf
        nameserver 127.0.0.1
        search {{ config.domainname }}
        EOF

        service dnsmasq start
        """
    )

    template = Environment(loader=BaseLoader).from_string(basic_config)
    return template.render(node=node, config=cfg, hosts=hosts)
