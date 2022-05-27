import logging
from dataclasses import dataclass
from ipaddress import IPv4Network

from serde import deserialize, serialize
from serde.toml import from_toml, to_toml

_LOGGER = logging.getLogger("__name__")


@deserialize
@serialize
@dataclass
class Config:
    loopbacks: IPv4Network = IPv4Network("10.0.0.0/8")
    p2pnets: IPv4Network = IPv4Network("172.16.0.0/12")
    nameserver: str = "8.8.8.8"
    domainname: str = "virl.lab"
    username: str = "cisco"
    password: str = "cisco"

    @classmethod
    def load(cls, filename: str) -> "Config":
        try:
            with open(filename) as fh:
                cfg = from_toml(cls, fh.read())
        except (FileNotFoundError, TypeError) as exc:
            if not isinstance(exc, FileNotFoundError):
                _LOGGER.error(exc)
            cfg = cls()
        return cfg

    def save(self, filename: str):
        with open(filename, "w+") as fh:
            fh.write(to_toml(self))
