from dataclasses import dataclass, replace
from ipaddress import IPv4Address, IPv4Interface
from typing import List


class TopogenError(Exception):
    """Base class for all errors raised by topogen"""


@dataclass
class Point:
    x: int
    y: int


class coords_generator:

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
                self.dir = coords_generator.DIRSM[self.dir]
            self.step += 1


@dataclass
class Interface:
    description: str
    address: IPv4Interface


@dataclass
class Node:
    hostname: str
    loopback: IPv4Interface
    interfaces: List[IPv4Interface]


@dataclass
class DNShost:
    name: str
    ipv4: IPv4Address
