from .tunnel_types import (
    MineShaftEntry,
    TunnelCave,
    TunnelEntryDecoration,
    TunnelPath,
    TunnelShape,
    TunnelSystem,
)


def create_tunnel_system(*args, **kwargs):
    """Create the configured tunnel system without importing Blender at package load."""
    from .create_tunnel_system import create_tunnel_system as _create_tunnel_system

    return _create_tunnel_system(*args, **kwargs)

__all__ = [
    "MineShaftEntry",
    "TunnelCave",
    "TunnelEntryDecoration",
    "TunnelPath",
    "TunnelShape",
    "TunnelSystem",
    "create_tunnel_system",
]
