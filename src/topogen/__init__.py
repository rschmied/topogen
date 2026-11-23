"""topogen topology generator"""

import importlib.metadata as importlib_metadata

from .config import Config
from .exporter import ExportLab, ExportLink, ExportNode, ExportTopology, write_yaml
from .main import main

_metadata = importlib_metadata.metadata("topogen")
__version__ = _metadata["Version"]
__description__ = _metadata["Summary"]


__all__ = [
    "Config",
    "ExportLab",
    "ExportLink",
    "ExportNode",
    "ExportTopology",
    "main",
    "write_yaml",
]
