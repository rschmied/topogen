from __future__ import annotations

from topogen.config import Config
from topogen.frr import frr_bootconfig


def test_frr_bootconfig_without_dhcp():
    out = frr_bootconfig(Config(domainname="lab.local"), "172.16.0.10", False)
    assert "#!/bin/bash" in out
    assert "/sbin/udhcpc -i eth0" not in out
    assert 'echo "nameserver 172.16.0.10" >/etc/resolv.conf' in out
    assert 'echo "search lab.local" >>/etc/resolv.conf' in out


def test_frr_bootconfig_with_dhcp():
    out = frr_bootconfig(Config(domainname="lab.local"), "172.16.0.10", True)
    assert "/sbin/udhcpc -i eth0" in out
    assert "exit 0" in out
