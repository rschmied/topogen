"""models for topogen topology generator"""

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

    address: IPv4Interface
    description: str = ""
    slot: int = 0


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
