"""
File Chain (see DEVELOPER.md):
Doc Version: v1.0.2
Date Modified: 2026-02-16

- Called by: main.py, render.py, dnshost.py, lxcfrr.py
- Purpose: Configuration loading and defaults management

TopoGen Configuration - Configuration Loading and Defaults Management

PURPOSE:
    Manages configuration loading from TOML files and provides sensible defaults
    for topology generation. Configuration includes IP address ranges, DNS settings,
    and default credentials for generated routers.

WHO READS ME:
    - main.py: Loads configuration via Config.load() during bootstrap
    - render.py: Uses Config instance for addressing, DNS, credentials

WHO I READ:
    - None (leaf module, no internal dependencies)

DEPENDENCIES:
    - serde: TOML serialization/deserialization (@deserialize, @serialize)
    - serde.toml: from_toml(), to_toml()
    - dataclasses: @dataclass decorator
    - ipaddress: IPv4Network for IP range definitions
    - logging: Configuration loading status messages

KEY EXPORTS:
    - Config: Dataclass containing all configuration parameters

CONFIG PARAMETERS:
    - loopbacks: IPv4Network for loopback addresses (default: 10.0.0.0/8)
    - p2pnets: IPv4Network for point-to-point links (default: 172.16.0.0/12)
    - nameserver: DNS server IP (default: 8.8.8.8)
    - domainname: Domain name for routers (default: virl.lab)
    - username: Router login username (default: cisco)
    - password: Router login password (default: cisco)

METHODS:
    - load(filename): Load configuration from TOML file, fall back to defaults
    - save(filename): Save current configuration to TOML file

FILE FORMAT:
    config.toml example:
    ```toml
    loopbacks = "10.0.0.0/8"
    p2pnets = "172.16.0.0/12"
    nameserver = "8.8.8.8"
    domainname = "virl.lab"
    username = "cisco"
    password = "cisco"
    ```
"""

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
