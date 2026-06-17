"""
File Chain (see DEVELOPER.md):
Doc Version: v1.0.1
Date Modified: 2026-02-16

- Called by: main.py, render.py, dnshost.py, lxcfrr.py, gui.py
- Purpose: Core data models for topology generation

TopoGen Data Models - Core Data Structures for Topology Generation

PURPOSE:
    Defines core data models used throughout topogen for representing network
    topology elements (nodes, interfaces, coordinates) and error handling.

WHO READS ME:
    - render.py: Uses all models for topology generation
    - main.py: Uses TopogenError for exception handling
    - dnshost.py: Uses DNShost model
    - lxcfrr.py: Uses TopogenNode for FRR configuration

WHO I READ:
    - None (leaf module, no internal dependencies)

DEPENDENCIES:
    - dataclasses: @dataclass decorator, replace()
    - ipaddress: IPv4Address, IPv4Interface for IP addressing

KEY EXPORTS:
    - TopogenError: Base exception class for all topogen errors
    - Point: 2D coordinate (x, y) for CML layout
    - CoordsGenerator: Iterator generating square spiral coordinates
    - TopogenInterface: Network interface with address, VRF, description, slot
    - TopogenNode: Network node with hostname, loopback, interfaces, coordinates
    - DNShost: DNS host node configuration

DATA MODELS:

    Point:
        - x: int (horizontal coordinate)
        - y: int (vertical coordinate)

    CoordsGenerator:
        - Generates coordinates in square spiral pattern
        - Used for deterministic node placement in CML GUI
        - Pattern: center → up → right → down → left (expanding outward)

    TopogenInterface:
        - address: IPv4Interface | None (IP address/netmask)
        - vrf: str | None (VRF name if applicable)
        - description: str (interface description/purpose)
        - slot: int (physical slot number)

    TopogenNode:
        - hostname: str (router hostname)
        - loopback: IPv4Interface (loopback0 address)
        - interfaces: list[TopogenInterface] (all interfaces)
        - coords: Point (X/Y position in CML)

    DNShost:
        - Represents DNS/NTP host node in simple/NX topologies
        - Contains addressing and configuration for DNS services
"""

from dataclasses import dataclass, replace
from ipaddress import IPv4Address, IPv4Interface


class TopogenError(Exception):
    """Base class for all errors raised by topogen"""


@dataclass
class Point:
    """a point in a carthesian coordinate system"""

    x: int
    y: int


class CoordsGenerator:
    """a generator which generates square spiral coordinates"""

    DIRSM = {"l": "u", "u": "r", "r": "d", "d": "l"}

    def __init__(self, distance: int = 200):
        self.distance = distance
        self.step = 1
        self.dir = "u"
        self.point = Point(0, 0)

    def __iter__(self):
        while True:
            for _ in (0, 1):
                for _ in range(self.step):
                    yield replace(self.point)
                    if self.dir == "u":
                        self.point.y += self.distance
                    elif self.dir == "r":
                        self.point.x += self.distance
                    elif self.dir == "d":
                        self.point.y -= self.distance
                    else:  # self.dir == "l"
                        self.point.x -= self.distance
                self.dir = CoordsGenerator.DIRSM[self.dir]
            self.step += 1


@dataclass
class TopogenInterface:
    """interface of a node, slot is the physical slot in the device"""

    address: IPv4Interface | None = None
    vrf: str | None = None
    description: str = ""
    slot: int = 0
    ipv6_address: str | None = None
    ipv6_link_local_address: str | None = None


@dataclass
class TopogenNode:
    """a node of a topology"""

    hostname: str
    loopback: IPv4Interface | None
    interfaces: list[TopogenInterface]


@dataclass
class DNShost:
    """a DNS host of a topology, this typically only exists once"""

    name: str
    ipv4: IPv4Address
