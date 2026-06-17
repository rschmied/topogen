"""
File Chain (see DEVELOPER.md):
Doc Version: v1.1.1
Date Modified: 2026-02-16

- Called by: Python import system (when `import topogen` is executed), entry_points (CLI commands)
- Reads from: importlib.metadata (package metadata), config.py, render.py, main.py
- Writes to: None (package initialization only, exports public API)
- Calls into: importlib.metadata.metadata, config.Config, render.Renderer, main.main

Purpose: Package initialization for TopoGen. Defines public API exports (Config, Renderer, main),
         loads package metadata (__version__, __description__), and provides central import point
         for the topology generator. This is the entry point for all `import topogen` statements.

Blast Radius: MEDIUM - Package-level changes affect all imports
              - Changes to __all__ affect public API surface
              - Import modifications affect all consumers
              - Metadata loading affects version reporting

Package Structure:
    - main.py: CLI entry point and argument parsing
    - render.py: Core topology generation and rendering logic
    - config.py: Configuration management
    - models.py: Data models (nodes, interfaces, coordinates)
    - dnshost.py: DNS host configuration generator
    - lxcfrr.py: FRR container configuration generator
    - colorlog.py: Colored log output formatter
    - gui.py: Optional Gooey-based GUI launcher
    - templates/: Jinja2 templates for router configurations

Topology Modes:
    - Simple/NX: Star topology with central switch + DNS host
    - Flat: Hierarchical unmanaged switch fabric
    - Flat-pair: Odd-even router pairing with switch fabric
    - DMVPN: Hub-spoke DMVPN with flat or flat-pair underlay

Output Modes:
    - Online: Direct CML2 API integration (live lab creation)
    - Offline: YAML file generation (import into CML2 later)

Entry Points:
    - topogen: CLI command (calls main.main())
    - topogen-gui: GUI command (calls gui.main())
    - python -m topogen.main: Direct module execution

Public API Exports:
    - Config: Configuration class
    - Renderer: Topology renderer class
    - main(): CLI entry point
    - __version__: Package version from metadata
    - __description__: Package description from metadata
"""

import importlib.metadata as importlib_metadata

from .config import Config
from .render import Renderer
from .main import main

_metadata = importlib_metadata.metadata("topogen")
__version__ = _metadata["Version"]
__description__ = _metadata["Summary"]


__all__ = ["Config", "Renderer", "main"]
