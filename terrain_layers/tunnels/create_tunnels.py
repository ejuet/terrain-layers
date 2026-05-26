from __future__ import annotations

from typing import TYPE_CHECKING
from .create_tunnel_entrypoint_modifier import create_tunnel_entrypoint_modifier


if TYPE_CHECKING:
    from terrain_layers.config.config_types import TerrainConfig


def create_tunnels(config: "TerrainConfig"):
    create_tunnel_entrypoint_modifier(config)
