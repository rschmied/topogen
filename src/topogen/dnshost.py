"""configuration template for a DNS host"""

from textwrap import dedent
from typing import List

from jinja2 import BaseLoader, Environment

from topogen.config import Config
from topogen.models import DNShost, Node


def dnshostconfig(cfg: Config, node: Node, hosts: List[DNShost]) -> str:
    """renders the DNS host template"""
    basic_config = dedent(
        r"""
        # this is a shell script which will be sourced at boot
        hostname {{ node.hostname }}
        # configurable user account
        USERNAME={{ config.username }}
        # consider to configure a strong password here instead of the var
        PASSWORD={{ config.password }}

        # if static IP is needed on this gateway host:
        #
        # ifdown eth0
        # cat <<EOF >/etc/network/interfaces
        # auto lo
        # iface lo inet loopback
        #
        # auto eth0
        # iface eth0 inet static
        #         hostname dns-host
        #         address 172.16.5.10/25
        #         gateway 172.16.5.1
        # EOF
        #
        # cat <<EOF >/etc/resolv.conf
        # nameserver 1.2.3.4 1.2.3.5
        # search corp.com
        # EOF
        # ifup eth0

        # if a proxy is needed, add it here
        #
        # export HTTPS_PROXY="http://proxy.corp.com:80/"
        # export HTTP_PROXY="http://proxy.corp.com:80/"

        apk update
        apk add dnsmasq iptables

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
        ip address add {{ node.interfaces[0].address }} dev eth1
        ip route add {{ config.loopbacks }} via {{ node.interfaces[1].address.ip }}
        ip route add {{ config.p2pnets }} via {{ node.interfaces[1].address.ip }}

        {%- for host in hosts %}
        echo -e "{{ host.ipv4 }}\t{{ host.name }}.{{ config.domainname }}" >>/etc/hosts
        {%- endfor %}

        cp /etc/resolv.conf /etc/resolv.dnsmasq
        cat <<EOF >/etc/resolv.conf
        nameserver 127.0.0.1
        search {{ config.domainname }}
        EOF

        # configure SSH params
        SSH_DIR=/home/{{ config.username }}/.ssh
        mkdir -p $SSH_DIR
        chown {{ config.username }}.{{ config.username }} $SSH_DIR
        cat <<EOF >$SSH_DIR/config
        # this is NOT secure but we can not truly differentiate CIDR
        # notation network prefixes as given by the config and have a
        # matching host line...
        # if grepcidr (http://www.pc-tools.net/unix/grepcidr/) would be
        # available, then we could do something like this
        #
        # Match exec "grepcidr {{ config.loopbacks }} <(echo %h) &>/dev/null"
        #   KexAlgorithms
        #   ...
        # instead we allow this globally (insecure but good enough for a virtual
        # lab)
        KexAlgorithms +diffie-hellman-group-exchange-sha1,diffie-hellman-group14-sha1
        EOF

        # prevent UDHCPC from overwriting resolv.conf
        UDHCPC="/etc/udhcpc"
        UDHCPC_CONF="$UDHCPC/udhcpc.conf"
        mkdir -p "$UDHCPC"

        echo "NO_DNS=eth0" >$UDHCPC_CONF

        # make it a router, masquerading outgoing packets
        iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
        echo 1 > /proc/sys/net/ipv4/ip_forward

        service dnsmasq start
        """
    )

    template = Environment(loader=BaseLoader).from_string(basic_config)  # type: ignore
    return template.render(node=node, config=cfg, hosts=hosts)
