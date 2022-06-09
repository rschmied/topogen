""" topogen topology generator
"""
import importlib.metadata as importlib_metadata

from .config import Config
from .render import Renderer

_metadata = importlib_metadata.metadata("topogen")
__version__ = _metadata["Version"]
__description__ = _metadata["Summary"]


__all__ = ["Config", "Renderer"]
