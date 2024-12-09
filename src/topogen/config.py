"""configuration for topogen"""

import logging
from dataclasses import dataclass
from ipaddress import IPv4Network

from serde import deserialize, serialize, SerdeError
from serde.toml import from_toml, to_toml

_LOGGER = logging.getLogger(__name__)


@deserialize
@serialize
@dataclass
class Config:
    """topology generator configuration"""

    loopbacks: IPv4Network = IPv4Network("10.0.0.0/8")
    p2pnets: IPv4Network = IPv4Network("172.16.0.0/12")
    nameserver: str = "8.8.8.8"
    domainname: str = "virl.lab"
    username: str = "cisco"
    password: str = "cisco"

    @classmethod
    def load(cls, filename: str) -> "Config":
        """load the configuration from the given file"""
        try:
            with open(filename, encoding="utf-8") as handle:
                cfg = from_toml(cls, handle.read())
            _LOGGER.info("Configuration loaded from file %s", filename)
        except (FileNotFoundError, TypeError, SerdeError) as exc:
            if not isinstance(exc, FileNotFoundError):
                _LOGGER.error(exc)
            cfg = cls()
            _LOGGER.warning("using configuration defaults")
        return cfg

    def save(self, filename: str):
        """save the configuration to the given file"""
        with open(filename, "w+", encoding="utf-8") as handle:
            handle.write(to_toml(self))
